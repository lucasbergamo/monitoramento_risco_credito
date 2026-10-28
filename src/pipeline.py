"""Orquestração ponta a ponta de campanhas reproduzíveis de monitoramento."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from mlflow import MlflowClient

from src.monitoring.drift import detect
from src.monitoring.tracking import TrackingError, track_operation
from src.simulation.scenarios import evaluate_scenarios, simulate
from src.utils.config import Settings
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest


class PipelineStageError(RuntimeError):
    """Diagnóstico seguro de uma falha operacional sem repetir valores de entrada."""

    def __init__(self, stage: str, failure_code: str) -> None:
        self.stage = stage
        self.failure_code = failure_code
        message = (
            "Tracking indisponível durante a campanha"
            if failure_code == "tracking_unavailable"
            else f"Falha operacional no estágio {stage}"
        )
        super().__init__(message)


def _code_revision(root: Path, fingerprint: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return f"source-fingerprint:{fingerprint}"
    return f"git:{result.stdout.strip()}"


def _snapshot(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise ValueError("Artefato da campanha ausente")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return file_hash(destination)


def _drift_fingerprint(drift: dict) -> dict:
    fields = (
        "dataset_manifest_hash",
        "scenario_version",
        "model_version",
        "gate_passed",
        "results",
    )
    return {key: drift[key] for key in fields if key in drift}


def _result_fingerprint(scenario_version: str, evaluation: dict, drift: dict) -> str:
    return content_hash(
        {
            "scenario_version": scenario_version,
            "evaluation": evaluation,
            "drift": _drift_fingerprint(drift),
        }
    )


def _stable_result(value):
    if isinstance(value, dict):
        volatile = {"run_id", "tracking_run_id", "key", "timestamp", "campaign_id"}
        return {
            name: _stable_result(child) for name, child in value.items() if name not in volatile
        }
    if isinstance(value, list):
        return [_stable_result(item) for item in value]
    return value


def _result_fingerprint_v2(scenario_version: str, evaluation: dict, drift: dict) -> str:
    return content_hash(
        {
            "scenario_version": scenario_version,
            "evaluation": _stable_result(evaluation),
            "drift": _stable_result(_drift_fingerprint(drift)),
        }
    )


def run_pipeline(settings: Settings, *, campaign_id: str | None = None) -> dict:
    """Executa geração, avaliação, drift e tracking com manifesto isolado por campanha.

    Uma rejeição de contrato é aceite somente se a validação confirmar o cenário
    inválido sem scores. Qualquer falha operacional interrompe a campanha.
    """
    campaign_id = campaign_id or uuid4().hex
    if not campaign_id.isascii() or not campaign_id.isalnum() or len(campaign_id) > 64:
        raise ValueError("campaign_id inválido")
    directory = settings.artifacts_dir / "campaigns" / campaign_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest_path = directory / "manifest.json"
    campaign = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "status": "running",
        "run_ids": {},
    }
    write_manifest(manifest_path, campaign)
    try:
        config_paths = [
            settings.project_root / "configs/project.yaml",
            settings.project_root / "configs/model.yaml",
            settings.project_root / "configs/scenarios.yaml",
            settings.project_root / "configs/monitoring.yaml",
        ]
        config_hashes = {path.name: file_hash(path) for path in config_paths}
        data_manifest = read_manifest(settings.data_dir / "gold/dataset_manifest.json")
        model_manifest = read_manifest(settings.models_dir / "current/manifest.json")
        code_fingerprint = content_hash(
            {
                str(path.relative_to(settings.project_root)): file_hash(path)
                for path in sorted(settings.project_root.glob("src/**/*.py"))
            }
        )
        campaign = {
            "schema_version": 1,
            "campaign_id": campaign_id,
            "status": "running",
            "code_revision": _code_revision(settings.project_root, code_fingerprint),
            "code_version": f"sha256:{code_fingerprint}",
            "code_fingerprint": code_fingerprint,
            "dataset_manifest_hash": content_hash(data_manifest),
            "model_version": model_manifest.get("version"),
            "config_hashes": config_hashes,
            "run_ids": {},
            "scenario_run_ids": {},
            "files": {},
        }
        for path in config_paths:
            campaign["files"][f"configs/{path.name}"] = _snapshot(
                path, directory / "configs" / path.name
            )
        campaign["files"]["dataset_manifest.json"] = _snapshot(
            settings.data_dir / "gold/dataset_manifest.json", directory / "dataset_manifest.json"
        )
        campaign["files"]["model_manifest.json"] = _snapshot(
            settings.models_dir / "current/manifest.json", directory / "model_manifest.json"
        )
        write_manifest(manifest_path, campaign)
    except Exception as error:
        campaign["status"] = "failed"
        campaign["error_type"] = type(error).__name__
        campaign["failed_stage"] = "prepare-evidence"
        campaign["failure_code"] = "stage_failed"
        write_manifest(manifest_path, campaign)
        raise PipelineStageError("prepare-evidence", "stage_failed") from error

    def run(command: str, operation) -> dict:
        try:
            result = track_operation(
                settings,
                command,
                operation,
                tags={"campaign_id": campaign_id},
            )
        except TrackingError as error:
            raise PipelineStageError(command, "tracking_unavailable") from error
        except Exception as error:
            raise PipelineStageError(command, "stage_failed") from error
        run_id = result.get("tracking_run_id")
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError("Run sem vínculo de tracking")
        campaign["run_ids"][command] = run_id
        return result

    try:
        scenario = run("simulate", lambda: simulate(settings))
        campaign["scenario_version"] = scenario["version"]
        evaluation = run("evaluate-scenarios", lambda: evaluate_scenarios(settings))
        evaluation.pop("tracking_run_id", None)
        campaign["scenario_run_ids"] = {
            entry["scenario"]: campaign["run_ids"]["evaluate-scenarios"]
            for entry in scenario["windows"]
        }
        if not evaluation.get("results") or not evaluation.get("paired_effects"):
            raise ValueError("Avaliação de cenários incompleta")
        invalid = [row for row in evaluation["results"] if row.get("scenario") == "invalid"]
        if len(invalid) != 1 or invalid[0].get("status") != "contract_rejected":
            raise ValueError("Rejeição esperada do cenário inválido não comprovada")
        if invalid[0].get("metrics") is not None:
            raise ValueError("Cenário inválido contém métricas de inferência")
        scenarios = {row.get("scenario") for row in evaluation["results"]}
        if not {"stable", "invalid", "data_drift", "concept_drift"}.issubset(scenarios):
            raise ValueError("Campanha não contém os quatro cenários")
        if not evaluation.get("gate_passed"):
            raise ValueError("Gate de avaliação de cenários reprovado")
        detection = run("detect", lambda: detect(settings))
        campaign["drift_run_id"] = detection.get("run_id")
        if detection.get("scenario_version") != scenario["version"]:
            raise ValueError("Detecção vinculada a outra versão de cenários")
        if not detection.get("gate_passed"):
            raise ValueError("Gate de drift reprovado")
        report_source = settings.artifacts_dir / "runs" / detection["run_id"] / "summary.json"
        campaign["files"]["drift_summary.json"] = _snapshot(
            report_source, directory / "drift_summary.json"
        )
        campaign["files"]["scenario_evaluation.json"] = _snapshot(
            settings.data_dir / "scenarios/evaluation.json",
            directory / "scenario_evaluation.json",
        )
        campaign["files"]["scenario_manifest.json"] = _snapshot(
            settings.data_dir / "scenarios/current/manifest.json",
            directory / "scenario_manifest.json",
        )
        campaign["scenario_results"] = {
            name: sum(row.get("scenario") == name for row in evaluation["results"])
            for name in ("stable", "invalid", "data_drift", "concept_drift")
        }
        campaign["status"] = "completed"
        campaign["result_hash_version"] = 2
        campaign["result_hash"] = _result_fingerprint_v2(
            campaign["scenario_version"], evaluation, detection
        )
        write_manifest(manifest_path, campaign)
        return campaign
    except Exception as error:
        campaign["status"] = "failed"
        campaign["error_type"] = type(error).__name__
        if isinstance(error, PipelineStageError):
            campaign["failed_stage"] = error.stage
            campaign["failure_code"] = error.failure_code
        write_manifest(manifest_path, campaign)
        raise


def verify_evidence(settings: Settings, campaign_id: str) -> dict:
    """Confere manifesto, hashes, resultados e IDs de uma campanha explícita."""
    if not campaign_id or not campaign_id.isascii() or not campaign_id.isalnum():
        raise ValueError("campaign_id inválido")
    directory = (settings.artifacts_dir / "campaigns" / campaign_id).resolve()
    root = (settings.artifacts_dir / "campaigns").resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Caminho de campanha inválido")
    campaign = read_manifest(directory / "manifest.json")
    if campaign.get("campaign_id") != campaign_id or campaign.get("status") != "completed":
        raise ValueError("Campanha ausente, incompleta ou incompatível")
    required_runs = {"simulate", "evaluate-scenarios", "detect"}
    if set(campaign.get("run_ids", {})) != required_runs or any(
        not isinstance(value, str) or not value for value in campaign["run_ids"].values()
    ):
        raise ValueError("Vínculos de tracking incompletos")
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    for run_id in campaign["run_ids"].values():
        run = client.get_run(run_id)
        if run.info.status != "FINISHED" or run.data.tags.get("campaign_id") != campaign_id:
            raise ValueError("Run de tracking ausente ou associado a outra campanha")
    for name, digest in campaign.get("files", {}).items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or file_hash(path) != digest:
            raise ValueError("Hash de evidência incompatível")
    for name, digest in campaign.get("config_hashes", {}).items():
        if campaign["files"].get(f"configs/{name}") != digest:
            raise ValueError("Configuração da campanha incompatível")
    dataset = read_manifest(directory / "dataset_manifest.json")
    model = read_manifest(directory / "model_manifest.json")
    if content_hash(dataset) != campaign.get("dataset_manifest_hash") or model.get(
        "version"
    ) != campaign.get("model_version"):
        raise ValueError("Versões de dados ou modelo incompatíveis")
    evaluation = read_manifest(directory / "scenario_evaluation.json")
    drift = read_manifest(directory / "drift_summary.json")
    scenarios = {item.get("scenario") for item in evaluation.get("results", [])}
    if not {"stable", "invalid", "data_drift", "concept_drift"}.issubset(scenarios):
        raise ValueError("Resultados dos cenários incompletos")
    invalid = [item for item in evaluation["results"] if item.get("scenario") == "invalid"]
    if (
        len(invalid) != 1
        or invalid[0].get("status") != "contract_rejected"
        or invalid[0].get("metrics") is not None
    ):
        raise ValueError("Evidência do lote inválido incompatível")
    scenario_manifest = read_manifest(directory / "scenario_manifest.json")
    if scenario_manifest.get("version") != campaign.get("scenario_version"):
        raise ValueError("Versão dos cenários incompatível")
    scenario_directory = (
        settings.data_dir / "scenarios/versions" / campaign["scenario_version"]
    ).resolve()
    if not scenario_directory.is_dir():
        raise ValueError("Versão imutável dos cenários ausente")
    if scenario_manifest.get("version") != content_hash(
        {key: value for key, value in scenario_manifest.items() if key != "version"}
    ):
        raise ValueError("Hash do manifesto dos cenários incompatível")
    for relative, digest in scenario_manifest.get("files", {}).items():
        source = (scenario_directory / relative).resolve()
        if (
            not source.is_relative_to(scenario_directory)
            or not source.is_file()
            or file_hash(source) != digest
        ):
            raise ValueError("Integridade da versão dos cenários inválida")
    invalid_path = scenario_directory / "invalid/000"
    if (invalid_path / "scores.parquet").exists():
        raise ValueError("Cenário inválido possui artefato de inferência")
    for name, expected_status, expected_origin in (
        ("stable", "available", "observed"),
        ("concept_drift", "available", "synthetic_external_shock"),
        ("data_drift", "labels_unavailable", "unavailable"),
    ):
        rows = [item for item in evaluation["results"] if item.get("scenario") == name]
        if len(rows) != scenario_manifest.get("window_count") or any(
            item.get("status") != expected_status or item.get("labels_origin") != expected_origin
            for item in rows
        ):
            raise ValueError("Estado de labels ou resultados incompatível")
    drift_rows = [
        item for item in drift.get("results", []) if item.get("comparison") == "data_drift"
    ]
    if len(drift_rows) != scenario_manifest.get("window_count") or any(
        len(item.get("features", [])) != 19 for item in drift_rows
    ):
        raise ValueError("Detecção não comprovou inferência das janelas válidas")
    if (
        drift.get("run_id") != campaign.get("drift_run_id")
        or drift.get("scenario_version") != campaign.get("scenario_version")
        or drift.get("model_version") != campaign.get("model_version")
        or not drift.get("gate_passed")
    ):
        raise ValueError("Resultado de drift incompatível")
    if set(campaign.get("scenario_run_ids", {})) != {
        "stable",
        "invalid",
        "data_drift",
        "concept_drift",
    } or any(
        value != campaign["run_ids"]["evaluate-scenarios"]
        for value in campaign["scenario_run_ids"].values()
    ):
        raise ValueError("Associação de cenários e runs incompatível")
    fingerprint = (
        _result_fingerprint_v2 if campaign.get("result_hash_version") == 2 else _result_fingerprint
    )
    expected_hash = fingerprint(campaign["scenario_version"], evaluation, drift)
    if campaign.get("result_hash") != expected_hash:
        raise ValueError("Hash de resultados incompatível")
    return {
        "campaign_id": campaign_id,
        "status": "verified",
        "run_ids": campaign["run_ids"],
        "scenario_version": campaign["scenario_version"],
        "result_hash": campaign["result_hash"],
    }
