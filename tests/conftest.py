"""CLI unit tests use isolated operations; tracking integration is tested separately."""

import pytest


@pytest.fixture(autouse=True)
def avoid_tracking_side_effects_for_cli_tests(monkeypatch):
    """Keep existing command tests independent of an external MLflow server."""
    monkeypatch.setattr(
        "src.cli.track_operation",
        lambda _settings, _command, operation: operation(),
    )
