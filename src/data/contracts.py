"""Contratos estritos e fronteira de bloqueio, sem expor valores individuais."""

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import pandera.pandas as pa
import yaml
from pandas.api.types import is_bool_dtype, is_float_dtype, is_integer_dtype
from pydantic import BaseModel, ConfigDict, Field

from src.data.prepare import ATTRIBUTES, FEATURES, PAY_COLUMNS, PAYMENT_COLUMNS, TARGET
from src.utils.config import PROJECT_ROOT


class ContractConfig(BaseModel):
    """Política versionada, sem sobrescrita implícita por ambiente."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1]
    contract_version: Literal["credit-v1"]
    pay_domain: list[int] = Field(min_length=1)
    sex_domain: list[int] = Field(min_length=1)
    education_domain: list[int] = Field(min_length=1)
    marriage_domain: list[int] = Field(min_length=1)


class Violation(BaseModel):
    """Contagem de ocorrências por regra e campo autorizado, sem índice ou valor."""

    model_config = ConfigDict(frozen=True)
    scope: Literal["source", "features", "keys", "labels", "batch"]
    column: str | None
    rule: str
    count: int = Field(gt=0)


class ValidationResult(BaseModel):
    """Resultado agregado; contagens de regras podem se sobrepor na mesma linha."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1
    contract_version: str
    rows_received: int
    rows_accepted: int
    rows_rejected: int
    violations: tuple[Violation, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.violations


class ContractRejected(ValueError):
    """Exceção segura: carrega somente o diagnóstico agregado."""

    def __init__(self, result: ValidationResult):
        super().__init__("Lote rejeitado pelo contrato de dados")
        self.result = result


def load_contract_config(path: Path | None = None) -> ContractConfig:
    path = path or PROJECT_ROOT / "configs/contracts.yaml"
    return ContractConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _numeric(series: pd.Series) -> bool:
    return (is_integer_dtype(series) or is_float_dtype(series)) and not is_bool_dtype(series)


def _safe_numeric_check(function: Callable) -> Callable:
    # Tipo inválido é relatado pela regra própria, sem disparar exceções com payload.
    return lambda series: function(series) if _numeric(series) else True


def _column(*, integer: bool = False, checks: list | None = None) -> pa.Column:
    type_check = (
        (lambda series: is_integer_dtype(series) and not is_bool_dtype(series))
        if integer
        else _numeric
    )
    return pa.Column(
        checks=[
            pa.Check(type_check, name="integer_type" if integer else "numeric_type"),
            pa.Check(_safe_numeric_check(np.isfinite), name="finite"),
            *(checks or []),
        ],
        nullable=False,
        coerce=False,
    )


def _domain(values: list[int], name: str) -> pa.Check:
    return pa.Check(lambda series: series.isin(values), name=name)


def build_schema(scope: str, config: ContractConfig) -> pa.DataFrameSchema:
    """Origem normalizada antes de group_id; features sem chave, demografia ou alvo."""
    financial = {name: _column(integer=name in PAY_COLUMNS) for name in FEATURES}
    financial["limit_bal"] = _column(
        checks=[pa.Check(_safe_numeric_check(lambda s: s > 0), name="positive_limit")]
    )
    for name in PAYMENT_COLUMNS:
        financial[name] = _column(
            checks=[pa.Check(_safe_numeric_check(lambda s: s >= 0), name="nonnegative_payment")]
        )
    for name in PAY_COLUMNS:
        financial[name] = _column(integer=True, checks=[_domain(config.pay_domain, "pay_domain")])
    key = _column(integer=True)
    key.unique = True
    label = _column(integer=True, checks=[_domain([0, 1], "binary_target")])
    if scope == "features":
        columns = financial
    elif scope == "keys":
        columns = {"record_id": key, "group_id": pa.Column(str, required=False)}
    elif scope == "labels":
        columns = {"record_id": key, TARGET: label}
    elif scope == "source":
        columns = {"record_id": key, **financial, TARGET: label}
        for name in ("sex", "education", "marriage"):
            columns[name] = _column(
                integer=True, checks=[_domain(getattr(config, f"{name}_domain"), f"{name}_domain")]
            )
        columns["age"] = _column(
            integer=True,
            checks=[pa.Check(_safe_numeric_check(lambda s: s > 0), name="positive_age")],
        )
        columns = {name: columns[name] for name in ["record_id", *ATTRIBUTES, TARGET]}
    else:
        raise ValueError("Schema de contrato desconhecido")
    return pa.DataFrameSchema(columns, strict=True, coerce=False, unique_column_names=True)


def _violations(table: pd.DataFrame, scope: str, config: ContractConfig) -> list[Violation]:
    schema = build_schema(scope, config)
    counts: Counter = Counter()
    if table.empty:
        counts[(None, "nonempty")] += 1
    try:
        schema.validate(table, lazy=True)
    except pa.errors.SchemaErrors as error:
        reasons = {
            "COLUMN_NOT_IN_SCHEMA": "unexpected_column",
            "COLUMN_NOT_IN_DATAFRAME": "missing_column",
            "SERIES_CONTAINS_NULLS": "not_null",
            "SERIES_CONTAINS_DUPLICATES": "unique_id",
            "DUPLICATE_COLUMN_LABELS": "unique_columns",
            "WRONG_DATATYPE": "dtype",
        }
        for failure in error.schema_errors:
            reason = failure.reason_code.name
            rule = reasons.get(reason)
            if rule is None:
                if reason != "DATAFRAME_CHECK" or not isinstance(failure.check, pa.Check):
                    # Erro inesperado do backend é operacional; não vira rejeição de negócio.
                    raise RuntimeError("Falha operacional no validador") from None
                rule = failure.check.name
            name = getattr(failure.schema, "name", None)
            column = name if isinstance(name, str) and name in schema.columns else None
            cases = failure.failure_cases
            counts[(column, rule)] += max(1, len(cases)) if isinstance(cases, pd.DataFrame) else 1
    return [
        Violation(scope=scope, column=column, rule=rule, count=count)
        for (column, rule), count in sorted(counts.items(), key=lambda item: str(item[0]))
    ]


def _result(rows: int, violations: list[Violation], config: ContractConfig) -> ValidationResult:
    return ValidationResult(
        contract_version=config.contract_version,
        rows_received=rows,
        rows_accepted=0 if violations else rows,
        rows_rejected=rows if violations else 0,
        violations=tuple(violations),
    )


def validate_table(
    table: pd.DataFrame, scope: str, config: ContractConfig | None = None
) -> ValidationResult:
    """Valida um schema isolado; devolve diagnóstico sem lançar rejeição esperada."""
    config = config or load_contract_config()
    return _result(len(table), _violations(table, scope, config), config)


def validate_batch(
    features: pd.DataFrame, keys: pd.DataFrame, config: ContractConfig | None = None
) -> ValidationResult:
    """Exige lote financeiro e chaves alinhados por posição, antes do consumidor.

    Retorna resultado válido ou lança ContractRejected. Nenhuma coerção, reordenação,
    inferência ou escrita é executada. O chamador só chama o consumidor após o retorno.
    """
    config = config or load_contract_config()
    violations = _violations(features, "features", config) + _violations(keys, "keys", config)
    if len(features) != len(keys) or not features.index.equals(keys.index):
        violations.append(Violation(scope="batch", column=None, rule="key_alignment", count=1))
    result = _result(len(features), violations, config)
    if not result.valid:
        raise ContractRejected(result)
    return result


def validate_labels(
    labels: pd.DataFrame, keys: pd.DataFrame, config: ContractConfig | None = None
) -> ValidationResult:
    """Exige associação 1:1 por record_id; ordem dos labels pode diferir das chaves."""
    config = config or load_contract_config()
    violations = _violations(labels, "labels", config) + _violations(keys, "keys", config)
    ids_valid = (
        "record_id" in labels
        and "record_id" in keys
        and not any(v.column == "record_id" or v.rule == "unique_columns" for v in violations)
    )
    if ids_valid and set(labels.record_id) != set(keys.record_id):
        violations.append(
            Violation(scope="labels", column="record_id", rule="label_alignment", count=1)
        )
    result = _result(len(labels), violations, config)
    if not result.valid:
        raise ContractRejected(result)
    return result
