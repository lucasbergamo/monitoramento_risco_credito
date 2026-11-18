"""Configuração básica, sem dependência do diretório corrente do chamador."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Argumentos explícitos prevalecem sobre ambiente, .env e defaults.

    Apenas os campos declarados são lidos do ambiente. Chaves extras no .env ou
    nos argumentos são erros. Defaults de negócio serão definidos com o pipeline.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", extra="forbid", hide_input_in_errors=True
    )

    project_root: Path = PROJECT_ROOT
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    artifacts_dir: Path = Path("artifacts")
    state_dir: Path = Path("state")
    dataset_archive: Path | None = None
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    mlflow_ui_uri: str = "http://127.0.0.1:5000"
    mlflow_tracking_uri: str = "http://127.0.0.1:5000"
    mlflow_runner_tracking_uri: str = "http://mlflow:5000"
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL deve ser DEBUG, INFO, WARNING, ERROR ou CRITICAL")
        return value

    @field_validator("mlflow_tracking_uri", "mlflow_runner_tracking_uri", "mlflow_ui_uri")
    @classmethod
    def valid_tracking_uri(cls, value: str) -> str:
        uri = urlsplit(value)
        if uri.username or uri.password or uri.query or uri.fragment:
            raise ValueError("MLFLOW_TRACKING_URI não aceita credenciais, query ou fragmento")
        if uri.scheme not in {"http", "https", "sqlite"}:
            raise ValueError("MLFLOW_TRACKING_URI exige HTTP(S) ou SQLite")
        if uri.scheme in {"http", "https"} and not uri.hostname:
            raise ValueError("MLFLOW_TRACKING_URI exige host")
        if uri.scheme == "sqlite" and (uri.netloc or not value.startswith("sqlite:///")):
            raise ValueError("SQLite exige URI sqlite:/// com caminho de banco")
        return value

    @field_validator("mlflow_ui_uri")
    @classmethod
    def ui_is_http(cls, value: str) -> str:
        if urlsplit(value).scheme not in {"http", "https"}:
            raise ValueError("MLFLOW_UI_URI exige HTTP(S)")
        return value

    @model_validator(mode="after")
    def resolve_paths(self) -> "Settings":
        if not self.project_root.is_absolute():
            raise ValueError("PROJECT_ROOT deve ser absoluto")
        self.project_root = self.project_root.resolve()
        for name in ("data_dir", "models_dir", "artifacts_dir", "state_dir"):
            path = getattr(self, name)
            setattr(self, name, (self.project_root / path).resolve())
        return self


class DataConfig(BaseModel):
    """Defaults versionados dos dados; ambiente não muda seeds ou schema."""

    model_config = {"extra": "forbid", "frozen": True, "strict": True}

    schema_version: Literal[1]
    source_url: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    xls_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_member: Literal["default of credit card clients.xls"]
    parser_version: Literal["uci-xls-v1"]
    split_seed: Literal[42]
    n_splits: Literal[20]
    reference_size: int = Field(gt=0)
    window_size: int = Field(gt=0)
    minimum_windows: int = Field(ge=4)
    minimum_rows: int = Field(ge=5000)
    timeout_seconds: int = Field(gt=0)
    max_archive_bytes: int = Field(gt=0)
    max_extracted_bytes: int = Field(gt=0)

    @field_validator("source_url")
    @classmethod
    def source_is_https(cls, value: str) -> str:
        if not value.startswith("https://archive.ics.uci.edu/"):
            raise ValueError("Fonte deve ser HTTPS da UCI")
        return value


def load_data_config(path: Path | None = None) -> DataConfig:
    """Lê YAML estrito, sem mesclar chaves de ambiente não declaradas."""
    import yaml

    path = path or PROJECT_ROOT / "configs" / "project.yaml"
    return DataConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
