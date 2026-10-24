"""Quatro variantes das mesmas janelas, com bundles locais imutáveis por hash."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict

from src.data.contracts import ContractRejected, validate_batch, validate_labels
from src.data.prepare import FEATURES, PAY_COLUMNS
from src.models.predict import predict_batch
from src.models.registry import load_bundle
from src.models.train import load_partition, verify_dataset
from src.monitoring.performance import compare_paired, evaluate_labels
from src.simulation.causal import intervene, latent_uniform
from src.utils.config import PROJECT_ROOT
from src.utils.logger import get_logger
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest

SCENARIOS = ("stable", "invalid", "data_drift", "concept_drift")


class ScenarioConfig(BaseModel):
    """Política fixa, independente da seed ambiental e sem chaves desconhecidas."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    simulator_version: Literal["credit-shock-v1"] = "credit-shock-v1"
    shock_seed: Literal[42] = 42
    bootstrap_seed: Literal[42] = 42
    bootstrap_resamples: Literal[1000] = 1000
    maximum_shock: Literal[0.35] = 0.35
    minimum_brier_increase: Literal[0.02] = 0.02
    confidence_level: Literal[0.95] = 0.95
    pay_increment: Literal[3] = 3
    limit_multiplier_increment: Literal[2] = 2
    amount_iqr_increment: Literal[2] = 2


def load_scenario_config(path: Path | None = None) -> ScenarioConfig:
    path = path or PROJECT_ROOT / "configs/scenarios.yaml"
    return ScenarioConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def transform_features(
    features: pd.DataFrame,
    selected: list[str],
    intensity: float,
    train_iqr: dict,
    config: ScenarioConfig,
) -> pd.DataFrame:
    """Altera somente as duas selecionadas; preserva tipos e arredonda inteiros."""
    if (
        len(selected) != 2
        or len(set(selected)) != 2
        or not set(selected) <= set(FEATURES)
        or not np.isfinite(intensity)
        or not 0 <= intensity <= 1
    ):
        raise ValueError("Transformação incompatível")
    result = features.copy()
    for name in selected:
        column = features[name]
        if name in PAY_COLUMNS:
            values = np.minimum(8, column + round(config.pay_increment * intensity))
        elif name == "limit_bal":
            values = column * (1 + config.limit_multiplier_increment * intensity)
        else:
            scale = train_iqr[name]
            if not np.isfinite(scale) or scale < 0:
                raise ValueError("IQR de treino inválido")
            values = column + config.amount_iqr_increment * intensity * max(scale, 1)
        if pd.api.types.is_integer_dtype(column):
            values = np.rint(values)
        result[name] = values.astype(column.dtype)
    return result


def invalid_batch(features: pd.DataFrame, keys: pd.DataFrame) -> tuple:
    """Três violações em linhas distintas, sem correção de registros."""
    if len(features) < 3:
        raise ValueError("Janela insuficiente para cenário inválido")
    features, keys = features.copy(), keys.copy()
    features.loc[features.index[0], "limit_bal"] = np.nan
    keys.loc[keys.index[1], "record_id"] = keys.record_id.iloc[0]
    features.loc[features.index[2], "pay_amt1"] = -1
    return features, keys


def _source_table(settings, dataset: dict, relative: str) -> pd.DataFrame:
    path = settings.data_dir / relative
    if file_hash(path) != dataset["files"][relative]:
        raise ValueError("Integridade da janela inválida")
    return pd.read_parquet(path)


def _verify_files(directory: Path, manifest: dict) -> None:
    for name, digest in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or file_hash(path) != digest:
            raise ValueError("Integridade do cenário inválida")


