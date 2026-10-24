"""Aquisição com hashes congelados e leitura restrita do membro XLS esperado."""

import hashlib
import io
import stat
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import pandas as pd

from src.data.prepare import SOURCE_COLUMNS
from src.utils.config import DataConfig
from src.utils.manifest import file_hash

ARCHIVE_NAME = "uci_credit.zip"


def extract_archive(archive: Path, destination: Path, config: DataConfig) -> Path:
    """Valida todos os membros antes de escrever; nunca usa extractall."""
    if archive.stat().st_size > config.max_archive_bytes:
        raise ValueError("Arquivo excede limite de aquisição")
    if file_hash(archive) != config.source_sha256:
        raise ValueError("Hash do ZIP incompatível com a origem congelada")
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        for member in members:
            name = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in member.filename
                or ":" in member.filename
                or stat.S_ISLNK(mode)
                or member.flag_bits & 1
            ):
                raise ValueError("Membro inseguro no ZIP")
        if len(members) != 1 or members[0].filename != config.archive_member:
            raise ValueError("Conteúdo do ZIP incompatível")
        if members[0].file_size > config.max_extracted_bytes:
            raise ValueError("XLS excede limite de extração")
        content = zipped.read(members[0])  # ZIP CRC também é verificado.
    if hashlib.sha256(content).hexdigest() != config.xls_sha256:
        raise ValueError("Hash do XLS incompatível")
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / config.archive_member
    if path.exists() and file_hash(path) != config.xls_sha256:
        raise ValueError("XLS bronze existente foi alterado")
    path.write_bytes(content)
    return path


def ingest(config: DataConfig, bronze: Path, archive: Path | None = None) -> Path:
    """Obtém ZIP por HTTP com timeout ou arquivo local; preserva bronze existente."""
    bronze.mkdir(parents=True, exist_ok=True)
    cached = bronze / ARCHIVE_NAME
    if cached.exists() and file_hash(cached) != config.source_sha256:
        raise ValueError("ZIP bronze existente foi alterado")
    # Um arquivo fornecido explicitamente sempre é verificado, mesmo com cache válido.
    if archive is not None:
        source = archive
    elif cached.exists():
        source = cached
    else:
        source = bronze / "download.tmp"
        try:
            with urllib.request.urlopen(
                config.source_url, timeout=config.timeout_seconds
            ) as response:
                if response.status != 200 or not response.url.startswith("https://"):
                    raise ValueError("Resposta HTTP incompatível")
                with source.open("wb") as output:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > config.max_archive_bytes:
                            raise ValueError("Download excede limite de aquisição")
                        output.write(chunk)
            xls = extract_archive(source, bronze, config)
            source.replace(cached)
            return xls
        finally:
            source.unlink(missing_ok=True)
    xls = extract_archive(source, bronze, config)
    if source.resolve() != cached.resolve():
        cached.write_bytes(source.read_bytes())
    return xls


def read_source(path: Path) -> pd.DataFrame:
    """Valida as duas linhas de cabeçalho e mapeia nomes, sem inferência posicional."""
    raw = pd.read_excel(io.BytesIO(path.read_bytes()), header=None, engine="xlrd")
    expected_top = [None, *[f"X{i}" for i in range(1, 24)], "Y"]
    if raw.shape[1] != 25 or len(raw) < 3:
        raise ValueError("Dimensões do XLS incompatíveis")
    top = [None if pd.isna(value) else value for value in raw.iloc[0]]
    if top != expected_top or raw.iloc[1].tolist() != list(SOURCE_COLUMNS):
        raise ValueError("Cabeçalhos do XLS incompatíveis")
    data = raw.iloc[2:].copy()
    data.columns = list(SOURCE_COLUMNS)
    return data.reset_index(drop=True)
