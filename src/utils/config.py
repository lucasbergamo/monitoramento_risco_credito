"""Configuração básica, sem dependência do diretório corrente do chamador."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
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
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    mlflow_tracking_uri: str = "http://127.0.0.1:5000"
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL deve ser DEBUG, INFO, WARNING, ERROR ou CRITICAL")
        return value

    @field_validator("mlflow_tracking_uri")
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

    @model_validator(mode="after")
    def resolve_paths(self) -> "Settings":
        if not self.project_root.is_absolute():
            raise ValueError("PROJECT_ROOT deve ser absoluto")
        self.project_root = self.project_root.resolve()
        for name in ("data_dir", "models_dir", "artifacts_dir", "state_dir"):
            path = getattr(self, name)
            setattr(self, name, (self.project_root / path).resolve())
        return self
