"""Regras estatísticas e eventos agregados, sem efeitos externos."""

import math


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down para toda a família numérica da janela, incluindo constantes."""
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in p_values.values()):
        raise ValueError("P-valores inválidos")
    ordered = sorted(p_values, key=lambda name: (p_values[name], name))
    adjusted, previous = {}, 0.0
    for rank, name in enumerate(ordered):
        previous = min(1.0, max(previous, (len(ordered) - rank) * p_values[name]))
        adjusted[name] = previous
    return adjusted


def feature_alerts(rows: list[dict], run_id: str, window: str) -> list[dict]:
    """Deduplica por execução/janela/tipo/feature; nova execução mantém outro evento."""
    events = {}
    for row in rows:
        if not row["operational_alert"]:
            continue
        key = f"{run_id}/{window}/feature_drift/{row['feature']}"
        metric = row["method"]
        if metric == "psi":
            condition = f"{row['feature']}: PSI {row['score']:.4f} >= {row['threshold']:.2f}"
        else:
            condition = (
                f"{row['feature']}: KS D {row['ks_d']:.4f} >= "
                f"{row['minimum_ks_d']:.2f}; p-Holm {row['p_adjusted']:.3g} "
                f"< {row['threshold']:.2f}"
            )
        events[key] = {
            "key": key,
            "run_id": run_id,
            "window": window,
            "type": "feature_drift",
            "feature": row["feature"],
            "condition": condition,
            "severity": "warning",
            "rule": row["operational_rule"],
            "metric": metric,
            "value": row["score"],
            "threshold": row["threshold"],
            "p_adjusted": row["p_adjusted"],
            "ks_d": row["ks_d"],
            "minimum_ks_d": row["minimum_ks_d"],
            "action": "Investigar coleta, variáveis e desempenho com labels disponíveis",
        }
    return list(events.values())
