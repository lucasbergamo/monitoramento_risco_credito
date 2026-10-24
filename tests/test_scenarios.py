"""Simulação completa com modelo e dados gerados durante os testes."""

import shutil
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import structlog
from pydantic import ValidationError

from src.cli import main
from src.data.contracts import ContractRejected, validate_batch
from src.data.prepare import FEATURES, PAY_COLUMNS, TARGET
from src.models.registry import promote
from src.models.train import train
from src.simulation.scenarios import (
    SCENARIOS,
    ScenarioConfig,
    evaluate_scenarios,
    invalid_batch,
    load_scenario_config,
    simulate,
    transform_features,
)
from src.utils.config import Settings, load_data_config
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest


@pytest.fixture(autouse=True)
def isolated_logging():
    # A CLI configura estado global; capturas de outros testes não podem vazar.
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


@pytest.fixture(scope="module")
def simulation_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("simulation")
    settings = Settings(_env_file=None, project_root=root)
    shutil.copytree(Path(__file__).parents[1] / "configs", root / "configs")
    rng = np.random.default_rng(42)
    config = load_data_config()
    schema = {name: "int64" for name in FEATURES}
    manifest = {
        "schema_version": 1,
        "feature_names": FEATURES,
        "schema": schema,
        "schema_hash": content_hash(schema),
        "source_sha256": config.source_sha256,
        "split_seed": 42,
        "split_hash": "a" * 64,
        "parser_version": config.parser_version,
        "effective_config": config.model_dump(),
        "config_hash": content_hash(config.model_dump()),
        "partitions": {},
        "files": {},
        "production_windows": {"complete_windows": 4, "window_size": 128},
    }
    offset = 0
    for name, count in [
        ("train", 900),
        ("validation", 400),
        *[(f"windows/{j:03d}", 128) for j in range(4)],
    ]:
        x = pd.DataFrame({key: rng.integers(1, 10000, count) for key in FEATURES})
        for key in PAY_COLUMNS:
            x[key] = rng.integers(-2, 5, count)
        y = ((x.pay_0 >= 3) | (x.pay_2 >= 3)).astype("int64")
        y = y ^ (rng.random(count) < 0.03).astype("int64")
        keys = pd.DataFrame(
            {
                "record_id": np.arange(offset, offset + count),
                "group_id": [f"g-{i}" for i in range(offset, offset + count)],
            }
        )
        labels = pd.DataFrame({"record_id": keys.record_id, TARGET: y})
        for kind, table in (("features", x), ("keys", keys), ("labels", labels)):
            relative = f"gold/{name}/{kind}.parquet"
            path = settings.data_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            table.to_parquet(path, index=False)
            manifest["files"][relative] = file_hash(path)
        manifest["partitions"][name] = {"row_count": count}
        offset += count
    write_manifest(settings.data_dir / "gold/dataset_manifest.json", manifest)
    assert train(settings)["gate_passed"]
    promote(settings)
    return root


@pytest.fixture
def simulation(simulation_root, tmp_path):
    shutil.copytree(simulation_root, tmp_path, dirs_exist_ok=True, symlinks=True)
    return Settings(_env_file=None, project_root=tmp_path)


def test_complete_generation_reexecution_and_evaluation(simulation):
    original = {
        str(p): file_hash(p) for p in (simulation.data_dir / "gold").rglob("*") if p.is_file()
    }
    model = (simulation.models_dir / "current").resolve()
    model_hashes = {p.name: file_hash(p) for p in model.iterdir()}
    first = simulate(simulation)
    assert first == simulate(simulation)
    assert set(entry["scenario"] for entry in first["windows"]) == set(SCENARIOS)
    assert (
        len(first["windows"]) == 13
    )  # Controle, entradas e alvo por janela; inválido só na primeira.
    assert len(first["drift_features"]) == 2
    current = simulation.data_dir / "scenarios/current"
    for j in range(4):
        stable, concept, drift = (
            current / scenario / f"{j:03d}"
            for scenario in ("stable", "concept_drift", "data_drift")
        )
        assert file_hash(stable / "features.parquet") == file_hash(concept / "features.parquet")
        assert file_hash(stable / "scores.parquet") == file_hash(concept / "scores.parquet")
        assert not (drift / "labels.parquet").exists()
        x = pd.read_parquet(stable / "features.parquet")
        xd = pd.read_parquet(drift / "features.parquet")
        unchanged = [key for key in FEATURES if key not in first["drift_features"]]
        pd.testing.assert_frame_equal(x[unchanged], xd[unchanged])
    assert file_hash(current / "stable/000/labels.parquet") == file_hash(
        current / "concept_drift/000/labels.parquet"
    )
    assert not (current / "invalid/000/scores.parquet").exists()
    report = evaluate_scenarios(simulation)
    assert report == evaluate_scenarios(simulation)
    assert len(report["paired_effects"]) == 4
    assert all(
        item["status"] == "labels_unavailable" and item["metrics"] is None
        for item in report["results"]
        if item["scenario"] == "data_drift"
    )
    last = report["paired_effects"][-1]
    assert report["gate_passed"] == (
        last["brier_difference"] > 0.02 and last["brier_difference_ci95"][0] > 0
    )
    assert {
        str(p): file_hash(p) for p in (simulation.data_dir / "gold").rglob("*") if p.is_file()
    } == original
    assert {p.name: file_hash(p) for p in model.iterdir()} == model_hashes
    assert str(simulation.project_root) not in str(report)
    assert "record_id" not in report
    assert "scores" not in report and "latent" not in report


