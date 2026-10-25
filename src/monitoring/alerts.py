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
        events[key] = {
            "key": key,
            "run_id": run_id,
            "window": window,
            "type": "feature_drift",
            "feature": row["feature"],
            "severity": "warning",
            "rule": row["operational_rule"],
            "metric": row["method"],
            "value": row["score"],
            "threshold": row["threshold"],
            "p_adjusted": row["p_adjusted"],
            "ks_d": row["ks_d"],
            "minimum_ks_d": row["minimum_ks_d"],
            "action": "Investigar coleta, variáveis e desempenho com labels disponíveis",
        }
    return list(events.values())
