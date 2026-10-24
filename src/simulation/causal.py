"""Intervenção no alvo e estimandos pareados exclusivos do simulador."""

import numpy as np
import pandas as pd

from src.data.contracts import validate_labels
from src.data.prepare import TARGET


def latent_uniform(keys: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Associa U aos IDs ordenados com RNG exclusivo, sem consultar X, Y ou scores."""
    if (
        keys.record_id.isna().any()
        or keys.record_id.duplicated().any()
        or not pd.api.types.is_integer_dtype(keys.record_id)
    ):
        raise ValueError("IDs inválidos para choque")
    ids = np.sort(keys.record_id.to_numpy())
    return pd.DataFrame({"record_id": ids, "u": np.random.default_rng(seed).random(len(ids))})


def intervene(labels: pd.DataFrame, latent: pd.DataFrame, r: float) -> pd.DataFrame:
    """Retorna Y(r)=Y(0) OR ((Y(0)=0) AND U<r), mantendo Y(0) intacto."""
    validate_labels(labels, labels[["record_id"]])
    if not np.isfinite(r) or not 0 <= r <= 0.35:
        raise ValueError("Intensidade de choque inválida")
    if (
        list(latent.columns) != ["record_id", "u"]
        or latent.record_id.duplicated().any()
        or latent.record_id.isna().any()
        or set(latent.record_id) != set(labels.record_id)
        or not np.isfinite(latent.u).all()
        or not latent.u.between(0, 1, inclusive="left").all()
    ):
        raise ValueError("Variável latente incompatível")
    u = latent.set_index("record_id").loc[labels.record_id, "u"].to_numpy()
    result = labels.copy()
    result[TARGET] = ((labels[TARGET].to_numpy() == 1) | (u < r)).astype("int64")
    return result


def paired_effect(y0, yr, scores, r: float, *, seed: int = 42, resamples: int = 1000) -> dict:
    """Bootstrap percentil por pares, sem retreino; IC condicional ao modelo/janela."""
    y0, yr, scores = (np.asarray(value) for value in (y0, yr, scores))
    if (
        y0.ndim != 1
        or not len(y0)
        or yr.shape != y0.shape
        or scores.shape != y0.shape
        or not set(y0) <= {0, 1}
        or not set(yr) <= {0, 1}
        or (yr < y0).any()
        or not np.isfinite(scores).all()
        or ((scores < 0) | (scores > 1)).any()
        or not 0 <= r <= 0.35
        or resamples != 1000
    ):
        raise ValueError("Pares ou configuração de bootstrap inválidos")
    delta_y = yr - y0
    delta_loss = (yr - scores) ** 2 - (y0 - scores) ** 2
    rng = np.random.default_rng(seed)
    # Uma reamostragem usa os mesmos IDs para ambos os potenciais e suas perdas.
    boot = np.empty((resamples, 2))
    for i in range(resamples):
        indices = rng.integers(0, len(y0), len(y0))
        boot[i] = [delta_y[indices].mean(), delta_loss[indices].mean()]
    expected = float(r * np.mean(y0 == 0))
    mc_se = float(np.sqrt(np.sum(y0 == 0) * r * (1 - r)) / len(y0))
    return {
        "row_count": len(y0),
        "r": float(r),
        "default_rate_difference": float(delta_y.mean()),
        "expected_default_rate_difference": expected,
        "default_rate_monte_carlo_se": mc_se,
        "default_rate_monte_carlo_interval_95_normal": [
            expected - 1.96 * mc_se,
            expected + 1.96 * mc_se,
        ],
        "default_rate_difference_ci95": np.quantile(boot[:, 0], [0.025, 0.975]).tolist(),
        "brier_difference": float(delta_loss.mean()),
        "brier_difference_ci95": np.quantile(boot[:, 1], [0.025, 0.975]).tolist(),
        "bootstrap_method": "paired_percentile",
        "bootstrap_seed": seed,
        "bootstrap_resamples": resamples,
    }
