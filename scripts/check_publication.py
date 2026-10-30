"""Inspeciona arquivos publicáveis, index e histórico sem imprimir valores sensíveis."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

# Padrões construídos para que a própria política não seja uma ocorrência literal.
PRIVATE = re.compile(
    r"ARQUI" + r"TETURA|BLOCOS_" + r"EXECUCAO|PLANO_" + r"ACAO|fiap-mlet-" + r"graduation"
    r"|\bB(?:[0-9]|1[01])\b|/ho" + r"me/[^\s]+|/Us" + r"ers/[^\s]+"
)
PERSONAL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\bRM[0-9]{5,}\b", re.I)
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}"
    r"|(?:password|api_key|secret)\s*[:=]\s*[\"\'][^\"\'\s]{8,}",
    re.I,
)
FORBIDDEN = {".pdf", ".xls", ".xlsx", ".parquet", ".joblib", ".pkl", ".sqlite", ".db", ".zip"}
BINARY_ALLOWED = {".png", ".jpg", ".jpeg"}


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def inspect(root: Path, *, cached: bool = False, history: bool = False) -> list[dict]:
    """Retorna caminho e categoria, sem copiar o conteúdo suspeito."""
    issues = []
    if history:
        # Todos os blobs alcançáveis, inclusive arquivos removidos, e metadados públicos.
        objects = git(root, "rev-list", "--objects", "--all").decode().splitlines()
        for entry in objects:
            oid, _, name = entry.partition(" ")
            if not name or git(root, "cat-file", "-t", oid).strip() != b"blob":
                continue
            issues.extend(check(name, git(root, "cat-file", "blob", oid)))
        messages = git(root, "log", "--all", "--format=%B").decode()
        if PRIVATE.search(messages) or SECRET.search(messages):
            issues.append({"path": "git-log", "rule": "private_or_secret"})
        return issues
    names = git(root, "ls-files", "-z").decode().split("\0")
    if not cached:
        names += git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    for name in sorted(set(filter(None, names))):
        path = root / name
        if cached:
            content = git(root, "show", f":{name}")
        elif path.is_symlink():
            issues.append({"path": name, "rule": "symlink"})
            continue
        elif path.is_file():
            content = path.read_bytes()
        else:
            continue
        issues.extend(check(name, content))
    return issues


def check(name: str, content: bytes) -> list[dict]:
    issues = []
    path = Path(name)
    if (
        path.suffix.lower() in FORBIDDEN
        or path.parts[0] in {"data", "models", "state", "artifacts"}
        or path.name in {".env", "AGENTS.md", "CLAUDE.md"}
    ):
        issues.append({"path": name, "rule": "forbidden_path"})
    if path.suffix.lower() in BINARY_ALLOWED:
        if not name.startswith("docs/evidencias/"):
            issues.append({"path": name, "rule": "unreviewed_image"})
        return issues
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [{"path": name, "rule": "unknown_binary"}]
    for rule, pattern in (
        ("private_reference", PRIVATE),
        ("personal_data", PERSONAL),
        ("secret", SECRET),
    ):
        if rule == "secret" and name == "tests/test_utils.py":
            text = text.replace("test-secret", "fixture")
        if pattern.search(name) or pattern.search(text):
            issues.append({"path": name, "rule": rule})
    if path.suffix.lower() == ".json":
        try:
            value = json.loads(text)

            def visit(obj):
                if isinstance(obj, dict):
                    for key, child in obj.items():
                        if key in {
                            "record_id",
                            "group_id",
                            "failure_cases",
                            "latent",
                            "individual_scores",
                        } and isinstance(child, (list, dict)):
                            issues.append({"path": name, "rule": "individual_payload"})
                        visit(child)
                elif isinstance(obj, list):
                    for child in obj:
                        visit(child)

            visit(value)
        except json.JSONDecodeError:
            issues.append({"path": name, "rule": "invalid_json"})
    if path.suffix.lower() == ".html":
        issues.append({"path": name, "rule": "html_requires_review"})
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    issues = inspect(args.root, cached=args.cached, history=args.history)
    print(json.dumps({"status": "failed" if issues else "passed", "issues": issues}, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
