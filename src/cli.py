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
from src.governance import governance
from src.models.evaluate import evaluate
from src.models.registry import PromotionRejected, promote
from src.models.train import train
from src.monitoring.reports import build_report
from src.monitoring.tracking import track_operation
from src.pipeline import PipelineStageError, run_pipeline, verify_evidence
from src.simulation.scenarios import evaluate_scenarios, simulate
from src.utils.config import DataConfig, Settings, load_data_config
from src.utils.logger import configure_logging, get_logger
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest
from src.utils.reproducibility import set_seed


def detect(settings):
    from src.monitoring.drift import detect as detect_operation

    return detect_operation(settings)


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
    logger = get_logger()
    logger.info("data_stage_started", stage="acquisition", status="running")
    xls = ingest(config, data_dir / "bronze", settings.dataset_archive)
    logger.info("data_stage_started", stage="normalization", status="running")
    data, audit = prepare(read_source(xls))
    logger.info("data_stage_started", stage="split", status="running")
    partitions = split(data, config)
    logger.info("data_stage_started", stage="persist", status="running")
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
    get_logger().info("data_stage_started", stage="integrity", status="running")
    manifest = read_manifest(settings.data_dir / "gold/dataset_manifest.json")
    for relative, expected in manifest["files"].items():
        path = (settings.data_dir / relative).resolve()
        if not path.is_relative_to(settings.data_dir) or file_hash(path) != expected:
            raise ValueError("Integridade dos dados locais inválida")
    return manifest


