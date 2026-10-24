"""Inferência financeira sem labels, bloqueada por contratos e integridade."""

from pathlib import Path

import pandas as pd
from threadpoolctl import threadpool_limits

from src.data.contracts import validate_batch
from src.models.registry import load_bundle


def predict_batch(features: pd.DataFrame, keys: pd.DataFrame, model_dir: Path) -> pd.DataFrame:
    """Retorna scores locais por ID após validar lote e modelo; não grava arquivos."""
    validate_batch(features, keys)
    estimators, manifest = load_bundle(model_dir)
    if features.columns.tolist() != manifest["feature_names"]:
        raise ValueError("Ordem ou nomes das features incompatíveis")
    with threadpool_limits(limits=manifest["effective_config"]["threads"]):
        scores = estimators["model"].predict_proba(features)[:, 1]
    return pd.DataFrame({"record_id": keys.record_id.to_numpy(), "score": scores})
