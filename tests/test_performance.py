"""Associação por chave, potenciais e incerteza com dados sintéticos próprios."""

import numpy as np
import pandas as pd
import pytest

from src.data.contracts import ContractRejected
from src.data.prepare import TARGET
from src.monitoring.performance import align_labels, compare_paired, evaluate_labels
from src.simulation.causal import intervene, latent_uniform, paired_effect


def frames():
    scores = pd.DataFrame({"record_id": [3, 1, 4, 2], "score": [0.1, 0.2, 0.8, 0.9]})
    labels = pd.DataFrame({"record_id": [3, 1, 4, 2], TARGET: [0, 0, 1, 1]})
    return scores, labels


def test_labels_missing_and_reordered():
    scores, labels = frames()
    assert evaluate_labels(scores, None) == {
        "status": "labels_unavailable",
        "metrics": None,
        "reason": "labels_not_associated",
    }
    assert evaluate_labels(scores, labels) == evaluate_labels(scores, labels.iloc[::-1])
    assert evaluate_labels(scores, labels)["metrics"]["brier"] == pytest.approx(0.025)
    assert evaluate_labels(scores, labels.assign(**{TARGET: 1}))["metrics"]["roc_auc"] is None


@pytest.mark.parametrize("problem", ["missing", "duplicate", "extra", "wrong", "null", "target"])
def test_bad_labels_rejected(problem):
    scores, labels = frames()
    if problem == "missing":
        labels = labels.iloc[:-1]
    elif problem == "duplicate":
        labels.loc[0, "record_id"] = labels.record_id.iloc[1]
    elif problem == "extra":
        labels = pd.concat([labels, pd.DataFrame({"record_id": [9], TARGET: [1]})])
    elif problem == "wrong":
        labels.loc[0, "record_id"] = 99
    elif problem == "null":
        labels.loc[0, TARGET] = np.nan
    else:
        labels.loc[0, TARGET] = 2
    with pytest.raises(ContractRejected):
        align_labels(scores, labels)


def test_uniform_independent_of_order_and_intervention_control():
    scores, labels = frames()
    keys = scores[["record_id"]]
    latent = latent_uniform(keys, 42)
    pd.testing.assert_frame_equal(latent, latent_uniform(keys.iloc[::-1], 42))
    np.testing.assert_array_equal(latent.u, np.random.default_rng(42).random(len(keys)))
    original = labels.copy()
    pd.testing.assert_frame_equal(intervene(labels, latent, 0), labels)
    changed = intervene(labels, latent, 0.35)
    expected = (labels[TARGET].to_numpy() == 1) | (
        latent.set_index("record_id").loc[labels.record_id, "u"].to_numpy() < 0.35
    )
    np.testing.assert_array_equal(changed[TARGET], expected.astype(int))
    pd.testing.assert_frame_equal(labels, original)
    for r in (-0.01, 0.36, np.nan):
        with pytest.raises(ValueError):
            intervene(labels, latent, r)
    with pytest.raises(ValueError):
        intervene(labels, latent.iloc[:-1], 0.1)
    with pytest.raises(ValueError):
        latent_uniform(pd.concat([keys, keys]), 42)


def test_known_paired_effect_and_zero_control():
    y0, yr, scores = np.array([0, 0, 1, 1]), np.array([1, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])
    result = paired_effect(y0, yr, scores, 0.35)
    assert result["default_rate_difference"] == 0.25
    assert result["expected_default_rate_difference"] == 0.175
    assert result["brier_difference"] == pytest.approx(0.2)
    assert result == paired_effect(y0, yr, scores, 0.35)
    zero = paired_effect(y0, y0, scores, 0)
    assert zero["brier_difference_ci95"] == [0, 0]
    assert zero["default_rate_difference_ci95"] == [0, 0]
    scores_frame, labels = frames()
    pair = compare_paired(scores_frame, scores_frame.iloc[::-1], labels, labels.iloc[::-1], 0)
    assert pair["metric_differences"] == {"brier": 0, "recall": 0, "roc_auc": 0}
    with pytest.raises(ValueError):
        compare_paired(scores_frame, scores_frame.assign(score=0.5), labels, labels, 0)
    with pytest.raises(ContractRejected):
        compare_paired(scores_frame, scores_frame.iloc[:-1], labels, labels, 0)
    with pytest.raises(ValueError):
        paired_effect(y0, yr, scores, 0.35, resamples=10)


@pytest.mark.parametrize("scores", [[], [0.2], [np.nan, 0.2, 0.3, 0.4], [-1, 0, 0, 1]])
def test_invalid_predictions(scores):
    predictions, labels = frames()
    if len(scores) != 4:
        predictions = predictions.iloc[: len(scores)].copy()
    predictions["score"] = scores
    with pytest.raises((ValueError, ContractRejected)):
        evaluate_labels(predictions, labels)
