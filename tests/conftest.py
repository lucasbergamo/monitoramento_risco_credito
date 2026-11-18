"""CLI unit tests use isolated operations; tracking integration is tested separately."""

import pytest
import structlog


@pytest.fixture(autouse=True)
def avoid_tracking_side_effects_for_cli_tests(monkeypatch):
    """Keep existing command tests independent of an external MLflow server."""
    monkeypatch.setattr(
        "src.cli.track_operation",
        lambda _settings, _command, operation: operation(),
    )


@pytest.fixture(autouse=True)
def reset_logging():
    """Isolate process-wide logging configuration between captured tests."""
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()
