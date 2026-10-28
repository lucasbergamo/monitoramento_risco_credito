"""Diagnóstico agregado de desempenho por grupos no teste congelado."""

import pandas as pd
from threadpoolctl import threadpool_limits

from src.data.prepare import DEMOGRAPHICS, TARGET
from src.models.registry import load_bundle
from src.models.train import load_partition, verify_dataset
from src.utils.manifest import content_hash, file_hash, write_manifest

MIN_GROUP_SIZE = 100
MIN_CLASS_SIZE = 20
AGE_BANDS = (
    ("21-34", 21, 34),
    ("35-49", 35, 49),
    ("50+", 50, None),
)


def _ratio(numerator: int, denominator: int, *, suppressed: bool = False) -> dict:
    return {
        "value": None if suppressed else float(numerator / denominator),
        "numerator": int(numerator),
        "denominator": int(denominator),
        "status": "suppressed" if suppressed else "available",
    }


def _group_metrics(labels, scores, threshold: float) -> dict:
    y = pd.Series(labels, dtype="int64").to_numpy()
    p = pd.Series(scores, dtype="float64").to_numpy()
    predicted = p >= threshold
    positives = y == 1
    negatives = y == 0
    true_positives = int((predicted & positives).sum())
    false_positives = int((predicted & negatives).sum())
    size_ok = len(y) >= MIN_GROUP_SIZE
    return {
        "n": int(len(y)),
        "positive_n": int(positives.sum()),
        "negative_n": int(negatives.sum()),
        "prevalence": _ratio(int(positives.sum()), len(y), suppressed=not size_ok),
        "recall": _ratio(
            true_positives,
            int(positives.sum()),
            suppressed=not size_ok or int(positives.sum()) < MIN_CLASS_SIZE,
        ),
        "false_positive_rate": _ratio(
            false_positives,
            int(negatives.sum()),
            suppressed=not size_ok or int(negatives.sum()) < MIN_CLASS_SIZE,
        ),
        "brier": None,
        "decision_threshold": float(threshold),
    }


def _brier_ratio(labels, scores, suppressed: bool) -> dict:
    y = pd.Series(labels, dtype="int64").to_numpy()
    p = pd.Series(scores, dtype="float64").to_numpy()
    return {
        "value": None if suppressed else float(((y - p) ** 2).mean()),
        "numerator": None if suppressed else float(((y - p) ** 2).sum()),
        "denominator": int(len(y)),
        "status": "suppressed" if suppressed else "available",
    }


def _metrics(labels, scores, threshold: float) -> dict:
    result = _group_metrics(labels, scores, threshold)
    result["brier"] = _brier_ratio(labels, scores, suppressed=result["n"] < MIN_GROUP_SIZE)
    return result


def _groups(audit: pd.DataFrame, labels, scores, threshold: float) -> dict:
    result = {"sex": [], "age_band": []}
    for code in sorted(audit["sex"].dropna().unique().tolist()):
        mask = audit["sex"].to_numpy() == code
        result["sex"].append(
            {
                "group": f"code_{int(code)}",
                **_metrics(labels[mask], scores[mask], threshold),
            }
        )
    age = audit["age"].to_numpy()
    assigned = pd.Series(False, index=range(len(audit)))
    for name, lower, upper in AGE_BANDS:
        mask = age >= lower
        if upper is not None:
            mask &= age <= upper
        assigned |= pd.Series(mask)
        result["age_band"].append(
            {"group": name, **_metrics(labels[mask], scores[mask], threshold)}
        )
    other = ~assigned.to_numpy()
    if other.any():
        result["age_band"].append(
            {"group": "outside_defined_bands", **_metrics(labels[other], scores[other], threshold)}
        )
    return result


def governance(settings) -> dict:
    """Calcula métricas do modelo aprovado sem inserir demografia nas features."""
    dataset = verify_dataset(settings)
    features, keys, labels, hashes = load_partition(settings, dataset, "test")
    audit_path = settings.data_dir / "silver/audit.parquet"
    expected_audit_hash = dataset["files"]["silver/audit.parquet"]
    if file_hash(audit_path) != expected_audit_hash:
        raise ValueError("Integridade da tabela de auditoria demográfica inválida")
    audit = pd.read_parquet(audit_path)
    if audit.columns.tolist() != ["record_id", *DEMOGRAPHICS]:
        raise ValueError("Schema da tabela de auditoria demográfica incompatível")
    if audit["record_id"].duplicated().any() or audit["record_id"].isna().any():
        raise ValueError("Chaves da tabela de auditoria demográfica inválidas")

    ordered_ids = keys["record_id"].to_numpy()
    audit_indexed = audit.set_index("record_id")
    if not set(ordered_ids).issubset(audit_indexed.index):
        raise ValueError("Tabela de auditoria não cobre as chaves do teste")
    test_audit = audit_indexed.loc[ordered_ids, ["sex", "age"]].reset_index(drop=True)
    y = labels.set_index("record_id").loc[ordered_ids, TARGET].to_numpy()
    estimators, model = load_bundle(settings.models_dir / "current")
    with threadpool_limits(limits=model["effective_config"]["threads"]):
        scores = estimators["model"].predict_proba(features)[:, 1]

    threshold = float(model["effective_config"]["decision_threshold"])
    report = {
        "schema_version": 1,
        "dataset_manifest_hash": content_hash(dataset),
        "model_version": model["version"],
        "model_sha256": model["model_sha256"],
        "partition": "test",
        "row_count": int(len(y)),
        "demographic_fields_used_for_grouping": ["sex", "age"],
        "demographic_fields_used_as_features": [],
        "minimum_group_size": MIN_GROUP_SIZE,
        "minimum_positive_or_negative_count": MIN_CLASS_SIZE,
        "age_bands": [name for name, _, _ in AGE_BANDS],
        "decision_threshold": threshold,
        "test_file_hashes": hashes,
        "audit_table_sha256": expected_audit_hash,
        "groups": _groups(test_audit, y, scores, threshold),
    }
    write_manifest(settings.project_root / "docs/evidencias/governanca.json", report)
    return report
