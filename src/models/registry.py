"""Bundles imutáveis e troca atômica de ponteiros locais em filesystem POSIX."""

import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier

from src.data.prepare import FEATURES
from src.models.evaluate import validation_gate
from src.models.train import ModelConfig, select_drift_features
from src.utils.manifest import content_hash, file_hash, read_manifest, write_manifest


class PromotionRejected(ValueError):
    """Gate de validação não atendido; current permanece intacto."""


def _point(root: Path, name: str, directory: Path) -> None:
    """Somente o rename do symlink torna a versão completa visível aos leitores."""
    destination = root / name
    # setup cria diretórios vazios no primeiro uso. rmdir recusa qualquer conteúdo.
    if destination.is_dir() and not destination.is_symlink():
        destination.rmdir()
    temporary = root / f".{name}-{uuid4().hex}"
    try:
        temporary.symlink_to(directory.relative_to(root), target_is_directory=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def load_bundle(directory: Path) -> tuple[dict, dict]:
    """Verifica manifesto, hash e schema antes/depois de desserializar joblib local.

    SHA-256 detecta corrupção, não autentica um arquivo recebido de terceiros.
    Joblib somente pode ser carregado de armazenamento confiável deste projeto.
    Resolve o ponteiro uma vez, evitando misturar versões durante promoção.
    """
    directory = directory.resolve(strict=True)
    manifest = read_manifest(directory / "manifest.json")
    expected_version = content_hash(
        {key: value for key, value in manifest.items() if key != "version"}
    )
    if manifest["version"] != expected_version:
        raise ValueError("Integridade do manifesto inválida")
    config = ModelConfig.model_validate(manifest["effective_config"])
    if (
        manifest["feature_names"] != FEATURES
        or manifest["config_hash"] != content_hash(config.model_dump())
        or manifest["parameters"] != config.estimator_params()
        or manifest["dummy_parameters"] != {"strategy": "prior"}
        or manifest["seed"] != config.seed
        or manifest["drift_features"]
        != select_drift_features(manifest["permutation_importance"]["features"])
        or manifest["gate_passed"]
        != validation_gate(manifest["validation"], config.minimum_validation_auc)
        or file_hash(directory / "model.joblib") != manifest["model_sha256"]
    ):
        raise ValueError("Integridade ou contrato do modelo inválido")
    estimators = joblib.load(directory / "model.joblib")
    if (
        set(estimators) != {"model", "dummy"}
        or not isinstance(estimators["model"], HistGradientBoostingClassifier)
        or not isinstance(estimators["dummy"], DummyClassifier)
    ):
        raise ValueError("Estimadores incompatíveis")
    for estimator in estimators.values():
        if list(estimator.feature_names_in_) != FEATURES or not np.array_equal(
            estimator.classes_, [0, 1]
        ):
            raise ValueError("Features ou classes do artefato incompatíveis")
    params = estimators["model"].get_params()
    if any(params[key] != value for key, value in manifest["parameters"].items()):
        raise ValueError("Parâmetros do artefato incompatíveis")
    if estimators["dummy"].strategy != "prior":
        raise ValueError("Comparador incompatível")
    return estimators, manifest


def save_bundle(root: Path, estimators: dict, manifest: dict) -> dict:
    """Materializa versão completa e verifica antes de apontar staging para ela."""
    bundles = root / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".training-", dir=root) as temporary:
        directory = Path(temporary)
        joblib.dump(estimators, directory / "model.joblib", compress=3)
        manifest = manifest | {"model_sha256": file_hash(directory / "model.joblib")}
        manifest["version"] = content_hash(manifest)
        write_manifest(directory / "manifest.json", manifest)
        load_bundle(directory)
        destination = bundles / manifest["version"]
        if destination.exists():
            load_bundle(destination)
        else:
            directory.rename(destination)
        _point(root, "staging", destination)
    return manifest


def promote(settings) -> dict:
    """Recalcula gate pela validação e copia bundle completo antes de trocar current.

    Métricas de teste nunca são consultadas. Falha antes do replace preserva a versão
    atual. Leitores carregam sempre a versão completa anterior ou a nova.
    """
    root = settings.models_dir
    source = (root / "staging").resolve(strict=True)
    _, manifest = load_bundle(source)
    if not manifest["gate_passed"]:
        raise PromotionRejected("Promoção bloqueada pelo gate de validação")
    approved = root / "approved"
    approved.mkdir(exist_ok=True)
    destination = approved / manifest["version"]
    if destination.exists():
        load_bundle(destination)
    else:
        with TemporaryDirectory(prefix=".promotion-", dir=root) as temporary:
            copy = Path(temporary) / "bundle"
            shutil.copytree(source, copy)
            load_bundle(copy)
            copy.rename(destination)
    _point(root, "current", destination)
    return manifest
