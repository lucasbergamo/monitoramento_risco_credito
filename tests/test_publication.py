"""Publicação recusa payloads e formatos proibidos sem expor o conteúdo."""

from scripts.check_publication import check


def test_publication_rejects_personal_payload_without_echoing_values():
    issues = check("docs/evidence.json", b'{"record_id": [1234567]}')
    assert issues == [{"path": "docs/evidence.json", "rule": "individual_payload"}]
    assert "1234567" not in str(issues)


def test_publication_accepts_schema_types_and_aggregates():
    assert check("docs/schema.json", b'{"record_id": "int64", "count": 30000}') == []


def test_publication_rejects_private_paths_generated_files_and_unknown_binary():
    assert check("models/model.joblib", b"abc")[0]["rule"] == "forbidden_path"
    assert check("docs/blob.dat", b"\xff")[0]["rule"] == "unknown_binary"
    assert check("docs/report.html", b"<html></html>")[0]["rule"] == "html_requires_review"


def test_publication_rejects_email_without_echoing_it():
    address = "person" + "@example.org"
    issues = check("docs/example.md", address.encode())
    assert issues[0]["rule"] == "personal_data"
    assert address not in str(issues)
