"""Métricas agregadas e avaliação final sem seleção pelo teste."""

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from threadpoolctl import threadpool_limits

from src.utils.manifest import content_hash, write_manifest


def metrics(labels, scores, threshold: float = 0.5) -> dict:
    """Métricas binárias com classe positiva 1; AP não é área trapezoidal PR."""
    labels, scores = np.asarray(labels), np.asarray(scores)
    if (
        labels.ndim != 1
        or scores.shape != labels.shape
        or set(labels) != {0, 1}
        or not np.isfinite(scores).all()
        or ((scores < 0) | (scores > 1)).any()
    ):
        raise ValueError("Avaliação exige duas classes e probabilidades alinhadas")
    predicted = scores >= threshold
    return {
        "row_count": len(labels),
        "prevalence": float(labels.mean()),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "average_precision": float(average_precision_score(labels, scores)),
        "brier": float(brier_score_loss(labels, scores)),
        "log_loss": float(log_loss(labels, scores, labels=[0, 1])),
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "confusion_matrix": confusion_matrix(labels, predicted, labels=[0, 1]).tolist(),
        "decision_threshold": threshold,
    }


def validation_gate(validation: dict, minimum_auc: float) -> bool:
    return bool(
        validation["model"]["roc_auc"] >= minimum_auc
        and validation["model"]["brier"] < validation["dummy"]["brier"]
    )


def evaluate(settings) -> dict:
    """Lê teste somente após carregar decisões congeladas no staging.

    O relatório de teste fica fora do bundle imutável e não é usado pela promoção.
    """
    from src.models.registry import load_bundle
    from src.models.train import load_partition, verify_dataset

    estimators, manifest = load_bundle(settings.models_dir / "staging")
    dataset = verify_dataset(settings)
    if content_hash(dataset) != manifest["dataset_manifest_hash"]:
        raise ValueError("Dataset diverge do treino congelado")
    features, keys, labels, _ = load_partition(settings, dataset, "test")
    # Predições precedem a associação explícita dos labels por ID.
    with threadpool_limits(limits=manifest["effective_config"]["threads"]):
        probabilities = {
            name: estimator.predict_proba(features)[:, 1] for name, estimator in estimators.items()
        }
    aligned = labels.set_index("record_id").loc[keys.record_id, "default_next_month"]
    report = {
        "schema_version": 1,
        "model_version": manifest["version"],
        "dataset_manifest_hash": manifest["dataset_manifest_hash"],
        "partition": "test",
        "metrics": {
            name: metrics(aligned, scores, manifest["effective_config"]["decision_threshold"])
            for name, scores in probabilities.items()
        },
    }
    write_manifest(settings.models_dir / "evaluations" / f"{manifest['version']}.json", report)
    write_manifest(
        settings.project_root / "docs/evidencias/baseline.json",
        {"schema_version": 1, "model_manifest": manifest, "test_evaluation": report},
    )
    return report
