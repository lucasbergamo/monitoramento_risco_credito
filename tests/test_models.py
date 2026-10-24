"""Fixtures treinadas no teste, leakage e promoção sem escrita parcial."""

import copy
import shutil
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from src.cli import main
from src.data.contracts import ContractRejected
from src.data.prepare import FEATURES, PAY_COLUMNS, TARGET
from src.models.evaluate import evaluate, metrics, validation_gate
from src.models.predict import predict_batch
from src.models.registry import PromotionRejected, load_bundle, promote
from src.models.train import (
    ModelConfig,
    load_model_config,
    load_partition,
    select_drift_features,
    train,
    verify_dataset,
)
from src.utils.config import Settings, load_data_config
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("trained")
    settings = Settings(_env_file=None, project_root=root)
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
    }
    offset = 0
    for name, count in (("train", 900), ("validation", 400), ("test", 400)):
        features = pd.DataFrame({key: rng.integers(1, 10000, count) for key in FEATURES})
        for key in PAY_COLUMNS:
            features[key] = rng.integers(-2, 5, count)
        labels = ((features.pay_0 >= 2) | (features.pay_2 >= 2)).astype("int64")
        labels = labels ^ (rng.random(count) < 0.03).astype("int64")
        keys = pd.DataFrame(
            {
                "record_id": np.arange(offset, offset + count),
                "group_id": [f"group-{i}" for i in range(offset, offset + count)],
            }
        )
        target = pd.DataFrame({"record_id": keys.record_id, TARGET: labels})
        for kind, table in (("features", features), ("keys", keys), ("labels", target)):
            path = settings.data_dir / f"gold/{name}/{kind}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            table.to_parquet(path, index=False)
            manifest["files"][f"gold/{name}/{kind}.parquet"] = file_hash(path)
        manifest["partitions"][name] = {"row_count": count}
        offset += count
    # Produção, referência individual e demografia não existem nesta fixture.
    write_manifest(settings.data_dir / "gold/dataset_manifest.json", manifest)
    (root / "configs").mkdir()
    shutil.copy(Path(__file__).parents[1] / "configs/model.yaml", root / "configs/model.yaml")
    assert train(settings)["gate_passed"]
    return settings


@pytest.fixture
def isolated(trained, tmp_path):
    shutil.copytree(trained.project_root, tmp_path, dirs_exist_ok=True, symlinks=True)
    return Settings(_env_file=None, project_root=tmp_path)


def test_train_validation_selection_and_reproducibility(isolated):
    estimators, manifest = load_bundle(isolated.models_dir / "staging")
    assert manifest["gate_passed"]
    assert manifest["drift_features"] == select_drift_features(
        manifest["permutation_importance"]["features"]
    )
    assert len(manifest["drift_features"]) == 2
    assert manifest["permutation_importance"]["n_repeats"] == 5
    assert all(
        len(item["repeats"]) == 5
        for item in manifest["permutation_importance"]["features"].values()
    )
    assert list(estimators["model"].feature_names_in_) == FEATURES
    assert estimators["model"].get_params()["categorical_features"] is None
    assert set(manifest["input_hashes"]) == {
        f"gold/{part}/{kind}.parquet"
        for part in ("train", "validation")
        for kind in ("features", "keys", "labels")
    }
    shutil.rmtree(isolated.data_dir / "gold/test")
    assert train(isolated) == manifest
    assert str(isolated.project_root) not in str(manifest)


