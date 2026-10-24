"""Entrada batch inicial: aquisição/preparação e inspeção agregada dos dados."""

import argparse
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.data.contracts import (
    ContractRejected,
    load_contract_config,
    validate_batch,
    validate_labels,
    validate_table,
)
from src.data.ingest import ARCHIVE_NAME, ingest, read_source
from src.data.prepare import DEMOGRAPHICS, FEATURES, TARGET, prepare
from src.data.split import split
from src.models.evaluate import evaluate
from src.models.registry import PromotionRejected, promote
from src.models.train import train
from src.utils.config import DataConfig, Settings, load_data_config
from src.utils.logger import configure_logging, get_logger
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest
from src.utils.reproducibility import set_seed


def prepare_dataset(settings: Settings, config: DataConfig) -> dict:
    """Executa aquisição e preparação; publica manifesto apenas após todas as verificações.

    Dados individuais ficam nas camadas locais. Somente schema, hashes e estatísticas
    agregadas atravessam a fronteira para docs/evidencias.
    """
    data_dir = settings.data_dir
    public_manifest = settings.project_root / "docs/evidencias/dataset_manifest.json"
    if public_manifest.exists():
        previous = read_manifest(public_manifest)
        if previous["source_sha256"] != config.source_sha256:
            raise ValueError("Origem diverge do manifesto congelado")
    set_seed(config.split_seed)
    xls = ingest(config, data_dir / "bronze", settings.dataset_archive)
    data, audit = prepare(read_source(xls))
    partitions = split(data, config)
    with TemporaryDirectory(prefix="preparation-", dir=data_dir) as temporary:
        staging = Path(temporary)
        (staging / "silver").mkdir()
        data.to_parquet(staging / "silver/normalized.parquet", index=False)
        data[["record_id", *DEMOGRAPHICS]].to_parquet(staging / "silver/audit.parquet", index=False)
        exports = {
            **partitions.tables,
            "reference": partitions.reference,
            **{f"windows/{i:03d}": window for i, window in enumerate(partitions.windows)},
            "production_remainder": partitions.remainder,
        }
        for name, table in exports.items():
            directory = staging / "gold" / name
            directory.mkdir(parents=True)
            table[FEATURES].to_parquet(directory / "features.parquet", index=False)
            table[["record_id", "group_id"]].to_parquet(directory / "keys.parquet", index=False)
            table[["record_id", TARGET]].to_parquet(directory / "labels.parquet", index=False)
        hashes = {
            str(path.relative_to(staging)): file_hash(path)
            for path in sorted(staging.rglob("*.parquet"))
        }
        hashes[f"bronze/{ARCHIVE_NAME}"] = file_hash(data_dir / "bronze" / ARCHIVE_NAME)
        hashes[f"bronze/{config.archive_member}"] = file_hash(xls)
        schema = {name: str(dtype) for name, dtype in data.dtypes.items()}
        manifest = {
            "schema_version": 1,
            "source_url": config.source_url,
            "source_sha256": config.source_sha256,
            "xls_sha256": config.xls_sha256,
            "parser_version": config.parser_version,
            "row_count": len(data),
            "feature_names": FEATURES,
            "schema": schema,
            "schema_hash": content_hash(schema),
            "split_seed": config.split_seed,
            "split_hash": partitions.split_hash,
            "split_algorithm": "StratifiedGroupKFold-20:10/3/3/4",
            "partitions": partitions.statistics,
            "reference": {
                "row_count": len(partitions.reference),
                "prevalence": float(partitions.reference[TARGET].mean()),
                "source_partition": "train",
            },
            "production_windows": {
                "window_size": config.window_size,
                "complete_windows": len(partitions.windows),
                "remainder_rows": len(partitions.remainder),
                "time_axis": "simulated_index",
            },
            "audit": audit,
            "effective_config": config.model_dump(),
            "config_hash": content_hash(config.model_dump()),
            "files": hashes,
        }
        for path in sorted(staging.rglob("*.parquet")):
            destination = data_dir / path.relative_to(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, destination)
    write_manifest(data_dir / "gold/dataset_manifest.json", manifest)
    write_manifest(public_manifest, manifest)
    return manifest


