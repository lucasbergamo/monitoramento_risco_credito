"""Regressões de prontidão e apresentação sem alterar resultados de domínio."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.cli import emit_output, main
from src.utils.config import Settings
from src.utils.logger import configure_logging, get_logger

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "up_code,state,container,expected",
    [
        (0, "running healthy", "fixture", 0),
        (0, "running starting", "fixture", 1),
        (0, "running unhealthy", "fixture", 1),
        (0, "exited unhealthy", "fixture", 1),
        (0, "dead unhealthy", "fixture", 1),
        (0, "running missing", "fixture", 1),
        (0, "running healthy", "", 1),
        (1, "running starting", "fixture", 1),
    ],
)
def test_tracking_gate_rejects_false_success(tmp_path, up_code, state, container, expected):
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        'compose) shift; case "$1" in\n'
        'up) printf "%s\\n" "$*" > "$CALLS"; exit "$UP_CODE" ;;\n'
        'ps) printf "%s" "$CONTAINER" ;; esac ;;\n'
        'inspect) printf "%s" "$STATE" ;;\n'
        "esac\n"
    )
    docker.chmod(0o755)
    calls = tmp_path / "calls"
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        UP_CODE=str(up_code),
        STATE=state,
        CONTAINER=container,
        CALLS=str(calls),
        TRACKING_WAIT_TIMEOUT="180",
    )
    completed = subprocess.run(
        ["sh", str(ROOT / "scripts/wait_tracking.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == expected
    assert "--wait --wait-timeout 180 mlflow" in calls.read_text()
    assert ("MLflow pronto." in completed.stderr) == (expected == 0)
    assert "Aguardando" in completed.stderr


def test_inspect_summary_and_explicit_json(monkeypatch, capsys):
    result = {
        "row_count": 30000,
        "partitions": {"train": {"row_count": 15000}},
        "reference": {"row_count": 5000},
        "production_windows": {"complete_windows": 6},
        "files": {"large-manifest": "preserved"},
    }
    monkeypatch.setattr("src.cli.inspect_dataset", lambda _: result)
    assert main(["inspect-data"]) == 0
    readable = capsys.readouterr().out
    assert "inspect-data: concluído" in readable
    assert "train: 15000 registros" in readable
    assert "large-manifest" not in readable
    assert "dataset_manifest.json" in readable
    assert main(["inspect-data", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == result
    assert "command_started" in captured.err


def test_json_failure_has_no_success_result(monkeypatch, capsys):
    def fail(_):
        raise ConnectionError("PRIVATE_SENTINEL")

    monkeypatch.setattr("src.cli.inspect_dataset", fail)
    assert main(["inspect-data", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "data_command_failed" in captured.err
    assert "PRIVATE_SENTINEL" not in captured.err


def test_operational_alert_fields_and_utf8(capsys):
    configure_logging()
    get_logger().warning(
        "operational_alert",
        feature="pay_amt3",
        scenario="validation",
        window="validation/003",
        condition="PSI 0.30 >= 0.25",
        action="Investigar variáveis",
        record_id="PRIVATE_SENTINEL",
    )
    output = capsys.readouterr().out
    event = json.loads(output)
    assert event["feature"] == "pay_amt3"
    assert event["scenario"] == "validation"
    assert event["window"] == "validation/003"
    assert event["condition"] == "PSI 0.30 >= 0.25"
    assert "variáveis" in output
    assert "PRIVATE_SENTINEL" not in output


def test_data_cli_does_not_import_detector():
    completed = subprocess.run(
        [sys.executable, "-c", "import sys; import src.cli; assert 'evidently' not in sys.modules"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("timeout", ["0", "000", "infinito", "-1"])
def test_tracking_gate_requires_finite_positive_timeout(timeout):
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/wait_tracking.sh")],
        env=dict(os.environ, TRACKING_WAIT_TIMEOUT=timeout),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert "Prazo de prontidão inválido" in result.stderr


@pytest.mark.parametrize("state,expected", [("running healthy", 0), ("running starting", 1)])
def test_status_checks_without_starting_service(tmp_path, state, expected):
    docker = tmp_path / "docker"
    calls = tmp_path / "calls"
    docker.write_text(
        "#!/bin/sh\n"
        'echo "$1 $2" >> "$CALLS"\n'
        'case "$1" in\n'
        'compose) [ "$2" = ps ] || exit 99; echo fixture ;;\n'
        'inspect) echo "$STATE" ;;\nesac\n'
    )
    docker.chmod(0o755)
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/wait_tracking.sh"), "--status"],
        env=dict(
            os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", CALLS=str(calls), STATE=state
        ),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == expected
    assert "compose up" not in calls.read_text()
    assert (result.stdout.strip() == "OK") == (expected == 0)


def test_evaluation_summary_keeps_test_metrics_and_host_relative_path(tmp_path, capsys):
    settings = Settings(project_root=tmp_path)
    result = {
        "model_version": "fixture-model",
        "partition": "test",
        "metrics": {
            "model": {"roc_auc": 0.7659699, "brier": 0.1380891, "recall": 0.3658291},
            "dummy": {"roc_auc": 0.5, "brier": 0.172221, "recall": 0.0},
        },
    }
    emit_output("evaluate", result, settings, json_output=False)
    output = capsys.readouterr().out
    assert "Teste: AUC 0.7660; Brier 0.1381; Recall 0.3658" in output
    assert "Baseline no teste: AUC 0.5000" in output
    assert "Artefato: models/evaluations/fixture-model.json" in output
    assert str(tmp_path) not in output
    emit_output("evaluate", result, settings, json_output=True)
    assert json.loads(capsys.readouterr().out) == result