def test_metrics_known_values_and_validation_only_gate():
    actual = metrics([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert actual["roc_auc"] == actual["average_precision"] == 1.0
    assert actual["brier"] == pytest.approx(0.025)
    assert actual["confusion_matrix"] == [[2, 0], [0, 2]]
    assert actual["precision"] == actual["recall"] == actual["f1"] == 1.0
    assert validation_gate({"model": actual, "dummy": {"brier": 0.25}}, 0.65)
    assert not validation_gate({"model": actual, "dummy": {"brier": 0.01}}, 0.65)
    assert metrics([0, 1], [0.1, 0.5])["recall"] == 1
    for labels, scores in (
        ([1, 1], [0.2, 0.3]),
        ([0, 1], [0.1]),
        ([0, 1], [0, np.nan]),
        ([0, 1], [-0.1, 1]),
    ):
        with pytest.raises(ValueError):
            metrics(labels, scores)


def test_selection_ties_support_and_insufficient_positive_features():
    importance = {
        "pay_0": {"mean": 0.1},
        "limit_bal": {"mean": 0.1},
        "pay_2": {"mean": 0.0},
        "unsupported": {"mean": 10.0},
    }
    assert select_drift_features(importance) == ["limit_bal", "pay_0"]
    with pytest.raises(ValueError, match="duas features"):
        select_drift_features(importance, ["pay_0", "pay_2"])


def test_evaluate_frozen_test_and_promote_without_using_test(isolated):
    _, manifest = load_bundle(isolated.models_dir / "staging")
    report = evaluate(isolated)
    assert report["partition"] == "test"
    assert report["model_version"] == manifest["version"]
    assert report["metrics"]["model"]["row_count"] == 400
    evidence = read_manifest(isolated.project_root / "docs/evidencias/baseline.json")
    assert evidence["model_manifest"] == manifest
    assert evidence["test_evaluation"] == report
    # Relatório de teste ruim não influencia a promoção.
    write_manifest(
        isolated.models_dir / "evaluations" / f"{manifest['version']}.json",
        report | {"metrics": {"model": {"roc_auc": 0.1}}},
    )
    promote(isolated)
    assert load_bundle(isolated.models_dir / "current")[1] == manifest
    assert (isolated.models_dir / "current").is_symlink()
    shutil.rmtree(isolated.data_dir / "gold/test")
    promote(isolated)


def test_impossible_gate_preserves_current_and_cli_code(isolated, monkeypatch, capsys):
    promote(isolated)
    current = (isolated.models_dir / "current").resolve()
    expected = {path.name: path.read_bytes() for path in current.iterdir()}
    negative = train(isolated, ModelConfig(minimum_validation_auc=1.1))
    assert not negative["gate_passed"]
    with pytest.raises(PromotionRejected):
        promote(isolated)
    assert (isolated.models_dir / "current").resolve() == current
    assert {path.name: path.read_bytes() for path in current.iterdir()} == expected
    monkeypatch.setenv("PROJECT_ROOT", str(isolated.project_root))
    assert main(["promote"]) == 2
    assert "model_gate_rejected" in capsys.readouterr().out
    assert load_model_config().minimum_validation_auc == 0.65


def test_copy_and_atomic_switch_failure_preserve_current(isolated):
    promote(isolated)
    current = (isolated.models_dir / "current").resolve()
    train(isolated, ModelConfig(minimum_validation_auc=0.66))
    with patch("src.models.registry.shutil.copytree", side_effect=OSError("copy failed")):
        with pytest.raises(OSError):
            promote(isolated)
    assert (isolated.models_dir / "current").resolve() == current
    with patch("src.models.registry.os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError):
            promote(isolated)
    assert (isolated.models_dir / "current").resolve() == current
    assert not list(isolated.models_dir.glob(".current-*"))
    assert not list(isolated.models_dir.glob(".promotion-*"))
    promote(isolated)
    assert (isolated.models_dir / "current").resolve() != current


def test_predict_contract_before_inference_and_no_labels(isolated):
    promote(isolated)
    dataset = verify_dataset(isolated)
    features, keys, _, _ = load_partition(isolated, dataset, "test")
    scores = predict_batch(features, keys, isolated.models_dir / "current")
    assert scores.columns.tolist() == ["record_id", "score"]
    assert scores.record_id.tolist() == keys.record_id.tolist()
    assert scores.score.between(0, 1).all()
    with patch("src.models.predict.load_bundle", side_effect=AssertionError("consumer called")):
        for extra in (TARGET, "record_id", "sex", "age", "education", "marriage"):
            with pytest.raises(ContractRejected):
                predict_batch(features.assign(**{extra: 1}), keys, isolated.models_dir / "current")
    with pytest.raises(ValueError, match="Ordem"):
        predict_batch(features[FEATURES[::-1]], keys, isolated.models_dir / "current")


@pytest.mark.parametrize("problem", ["artifact", "manifest", "order", "names"])
def test_corruption_rejected_before_deserialization(isolated, problem):
    directory = (isolated.models_dir / "staging").resolve()
    if problem == "artifact":
        (directory / "model.joblib").write_bytes(b"corrupt")
    else:
        manifest = read_manifest(directory / "manifest.json")
        if problem == "order":
            manifest["feature_names"] = FEATURES[::-1]
        elif problem == "names":
            manifest["feature_names"][0] = TARGET
        else:
            manifest["gate_passed"] = False
        if problem in {"order", "names"}:
            manifest["version"] = content_hash(
                {k: v for k, v in manifest.items() if k != "version"}
            )
        write_manifest(directory / "manifest.json", manifest)
    with patch("src.models.registry.joblib.load", side_effect=AssertionError("unsafe load")):
        with pytest.raises(ValueError):
            load_bundle(directory)


def test_embedded_features_checked_after_hash(isolated):
    directory = (isolated.models_dir / "staging").resolve()
    estimators, manifest = load_bundle(directory)
    estimators["model"].feature_names_in_ = np.array(FEATURES[::-1])
    joblib.dump(estimators, directory / "model.joblib")
    manifest["model_sha256"] = file_hash(directory / "model.joblib")
    manifest["version"] = content_hash({k: v for k, v in manifest.items() if k != "version"})
    write_manifest(directory / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Features"):
        load_bundle(directory)


def test_data_hash_schema_and_frozen_evaluation(isolated):
    manifest = verify_dataset(isolated)
    changed = copy.deepcopy(manifest)
    changed["feature_names"] = FEATURES[::-1]
    write_manifest(isolated.data_dir / "gold/dataset_manifest.json", changed)
    with pytest.raises(ValueError, match="preparação"):
        train(isolated)
    write_manifest(isolated.data_dir / "gold/dataset_manifest.json", manifest)
    path = isolated.data_dir / "gold/train/features.parquet"
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Integridade"):
        train(isolated)
    write_manifest(
        isolated.data_dir / "gold/dataset_manifest.json", manifest | {"split_hash": "b" * 64}
    )
    with pytest.raises(ValueError, match="diverge"):
        evaluate(isolated)


def test_label_association_by_id_and_cli_success(isolated, monkeypatch, capsys):
    manifest = verify_dataset(isolated)
    path = isolated.data_dir / "gold/validation/labels.parquet"
    pd.read_parquet(path).iloc[::-1].to_parquet(path, index=False)
    manifest["files"]["gold/validation/labels.parquet"] = file_hash(path)
    write_manifest(isolated.data_dir / "gold/dataset_manifest.json", manifest)
    first = load_bundle(isolated.models_dir / "staging")[1]
    second = train(isolated)
    assert first["validation"] == second["validation"]
    assert first["drift_features"] == second["drift_features"]
    monkeypatch.setenv("PROJECT_ROOT", str(isolated.project_root))
    assert main(["train", "--models-dir", "models"]) == 0
    assert main(["evaluate"]) == 0
    assert main(["promote"]) == 0
    assert "model_command_completed" in capsys.readouterr().out
    monkeypatch.setattr("src.cli.train", lambda _: {"gate_passed": False})
    assert main(["train"]) == 2


def test_model_config_forbids_silent_changes():
    config = load_model_config().model_dump()
    for changes in (
        {"unknown": True},
        {"seed": 7},
        {"minimum_validation_auc": 0.64},
        {"early_stopping": True},
        {"decision_threshold": 0.3},
    ):
        with pytest.raises(ValidationError):
            ModelConfig.model_validate(config | changes)
