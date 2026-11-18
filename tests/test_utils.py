"""Contratos de configuração, reprodutibilidade e saneamento de logs."""

import json
import random

import numpy as np
import pytest
from pydantic import ValidationError

from src.utils.config import Settings
from src.utils.logger import configure_logging, get_logger
from src.utils.reproducibility import set_seed


def test_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, project_root=tmp_path / "project")
    assert settings.data_dir == tmp_path / "project" / "data"
    assert settings.models_dir == tmp_path / "project" / "models"
    assert settings.state_dir == tmp_path / "project" / "state"
    assert settings.artifacts_dir == tmp_path / "project" / "artifacts"


def test_explicit_config_overrides_environment_and_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SEED=12\n")
    monkeypatch.setenv("SEED", "15")
    assert Settings(_env_file=env_file, seed=21).seed == 21
    assert Settings(_env_file=env_file).seed == 15
    monkeypatch.delenv("SEED")
    assert Settings(_env_file=env_file).seed == 12


@pytest.mark.parametrize(
    "overrides",
    [
        {"seed": -1},
        {"seed": 2**32},
        {"log_level": "INVALID"},
        {"mlflow_tracking_uri": "file:///tmp/store"},
        {"mlflow_tracking_uri": "http://"},
        {"project_root": "relative"},
        {"mlflow_tracking_uri": "sqlite://server/store"},
        {"unknown_option": True},
        {"mlflow_ui_uri": "sqlite:///tmp/store"},
    ],
)
def test_invalid_config_fails(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_unknown_dotenv_key_is_an_error(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TYPO_SEED=42\n")
    with pytest.raises(ValidationError, match="Extra inputs"):
        Settings(_env_file=env_file)


def test_credentials_are_not_repeated_in_diagnostic():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, mlflow_tracking_uri="http://user:test-secret@localhost:5000")
    assert "test-secret" not in str(error.value)
    assert "MLFLOW_TRACKING_URI" in str(error.value)


def test_logging_discards_payloads_and_secrets(capsys):
    configure_logging()
    get_logger().info(
        "environment_checked",
        row_count=100,
        password="test-secret",
        payload={"record_id": "private-record"},
        exc_info=ValueError("private-error"),
    )
    output = capsys.readouterr().out
    event = json.loads(output)
    assert event["event"] == "environment_checked"
    assert event["row_count"] == 100
    assert event["level"] == "info"
    assert "timestamp" in event
    for forbidden in ("test-secret", "private-record", "private-error"):
        assert forbidden not in output


def test_log_level_filters_debug(capsys):
    configure_logging("WARNING")
    get_logger().debug("debug_hidden")
    assert capsys.readouterr().out == ""


def test_seed_repeats_independent_and_legacy_generators():
    first = set_seed(42)
    expected = (first.random(4), np.random.random(4), random.random())
    second = set_seed(42)
    actual = (second.random(4), np.random.random(4), random.random())
    np.testing.assert_array_equal(actual[0], expected[0])
    np.testing.assert_array_equal(actual[1], expected[1])
    assert actual[2] == expected[2]


@pytest.mark.parametrize("seed", [-1, 2**32, True, 1.5])
def test_seed_rejects_invalid_values(seed):
    with pytest.raises(ValueError, match="seed deve"):
        set_seed(seed)
