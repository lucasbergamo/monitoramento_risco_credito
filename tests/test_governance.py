"""Métricas de grupos com fixtures próprias e retenção contida ao estado gerado."""

import json
import os
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from scripts.retention import _delete_candidates, plan_retention
from src.governance import MIN_CLASS_SIZE, MIN_GROUP_SIZE, _metrics, governance
from src.utils.config import Settings
from src.utils.manifest import file_hash


def test_group_metric_denominators_and_suppression():
    labels = np.array([1] * MIN_CLASS_SIZE + [0] * (MIN_GROUP_SIZE - MIN_CLASS_SIZE))
    scores = np.array([0.8] * MIN_CLASS_SIZE + [0.4] * (MIN_GROUP_SIZE - MIN_CLASS_SIZE))
    result = _metrics(labels, scores, 0.5)
    assert result["n"] == MIN_GROUP_SIZE
    assert result["prevalence"] == {
        "value": MIN_CLASS_SIZE / MIN_GROUP_SIZE,
        "numerator": MIN_CLASS_SIZE,
        "denominator": MIN_GROUP_SIZE,
        "status": "available",
    }
    assert result["recall"]["numerator"] == result["recall"]["denominator"] == MIN_CLASS_SIZE
    assert result["false_positive_rate"]["numerator"] == 0
    assert result["false_positive_rate"]["denominator"] == MIN_GROUP_SIZE - MIN_CLASS_SIZE
    assert result["brier"]["denominator"] == MIN_GROUP_SIZE

    small = _metrics([1] * (MIN_GROUP_SIZE - 1), [0.8] * (MIN_GROUP_SIZE - 1), 0.5)
    assert small["prevalence"]["value"] is None
    assert small["recall"]["value"] is None
    assert small["brier"]["value"] is None
    few_positives = _metrics([1] * (MIN_CLASS_SIZE - 1) + [0] * 100, [0.8] * 119, 0.5)
    assert few_positives["recall"]["value"] is None
    assert few_positives["false_positive_rate"]["value"] is not None


def test_governance_uses_separate_features_and_audit_table(tmp_path, monkeypatch):
    import src.governance as governance_module
    from src.data.prepare import FEATURES, TARGET

    settings = Settings(_env_file=None, project_root=tmp_path)
    audit_path = settings.data_dir / "silver/audit.parquet"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    ids = np.arange(400)
    audit = pd.DataFrame(
        {
            "record_id": ids,
            "sex": np.where(np.arange(len(ids)) % 2, 1, 2),
            "education": 1,
            "marriage": 1,
            "age": np.resize(np.array([25, 40, 60, 19]), len(ids)),
        }
    )
    audit.to_parquet(audit_path, index=False)
    data_manifest = {
        "files": {
            "silver/audit.parquet": file_hash(audit_path),
            "gold/test/features.parquet": "a" * 64,
            "gold/test/keys.parquet": "b" * 64,
            "gold/test/labels.parquet": "c" * 64,
        }
    }
    features = pd.DataFrame({name: np.zeros(len(ids)) for name in FEATURES})
    keys = pd.DataFrame({"record_id": ids, "group_id": [f"g-{i}" for i in ids]})
    labels = pd.DataFrame({"record_id": ids, TARGET: np.resize([0, 1], len(ids))})

    class Model:
        def predict_proba(self, values):
            assert values.columns.tolist() == FEATURES
            assert not {"sex", "age", "education", "marriage"}.intersection(values.columns)
            positive = np.resize([0.3, 0.7], len(values))
            return np.column_stack([1 - positive, positive])

    monkeypatch.setattr(governance_module, "verify_dataset", lambda _settings: data_manifest)
    monkeypatch.setattr(
        governance_module,
        "load_partition",
        lambda *_args: (
            features,
            keys,
            labels,
            {
                key: value
                for key, value in data_manifest["files"].items()
                if key.startswith("gold/test/")
            },
        ),
    )
    monkeypatch.setattr(
        governance_module,
        "load_bundle",
        lambda _path: (
            {"model": Model()},
            {
                "version": "v1",
                "model_sha256": "d" * 64,
                "effective_config": {"threads": 1, "decision_threshold": 0.5},
            },
        ),
    )

    report = governance(settings)
    assert report["partition"] == "test"
    assert report["row_count"] == 400
    assert report["demographic_fields_used_as_features"] == []
    assert report["groups"]["sex"][0]["n"] == 200
    assert [group["group"] for group in report["groups"]["age_band"]] == [
        "21-34",
        "35-49",
        "50+",
        "outside_defined_bands",
    ]
    assert report["groups"]["age_band"][-1]["n"] == 100
    evidence = json.loads((settings.project_root / "docs/evidencias/governanca.json").read_text())
    assert evidence == report
    assert TARGET not in report["demographic_fields_used_for_grouping"]
    assert not any("record_id" in group for groups in report["groups"].values() for group in groups)


def test_retention_dry_run_is_confined_and_delete_requires_explicit_call(tmp_path):
    now = datetime(2026, 10, 28, tzinfo=UTC)
    old = tmp_path / "artifacts/runs/old-run"
    old.mkdir(parents=True)
    summary = old / "summary.json"
    summary.write_text('{"schema_version":1}\n')
    old_timestamp = now.timestamp() - 31 * 86400
    os.utime(summary, (old_timestamp, old_timestamp))
    os.utime(old, (old_timestamp, old_timestamp))

    external = tmp_path.parent / f"{tmp_path.name}-outside"
    external.mkdir()
    (external / "keep.txt").write_text("preserve")
    (tmp_path / "artifacts/runs/external-link").symlink_to(external, target_is_directory=True)

    planned = plan_retention(tmp_path, now=now)
    assert planned == [{"path": "artifacts/runs/old-run", "age_days": 31}]
    assert old.exists()
    assert (external / "keep.txt").exists()
    deleted = _delete_candidates(tmp_path, planned)
    assert deleted == ["artifacts/runs/old-run"]
    assert not old.exists()
    assert (external / "keep.txt").read_text() == "preserve"


def test_retention_rejects_external_root_and_unexpected_delete_path(tmp_path):
    root = tmp_path / "project"
    external = tmp_path / "outside"
    external.mkdir()
    root.mkdir()
    (root / "artifacts").mkdir()
    (root / "artifacts/runs").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="sai da raiz"):
        plan_retention(root)
    safe_root = tmp_path / "safe-project"
    (safe_root / "artifacts/runs").mkdir(parents=True)
    with pytest.raises(ValueError, match="fora do escopo"):
        _delete_candidates(safe_root, [{"path": "data/gold/test", "age_days": 99}])