def emit_output(command: str, result: dict, settings: Settings, *, json_output: bool) -> None:
    """O resultado completo permanece disponível para consumidores explícitos de JSON."""
    if json_output:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return
    gate = result.get("gate_passed")
    state = "gate reprovado" if gate is False else result.get("status", "concluído")
    print(f"{command}: {state}.")
    for key in ("campaign_id", "row_count", "model_version", "version", "tracking_run_id"):
        if key in result:
            print(f"{key}: {result[key]}")
    if command in {"data", "inspect-data"}:
        for name, partition in result.get("partitions", {}).items():
            print(f"  {name}: {partition['row_count']} registros")
        reference = result.get("reference", {})
        windows = result.get("production_windows", {})
        print(
            f"Referência: {reference.get('row_count', '?')} registros; "
            f"janelas completas: {windows.get('complete_windows', '?')}."
        )
    validation = result.get("validation", {}).get("model", {})
    if validation:
        print(f"Validação: AUC {validation.get('roc_auc')}; Brier {validation.get('brier')}.")
    if command == "evaluate":
        metrics = result.get("metrics", {})
        for name, label in (("model", "Teste"), ("dummy", "Baseline no teste")):
            values = metrics.get(name, {})
            summary = "; ".join(
                f"{title} {values[key]:.4f}"
                for key, title in (("roc_auc", "AUC"), ("brier", "Brier"), ("recall", "Recall"))
                if key in values
            )
            if summary:
                print(f"{label}: {summary}.")
    if gate is not None:
        print(f"Gate: {'aprovado' if gate else 'reprovado'}.")
    if command == "detect":
        print(f"Comparações: {len(result.get('results', []))}; gate: {gate}.")
    evidence = {
        "data": settings.data_dir / "gold/dataset_manifest.json",
        "inspect-data": settings.data_dir / "gold/dataset_manifest.json",
        "train": settings.models_dir / "staging/manifest.json",
        "promote": settings.models_dir / "current/manifest.json",
        "evaluate": settings.models_dir
        / "evaluations"
        / f"{result.get('model_version', 'unknown')}.json",
        "simulate": settings.data_dir / "scenarios/current/manifest.json",
        "evaluate-scenarios": settings.data_dir / "scenarios/evaluation.json",
        "governance": settings.project_root / "docs/evidencias/governanca.json",
    }.get(command)
    if command in {"demo", "report", "verify-evidence"}:
        directory = settings.artifacts_dir / "campaigns" / result["campaign_id"]
        evidence = directory / ("index.html" if command == "report" else "manifest.json")
    elif command == "detect":
        evidence = settings.artifacts_dir / "runs" / result["run_id"] / "summary.json"
    if evidence is not None:
        displayed = (
            evidence.relative_to(settings.project_root)
            if evidence.is_relative_to(settings.project_root)
            else evidence
        )
        print(f"Artefato: {displayed}")
    if command == "report":
        print(f"Tracking: {result['tracking_status']}; runs: {result['run_count']}.")
    if result.get("tracking_run_id") or command == "report":
        print(f"UI MLflow: {settings.mlflow_ui_uri}")


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
    for command in (
        "train",
        "evaluate",
        "promote",
        "simulate",
        "evaluate-scenarios",
        "detect",
        "governance",
    ):
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
    report_command = commands.add_parser("report")
    report_command.add_argument("--data-dir", type=Path)
    report_command.add_argument("--models-dir", type=Path)
    report_command.add_argument("--campaign-id", required=True)
    demo_command = commands.add_parser("demo")
    demo_command.add_argument("--campaign-id")
    verify_command = commands.add_parser("verify-evidence")
    verify_command.add_argument("--campaign-id", required=True)
    for subcommand in commands.choices.values():
        subcommand.add_argument(
            "--json", action="store_true", help="Emite o resultado completo em JSON"
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
        configure_logging(settings.log_level, json_output=args.json)
        logger.info("command_started", stage=args.command, status="running")
        if args.command == "detect":
            result = track_operation(settings, "detect", lambda: detect(settings))
            emit_output(args.command, result, settings, json_output=args.json)
            if not result["gate_passed"]:
                return 2
        elif args.command == "governance":
            result = governance(settings)
            emit_output(args.command, result, settings, json_output=args.json)
        elif args.command in {"simulate", "evaluate-scenarios"}:
            result = track_operation(
                settings,
                args.command,
                lambda: {"simulate": simulate, "evaluate-scenarios": evaluate_scenarios}[
                    args.command
                ](settings),
            )
            emit_output(args.command, result, settings, json_output=args.json)
            if args.command == "evaluate-scenarios" and not result["gate_passed"]:
                return 2
        elif args.command in {"train", "evaluate", "promote"}:
            result = track_operation(
                settings,
                args.command,
                lambda: {"train": train, "evaluate": evaluate, "promote": promote}[args.command](
                    settings
                ),
            )
            logger.info("model_command_completed", stage=args.command, status="success")
            emit_output(args.command, result, settings, json_output=args.json)
            if args.command == "train" and not result["gate_passed"]:
                logger.warning("model_gate_rejected", status="rejected")
                return 2
        elif args.command == "validate":
            config = load_contract_config(settings.project_root / "configs/contracts.yaml")

            def validate_operation():
                table = read_batch(args.batch)
                if args.schema == "source":
                    validation_result = validate_table(table, "source", config)
                    if not validation_result.valid:
                        raise ContractRejected(validation_result)
                    return validation_result.model_dump(mode="json")
                if args.keys is None:
                    raise ValueError("Chaves do lote exigidas")
                keys = read_batch(args.keys)
                validator = validate_batch if args.schema == "features" else validate_labels
                return validator(table, keys, config).model_dump(mode="json")

            result = track_operation(settings, "validate", validate_operation)
            logger.info("contract_accepted", status="success", **result)
            if args.json:
                emit_output(args.command, result, settings, json_output=True)
        elif args.command == "data":
            config = load_data_config(settings.project_root / "configs/project.yaml")
            result = track_operation(settings, "data", lambda: prepare_dataset(settings, config))
            logger.info("dataset_prepared", row_count=result["row_count"], status="success")
            emit_output(args.command, result, settings, json_output=args.json)
        elif args.command == "report":
            result = build_report(settings, campaign_id=args.campaign_id)
            emit_output(args.command, result, settings, json_output=args.json)
        elif args.command == "demo":
            result = run_pipeline(settings, campaign_id=args.campaign_id)
            emit_output(args.command, result, settings, json_output=args.json)
        elif args.command == "verify-evidence":
            result = verify_evidence(settings, args.campaign_id)
            emit_output(args.command, result, settings, json_output=args.json)
        else:
            result = track_operation(settings, "inspect-data", lambda: inspect_dataset(settings))
            emit_output(args.command, result, settings, json_output=args.json)
        return 0
    except PromotionRejected:
        logger.warning("model_gate_rejected", status="rejected")
        return 2
    except ContractRejected as error:
        logger.warning("contract_rejected", status="rejected", **error.result.model_dump())
        return 2
    except PipelineStageError as error:
        logger.error(
            "campaign_command_failed",
            stage=error.stage,
            failure_code=error.failure_code,
            status="failed",
        )
        return 1
    except Exception as error:
        # Mensagens de bibliotecas podem conter caminhos ou valores individuais.
        event = (
            "drift_command_failed"
            if command == "detect"
            else "scenario_command_failed"
            if command in {"simulate", "evaluate-scenarios"}
            else "model_command_failed"
            if command in {"train", "evaluate", "promote"}
            else "validation_command_failed"
            if command == "validate"
            else "campaign_command_failed"
            if command in {"demo", "verify-evidence", "report"}
            else "governance_command_failed"
            if command == "governance"
            else "data_command_failed"
        )
        logger.error(event, error_type=type(error).__name__, status="failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
