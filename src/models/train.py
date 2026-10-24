"""Treino exclusivo na partição de treino e decisões congeladas pela validação."""

import platform
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from threadpoolctl import threadpool_limits

from src.data.contracts import validate_batch, validate_labels
from src.data.prepare import FEATURES, TARGET
from src.models.evaluate import metrics, validation_gate
from src.utils.config import PROJECT_ROOT, load_data_config
from src.utils.manifest import content_hash, file_hash, read_manifest
from src.utils.reproducibility import set_seed


class ModelConfig(BaseModel):
    """Parâmetros fixados; o piso pode ser elevado em testes negativos explícitos."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    seed: Literal[42] = 42
    threads: Literal[1] = 1
    max_iter: Literal[150] = 150
    max_leaf_nodes: Literal[15] = 15
    learning_rate: Literal[0.1] = 0.1
    l2_regularization: Literal[1.0] = 1.0
    early_stopping: Literal[False] = False
    categorical_features: None = None
    decision_threshold: Literal[0.5] = 0.5
    minimum_validation_auc: float = Field(default=0.65, ge=0.65, allow_inf_nan=False)
    importance_repeats: Literal[5] = 5

    def estimator_params(self) -> dict:
        return {
            name: getattr(self, name)
            for name in (
                "max_iter",
                "max_leaf_nodes",
                "learning_rate",
                "l2_regularization",
                "early_stopping",
                "categorical_features",
            )
        } | {"random_state": self.seed}


def load_model_config(path: Path | None = None) -> ModelConfig:
    path = path or PROJECT_ROOT / "configs/model.yaml"
    return ModelConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def verify_dataset(settings) -> dict:
    """Confere contrato do manifesto sem abrir teste ou produção para selecionar modelo."""
    manifest = read_manifest(settings.data_dir / "gold/dataset_manifest.json")
    config = load_data_config()
    if (
        manifest["feature_names"] != FEATURES
        or manifest["schema_hash"] != content_hash(manifest["schema"])
        or any(manifest["schema"].get(name) != "int64" for name in FEATURES)
        or manifest["effective_config"] != config.model_dump()
        or manifest["config_hash"] != content_hash(config.model_dump())
        or manifest["source_sha256"] != config.source_sha256
        or manifest["split_seed"] != config.split_seed
        or manifest["parser_version"] != config.parser_version
        or len(manifest["split_hash"]) != 64
    ):
        raise ValueError("Manifesto de preparação incompatível")
    return manifest


def load_partition(settings, manifest: dict, name: str) -> tuple:
    """Verifica hashes antes de ler e associa labels por chave, nunca por posição."""
    if name not in {"train", "validation", "test"}:
        raise ValueError("Partição de modelagem desconhecida")
    tables = {}
    hashes = {}
    for kind in ("features", "keys", "labels"):
        relative = f"gold/{name}/{kind}.parquet"
        path = settings.data_dir / relative
        if file_hash(path) != manifest["files"][relative]:
            raise ValueError("Integridade da partição inválida")
        tables[kind] = pd.read_parquet(path)
        hashes[relative] = manifest["files"][relative]
    features, keys, labels = (tables[kind] for kind in ("features", "keys", "labels"))
    validate_batch(features, keys)
    validate_labels(labels, keys)
    if features.columns.tolist() != FEATURES or set(labels[TARGET]) != {0, 1}:
        raise ValueError("Ordem de features ou classes incompatíveis")
    if len(features) != manifest["partitions"][name]["row_count"]:
        raise ValueError("Contagem da partição incompatível")
    return features, keys, labels, hashes


def select_drift_features(importances: dict, supported=FEATURES) -> list[str]:
    """Todas as 19 financeiras têm transformação definida; empate usa nome crescente."""
    candidates = [
        name for name in supported if name in importances and importances[name]["mean"] > 0
    ]
    selected = sorted(candidates, key=lambda name: (-importances[name]["mean"], name))[:2]
    if len(selected) != 2:
        raise ValueError("Menos de duas features suportadas com importância positiva")
    return selected


def train(settings, config: ModelConfig | None = None) -> dict:
    """Treina HGB/Dummy e publica staging após métricas e seleção na validação.

    Não lê teste, produção ou auditoria demográfica. Artefato reprovado é preservado
    em staging para diagnóstico; somente a promoção exige gate aprovado.
    """
    from src.models.registry import save_bundle

    config = config or load_model_config(settings.project_root / "configs/model.yaml")
    set_seed(config.seed)
    dataset = verify_dataset(settings)
    x_train, train_keys, train_labels, train_hashes = load_partition(settings, dataset, "train")
    x_validation, keys, labels, validation_hashes = load_partition(settings, dataset, "validation")
    if set(train_keys.record_id) & set(keys.record_id) or set(train_keys.group_id) & set(
        keys.group_id
    ):
        raise ValueError("Interseção entre treino e validação")
    y_train = train_labels.set_index("record_id").loc[train_keys.record_id, TARGET].to_numpy()
    y_validation = labels.set_index("record_id").loc[keys.record_id, TARGET].to_numpy()
    estimators = {
        "model": HistGradientBoostingClassifier(**config.estimator_params()),
        "dummy": DummyClassifier(strategy="prior"),
    }
    with threadpool_limits(limits=config.threads):
        for estimator in estimators.values():
            estimator.fit(x_train, y_train)
        validation = {
            name: metrics(y_validation, estimator.predict_proba(x_validation)[:, 1])
            for name, estimator in estimators.items()
        }
        importance = permutation_importance(
            estimators["model"],
            x_validation,
            y_validation,
            scoring="roc_auc",
            n_repeats=config.importance_repeats,
            random_state=config.seed,
            n_jobs=1,
        )
    importances = {
        name: {
            "mean": float(importance.importances_mean[i]),
            "std": float(importance.importances_std[i]),
            "repeats": importance.importances[i].tolist(),
        }
        for i, name in enumerate(FEATURES)
    }
    drift_features = select_drift_features(importances)
    manifest = {
        "schema_version": 1,
        "feature_names": FEATURES,
        "dataset_manifest_hash": content_hash(dataset),
        "source_sha256": dataset["source_sha256"],
        "split_hash": dataset["split_hash"],
        "preparation": {
            "parser_version": dataset["parser_version"],
            "schema_hash": dataset["schema_hash"],
            "config_hash": dataset["config_hash"],
        },
        "input_hashes": train_hashes | validation_hashes,
        "train": {"row_count": len(x_train), "prevalence": float(np.mean(y_train))},
        "parameters": config.estimator_params(),
        "dummy_parameters": {"strategy": "prior"},
        "effective_config": config.model_dump(),
        "config_hash": content_hash(config.model_dump()),
        "seed": config.seed,
        "versions": {
            "python": platform.python_version(),
            **{name: version(name) for name in ("scikit-learn", "numpy", "pandas", "joblib")},
        },
        "validation": validation,
        "gate_passed": validation_gate(validation, config.minimum_validation_auc),
        "permutation_importance": {
            "partition": "validation",
            "scoring": "roc_auc",
            "n_repeats": 5,
            "seed": config.seed,
            "features": importances,
        },
        "drift_features": drift_features,
        "reference": {
            "source_partition": "train",
            "files": {
                name: digest
                for name, digest in dataset["files"].items()
                if name.startswith("gold/reference/")
            },
        },
    }
    return save_bundle(settings.models_dir, estimators, manifest)
