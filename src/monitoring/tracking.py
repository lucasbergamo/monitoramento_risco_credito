"""Publicação de métricas e artefatos agregados no MLflow remoto."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4

from mlflow import MlflowClient
from mlflow.entities import Metric, ViewType
from mlflow.environment_variables import MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT

from src.monitoring.resources import ProcessResources
from src.utils.config import Settings
from src.utils.logger import get_logger


class TrackingError(RuntimeError):
    """Erro de publicação depois que os resultados locais já foram gravados."""


class TrackedRun(AbstractContextManager):
    def __init__(
        self,
        settings: Settings,
        experiment_name: str,
        run_name: str,
        *,
        tags: dict[str, str] | None = None,
    ) -> None:
        MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT.set(True)
        self.settings = settings
        self.experiment_name = experiment_name
        self.run_name = run_name
        self.tags = tags or {}
        self.resources = ProcessResources()
        self.run_id: str | None = None
        self._run = None
        self.client = None
        self._failure: Exception | None = None
        self._pending_metrics: list[tuple[dict[str, float], int]] = []
        self._pending_artifacts: list[tuple[str, dict[str, Any]]] = []
        self._startup_error: Exception | None = None

    def __enter__(self) -> TrackedRun:
        try:
            self._start_remote_run()
        except Exception as error:
            self._startup_error = error
            get_logger().error(
                "tracking_failed",
                stage=self.experiment_name,
                status="failed",
                error_type=type(error).__name__,
            )
        self.resources.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        resource_metrics = self.resources.finish()
        if exc is not None:
            self._failure = exc
        try:
            if self._run is None:
                self._start_remote_run()
            if exc is not None and type(exc).__name__ == "ContractRejected":
                result = getattr(exc, "result", None)
                violations = result.model_dump(mode="json") if result is not None else {}
                self.log_json(
                    "alerts.json",
                    {
                        "schema_version": 1,
                        "events": [
                            {
                                "type": "rejection",
                                "severity": "warning",
                                "condition": "contract_rejected",
                                "violations": violations,
                                "action": "Corrigir o lote e executar a validação novamente",
                            }
                        ],
                    },
                )
                get_logger().warning(
                    "operational_alert",
                    run_id=self.run_id,
                    alert_type="rejection",
                    severity="warning",
                    action="Corrigir o lote e executar a validação novamente",
                    status="rejected",
                )
            get_logger().info("tracking_started", stage=self.experiment_name, status="running")
            for metrics, step in self._pending_metrics:
                self._log_metrics(metrics, step=step)
            for name, payload in self._pending_artifacts:
                self._upload_json(name, payload)
            self._log_metrics(
                {
                    "resources.duration_seconds": float(resource_metrics["duration_seconds"]),
                    "resources.cpu_seconds": float(resource_metrics["cpu_seconds"]),
                    "resources.rss_peak_bytes": float(resource_metrics["rss_peak_bytes"]),
                },
                step=0,
            )
            if exc is not None:
                self.client.set_tag(self.run_id, "operation.error_type", type(exc).__name__)
            self.client.set_terminated(self.run_id, status="FAILED" if exc else "FINISHED")
            get_logger().info(
                "tracking_published",
                run_id=self.run_id,
                stage=self.experiment_name,
                status="failed" if exc else "success",
            )
        except Exception as error:
            get_logger().error(
                "tracking_failed",
                stage=self.experiment_name,
                status="failed",
                error_type=type(error).__name__,
            )
            if exc is None:
                raise TrackingError("Falha ao finalizar run no MLflow") from error
            exc.add_note("A publicação da falha no MLflow também não foi concluída")
        return False

    def log_metrics(self, metrics: dict[str, float | int], *, step: int = 0) -> None:
        safe = {key: float(value) for key, value in metrics.items() if _valid_metric(key, value)}
        if len(safe) != len(metrics):
            raise ValueError("Métrica contém nome ou valor inválido")
        if self._run is None:
            self._pending_metrics.append((safe, step))
        else:
            self._log_metrics(safe, step=step)

    def _log_metrics(self, metrics: dict[str, float], *, step: int) -> None:
        timestamp = int(time() * 1000)
        self.client.log_batch(
            self.run_id,
            metrics=[Metric(key, float(value), timestamp, step) for key, value in metrics.items()],
        )

    def log_json(self, name: str, payload: dict[str, Any]) -> None:
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("Artefato deve ser um arquivo JSON no diretório raiz")
        if self._run is None:
            self._pending_artifacts.append((name, payload))
            return
        self._upload_json(name, payload)

    def _upload_json(self, name: str, payload: dict[str, Any]) -> None:
        path = Path(self.settings.artifacts_dir) / ".tracking-tmp" / uuid4().hex / name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False),
                encoding="utf-8",
            )
            self.client.log_artifact(self.run_id, str(path), artifact_path="reports")
        finally:
            path.unlink(missing_ok=True)
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
            parent = directory.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()

    def _start_remote_run(self) -> None:
        # A API do cliente recebe tags explícitas e não tenta descobrir um Git ausente.
        # O manifesto da campanha mantém fingerprint de fontes e hashes de artefatos.
        if self.client is None:
            self.client = MlflowClient(tracking_uri=self.settings.mlflow_tracking_uri)
        client = self.client
        experiment = client.get_experiment_by_name(self.experiment_name)
        experiment_id = (
            experiment.experiment_id
            if experiment is not None
            else client.create_experiment(self.experiment_name)
        )
        clean_tags = {"mlflow.runName": self.run_name, **self.tags}
        if any(not _safe_tag(key, value) for key, value in clean_tags.items()):
            raise ValueError("Tag de tracking contém campo não permitido")
        self._run = client.create_run(experiment_id=experiment_id, tags=clean_tags)
        self.run_id = self._run.info.run_id

    def log_result(self, result: dict[str, Any], *, command: str) -> None:
        """Registra métricas agregadas e relatório sanitizado após gravar o resultado local."""
        if isinstance(result.get("model_version"), str):
            self.set_tag("model_version", result["model_version"])
        if isinstance(result.get("scenario_version"), str):
            self.set_tag("scenario_version", result["scenario_version"])
        if command == "detect":
            for index, comparison in enumerate(result.get("results", []), start=1):
                metrics = {
                    f"{comparison['comparison']}.{comparison['window_index']}.feature_count": len(
                        comparison.get("features", [])
                    ),
                    f"{comparison['comparison']}.{comparison['window_index']}.alert_count": len(
                        comparison.get("alerts", [])
                    ),
                }
                self.log_metrics(metrics, step=index)
        else:
            _log_numeric_leaves(self, result, prefix=command)
        payload = _report_payload(result)
        self.log_json("summary.json", payload)
        if command == "detect":
            events = [
                {
                    **alert,
                    "model_version": result.get("model_version"),
                    "scenario_version": result.get("scenario_version"),
                }
                for comparison in result.get("results", [])
                for alert in comparison.get("alerts", [])
            ]
            evaluation_path = self.settings.data_dir / "scenarios/evaluation.json"
            if evaluation_path.is_file():
                evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
                last_pair = evaluation.get("paired_effects", [])[-1:]
                matches_detection = evaluation.get("scenario_version") == result.get(
                    "scenario_version"
                ) and evaluation.get("model_version") == result.get("model_version")
                if last_pair and matches_detection:
                    pair = last_pair[0]
                    threshold = evaluation.get("gate", {}).get("minimum_brier_increase_exclusive")
                    increase = pair.get("brier_difference")
                    if threshold is not None and increase is not None and increase > threshold:
                        events.append(
                            {
                                "type": "performance_degraded",
                                "severity": "critical",
                                "condition": f"Brier pareado {increase:.6f} > {threshold:.6f}",
                                "model_version": result.get("model_version"),
                                "scenario_version": result.get("scenario_version"),
                                "window": (f"concept_drift/{pair.get('window_index', 0):03d}"),
                                "action": (
                                    "Investigar mudança de conceito e revisar "
                                    "desempenho supervisionado"
                                ),
                            }
                        )
            self.log_json(
                "alerts.json",
                {
                    "schema_version": 1,
                    "run_id": result.get("run_id"),
                    "model_version": result.get("model_version"),
                    "scenario_version": result.get("scenario_version"),
                    "events": events,
                },
            )
            for event in events:
                get_logger().warning(
                    "operational_alert",
                    run_id=result.get("run_id"),
                    window=event.get("window"),
                    scenario=(event.get("window") or "").partition("/")[0],
                    feature=event.get("feature"),
                    condition=event.get("condition"),
                    metric=event.get("metric"),
                    value=event.get("value"),
                    threshold=event.get("threshold"),
                    alert_type=event.get("type"),
                    severity=event.get("severity"),
                    action=event.get("action"),
                    status="alert",
                )

    def set_tag(self, key: str, value: str) -> None:
        if not _safe_tag(key, value):
            raise ValueError("Tag contém campo não permitido")
        if self._run is None:
            self.tags[key] = value
        else:
            self.client.set_tag(self.run_id, key, value)


def _log_numeric_leaves(run: TrackedRun, value: Any, *, prefix: str, step: int = 0) -> None:
    import math

    if isinstance(value, dict):
        for key, child in value.items():
            _log_numeric_leaves(run, child, prefix=f"{prefix}.{key}", step=step)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _log_numeric_leaves(run, child, prefix=f"{prefix}.{index}", step=index + 1)
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        normalized = "".join(char if char.isalnum() or char in "._-" else "_" for char in prefix)
        run.log_metrics({normalized[:240]: float(value)}, step=step)


def _report_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Remove raw rows, IDs, scores and paths even if a future result adds them."""
    blocked = {"record_id", "group_id", "user_id", "email", "path", "scores", "rows"}
    if isinstance(result, dict):
        return {
            key: _report_payload(value)
            for key, value in result.items()
            if key.lower() not in blocked and not key.lower().endswith("_path")
        }
    if isinstance(result, list):
        return [_report_payload(value) for value in result]
    return result


