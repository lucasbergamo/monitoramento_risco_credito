"""Contratos adversos com dados sintéticos e consumidor espião independente."""

import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from src.cli import main
from src.data.contracts import (
    ContractRejected,
    load_contract_config,
    validate_batch,
    validate_labels,
    validate_table,
)
from src.data.prepare import ATTRIBUTES, FEATURES, TARGET


@pytest.fixture
def batch():
    table = pd.DataFrame({name: [0, 0, 0] for name in FEATURES})
    table["limit_bal"] = [100000, 200000, 300000]
    keys = pd.DataFrame({"record_id": [1, 2, 3]})
    return table, keys


def rules(result):
    return {item.rule for item in result.violations}


@pytest.mark.parametrize(
    ("column", "value", "rule"),
    [
        ("limit_bal", 0, "positive_limit"),
        ("limit_bal", np.nan, "not_null"),
        ("pay_amt1", -1, "nonnegative_payment"),
        ("pay_0", 10, "pay_domain"),
        ("pay_5", 1.5, "integer_type"),
        ("bill_amt1", np.inf, "finite"),
        ("bill_amt1", -np.inf, "finite"),
        ("bill_amt1", "private-payload", "numeric_type"),
        ("bill_amt1", True, "numeric_type"),
    ],
)
def test_independent_feature_violations(batch, column, value, rule):
    features, keys = batch
    if isinstance(value, (str, bool)):
        features[column] = value
    else:
        features[column] = (
            features[column].astype(float) if isinstance(value, float) else features[column]
        )
        features.loc[0, column] = value
    with pytest.raises(ContractRejected) as error:
        validate_batch(features, keys)
    assert rule in rules(error.value.result)
    assert error.value.result.rows_accepted == 0
    assert error.value.result.rows_rejected == 3
    assert "private-payload" not in str(error.value)
    assert "private-payload" not in error.value.result.model_dump_json()


def test_combined_violations_block_consumer_and_keep_input(batch):
    features, keys = batch
    features["limit_bal"] = features.limit_bal.astype(float)
    features.loc[0, "limit_bal"] = np.nan
    features.loc[2, "pay_amt1"] = -1
    keys.loc[1, "record_id"] = 1
    original = features.copy(deep=True)
    consumer = Mock()
    with pytest.raises(ContractRejected) as error:
        validate_batch(features, keys)
        consumer(features)
    consumer.assert_not_called()
    assert {"not_null", "nonnegative_payment", "unique_id"} <= rules(error.value.result)
    counts = {item.rule: item.count for item in error.value.result.violations}
    assert counts["unique_id"] == 2
    assert counts["not_null"] == 1
    pd.testing.assert_frame_equal(features, original)


def test_valid_rare_financial_values_and_all_pay_codes(batch):
    features, keys = batch
    features["limit_bal"] = [10**12, 0.01, 10**10]
    features["bill_amt1"] = [-(10**12), -0.25, 10**12]
    features["pay_amt1"] = [10**12, 0, 0.25]
    for code in range(-2, 10):
        for column in ("pay_0", "pay_2", "pay_3", "pay_4", "pay_5", "pay_6"):
            features[column] = code
        assert validate_batch(features, keys).valid
    consumer = Mock()
    validate_batch(features, keys)
    consumer(features)
    consumer.assert_called_once()


@pytest.mark.parametrize("column", [TARGET, "record_id", "sex", "private-column-name"])
def test_unexpected_columns_are_rejected_and_not_echoed(batch, column):
    features, keys = batch
    features[column] = 1
    with pytest.raises(ContractRejected) as error:
        validate_batch(features, keys)
    assert "unexpected_column" in rules(error.value.result)
    assert "private-column-name" not in error.value.result.model_dump_json()


def test_missing_and_duplicate_column_names(batch):
    features, _ = batch
    assert "missing_column" in rules(validate_table(features.drop(columns="pay_0"), "features"))
    duplicated = pd.concat([features, features[["pay_0"]]], axis=1)
    assert "unique_columns" in rules(validate_table(duplicated, "features"))


def test_keys_alignment_and_empty_batch(batch):
    features, keys = batch
    for invalid in (keys.iloc[:2], keys.set_axis([3, 4, 5])):
        with pytest.raises(ContractRejected) as error:
            validate_batch(features, invalid)
        assert "key_alignment" in rules(error.value.result)
    with pytest.raises(ContractRejected) as error:
        validate_batch(features.iloc[:0], keys.iloc[:0])
    assert "nonempty" in rules(error.value.result)


@pytest.mark.parametrize("problem", ["null", "duplicate", "fraction", "text"])
def test_invalid_keys(batch, problem):
    features, keys = batch
    if problem == "null":
        keys = keys.astype(float)
        keys.loc[0, "record_id"] = np.nan
    elif problem == "duplicate":
        keys.loc[1, "record_id"] = 1
    elif problem == "fraction":
        keys = keys.astype(float) + 0.5
    else:
        keys["record_id"] = "private-id"
    with pytest.raises(ContractRejected):
        validate_batch(features, keys)


