"""Associação de labels após predição e avaliação supervisionada pareada."""

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from src.data.contracts import validate_labels
from src.data.prepare import TARGET
from src.models.evaluate import metrics
from src.simulation.causal import paired_effect


def align_labels(predictions: pd.DataFrame, labels: pd.DataFrame) -> np.ndarray:
    """Rejeita IDs ausentes/extras/duplicados; nunca associa labels pela posição."""
    if (
        list(predictions.columns) != ["record_id", "score"]
        or predictions.empty
        or not np.isfinite(predictions.score).all()
        or not predictions.score.between(0, 1).all()
    ):
        raise ValueError("Predições inválidas")
    validate_labels(labels, predictions[["record_id"]])
    return labels.set_index("record_id").loc[predictions.record_id, TARGET].to_numpy()


def evaluate_labels(predictions: pd.DataFrame, labels: pd.DataFrame | None) -> dict:
    """Ausência de labels é explícita; métricas nunca são preenchidas com zero."""
    if labels is None:
        return {"status": "labels_unavailable", "metrics": None, "reason": "labels_not_associated"}
    y = align_labels(predictions, labels)
    if set(y) != {0, 1}:
        return {
            "status": "partial",
            "reason": "single_class",
            "metrics": {
                "row_count": len(y),
                "prevalence": float(y.mean()),
                "brier": float(brier_score_loss(y, predictions.score)),
                "roc_auc": None,
                "average_precision": None,
                "recall": None,
            },
        }
    return {"status": "available", "metrics": metrics(y, predictions.score)}


def compare_paired(
    stable: pd.DataFrame,
    concept: pd.DataFrame,
    original: pd.DataFrame,
    synthetic: pd.DataFrame,
    r: float,
    *,
    seed: int = 42,
    resamples: int = 1000,
) -> dict:
    """Exige mesmos IDs/scores e associa os dois alvos independentemente por chave."""
    y0 = align_labels(stable, original)
    # Valida duplicatas antes da reordenação, para impedir associações ambíguas.
    align_labels(concept, synthetic)
    if set(stable.record_id) != set(concept.record_id):
        raise ValueError("IDs do par incompatíveis")
    aligned = concept.set_index("record_id").loc[stable.record_id, "score"].to_numpy()
    if not np.array_equal(stable.score.to_numpy(), aligned):
        raise ValueError("Scores do par incompatíveis")
    yr = align_labels(stable, synthetic)
    result = paired_effect(y0, yr, stable.score.to_numpy(), r, seed=seed, resamples=resamples)
    before, after = evaluate_labels(stable, original), evaluate_labels(stable, synthetic)
    result["original"] = before
    result["synthetic"] = after
    result["metric_differences"] = {
        name: (
            after["metrics"][name] - before["metrics"][name]
            if after["metrics"][name] is not None and before["metrics"][name] is not None
            else None
        )
        for name in ("brier", "recall", "roc_auc")
    }
    return result
