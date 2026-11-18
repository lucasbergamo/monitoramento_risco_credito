"""Adaptador Evidently 0.7 e diagnóstico agregado de mudanças nas features."""

import json
import warnings
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import ks_2samp

from src.data.contracts import ContractRejected, validate_table
from src.data.prepare import FEATURES, PAY_COLUMNS
from src.models.train import verify_dataset
from src.monitoring.alerts import feature_alerts, holm_adjust
from src.utils.config import PROJECT_ROOT
from src.utils.logger import get_logger
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest

# Evidently 0.7.23 contém este escape inválido em um único descritor.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r"invalid escape sequence '\\d'",
        category=SyntaxWarning,
        module=r"evidently\.descriptors\.text_match",
    )
    from evidently import DataDefinition, Dataset, Report
    from evidently.metrics import ValueDrift


class MonitoringConfig(BaseModel):
    """Política fixa sem sobrescritas ambientais de método, seed ou limiares."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1] = 1
    categorical_method: Literal["psi"] = "psi"
    categorical_threshold: Literal[0.25] = 0.25
    numerical_method: Literal["ks"] = "ks"
    numerical_threshold: Literal[0.01] = 0.01
    minimum_ks_d: Literal[0.10] = 0.10
    minimum_sample_size: int = Field(default=20, ge=20)
    validation_window_size: Literal[1000] = 1000


def load_monitoring_config(path: Path | None = None) -> MonitoringConfig:
    path = path or PROJECT_ROOT / "configs/monitoring.yaml"
    return MonitoringConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def extract_scores(payload: dict, config: MonitoringConfig) -> dict[str, float]:
    """Valida identidade semântica (tipo/coluna/método/limiar), nunca posição ou hash."""
    scores = {}
    for metric in payload["metrics"]:
        spec = metric["config"]
        name = spec.get("column")
        if spec.get("type") != "evidently:metric_v2:ValueDrift" or name not in FEATURES:
            raise ValueError("Métrica inesperada no snapshot")
        categorical = name in PAY_COLUMNS
        method = config.categorical_method if categorical else config.numerical_method
        threshold = config.categorical_threshold if categorical else config.numerical_threshold
        score = float(metric["value"])
        if (
            name in scores
            or spec.get("method") != method
            or spec.get("threshold") != threshold
            or not np.isfinite(score)
            or score < 0
            or (not categorical and score > 1)
        ):
            raise ValueError("Semântica de drift incompatível")
        scores[name] = score
    if set(scores) != set(FEATURES):
        raise ValueError("Features ausentes no snapshot")
    return scores


def _feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not frame.columns.is_unique or not set(FEATURES).issubset(frame.columns):
        raise ValueError("Features ausentes ou duplicadas")
    # A seleção explícita também exclui ID, labels, demografia e metadados do simulador.
    selected = frame.loc[:, FEATURES].copy()
    result = validate_table(selected, "features")
    if not result.valid:
        raise ContractRejected(result)
    return selected


def detect_drift(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    output: Path,
    *,
    run_id: str,
    window: str,
    config: MonitoringConfig | None = None,
) -> dict:
    """Compara 19 features, grava snapshot local e retorna somente métricas agregadas.

    Lotes com menos de minimum_sample_size não produzem evidência estatística e
    falham explicitamente. Não recebem resultado negativo artificial.
    """
    config = config or load_monitoring_config()
    if min(len(reference), len(current)) < config.minimum_sample_size:
        raise ValueError("Amostra insuficiente para diagnóstico de drift")
    reference, current = _feature_frame(reference), _feature_frame(current)
    definition = DataDefinition(
        categorical_columns=PAY_COLUMNS,
        numerical_columns=[name for name in FEATURES if name not in PAY_COLUMNS],
    )
    metrics = [
        ValueDrift(
            column=name,
            method=config.categorical_method if name in PAY_COLUMNS else config.numerical_method,
            threshold=(
                config.categorical_threshold if name in PAY_COLUMNS else config.numerical_threshold
            ),
        )
        for name in FEATURES
    ]
    snapshot = Report(metrics).run(
        reference_data=Dataset.from_pandas(reference, data_definition=definition),
        current_data=Dataset.from_pandas(current, data_definition=definition),
    )
    scores = extract_scores(json.loads(snapshot.json()), config)
    numerical = {
        name: ks_2samp(reference[name], current[name], alternative="two-sided", method="auto")
        for name in FEATURES
        if name not in PAY_COLUMNS
    }
    adjusted = holm_adjust({name: scores[name] for name in numerical})
    rows = []
    for name in FEATURES:
        categorical = name in PAY_COLUMNS
        score = scores[name]
        if not categorical and not np.isclose(score, numerical[name].pvalue, rtol=1e-10, atol=0):
            raise ValueError("KS Evidently diverge do SciPy")
        report_drift = (
            score >= config.categorical_threshold
            if categorical
            else score < config.numerical_threshold
        )
        operational = (
            report_drift
            if categorical
            else adjusted[name] < config.numerical_threshold
            and numerical[name].statistic >= config.minimum_ks_d
        )
        rows.append(
            {
                "feature": name,
                "type": "categorical" if categorical else "numerical",
                "method": "psi" if categorical else "ks",
                "score": score,
                "score_unit": "PSI" if categorical else "p_value",
                "threshold": config.categorical_threshold
                if categorical
                else config.numerical_threshold,
                "reference_n": len(reference),
                "current_n": len(current),
                "p_raw": None if categorical else score,
                "p_adjusted": None if categorical else adjusted[name],
                "ks_d": None if categorical else float(numerical[name].statistic),
                "minimum_ks_d": None if categorical else config.minimum_ks_d,
                "numeric_family_size": len(numerical),
                "report_drift": bool(report_drift),
                "operational_alert": bool(operational),
                "operational_rule": "PSI >= 0.25"
                if categorical
                else "Holm p < 0.01 AND KS D >= 0.10",
            }
        )
    output.mkdir(parents=True, exist_ok=False)
    snapshot.save_html(str(output / "evidently.html"))
    snapshot.save_json(str(output / "evidently.json"))
    result = {
        "schema_version": 1,
        "status": "available",
        "effective_config": config.model_dump(),
        "config_hash": content_hash(config.model_dump()),
        "versions": {package: version(package) for package in ("evidently", "scipy")},
        "features": rows,
        "alerts": feature_alerts(rows, run_id, window),
    }
    write_manifest(output / "normalized.json", result)
    get_logger().info(
        "drift_comparison_completed",
        run_id=run_id,
        window=window,
        status="success",
        row_count=len(current),
    )
    return result


def detect(settings) -> dict:
    """Executa controles, validação e cenários; snapshots ficam somente em artifacts."""
    config = load_monitoring_config(settings.project_root / "configs/monitoring.yaml")
    dataset = verify_dataset(settings)
    scenario_dir = (settings.data_dir / "scenarios/current").resolve()
    scenario = read_manifest(scenario_dir / "manifest.json")
    if scenario["version"] != content_hash(
        {k: v for k, v in scenario.items() if k != "version"}
    ) or scenario["dataset_manifest_hash"] != content_hash(dataset):
        raise ValueError("Cenários incompatíveis com dados")
    for relative, digest in scenario["files"].items():
        path = (scenario_dir / relative).resolve()
        if not path.is_relative_to(scenario_dir) or file_hash(path) != digest:
            raise ValueError("Integridade do cenário inválida")

    def source(relative):
        path = (settings.data_dir / relative).resolve()
        if (
            not path.is_relative_to(settings.data_dir)
            or file_hash(path) != dataset["files"][relative]
        ):
            raise ValueError("Integridade da referência inválida")
        return pd.read_parquet(path)

    reference = source("gold/reference/features.parquet")
    validation = source("gold/validation/features.parquet")
    run_id = str(uuid4())
    root = settings.artifacts_dir / "runs" / run_id
    root.mkdir(parents=True, exist_ok=False)
    results = []

    def compare(name, window, ref, cur):
        key = f"{name}/{window:03d}"
        result = detect_drift(ref, cur, root / key, run_id=run_id, window=key, config=config)
        results.append({"comparison": name, "window_index": window, **result})
        return result

    compare("identical", 0, reference, reference.copy())
    size = config.validation_window_size
    for j in range(len(validation) // size):
        compare("validation", j, reference, validation.iloc[j * size : (j + 1) * size])
    for j in range(scenario["window_count"]):
        stable = pd.read_parquet(scenario_dir / "stable" / f"{j:03d}/features.parquet")
        concept = pd.read_parquet(scenario_dir / "concept_drift" / f"{j:03d}/features.parquet")
        if not stable.equals(concept):
            raise ValueError("Features pareadas diferentes")
        compare("stable", j, reference, stable)
        altered = pd.read_parquet(scenario_dir / "data_drift" / f"{j:03d}/features.parquet")
        compare("data_drift", j, reference, altered)
        compare("stable_vs_concept", j, stable, concept)
    last = next(r for r in reversed(results) if r["comparison"] == "data_drift")
    detected = {row["feature"] for row in last["features"] if row["operational_alert"]}
    controls_clean = all(
        not r["alerts"] for r in results if r["comparison"] in {"identical", "stable_vs_concept"}
    )
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "dataset_manifest_hash": content_hash(dataset),
        "scenario_version": scenario["version"],
        "model_version": scenario["model_version"],
        "drift_features": scenario["drift_features"],
        "validation_remainder_rows": len(validation) % size,
        "gate_passed": controls_clean and set(scenario["drift_features"]).issubset(detected),
        "results": results,
    }
    write_manifest(
        root / "alerts.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "events": [event for result in results for event in result["alerts"]],
        },
    )
    write_manifest(root / "summary.json", report)
    # Publicação deliberada ocorre somente após inspeção da evidência agregada.
    return report