def test_labels_are_separate_binary_and_one_to_one(batch):
    _, keys = batch
    labels = keys.assign(default_next_month=[0, 1, 0])
    assert validate_labels(labels.iloc[::-1], keys).valid
    for invalid, rule in (
        (labels.assign(default_next_month=2), "binary_target"),
        (labels.drop(columns=TARGET), "missing_column"),
        (labels.assign(record_id=[1, 1, 3]), "unique_id"),
        (labels.assign(record_id=[1, 2, 4]), "label_alignment"),
        (labels.iloc[:2], "label_alignment"),
    ):
        with pytest.raises(ContractRejected) as error:
            validate_labels(invalid, keys)
        assert rule in rules(error.value.result)
    with pytest.raises(ContractRejected) as error:
        validate_labels(labels.assign(record_id=[1, 2, 4], default_next_month=2), keys)
    assert {"binary_target", "label_alignment"} <= rules(error.value.result)


def test_optional_group_id_type(batch):
    features, keys = batch
    assert validate_batch(features, keys.assign(group_id="synthetic-group")).valid
    with pytest.raises(ContractRejected) as error:
        validate_batch(features, keys.assign(group_id=5))
    assert "dtype" in rules(error.value.result)


def test_normalized_source_schema(batch):
    features, keys = batch
    source = pd.concat([keys, features], axis=1).assign(
        sex=1, education=0, marriage=0, age=21, default_next_month=0
    )[["record_id", *ATTRIBUTES, TARGET]]
    assert validate_table(source, "source").valid
    for column, value, rule in (
        ("sex", 3, "sex_domain"),
        ("education", 7, "education_domain"),
        ("marriage", 4, "marriage_domain"),
        ("age", 0, "positive_age"),
        (TARGET, -1, "binary_target"),
    ):
        invalid = source.copy()
        invalid[column] = value
        assert rule in rules(validate_table(invalid, "source"))


@pytest.mark.parametrize("extension", ["csv", "parquet"])
def test_cli_codes_and_private_diagnostics(batch, tmp_path, capsys, extension):
    features, keys = batch
    path = tmp_path / f"private-batch.{extension}"
    key_path = tmp_path / f"private-keys.{extension}"

    def save(frame, destination):
        getattr(frame, f"to_{extension}")(destination, index=False)

    save(features, path)
    save(keys, key_path)
    args = ["validate", "--batch", str(path), "--keys", str(key_path)]
    assert main(args) == 0
    features["private-column"] = "private-value"
    save(features, path)
    assert main(args) == 2
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["event"] == "contract_rejected"
    assert events[-1]["violations"][0]["rule"] == "unexpected_column"
    assert "private-" not in json.dumps(events)
    assert (
        main(
            ["validate", "--batch", str(tmp_path / "private-missing.csv"), "--keys", str(key_path)]
        )
        == 1
    )
    assert main(["validate", "--batch", str(path)]) == 1
    assert main(["validate", "--batch", str(path), "--schema", "private-option"]) == 1
    assert "private-" not in capsys.readouterr().out


def test_invalid_config_is_operational(tmp_path):
    path = tmp_path / "contracts.yaml"
    config = load_contract_config().model_dump()
    config["unexpected"] = 1
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValidationError):
        load_contract_config(path)


def test_unknown_schema_is_operational(batch):
    with pytest.raises(ValueError):
        validate_table(batch[0], "unknown")


def test_diagnostic_counts_all_failures_without_sampling(batch):
    features, keys = batch
    features = pd.concat([features] * 10, ignore_index=True)
    keys = pd.DataFrame({"record_id": range(len(features))})
    features["pay_amt1"] = -1
    with pytest.raises(ContractRejected) as error:
        validate_batch(features, keys)
    failures = [v for v in error.value.result.violations if v.rule == "nonnegative_payment"]
    assert failures[0].count == 30


def test_cli_labels_source_and_operational_failures(batch, tmp_path, capsys, monkeypatch):
    features, keys = batch
    key_path = tmp_path / "keys.parquet"
    keys.to_parquet(key_path, index=False)
    label_path = tmp_path / "labels.parquet"
    keys.assign(default_next_month=[0, 1, 0]).to_parquet(label_path, index=False)
    assert (
        main(
            ["validate", "--schema", "labels", "--batch", str(label_path), "--keys", str(key_path)]
        )
        == 0
    )
    source_path = tmp_path / "source.parquet"
    pd.concat([keys, features], axis=1).assign(
        sex=1, education=0, marriage=0, age=21, default_next_month=0
    ).to_parquet(source_path, index=False)
    assert main(["validate", "--schema", "source", "--batch", str(source_path)]) == 0
    assert main(["validate", "--schema", "source", "--batch", str(label_path)]) == 2
    unsupported = tmp_path / "private.txt"
    unsupported.write_text("private-value")
    assert main(["validate", "--batch", str(unsupported), "--keys", str(key_path)]) == 1
    broken = tmp_path / "private.parquet"
    broken.write_text("private-value")
    assert main(["validate", "--batch", str(broken), "--keys", str(key_path)]) == 1

    def fail_config(_):
        raise ValueError("private-value")

    monkeypatch.setattr("src.cli.load_contract_config", fail_config)
    assert main(["validate", "--batch", str(label_path)]) == 1
    assert "private" not in capsys.readouterr().out