def inspect_dataset(settings: Settings) -> dict:
    """Verifica integridade de todos os arquivos locais e retorna apenas agregados."""
    manifest = read_manifest(settings.data_dir / "gold/dataset_manifest.json")
    for relative, expected in manifest["files"].items():
        path = (settings.data_dir / relative).resolve()
        if not path.is_relative_to(settings.data_dir) or file_hash(path) != expected:
            raise ValueError("Integridade dos dados locais inválida")
    return manifest


class CommandParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("Argumentos de comando inválidos")


def read_batch(path: Path) -> pd.DataFrame:
    """Formatos explícitos; CSV usa inferência de tipos, sem correção de valores."""
    if path.suffix == ".csv":
        return pd.read_csv(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError("Formato de lote não suportado")


def main(argv: list[str] | None = None) -> int:
    parser = CommandParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("train", "evaluate", "promote"):
        subcommand = commands.add_parser(command)
        subcommand.add_argument("--data-dir", type=Path)
        subcommand.add_argument("--models-dir", type=Path)
    for command in ("data", "inspect-data"):
        subcommand = commands.add_parser(command)
        subcommand.add_argument("--data-dir", type=Path)
        if command == "data":
            subcommand.add_argument("--archive", type=Path)
    validation = commands.add_parser("validate")
    validation.add_argument("--batch", type=Path, required=True)
    validation.add_argument("--keys", type=Path)
    validation.add_argument(
        "--schema", choices=("features", "source", "labels"), default="features"
    )
    configure_logging()
    logger = get_logger()
    command = None
    try:
        args = parser.parse_args(argv)
        command = args.command
        overrides = {}
        if getattr(args, "data_dir", None) is not None:
            overrides["data_dir"] = args.data_dir
        if getattr(args, "models_dir", None) is not None:
            overrides["models_dir"] = args.models_dir
        if args.command == "data" and args.archive is not None:
            overrides["dataset_archive"] = args.archive
        settings = Settings(**overrides)
        configure_logging(settings.log_level)
        if args.command in {"train", "evaluate", "promote"}:
            result = {"train": train, "evaluate": evaluate, "promote": promote}[args.command](
                settings
            )
            logger.info("model_command_completed", stage=args.command, status="success")
            print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
            if args.command == "train" and not result["gate_passed"]:
                logger.warning("model_gate_rejected", status="rejected")
                return 2
        elif args.command == "validate":
            config = load_contract_config(settings.project_root / "configs/contracts.yaml")
            table = read_batch(args.batch)
            if args.schema == "source":
                result = validate_table(table, "source", config)
                if not result.valid:
                    raise ContractRejected(result)
            else:
                if args.keys is None:
                    raise ValueError("Chaves do lote exigidas")
                keys = read_batch(args.keys)
                validator = validate_batch if args.schema == "features" else validate_labels
                result = validator(table, keys, config)
            logger.info("contract_accepted", status="success", **result.model_dump())
        elif args.command == "data":
            config = load_data_config(settings.project_root / "configs/project.yaml")
            result = prepare_dataset(settings, config)
            logger.info("dataset_prepared", row_count=result["row_count"], status="success")
        else:
            result = inspect_dataset(settings)
            print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except PromotionRejected:
        logger.warning("model_gate_rejected", status="rejected")
        return 2
    except ContractRejected as error:
        logger.warning("contract_rejected", status="rejected", **error.result.model_dump())
        return 2
    except Exception as error:
        # Mensagens de bibliotecas podem conter caminhos ou valores individuais.
        event = (
            "model_command_failed"
            if command in {"train", "evaluate", "promote"}
            else "validation_command_failed"
            if command == "validate"
            else "data_command_failed"
        )
        logger.error(event, error_type=type(error).__name__, status="failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
