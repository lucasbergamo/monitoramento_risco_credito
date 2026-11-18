"""Campanhas isoladas, vínculo real com MLflow e falhas sem falso sucesso."""

import json
import os

import pytest
from mlflow import MlflowClient

from src.monitoring.tracking import TrackingError, track_operation
from src.pipeline import PipelineStageError, run_pipeline, verify_evidence
from src.utils.config import Settings
from src.utils.manifest import content_hash, write_manifest


@pytest.fixture(autouse=True)
def isolated_artifacts(tmp_path, monkeypatch):
    """Keep embedded MLflow artifacts inside each test temporary directory."""
    monkeypatch.chdir(tmp_path)


def setup_campaign_root(root):
    settings = Settings(
        _env_file=None,
        project_root=root,
        mlflow_tracking_uri=f"sqlite:///{root / 'tracking.db'}",
    )
    (root / "configs").mkdir()
    for name in ("project", "model", "scenarios", "monitoring"):
        (root / "configs" / f"{name}.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    write_manifest(settings.data_dir / "gold/dataset_manifest.json", {"schema_version": 1})
    write_manifest(
        settings.models_dir / "current/manifest.json",
        {"schema_version": 1, "version": "model-v1"},
    )
    return settings


def install_fake_stages(monkeypatch, settings, *, invalid_status="contract_rejected"):
    from src import pipeline

    scenario_manifest = {"schema_version": 1, "files": {}, "window_count": 1}
    version = content_hash(scenario_manifest)
    windows = [
        {"scenario": name, "window_index": 0}
        for name in ("stable", "invalid", "data_drift", "concept_drift")
    ]
    write_manifest(
        settings.data_dir / "scenarios/versions" / version / "manifest.json",
        scenario_manifest | {"version": version},
    )
    (settings.data_dir / "scenarios/current").symlink_to(
        settings.data_dir / "scenarios/versions" / version, target_is_directory=True
    )

    monkeypatch.setattr(
        pipeline,
        "simulate",
        lambda _settings: {"version": version, "windows": windows},
    )

    def fake_evaluate(_settings):
        result = {
            "schema_version": 1,
            "scenario_version": version,
            "model_version": "model-v1",
            "gate_passed": True,
            "paired_effects": [{"brier_difference": 0.1}],
            "results": [
                {
                    "scenario": name,
                    "window_index": 0,
                    "status": invalid_status
                    if name == "invalid"
                    else "labels_unavailable"
                    if name == "data_drift"
                    else "available",
                    "labels_origin": {
                        "stable": "observed",
                        "invalid": "unavailable",
                        "data_drift": "unavailable",
                        "concept_drift": "synthetic_external_shock",
                    }[name],
                    "metrics": None if name in {"invalid", "data_drift"} else {"brier": 0.1},
                }
                for name in ("stable", "invalid", "data_drift", "concept_drift")
            ],
        }
        write_manifest(settings.data_dir / "scenarios/evaluation.json", result)
        return result

    monkeypatch.setattr(pipeline, "evaluate_scenarios", fake_evaluate)

    def fake_detect(_settings):
        result = {
            "schema_version": 1,
            "run_id": "drift-run-v1",
            "scenario_version": version,
            "model_version": "model-v1",
            "gate_passed": True,
            "results": [
                {
                    "comparison": "data_drift",
                    "window_index": 0,
                    "features": [{} for _ in range(19)],
                    "alerts": [],
                }
            ],
        }
        write_manifest(settings.artifacts_dir / "runs/drift-run-v1/summary.json", result)
        return result

    monkeypatch.setattr(pipeline, "detect", fake_detect)


def test_campaign_runs_are_explicit_verified_and_coexist(tmp_path, monkeypatch):
    settings = setup_campaign_root(tmp_path)
    install_fake_stages(monkeypatch, settings)

    first = run_pipeline(settings, campaign_id="campaign001")
    second = run_pipeline(settings, campaign_id="campaign002")
    assert first["status"] == second["status"] == "completed"
    assert first["run_ids"] != second["run_ids"]
    assert verify_evidence(settings, "campaign001")["status"] == "verified"
    assert verify_evidence(settings, "campaign002")["status"] == "verified"
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    for run_id in first["run_ids"].values():
        run = client.get_run(run_id)
        assert run.data.tags["campaign_id"] == "campaign001"
        assert run.info.status == "FINISHED"
    assert (settings.artifacts_dir / "campaigns/campaign001/manifest.json").is_file()
    assert (settings.artifacts_dir / "campaigns/campaign002/manifest.json").is_file()


def test_invalid_batch_must_be_rejected_and_campaign_failure_persists(tmp_path, monkeypatch):
    settings = setup_campaign_root(tmp_path)
    install_fake_stages(monkeypatch, settings, invalid_status="available")

    with pytest.raises(ValueError, match="Rejeição esperada"):
        run_pipeline(settings, campaign_id="badcampaign001")
    failed = json.loads(
        (settings.artifacts_dir / "campaigns/badcampaign001/manifest.json").read_text()
    )
    assert failed["status"] == "failed"
    assert failed["error_type"] == "ValueError"
    with pytest.raises(ValueError, match="incompleta"):
        verify_evidence(settings, "badcampaign001")


def test_evidence_hash_tampering_fails_closed(tmp_path, monkeypatch):
    settings = setup_campaign_root(tmp_path)
    install_fake_stages(monkeypatch, settings)
    run_pipeline(settings, campaign_id="campaign003")
    summary = settings.artifacts_dir / "campaigns/campaign003/drift_summary.json"
    summary.write_text('{"schema_version":1}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Hash"):
        verify_evidence(settings, "campaign003")


def test_tracking_failure_is_safe_and_persisted(tmp_path, monkeypatch):
    from src import pipeline

    settings = setup_campaign_root(tmp_path)

    def unavailable(*_args, **_kwargs):
        raise TrackingError("offline")

    monkeypatch.setattr(pipeline, "track_operation", unavailable)

    with pytest.raises(PipelineStageError) as error:
        run_pipeline(settings, campaign_id="trackingfailure001")
    assert error.value.failure_code == "tracking_unavailable"
    failed = json.loads(
        (settings.artifacts_dir / "campaigns/trackingfailure001/manifest.json").read_text()
    )
    assert failed["failed_stage"] == "simulate"
    assert failed["failure_code"] == "tracking_unavailable"


def test_missing_input_manifest_marks_campaign_failed(tmp_path):
    settings = setup_campaign_root(tmp_path)
    (settings.data_dir / "gold/dataset_manifest.json").unlink()

    with pytest.raises(PipelineStageError) as error:
        run_pipeline(settings, campaign_id="missingmanifest001")

    assert error.value.stage == "prepare-evidence"
    assert error.value.failure_code == "stage_failed"
    failed = json.loads(
        (settings.artifacts_dir / "campaigns/missingmanifest001/manifest.json").read_text()
    )
    assert failed["status"] == "failed"
    assert failed["failed_stage"] == "prepare-evidence"
    assert failed["error_type"] == "FileNotFoundError"


def test_data_or_model_stage_failure_propagates_safe_diagnostic(tmp_path, monkeypatch):
    from src import pipeline

    settings = setup_campaign_root(tmp_path)
    install_fake_stages(monkeypatch, settings)
    monkeypatch.setattr(
        pipeline,
        "simulate",
        lambda _settings: (_ for _ in ()).throw(ValueError("sensitive source detail")),
    )

    with pytest.raises(PipelineStageError, match="Falha operacional") as error:
        run_pipeline(settings, campaign_id="sourcefailure001")
    assert error.value.stage == "simulate"
    assert error.value.failure_code == "stage_failed"
    assert "sensitive" not in str(error.value)


def test_http_tracking_service_when_configured(tmp_path):
    uri = os.getenv("TC4_TRACKING_INTEGRATION_URI")
    if not uri:
        pytest.skip("Serviço temporário de tracking não configurado")
    settings = Settings(_env_file=None, project_root=tmp_path, mlflow_tracking_uri=uri)
    result = track_operation(
        settings,
        "demo-integration",
        lambda: {"status": "fixture", "count": 4},
        tags={"campaign_id": "integration001"},
    )
    client = MlflowClient(tracking_uri=uri)
    run = client.get_run(result["tracking_run_id"])
    assert run.info.status == "FINISHED"
    assert run.data.tags["campaign_id"] == "integration001"
    assert run.data.metrics["demo-integration.count"] == 4
