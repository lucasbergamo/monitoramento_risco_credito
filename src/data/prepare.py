"""Normalização explícita e auditoria agregada da origem histórica."""

import numpy as np
import pandas as pd

from src.utils.manifest import content_hash

PAY_COLUMNS = ["pay_0", *[f"pay_{i}" for i in range(2, 7)]]
BILL_COLUMNS = [f"bill_amt{i}" for i in range(1, 7)]
PAYMENT_COLUMNS = [f"pay_amt{i}" for i in range(1, 7)]
DEMOGRAPHICS = ["sex", "education", "marriage", "age"]
FEATURES = ["limit_bal", *PAY_COLUMNS, *BILL_COLUMNS, *PAYMENT_COLUMNS]
ATTRIBUTES = ["limit_bal", *DEMOGRAPHICS, *PAY_COLUMNS, *BILL_COLUMNS, *PAYMENT_COLUMNS]
TARGET = "default_next_month"
SOURCE_COLUMNS = {
    "ID": "record_id",
    **{name.upper(): name for name in ATTRIBUTES},
    "default payment next month": TARGET,
}


def prepare(source: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Retorna tabela int64 ordenada por ID e achados sem linhas individuais.

    Não elimina registros repetidos nem atribui semântica a códigos não especificados.
    O grupo considera os 23 atributos da origem e exclui ID e target.
    """
    if source.columns.tolist() != list(SOURCE_COLUMNS):
        raise ValueError("Schema de origem incompatível")
    normalized = source.rename(columns=SOURCE_COLUMNS).copy()
    for name in normalized.columns:
        values = pd.to_numeric(normalized[name], errors="raise")
        if (
            values.isna().any()
            or not np.isfinite(values).all()
            or (values % 1 != 0).any()
            or (values < -(2**63)).any()
            or (values >= 2**63).any()
        ):
            raise ValueError("Origem exige valores inteiros finitos, sem ausentes")
        normalized[name] = values.astype("int64")
    if not normalized.record_id.is_unique:
        raise ValueError("IDs repetidos na origem")
    if set(normalized[TARGET].unique()) != {0, 1}:
        raise ValueError("Alvo exige as duas classes binárias")
    normalized = normalized.sort_values("record_id").reset_index(drop=True)
    normalized["group_id"] = [
        content_hash([int(value) for value in row])
        for row in normalized[ATTRIBUTES].itertuples(index=False, name=None)
    ]
    counts = normalized.groupby("group_id").size()
    targets = normalized.groupby("group_id")[TARGET].nunique()
    audit = {
        "normalized_dtypes": {name: str(dtype) for name, dtype in normalized.dtypes.items()},
        "missing_values": 0,
        "unique_ids": True,
        "categories": {
            name: sorted(int(value) for value in normalized[name].unique())
            for name in ["sex", "education", "marriage", *PAY_COLUMNS]
        },
        "negative_bills": {name: int((normalized[name] < 0).sum()) for name in BILL_COLUMNS},
        "negative_payments": {name: int((normalized[name] < 0).sum()) for name in PAYMENT_COLUMNS},
        "nonpositive_limits": int((normalized.limit_bal <= 0).sum()),
        "duplicate_groups": int((counts > 1).sum()),
        "records_in_duplicate_groups": int(counts[counts > 1].sum()),
        "extra_duplicate_records": int((counts - 1).sum()),
        "groups_with_conflicting_labels": int((targets > 1).sum()),
        "group_count": len(counts),
    }
    return normalized, audit