def tracked_run(
    settings: Settings,
    experiment_name: str,
    run_name: str,
    *,
    tags: dict[str, str] | None = None,
) -> TrackedRun:
    return TrackedRun(settings, experiment_name, run_name, tags=tags)


def track_operation(
    settings: Settings,
    command: str,
    operation: Callable[[], dict],
    *,
    tags: dict[str, str] | None = None,
) -> dict:
    baseline = command in {"train", "evaluate", "promote"}
    experiment = "credit-baseline" if baseline else "credit-monitoring"
    run_name = experiment
    result: dict[str, Any] | None = None
    try:
        with tracked_run(
            settings,
            experiment,
            run_name,
            tags={"component": command, **(tags or {})},
        ) as run:
            result = operation()
            result["tracking_run_id"] = run.run_id
            if command == "detect":
                summary = (
                    settings.artifacts_dir / "runs" / result.get("run_id", "") / "summary.json"
                )
                if summary.is_file():
                    from src.utils.manifest import write_manifest

                    write_manifest(summary, result)
            run.log_result(result, command=command)
    except TrackingError:
        if result is not None:
            result["tracking_status"] = "unavailable"
            result["tracking_run_id"] = None
            if command == "detect":
                destination = settings.artifacts_dir / "runs" / result.get("run_id", "")
                if (destination / "summary.json").is_file():
                    from src.utils.manifest import write_manifest

                    write_manifest(destination / "summary.json", result)
            diagnostic = settings.artifacts_dir / "runs" / "tracking-failures"
            diagnostic.mkdir(parents=True, exist_ok=True)
            (diagnostic / f"{command}.json").write_text(
                json.dumps({"command": command, "status": "tracking_unavailable"}, sort_keys=True),
                encoding="utf-8",
            )
        raise
    return result or {}