def simulate(settings) -> dict:
    """Publica geração completa e determinística; falha preserva current anterior.

    Predição e estado labels_unavailable são persistidos antes de abrir os labels.
    Dados individuais, scores e U permanecem exclusivamente sob data/scenarios.
    """
    config = load_scenario_config(settings.project_root / "configs/scenarios.yaml")
    dataset = verify_dataset(settings)
    _, model = load_bundle(settings.models_dir / "current")
    if content_hash(dataset) != model["dataset_manifest_hash"]:
        raise ValueError("Dataset diverge do modelo congelado")
    count = dataset["production_windows"]["complete_windows"]
    if count < 4:
        raise ValueError("Menos de quatro janelas completas")
    train, _, _, _ = load_partition(settings, dataset, "train")
    train_iqr = (train.quantile(0.75) - train.quantile(0.25)).to_dict()
    selected = model["drift_features"]
    windows = []
    for j in range(count):
        prefix = f"gold/windows/{j:03d}"
        features = _source_table(settings, dataset, f"{prefix}/features.parquet")
        keys = _source_table(settings, dataset, f"{prefix}/keys.parquet")
        validate_batch(features, keys)
        if len(features) != dataset["production_windows"]["window_size"]:
            raise ValueError("Tamanho de janela incompatível")
        windows.append((features, keys, prefix))
    all_keys = pd.concat([keys[["record_id"]] for _, keys, _ in windows], ignore_index=True)
    latent = latent_uniform(all_keys, config.shock_seed)
    output = settings.data_dir / "scenarios"
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".simulation-", dir=output) as temporary:
        staging = Path(temporary)
        latent.to_parquet(staging / "latent.parquet", index=False)
        entries = []
        for j, (original, keys, prefix) in enumerate(windows):
            intensity = j / (count - 1)
            stable_scores = None
            original_labels = None
            for scenario in SCENARIOS:
                if scenario == "invalid" and j != 0:
                    continue
                directory = staging / scenario / f"{j:03d}"
                directory.mkdir(parents=True)
                features, scenario_keys = original.copy(), keys.copy()
                r = config.maximum_shock * intensity if scenario == "concept_drift" else 0.0
                if scenario == "data_drift":
                    features = transform_features(original, selected, intensity, train_iqr, config)
                elif scenario == "invalid":
                    features, scenario_keys = invalid_batch(original, keys)
                features.to_parquet(directory / "features.parquet", index=False)
                scenario_keys.to_parquet(directory / "keys.parquet", index=False)
                entry = {
                    "schema_version": 1,
                    "scenario": scenario,
                    "window_index": j,
                    "source_split_hash": dataset["split_hash"],
                    "source_feature_sha256": dataset["files"][f"{prefix}/features.parquet"],
                    "source_key_sha256": dataset["files"][f"{prefix}/keys.parquet"],
                    "source_label_sha256": dataset["files"][f"{prefix}/labels.parquet"],
                    "seed": config.shock_seed,
                    "simulator_version": config.simulator_version,
                    "intensity": intensity if scenario == "data_drift" else r,
                    "transformed_columns": selected if scenario == "data_drift" else [],
                    "feature_sha256": file_hash(directory / "features.parquet"),
                    "labels_origin": "unavailable",
                    "pre_label_status": "labels_unavailable",
                    "row_count": len(features),
                }
                try:
                    scores = predict_batch(features, scenario_keys, settings.models_dir / "current")
                except ContractRejected as error:
                    if scenario != "invalid":
                        raise
                    entry["contract"] = error.result.model_dump(mode="json")
                    entry["status"] = "contract_rejected"
                    write_manifest(directory / "manifest.json", entry)
                    entries.append(entry)
                    continue
                if scenario == "invalid":
                    raise ValueError("Cenário inválido não foi rejeitado")
                scores.to_parquet(directory / "scores.parquet", index=False)
                entry["score_sha256"] = file_hash(directory / "scores.parquet")
                entry["status"] = "labels_unavailable"
                write_manifest(directory / "manifest.json", entry)
                # Somente agora os rótulos entram na avaliação, por chave.
                if scenario == "stable":
                    stable_scores = scores
                    original_labels = _source_table(settings, dataset, f"{prefix}/labels.parquet")
                    validate_labels(original_labels, keys)
                    original_labels.to_parquet(directory / "labels.parquet", index=False)
                    entry["labels_origin"] = "observed"
                    entry["status"] = "labels_available"
                elif scenario == "concept_drift":
                    if entry["feature_sha256"] != file_hash(
                        staging / "stable" / f"{j:03d}" / "features.parquet"
                    ) or not scores.equals(stable_scores):
                        raise ValueError("Features ou scores do par divergentes")
                    synthetic = intervene(
                        original_labels, latent[latent.record_id.isin(keys.record_id)], r
                    )
                    synthetic.to_parquet(directory / "labels.parquet", index=False)
                    entry["labels_origin"] = "synthetic_external_shock"
                    entry["status"] = "labels_available"
                write_manifest(directory / "manifest.json", entry)
                entries.append(entry)
        manifest = {
            "schema_version": 1,
            "simulator_version": config.simulator_version,
            "dataset_manifest_hash": content_hash(dataset),
            "source_split_hash": dataset["split_hash"],
            "source_sha256": dataset["source_sha256"],
            "model_version": model["version"],
            "effective_config": config.model_dump(),
            "config_hash": content_hash(config.model_dump()),
            "drift_features": selected,
            "train_iqr": train_iqr,
            "transformations": {
                "PAY": "min(8,x+round(3*a))",
                "LIMIT_BAL": "x*(1+2*a)",
                "AMOUNT": "x+2*a*max(IQR_train,1)",
                "integer_rounding": "nearest_even",
            },
            "latent_assignment": "sorted_all_window_ids_exclusive_numpy_generator",
            "window_count": count,
            "windows": entries,
            "files": {
                str(path.relative_to(staging)): file_hash(path)
                for path in sorted(staging.rglob("*"))
                if path.is_file()
            },
        }
        manifest["version"] = content_hash(manifest)
        write_manifest(staging / "manifest.json", manifest)
        versions = output / "versions"
        versions.mkdir(exist_ok=True)
        destination = versions / manifest["version"]
        if destination.exists():
            if read_manifest(destination / "manifest.json") != manifest:
                raise ValueError("Geração existente incompatível")
            _verify_files(destination, manifest)
        else:
            staging.rename(destination)
        pointer = output / f".current-{uuid4().hex}"
        try:
            pointer.symlink_to(destination.relative_to(output), target_is_directory=True)
            os.replace(pointer, output / "current")
        finally:
            pointer.unlink(missing_ok=True)
    get_logger().info("scenarios_generated", status="success", row_count=len(all_keys))
    return manifest


