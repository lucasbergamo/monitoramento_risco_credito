"""Relatório HTML derivado de runs e artefatos locais reais/agregados."""

import json

from src.monitoring.reports import build_report
from src.utils.config import Settings


def test_report_links_matching_drift_and_scenario_results(tmp_path, monkeypatch):
    settings = Settings(project_root=tmp_path, mlflow_tracking_uri="http://mlflow:5000")
    data_manifest = settings.data_dir / "gold/dataset_manifest.json"
    data_manifest.parent.mkdir(parents=True)
    data_manifest.write_text(
        json.dumps({"schema_version": 1, "row_count": 30000}),
        encoding="utf-8",
    )
    model_manifest = settings.models_dir / "current/manifest.json"
    model_manifest.parent.mkdir(parents=True)
    model_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "model-abc",
                "validation": {"model": {"roc_auc": 0.71, "brier": 0.14}},
            }
        ),
        encoding="utf-8",
    )
    run_dir = settings.artifacts_dir / "runs" / "run-current"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-current",
                "tracking_run_id": "run-current",
                "scenario_version": "scenario-abc",
                "model_version": "model-abc",
                "results": [
                    {
                        "comparison": "data_drift",
                        "window_index": 2,
                        "alerts": [
                            {"type": "feature_drift", "severity": "warning", "condition": "PSI"}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scenario_path = settings.data_dir / "scenarios/evaluation.json"
    scenario_path.parent.mkdir(parents=True)
    scenario_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scenario_version": "scenario-abc",
                "model_version": "model-abc",
                "gate": {"minimum_brier_increase_exclusive": 0.02},
                "paired_effects": [{"brier_difference": 0.08}],
                "results": [
                    {"scenario": "invalid", "window_index": 0, "status": "contract_rejected"},
                    {
                        "scenario": "stable",
                        "window_index": 2,
                        "status": "available",
                        "metrics": {"roc_auc": 0.72, "brier": 0.13},
                    },
                    {"scenario": "data_drift", "window_index": 2, "status": "labels_unavailable"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.monitoring.reports.recent_runs",
        lambda *_: [
            {
                "run_id": "run-current",
                "run_name": "credit-monitoring",
                "experiment": "credit-monitoring",
                "status": "FINISHED",
                "start_time": 1,
                "metrics": {
                    "resources.duration_seconds": 1.2,
                    "resources.cpu_seconds": 0.1,
                    "resources.rss_peak_bytes": 1000,
                },
            }
        ],
    )

    report = build_report(settings)
    document = (settings.artifacts_dir / "runs/index.html").read_text(encoding="utf-8")

    assert report["drift_run_id"] == "run-current"
    assert all(layer["status"] == "available" for layer in report["layers"].values())
    assert report["scenario_version"] == "scenario-abc"
    assert report["layers"]["resources"]["run_id"] == "run-current"
    assert report["scenario_evaluation_status"] == "available"
    assert {item["scenario"]: item["status"] for item in report["scenario_comparison"]} == {
        "data_drift": "labels_unavailable",
        "invalid": "contract_rejected",
        "stable": "available",
    }
    assert {alert["type"] for alert in report["alerts"]} == {
        "feature_drift",
        "performance_degraded",
        "rejection",
    }
    assert "run-current/summary.json" in document
    assert "../../data/scenarios/evaluation.json" in document
    assert "Comparação de cenários" in document
    assert "0.7200" in document
    assert "ROC AUC" in document
    assert 'aria-label="Quantidade de alertas por tipo"' in document
    assert "<svg" in document
    assert '<p class="available">' in document


def test_report_marks_missing_tracking_and_reports_unavailable(tmp_path, monkeypatch):
    settings = Settings(project_root=tmp_path)

    def unavailable(_):
        raise ConnectionError("offline")

    monkeypatch.setattr("src.monitoring.reports.recent_runs", unavailable)
    report = build_report(settings)
    document = (settings.artifacts_dir / "runs/index.html").read_text(encoding="utf-8")

    assert report["tracking_status"] == "unavailable"
    assert "Indisponível" in document


def test_report_does_not_join_stale_scenario_metrics(tmp_path, monkeypatch):
    settings = Settings(project_root=tmp_path)
    run_dir = settings.artifacts_dir / "runs" / "run-current"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run-current",
                "scenario_version": "scenario-current",
                "model_version": "model-current",
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    scenario_path = settings.data_dir / "scenarios/evaluation.json"
    scenario_path.parent.mkdir(parents=True)
    scenario_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scenario_version": "scenario-old",
                "model_version": "model-old",
                "gate": {"minimum_brier_increase_exclusive": 0.02},
                "paired_effects": [{"brier_difference": 0.8}],
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.monitoring.reports.recent_runs", lambda *_: [])

    report = build_report(settings)

    assert report["scenario_evaluation_status"] == "unavailable"
    assert report["sources"]["scenario_evaluation"] is None
    assert not any(alert["type"] == "performance_degraded" for alert in report["alerts"])