def recent_runs(settings: Settings, limit: int = 100) -> list[dict[str, Any]]:
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    experiments = client.search_experiments(view_type=ViewType.ACTIVE_ONLY)
    rows = []
    for experiment in experiments:
        for run in client.search_runs(
            [experiment.experiment_id], order_by=["attributes.start_time DESC"], max_results=limit
        ):
            rows.append(
                {
                    "run_id": run.info.run_id,
                    "run_name": run.data.tags.get("mlflow.runName", "unnamed"),
                    "experiment": experiment.name,
                    "status": run.info.status,
                    "start_time": run.info.start_time,
                    "metrics": run.data.metrics,
                }
            )
    return sorted(rows, key=lambda item: item["start_time"] or 0, reverse=True)[:limit]


def _valid_metric(name: str, value: float | int) -> bool:
    import math

    return (
        bool(name)
        and len(name) <= 250
        and all(part.replace("_", "").replace("-", "").isalnum() for part in name.split("."))
        and isinstance(value, (float, int))
        and math.isfinite(float(value))
    )


def _safe_tag(key: str, value: str) -> bool:
    allowed = {
        "mlflow.runName",
        "component",
        "model_version",
        "scenario_version",
        "campaign_id",
        "status",
    }
    return (
        key in allowed
        and len(value) <= 128
        and all(char.isalnum() or char in "-_./" for char in value)
    )