def evaluate_scenarios(settings) -> dict:
    """Verifica geração completa, hashes e pares antes de publicar somente agregados."""
    directory = (settings.data_dir / "scenarios/current").resolve()
    manifest = read_manifest(directory / "manifest.json")
    config = load_scenario_config(settings.project_root / "configs/scenarios.yaml")
    _, model = load_bundle(settings.models_dir / "current")
    if (
        manifest["version"] != content_hash({k: v for k, v in manifest.items() if k != "version"})
        or directory.name != manifest["version"]
        or manifest["effective_config"] != config.model_dump()
        or manifest["model_version"] != model["version"]
        or manifest["dataset_manifest_hash"] != model["dataset_manifest_hash"]
        or manifest["config_hash"] != content_hash(config.model_dump())
    ):
        raise ValueError("Manifesto do cenário incompatível")
    _verify_files(directory, manifest)
    latent = pd.read_parquet(directory / "latent.parquet")
    stable_keys = pd.concat(
        [
            pd.read_parquet(directory / "stable" / f"{j:03d}" / "keys.parquet")[["record_id"]]
            for j in range(manifest["window_count"])
        ],
        ignore_index=True,
    )
    if not latent.equals(latent_uniform(stable_keys, config.shock_seed)):
        raise ValueError("Associação de U incompatível")
    results, pairs = [], []
    for entry in manifest["windows"]:
        scenario, j = entry["scenario"], entry["window_index"]
        path = directory / scenario / f"{j:03d}"
        features, keys = (
            pd.read_parquet(path / f"{kind}.parquet") for kind in ("features", "keys")
        )
        if scenario == "invalid":
            try:
                validate_batch(features, keys)
            except ContractRejected as error:
                if (
                    error.result.model_dump(mode="json") != entry["contract"]
                    or (path / "scores.parquet").exists()
                ):
                    raise ValueError("Diagnóstico de rejeição incompatível") from None
            else:
                raise ValueError("Rejeição esperada ausente")
            results.append(
                {
                    "scenario": scenario,
                    "window_index": j,
                    "status": "contract_rejected",
                    "metrics": None,
                    "contract": entry["contract"],
                }
            )
            continue
        validate_batch(features, keys)
        scores = pd.read_parquet(path / "scores.parquet")
        if not scores.record_id.equals(keys.record_id):
            raise ValueError("Chaves de predição incompatíveis")
        labels = None if scenario == "data_drift" else pd.read_parquet(path / "labels.parquet")
        if scenario == "data_drift" and (path / "labels.parquet").exists():
            raise ValueError("Labels indisponíveis não podem ser usados")
        if scenario == "data_drift":
            stable_features = pd.read_parquet(
                directory / "stable" / f"{j:03d}" / "features.parquet"
            )
            expected = transform_features(
                stable_features,
                manifest["drift_features"],
                j / (manifest["window_count"] - 1),
                manifest["train_iqr"],
                config,
            )
            if not features.equals(expected):
                raise ValueError("Transformação de entrada incompatível")
        performance = evaluate_labels(scores, labels)
        results.append(
            {
                "scenario": scenario,
                "window_index": j,
                "labels_origin": entry["labels_origin"],
                **performance,
            }
        )
        if scenario == "concept_drift":
            stable = directory / "stable" / f"{j:03d}"
            if file_hash(path / "features.parquet") != file_hash(stable / "features.parquet"):
                raise ValueError("Features do par incompatíveis")
            original_labels = pd.read_parquet(stable / "labels.parquet")
            expected_labels = intervene(
                original_labels,
                latent[latent.record_id.isin(keys.record_id)],
                config.maximum_shock * j / (manifest["window_count"] - 1),
            )
            if not labels.equals(expected_labels):
                raise ValueError("Intervenção no alvo incompatível")
            pair = compare_paired(
                pd.read_parquet(stable / "scores.parquet"),
                scores,
                pd.read_parquet(stable / "labels.parquet"),
                labels,
                entry["intensity"],
                seed=config.bootstrap_seed,
                resamples=config.bootstrap_resamples,
            )
            pairs.append({"window_index": j, **pair})
    if len(pairs) != manifest["window_count"]:
        raise ValueError("Pares incompletos")
    last = pairs[-1]
    gate = bool(
        last["brier_difference"] > config.minimum_brier_increase
        and last["brier_difference_ci95"][0] > 0
    )
    report = {
        "schema_version": 1,
        "scenario_version": manifest["version"],
        "model_version": manifest["model_version"],
        "config_hash": manifest["config_hash"],
        "window_count": manifest["window_count"],
        "drift_features": manifest["drift_features"],
        "results": results,
        "paired_effects": pairs,
        "gate_passed": gate,
        "gate": {
            "minimum_brier_increase_exclusive": config.minimum_brier_increase,
            "minimum_ci95_lower_exclusive": 0.0,
            "window_index": last["window_index"],
        },
    }
    write_manifest(settings.data_dir / "scenarios/evaluation.json", report)
    write_manifest(settings.project_root / "docs/evidencias/scenarios.json", report)
    get_logger().info("scenarios_evaluated", status="success" if gate else "rejected")
    return report
