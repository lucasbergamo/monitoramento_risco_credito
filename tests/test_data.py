"""Fixtures sintéticas próprias, sem dependência do download ou de artefatos reais."""

import io
import json
import struct
import zipfile
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from xlrd.biffh import XLRDError

from src.cli import inspect_dataset, main, prepare_dataset
from src.data.ingest import ARCHIVE_NAME, extract_archive, ingest, read_source
from src.data.prepare import ATTRIBUTES, DEMOGRAPHICS, FEATURES, TARGET, prepare
from src.data.split import PARTITIONS, split
from src.utils.config import Settings, load_data_config
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest


@pytest.fixture
def config():
    return load_data_config()


@pytest.fixture
def source():
    rng = np.random.default_rng(7)
    n = 6000
    values = {
        "ID": np.arange(1, n + 1),
        **{name.upper(): rng.integers(0, 10000, n) for name in ATTRIBUTES},
        "default payment next month": np.tile([0, 0, 0, 1], n // 4),
    }
    frame = pd.DataFrame(values)
    # Clientes distintos com vetores idênticos e labels conflitantes.
    frame.loc[1:3, list(values)[1:-1]] = frame.loc[0, list(values)[1:-1]].to_numpy()
    frame.loc[0:3, "default payment next month"] = [0, 1, 0, 1]
    return frame


def xls_bytes(frame):
    """Escreve uma planilha BIFF2 mínima, legível por xlrd, somente para testes."""

    def record(code, value):
        return struct.pack("<HH", code, len(value)) + value

    output = bytearray(record(0x0009, struct.pack("<HH", 2, 0x0010)))
    rows = [
        ["", *[f"X{i}" for i in range(1, 24)], "Y"],
        list(frame.columns),
        *frame.to_numpy().tolist(),
    ]
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            cell = struct.pack("<HH3s", row_index, column_index, b"\0\0\0")
            if isinstance(value, str):
                encoded = value.encode("latin1")
                output += record(0x0004, cell + bytes([len(encoded)]) + encoded)
            else:
                output += record(0x0003, cell + struct.pack("<d", value))
    return bytes(output) + record(0x000A, b"")


def make_archive(tmp_path, config, content, name=None):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(name or config.archive_member, content)
    import hashlib

    adjusted = config.model_copy(
        update={
            "source_sha256": file_hash(archive),
            "xls_sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    return archive, adjusted


def test_parser_real_xls_format_with_own_fixture(tmp_path, source):
    path = tmp_path / "fixture.xls"
    path.write_bytes(xls_bytes(source.iloc[:4]))
    actual = read_source(path)
    pd.testing.assert_frame_equal(actual.astype("int64"), source.iloc[:4])


def test_parser_rejects_wrong_headers_and_non_excel(tmp_path, source):
    path = tmp_path / "fixture.xls"
    changed = source.iloc[:4].rename(columns={"ID": "OTHER"})
    path.write_bytes(xls_bytes(changed))
    with pytest.raises(ValueError, match="Cabeçalhos"):
        read_source(path)
    path.write_bytes(b"not an excel document")
    with pytest.raises(XLRDError):
        read_source(path)


def test_prepare_audits_without_dropping_records(source):
    frame, audit = prepare(source)
    assert len(frame) == len(source)
    assert audit["unique_ids"]
    assert audit["records_in_duplicate_groups"] == 4
    assert audit["groups_with_conflicting_labels"] == 1
    assert frame.loc[:3, "group_id"].nunique() == 1
    assert len(FEATURES) == 19
    assert not set(FEATURES) & {"record_id", TARGET, *DEMOGRAPHICS}
    assert all(str(dtype) == "int64" for dtype in frame.drop(columns="group_id").dtypes)


@pytest.mark.parametrize(
    "problem", ["schema", "duplicate_id", "null", "fraction", "inf", "text", "label"]
)
def test_prepare_rejects_invalid_origin(source, problem):
    if problem == "schema":
        source = source.drop(columns="SEX")
    elif problem == "duplicate_id":
        source.loc[1, "ID"] = source.loc[0, "ID"]
    elif problem == "label":
        source.loc[0, "default payment next month"] = 3
    else:
        source["LIMIT_BAL"] = source["LIMIT_BAL"].astype(object)
        source.loc[0, "LIMIT_BAL"] = {
            "null": None,
            "fraction": 0.5,
            "inf": float("inf"),
            "text": "invalid",
        }[problem]
    with pytest.raises((ValueError, TypeError)):
        prepare(source)


def test_prepare_preserves_observed_special_codes_and_negative_bills(source):
    source.loc[0, ["PAY_0", "EDUCATION", "MARRIAGE", "BILL_AMT1"]] = [-2, 6, 0, -10]
    frame, audit = prepare(source)
    assert frame.loc[0, "bill_amt1"] == -10
    assert -2 in audit["categories"]["pay_0"]
    assert 6 in audit["categories"]["education"]
    assert audit["negative_bills"]["bill_amt1"] == 1


def test_group_split_reference_windows_and_determinism(source, config):
    frame, _ = prepare(source)
    config = config.model_copy(update={"window_size": 200, "reference_size": 1000})
    result = split(frame, config)
    shuffled = split(frame.sample(frac=1, random_state=91), config)
    assert result.split_hash == shuffled.split_hash
    assert sum(len(table) for table in result.tables.values()) == len(source)
    for left in PARTITIONS:
        assert set(result.tables[left][TARGET]) == {0, 1}
        for right in PARTITIONS:
            if left != right:
                assert not set(result.tables[left].group_id) & set(result.tables[right].group_id)
                assert not set(result.tables[left].record_id) & set(result.tables[right].record_id)
    assert set(result.reference.record_id) <= set(result.tables["train"].record_id)
    assert not set(result.reference.record_id) & set(result.tables["production_pool"].record_id)
    ids = [key for window in result.windows for key in window.record_id]
    assert len(ids) == len(set(ids))
    assert len(result.windows) >= 4
    assert all(len(window) == 200 for window in result.windows)
    assert set(ids) | set(result.remainder.record_id) == set(
        result.tables["production_pool"].record_id
    )
    assert set(ids).isdisjoint(result.remainder.record_id)


def test_split_rejects_insufficient_rows_and_windows(source, config):
    frame, _ = prepare(source)
    with pytest.raises(ValueError, match="5.000"):
        split(frame.iloc[:100], config)
    with pytest.raises(ValueError, match="quatro janelas"):
        split(frame, config)


@pytest.mark.parametrize("name", ["../escape.xls", "/absolute.xls", "a\\evil.xls", "C:evil.xls"])
def test_unsafe_archive_rejected_before_writing(tmp_path, config, name):
    archive, config = make_archive(tmp_path, config, b"synthetic", name)
    with pytest.raises(ValueError, match="inseguro"):
        extract_archive(archive, tmp_path / "bronze", config)
    assert not (tmp_path / "bronze").exists()


def test_symlink_and_unexpected_members_rejected(tmp_path, config):
    archive, config = make_archive(tmp_path, config, b"synthetic", "other.xls")
    with pytest.raises(ValueError, match="Conteúdo"):
        extract_archive(archive, tmp_path / "bronze", config)
    with zipfile.ZipFile(archive, "w") as zipped:
        info = zipfile.ZipInfo(config.archive_member)
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        zipped.writestr(info, "target")
    config = config.model_copy(update={"source_sha256": file_hash(archive)})
    with pytest.raises(ValueError, match="inseguro"):
        extract_archive(archive, tmp_path / "bronze", config)


def test_hash_mismatch_does_not_replace_manifest_or_bronze(tmp_path, config):
    archive, config = make_archive(tmp_path, config, b"synthetic")
    bronze = tmp_path / "bronze"
    ingest(config, bronze, archive)
    previous = (bronze / ARCHIVE_NAME).read_bytes()
    archive.write_bytes(archive.read_bytes() + b"changed")
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, {"schema_version": 1, "source_sha256": config.source_sha256})
    expected = manifest.read_bytes()
    with pytest.raises(ValueError, match="Hash do ZIP"):
        ingest(config, bronze, archive)
    assert (bronze / ARCHIVE_NAME).read_bytes() == previous
    assert manifest.read_bytes() == expected
    (bronze / ARCHIVE_NAME).write_bytes(b"corrupt cache")
    with pytest.raises(ValueError, match="existente foi alterado"):
        ingest(config, bronze)


def test_xls_hash_and_size_rejected(tmp_path, config):
    archive, config = make_archive(tmp_path, config, b"synthetic")
    with pytest.raises(ValueError, match="Hash do XLS"):
        extract_archive(
            archive, tmp_path / "bronze", config.model_copy(update={"xls_sha256": "0" * 64})
        )
    for key in ("max_archive_bytes", "max_extracted_bytes"):
        with pytest.raises(ValueError, match="limite"):
            extract_archive(archive, tmp_path / "bronze", config.model_copy(update={key: 1}))


def test_download_timeout_bounds_cache_and_cleanup(tmp_path, config):
    archive, config = make_archive(tmp_path, config, b"synthetic")

    class Response(io.BytesIO):
        status = 200
        url = config.source_url

    bronze = tmp_path / "bronze"
    with patch("urllib.request.urlopen", return_value=Response(archive.read_bytes())) as download:
        ingest(config, bronze)
        assert download.call_args.kwargs["timeout"] == config.timeout_seconds
    with patch("urllib.request.urlopen", side_effect=AssertionError("cache should be used")):
        ingest(config, bronze)
    for status, url, limit in [
        (500, config.source_url, 20000000),
        (200, "http://bad", 20000000),
        (200, config.source_url, 1),
    ]:
        response = Response(archive.read_bytes())
        response.status, response.url = status, url
        other = tmp_path / f"bronze-{status}-{limit}-{len(url)}"
        with patch("urllib.request.urlopen", return_value=response), pytest.raises(ValueError):
            ingest(config.model_copy(update={"max_archive_bytes": limit}), other)
        assert not (other / "download.tmp").exists()
    with patch("urllib.request.urlopen", side_effect=TimeoutError), pytest.raises(TimeoutError):
        ingest(config, tmp_path / "timeout")
    assert not (tmp_path / "timeout/download.tmp").exists()


def test_end_to_end_local_fixture_and_manifest_integrity(tmp_path, source, config):
    archive, config = make_archive(tmp_path, config, xls_bytes(source))
    config = config.model_copy(update={"window_size": 200, "reference_size": 1000})
    settings = Settings(_env_file=None, project_root=tmp_path, dataset_archive=archive)
    first = prepare_dataset(settings, config)
    second = prepare_dataset(settings, config)
    assert first == second == inspect_dataset(settings)
    assert first["source_sha256"] == file_hash(archive)
    assert first["row_count"] == 6000
    assert str(tmp_path) not in json.dumps(first)
    assert "record_id" not in first["feature_names"]
    features = pd.read_parquet(settings.data_dir / "gold/train/features.parquet")
    assert features.columns.tolist() == FEATURES
    assert features.index.name is None
    manifest_path = tmp_path / "docs/evidencias/dataset_manifest.json"
    previous = manifest_path.read_bytes()
    archive.write_bytes(archive.read_bytes() + b"mutated")
    with pytest.raises(ValueError, match="Hash do ZIP"):
        prepare_dataset(settings, config)
    assert manifest_path.read_bytes() == previous
    features_path = settings.data_dir / "gold/train/features.parquet"
    features_path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Integridade"):
        inspect_dataset(settings)


def test_manifest_validation_and_canonical_hash(tmp_path):
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    with pytest.raises(ValueError):
        content_hash({"nan": float("nan")})
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version": 99}')
    with pytest.raises(ValueError, match="Versão"):
        read_manifest(path)


def test_config_unknown_keys_and_invalid_source(config):
    for changes in ({"unknown": True}, {"source_url": "http://invalid"}, {"split_seed": 23}):
        with pytest.raises(ValidationError):
            type(config).model_validate(config.model_dump() | changes)


def test_cli_success_and_sanitized_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("src.cli.load_data_config", lambda _: object())
    monkeypatch.setattr("src.cli.prepare_dataset", lambda *_: {"row_count": 5000})
    assert main(["data", "--archive", str(tmp_path / "archive.zip"), "--data-dir", "other"]) == 0
    monkeypatch.setattr("src.cli.inspect_dataset", lambda _: {"schema_version": 1})
    assert main(["inspect-data"]) == 0

    def fail(*_):
        raise ValueError("sensitive-path-or-value")

    monkeypatch.setattr("src.cli.prepare_dataset", fail)
    assert main(["data"]) == 1
    output = capsys.readouterr().out
    assert "sensitive-path-or-value" not in output
    assert "ValueError" in output
