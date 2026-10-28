"""Lista ou remove explicitamente execuções locais de diagnóstico expiradas."""

import argparse
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_RELATIVE = Path("artifacts/runs")


def _runs_root(project_root: Path) -> Path:
    root = project_root.resolve(strict=True)
    runs = root / RUNS_RELATIVE
    resolved = runs.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("O diretório de execuções sai da raiz do projeto")
    if runs.exists() and runs.is_symlink():
        raise ValueError("O diretório de execuções não pode ser link simbólico")
    return runs


def _latest_mtime(directory: Path) -> float:
    latest = directory.stat(follow_symlinks=False).st_mtime
    for parent, dirs, files in os.walk(directory, followlinks=False):
        parent_path = Path(parent)
        dirs[:] = [name for name in dirs if not (parent_path / name).is_symlink()]
        for name in files:
            path = parent_path / name
            if not path.is_symlink():
                latest = max(latest, path.stat(follow_symlinks=False).st_mtime)
    return latest


def plan_retention(
    project_root: Path = PROJECT_ROOT,
    *,
    now: datetime | None = None,
    older_than_days: int = 30,
) -> list[dict]:
    """Planeja somente subdiretórios diretos de artifacts/runs pelo último mtime."""
    if not 1 <= older_than_days <= 3650:
        raise ValueError("A retenção deve estar entre 1 e 3650 dias")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("A data de referência deve incluir fuso horário")
    cutoff = (now - timedelta(days=older_than_days)).timestamp()
    runs = _runs_root(project_root)
    if not runs.exists():
        return []
    candidates = []
    for entry in sorted(runs.iterdir(), key=lambda path: path.name):
        if entry.is_symlink() or not entry.is_dir():
            continue
        resolved = entry.resolve(strict=True)
        if not resolved.is_relative_to(runs.resolve(strict=True)):
            continue
        latest = _latest_mtime(entry)
        if latest < cutoff:
            candidates.append(
                {
                    "path": entry.relative_to(Path(project_root).resolve()).as_posix(),
                    "age_days": int((now.timestamp() - latest) // 86400),
                }
            )
    return candidates


def _delete_candidates(project_root: Path, candidates: list[dict]) -> list[str]:
    root = project_root.resolve(strict=True)
    runs = _runs_root(root).resolve(strict=True)
    deleted = []
    for candidate in candidates:
        relative = Path(candidate["path"])
        if relative.parts[:2] != RUNS_RELATIVE.parts or len(relative.parts) != 3:
            raise ValueError("Caminho fora do escopo de retenção")
        target = root / relative
        if target.is_symlink() or not target.is_dir():
            raise ValueError("Candidato de retenção mudou após o planejamento")
        resolved = target.resolve(strict=True)
        if not resolved.is_relative_to(runs):
            raise ValueError("Candidato de retenção sai do diretório permitido")
        shutil.rmtree(target)
        deleted.append(relative.as_posix())
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-days", type=int, default=30)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="remove os diretórios listados; sem esta opção, apenas simula",
    )
    args = parser.parse_args(argv)
    candidates = plan_retention(older_than_days=args.older_than_days)
    deleted = _delete_candidates(PROJECT_ROOT, candidates) if args.delete else []
    print(
        json.dumps(
            {
                "mode": "delete" if args.delete else "dry_run",
                "older_than_days": args.older_than_days,
                "candidates": candidates,
                "deleted": deleted,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
