"""Logs JSON limitados a metadados operacionais agregados."""

import logging
import sys
from typing import Any

import structlog

# Payloads, credenciais, exceções e linhas de DataFrame não atravessam o logger.
SAFE_FIELDS = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "run_id",
        "campaign_id",
        "stage",
        "status",
        "row_count",
        "rows_received",
        "rows_accepted",
        "rows_rejected",
        "duration_seconds",
        "error_type",
        "seed",
        "schema_version",
        "contract_version",
        "violations",
    }
)


def aggregated_fields(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Descarta campos não autorizados; eventos devem ser mensagens estáticas."""
    return {key: value for key, value in event_dict.items() if key in SAFE_FIELDS}


def configure_logging(level: str = "INFO") -> None:
    """Configura saída JSON em stdout sem stack traces ou payloads de entrada."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            aggregated_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger() -> Any:
    """Obtém logger com o contrato de campos definido neste módulo."""
    return structlog.get_logger()
