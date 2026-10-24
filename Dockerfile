FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=42 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

FROM base AS tooling
ENV POETRY_VERSION=2.5.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_CONFIG_DIR=/tmp/poetry-config \
    POETRY_CACHE_DIR=/tmp/poetry-cache
RUN python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install --no-cache-dir "poetry==${POETRY_VERSION}"
ENV PATH="/opt/poetry/bin:${PATH}"
WORKDIR /workspace

FROM tooling AS dependencies
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
COPY pyproject.toml poetry.lock ./
RUN poetry check --lock && poetry sync --only main --no-root

FROM dependencies AS dev-dependencies
RUN poetry sync --with dev --no-root

FROM base AS runtime
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN groupadd --gid "${HOST_GID}" app \
    && useradd --uid "${HOST_UID}" --gid app --create-home app
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY src ./src
COPY configs ./configs
RUN mkdir -p data/bronze data/silver data/gold data/scenarios \
    models/staging models/current artifacts/runs state/mlflow \
    && chown -R app:app /app
USER app
CMD ["python", "-c", "from src.utils.config import Settings; from src.utils.logger import configure_logging, get_logger; s = Settings(); configure_logging(s.log_level); get_logger().info('foundation_ready', seed=s.seed)"]

FROM runtime AS dev
COPY --from=dev-dependencies /opt/venv /opt/venv
COPY pyproject.toml poetry.lock ./
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q"]
