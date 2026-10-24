"""Prova executável das versões e fronteiras reais, sem dados externos."""

import importlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.utils.reproducibility import set_seed


@pytest.fixture
def synthetic_data():
    rng = set_seed(42)
    frame = pd.DataFrame({"balance": rng.uniform(1, 100, 100), "payment": rng.uniform(0, 20, 100)})
    labels = (frame["balance"] > 50).astype(int)
    return frame, labels


def test_python_and_pinned_versions():
    assert sys.version_info[:2] == (3, 12)
    expected = {
        "scikit-learn": "1.9.1",
        "pandera": "0.34.1",
        "evidently": "0.7.23",
        "mlflow": "3.16.1",
        "pandas": "2.3.3",
        "numpy": "2.2.6",
        "scipy": "1.15.3",
    }
    for package, pin in expected.items():
        assert version(package) == pin


@pytest.mark.parametrize(
    "module",
    [
        "pyarrow",
        "xlrd",
        "joblib",
        "pydantic_settings",
        "structlog",
        "psutil",
        "matplotlib",
        "jinja2",
        "yaml",
    ],
)
def test_complementary_dependencies_import(module):
    importlib.import_module(module)


def test_real_libraries_roundtrip(synthetic_data, tmp_path):
    import pandera.pandas as pa
    from evidently import Report
    from evidently.presets import DataDriftPreset
    from mlflow.tracking import MlflowClient
    from sklearn.ensemble import HistGradientBoostingClassifier

    features, labels = synthetic_data
    schema = pa.DataFrameSchema(
        {"balance": pa.Column(float, pa.Check.gt(0)), "payment": pa.Column(float, pa.Check.ge(0))},
        strict=True,
    )
    validated = schema.validate(features, lazy=True)
    # A seed é definida pela fixture antes da geração; o estimador também a recebe.
    model = HistGradientBoostingClassifier(
        max_iter=10,
        max_leaf_nodes=3,
        early_stopping=False,
        categorical_features=None,
        random_state=42,
    ).fit(validated, labels)
    scores = model.predict_proba(validated)[:, 1]
    assert scores.shape == (100,)
    assert np.isfinite(scores).all()
    assert scores[labels == 1].mean() > scores[labels == 0].mean()

    snapshot = Report([DataDriftPreset()]).run(
        current_data=validated.copy(), reference_data=validated
    )
    html_path = tmp_path / "environment.html"
    json_path = tmp_path / "environment.json"
    snapshot.save_html(str(html_path))
    snapshot.save_json(str(json_path))
    assert "<html" in html_path.read_text().lower()
    payload = json.loads(json_path.read_text())
    assert payload["metrics"]

    tracking_uri = f"sqlite:///{tmp_path / 'tracking.db'}"
    artifact_store = tmp_path / "store"
    artifact_store.mkdir()
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment_id = client.create_experiment(
        "environment", artifact_location=artifact_store.as_uri()
    )
    run = client.create_run(experiment_id)
    run_id = run.info.run_id
    client.log_param(run_id, "seed", "42")
    client.log_metric(run_id, "prediction_count", len(scores))
    client.log_artifact(run_id, str(json_path))
    client.log_artifact(run_id, str(html_path))
    client.set_terminated(run_id)

    # Novo cliente precisa recuperar o estado persistido, não só memória do writer.
    reader = MlflowClient(tracking_uri=tracking_uri)
    restored = reader.get_run(run_id)
    assert restored.info.status == "FINISHED"
    assert restored.data.params["seed"] == "42"
    assert restored.data.metrics["prediction_count"] == 100
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    for original in (json_path, html_path):
        downloaded = reader.download_artifacts(run_id, original.name, str(downloads))
        assert Path(downloaded).read_bytes() == original.read_bytes()
    assert (tmp_path / "tracking.db").is_file()


def test_pandera_aggregates_independent_failures(synthetic_data):
    import pandera.pandas as pa

    features, _ = synthetic_data
    schema = pa.DataFrameSchema(
        {"balance": pa.Column(float, pa.Check.gt(0)), "payment": pa.Column(float, pa.Check.ge(0))},
        strict=True,
    )
    invalid = features.copy()
    invalid.loc[0, "balance"] = np.nan
    invalid.loc[1, "payment"] = -1.0
    with pytest.raises(pa.errors.SchemaErrors) as error:
        schema.validate(invalid, lazy=True)
    assert set(error.value.failure_cases["column"]) == {"balance", "payment"}
