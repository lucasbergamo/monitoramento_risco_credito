"""Regressões da fronteira Evidently real e da regra operacional."""

import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import structlog
from pydantic import ValidationError

from src.cli import main
from src.data.contracts import ContractRejected
from src.data.prepare import FEATURES, PAY_COLUMNS, TARGET
from src.monitoring.alerts import feature_alerts, holm_adjust
from src.monitoring.drift import (
    MonitoringConfig,
    detect_drift,
    extract_scores,
    load_monitoring_config,
)


@pytest.fixture(autouse=True)
def isolated_logging():
    # A CLI de outros módulos pode manter um stream de captura já encerrado.
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


@pytest.fixture
def frames():
    rng = np.random.default_rng(42)
    frame = pd.DataFrame(
        {
            name: rng.choice([-2, 0, 1], 300)
            if name in PAY_COLUMNS
            else rng.integers(1, 10000, 300)
            for name in FEATURES
        }
    )
    return frame, frame.copy()


def compare(frames, tmp_path):
    return detect_drift(*frames, tmp_path / "report", run_id="synthetic", window="000")


def by_name(result):
    return {r["feature"]: r for r in result["features"]}


def test_identical_real_snapshot_and_semantic_extraction(frames, tmp_path):
    result = compare(frames, tmp_path)
    assert len(result["features"]) == 19
    assert not result["alerts"]
    assert not any(r["report_drift"] for r in result["features"])
    assert "<html" in (tmp_path / "report/evidently.html").read_text().lower()
    payload = json.loads((tmp_path / "report/evidently.json").read_text())
    payload["metrics"].reverse()
    for item in payload["metrics"]:
        item["id"] = "opaque-id-may-change"
        item["metric_name"] = "display-name-may-change"
    assert extract_scores(payload, load_monitoring_config()) == {
        r["feature"]: r["score"] for r in result["features"]
    }
    payload["metrics"].append(payload["metrics"][0])
    with pytest.raises(ValueError, match="Semântica"):
        extract_scores(payload, load_monitoring_config())


def test_known_shift_and_alert_metadata(frames, tmp_path):
    ref, cur = frames
    cur["pay_0"] = 8
    cur["limit_bal"] += 100000
    result = compare((ref, cur), tmp_path)
    rows = by_name(result)
    assert {r["feature"] for r in result["alerts"]} == {"pay_0", "limit_bal"}
    assert rows["pay_0"]["p_raw"] is None
    assert rows["pay_0"]["score_unit"] == "PSI"
    assert rows["limit_bal"]["ks_d"] == 1
    assert rows["limit_bal"]["p_adjusted"] < 0.01
    assert rows["limit_bal"]["numeric_family_size"] == 13
    assert all(r["severity"] == "warning" and r["action"] for r in result["alerts"])
    assert all(r["condition"] for r in result["alerts"])
    assert any("PSI" in r["condition"] for r in result["alerts"])
    assert any("p-Holm" in r["condition"] for r in result["alerts"])
    duplicate = feature_alerts(result["features"] * 2, "synthetic", "000")
    assert duplicate == result["alerts"]
    assert feature_alerts(result["features"], "another", "000")[0]["key"] != duplicate[0]["key"]


def test_constant_and_absent_categories(frames, tmp_path):
    ref, cur = frames
    ref.loc[:, :] = 1
    cur.loc[:, :] = 1
    result = compare((ref, cur), tmp_path)
    assert not result["alerts"]
    assert all(r["score"] == (0 if r["type"] == "categorical" else 1) for r in result["features"])
    cur["pay_0"] = 8
    shifted = detect_drift(ref, cur, tmp_path / "shift", run_id="s", window="1")
    row = by_name(shifted)["pay_0"]
    # União das categorias, zero substituído por 0.0001 em cada distribuição.
    expected = 2 * (1 - 0.0001) * np.log(1 / 0.0001)
    assert row["score"] == pytest.approx(expected)
    assert row["operational_alert"]


def test_metadata_and_labels_never_enter_report(frames, tmp_path):
    ref, cur = frames
    for column in ("record_id", TARGET, "U", "r", "window_index", "score", "sex", "age"):
        ref[column] = "PRIVATE_SENTINEL_REFERENCE"
        cur[column] = "PRIVATE_SENTINEL_CHANGED_LABEL"
    result = compare((ref, cur), tmp_path)
    assert not result["alerts"]
    for name in ("evidently.html", "evidently.json", "normalized.json"):
        content = (tmp_path / "report" / name).read_text()
        assert "PRIVATE_SENTINEL" not in content
    assert {r["feature"] for r in result["features"]} == set(FEATURES)


@pytest.mark.parametrize("size", [0, 1, 19])
def test_insufficient_sample_is_error(frames, tmp_path, size):
    ref, cur = frames
    with pytest.raises(ValueError, match="Amostra insuficiente"):
        compare((ref, cur.iloc[:size]), tmp_path)
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("fault", ["missing", "duplicate", "null", "infinite"])
def test_invalid_feature_input(frames, tmp_path, fault):
    ref, cur = frames
    if fault == "missing":
        cur = cur.drop(columns="pay_0")
    elif fault == "duplicate":
        cur = pd.concat([cur, cur[["pay_0"]]], axis=1)
    elif fault == "null":
        cur.loc[0, "limit_bal"] = np.nan
    else:
        cur["limit_bal"] = np.inf
    with pytest.raises((ValueError, ContractRejected)):
        compare((ref, cur), tmp_path)


def test_holm_family_step_down_and_ties():
    assert holm_adjust({"c": 0.03, "a": 0.001, "b": 0.02, "d": 1}) == {
        "a": 0.004,
        "b": 0.06,
        "c": 0.06,
        "d": 1,
    }
    assert holm_adjust({"a": 0.01, "b": 0.01}) == {"a": 0.02, "b": 0.02}
    assert holm_adjust({}) == {}
    with pytest.raises(ValueError):
        holm_adjust({"a": float("nan")})


def test_report_significance_without_operational_magnitude(tmp_path):
    # Amostra grande: diferença pequena mas significativa, D continua abaixo de 0.10.
    ref = pd.DataFrame({name: np.ones(10000, dtype=int) for name in FEATURES})
    cur = ref.copy()
    cur.loc[:499, "limit_bal"] = 2
    row = by_name(compare((ref, cur), tmp_path))["limit_bal"]
    assert row["report_drift"]
    assert row["p_adjusted"] < 0.01
    assert row["ks_d"] == pytest.approx(0.05)
    assert not row["operational_alert"]


def test_policy_strict_and_cli_status(capsys):
    with pytest.raises(ValidationError):
        MonitoringConfig(numerical_threshold=0.05)
    with pytest.raises(ValidationError):
        MonitoringConfig(unknown=True)
    for gate, code in [(True, 0), (False, 2)]:
        with patch(
            "src.cli.detect", return_value={"run_id": "test", "gate_passed": gate, "results": []}
        ):
            assert main(["detect"]) == code
    with patch("src.cli.detect", side_effect=ValueError("PRIVATE_SENTINEL")):
        assert main(["detect"]) == 1
    assert "PRIVATE_SENTINEL" not in capsys.readouterr().out
