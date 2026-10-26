"""Persistência real em MLflow SQLite temporário e falha operacional."""

import json

import mlflow
import pytest
from mlflow import MlflowClient

from src.monitoring.resources import ProcessResources
from src.monitoring.tracking import TrackingError, recent_runs, track_operation
from src.utils.config import Settings


def test_tracking_persists_run_metrics_and_aggregate_artifact(tmp_path):
    settings = Settings(
        project_root=tmp_path,
        mlflow_tracking_uri=f"sqlite:///{tmp_path / 'tracking.db'}",
    )
    result = track_operation(
        settings,
        "train",
        lambda: {"validation": {"roc_auc": 0.71, "brier": 0.14}},
    )

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    runs = recent_runs(settings)
    assert result["validation"]["roc_auc"] == 0.71
    assert runs[0]["experiment"] == "credit-baseline"
    assert runs[0]["run_name"] == "credit-baseline"
    assert runs[0]["metrics"]["train.validation.roc_auc"] == 0.71
    local = client.download_artifacts(runs[0]["run_id"], "reports/summary.json")
    assert json.loads(open(local, encoding="utf-8").read()) == result
    assert runs[0]["metrics"]["resources.rss_peak_bytes"] > 0


def test_tracking_unavailable_preserves_local_output_and_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    settings = Settings(
        project_root=tmp_path,
        mlflow_tracking_uri="http://127.0.0.1:1",
    )
    output = tmp_path / "local-result.json"

    def operation():
        output.write_text('{"result":"preserved"}', encoding="utf-8")
        return {"result": "preserved"}

    with pytest.raises(TrackingError, match="MLflow"):
        track_operation(settings, "detect", operation)

    assert json.loads(output.read_text(encoding="utf-8")) == {"result": "preserved"}
    assert json.loads(
        (tmp_path / "artifacts/runs/tracking-failures/detect.json").read_text(encoding="utf-8")
    ) == {"command": "detect", "status": "tracking_unavailable"}


def test_resource_measurement_samples_short_job_without_sleep():
    resources = ProcessResources()
    resources.start()
    sum(range(1000))
    measured = resources.finish()

    assert measured["duration_seconds"] >= 0
    assert measured["cpu_seconds"] >= 0
    assert measured["rss_peak_bytes"] > 0
    assert measured["resource_scope"] == "process_and_children_excluded"