def test_invalid_and_isolated_rules_block_before_model(simulation):
    x = pd.read_parquet(simulation.data_dir / "gold/windows/000/features.parquet")
    keys = pd.read_parquet(simulation.data_dir / "gold/windows/000/keys.parquet")
    bad_x, bad_keys = invalid_batch(x, keys)
    with pytest.raises(ContractRejected) as error:
        validate_batch(bad_x, bad_keys)
    assert {v.rule for v in error.value.result.violations} >= {
        "not_null",
        "unique_id",
        "nonnegative_payment",
    }
    for features, identifiers in (
        (bad_x.assign(pay_amt1=x.pay_amt1), keys),
        (x, bad_keys),
        (x.assign(pay_amt1=bad_x.pay_amt1), keys),
    ):
        with patch(
            "src.models.predict.load_bundle", side_effect=AssertionError("inference called")
        ):
            from src.models.predict import predict_batch

            with pytest.raises(ContractRejected):
                predict_batch(features, identifiers, simulation.models_dir / "current")


def test_transformation_formulas_and_rounding():
    x = pd.DataFrame({key: pd.Series([1, 2, 3], dtype="int64") for key in FEATURES})
    x["pay_0"] = [7, -2, 2]
    config = ScenarioConfig()
    iqr = {key: 4.0 for key in FEATURES}
    result = transform_features(x, ["pay_0", "limit_bal"], 1, iqr, config)
    assert result.pay_0.tolist() == [8, 1, 5]
    assert result.limit_bal.tolist() == [3, 6, 9]
    result = transform_features(x, ["bill_amt1", "pay_amt1"], 0.5, iqr, config)
    assert result.bill_amt1.tolist() == [5, 6, 7]
    assert result.pay_amt1.tolist() == [5, 6, 7]
    assert result.dtypes.equals(x.dtypes)
    pd.testing.assert_frame_equal(transform_features(x, ["pay_0", "limit_bal"], 0, iqr, config), x)
    with pytest.raises(ValueError):
        transform_features(x, ["pay_0", "pay_0"], 1, iqr, config)


def test_corruption_and_failure_preserve_current(simulation):
    manifest = simulate(simulation)
    pointer = (simulation.data_dir / "scenarios/current").resolve()
    source = simulation.data_dir / "gold/windows/001/features.parquet"
    source.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Integridade"):
        simulate(simulation)
    assert (simulation.data_dir / "scenarios/current").resolve() == pointer
    (pointer / "concept_drift/003/labels.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Integridade"):
        evaluate_scenarios(simulation)
    assert read_manifest(pointer / "manifest.json") == manifest


def test_cli_and_config(simulation, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_ROOT", str(simulation.project_root))
    monkeypatch.setenv("SEED", "123")
    assert main(["simulate", "--data-dir", "data", "--models-dir", "models"]) == 0
    report = evaluate_scenarios(simulation)
    assert main(["evaluate-scenarios"]) == (0 if report["gate_passed"] else 2)
    assert "scenarios_generated" in capsys.readouterr().out
    monkeypatch.setattr("src.cli.evaluate_scenarios", lambda _: {"gate_passed": False})
    assert main(["evaluate-scenarios"]) == 2
    monkeypatch.setattr("src.cli.simulate", lambda _: (_ for _ in ()).throw(OSError("private")))
    assert main(["simulate"]) == 1
    output = capsys.readouterr().out
    assert "scenario_command_failed" in output
    assert "private" not in output
    assert load_scenario_config().shock_seed == 42
    for changes in (
        {"shock_seed": 43},
        {"unknown": 1},
        {"maximum_shock": 0.5},
        {"bootstrap_resamples": 10},
        {"minimum_brier_increase": 0.01},
    ):
        with pytest.raises(ValidationError):
            ScenarioConfig.model_validate(ScenarioConfig().model_dump() | changes)
