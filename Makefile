.DEFAULT_GOAL := help
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
COMPOSE := docker compose

.PHONY: help setup lock check-lock build lint test docker-lint docker-test

help: ## Lista os comandos disponíveis.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Prepara .env e diretórios graváveis com o usuário do host.
	@test -f .env || cp .env.example .env
	mkdir -p docs/evidencias data/bronze data/silver data/gold data/scenarios models/staging models/current artifacts/runs state/mlflow
	@for dir in data models artifacts state; do test -w "$$dir" || { echo "Diretório sem permissão de escrita: $$dir"; exit 1; }; done

lock: ## Resolve dependências com Python/Poetry isolados em Docker.
	docker build --target tooling -t monitoramento-risco-credito:tooling .
	docker run --rm --user $(HOST_UID):$(HOST_GID) -e POETRY_VIRTUALENVS_CREATE=false -v "$(CURDIR):/workspace" monitoramento-risco-credito:tooling poetry lock

check-lock:
	@test -s poetry.lock || { echo "poetry.lock ausente. Execute make lock com acesso ao Docker e ao PyPI."; exit 1; }

build: check-lock ## Constrói as imagens de desenvolvimento e runtime a partir do lock.
	$(COMPOSE) build runner
	docker build --target runtime --build-arg HOST_UID=$(HOST_UID) --build-arg HOST_GID=$(HOST_GID) -t monitoramento-risco-credito:runtime .

lint: ## Executa lint e conferência de formatação no ambiente Poetry local.
	poetry run ruff check .
	poetry run ruff format --check .

test: ## Executa os testes no ambiente Poetry local.
	poetry run pytest -q --cov=src --cov-report=term-missing

docker-lint: ## Executa lint e formatação na imagem construída.
	$(COMPOSE) run --rm ci ruff check --no-cache .
	$(COMPOSE) run --rm ci ruff format --check --no-cache .

docker-test: ## Executa testes sem dados ou modelos do host.
	$(COMPOSE) run --rm ci python -m pytest -q -p no:cacheprovider --cov=src --cov-report=term-missing --cov-report=xml:/tmp/coverage.xml

.PHONY: data inspect-data docker-data docker-inspect-data

data: ## Adquire, audita e prepara as partições locais.
	poetry run python -m src.cli data

inspect-data: ## Verifica hashes locais e mostra somente agregados.
	poetry run python -m src.cli inspect-data

docker-data: ## Prepara dados em Docker, com ZIP local opcional em DATASET_ARCHIVE.
ifdef DATASET_ARCHIVE
	$(COMPOSE) run --rm --volume "$(abspath $(DATASET_ARCHIVE)):/input/dataset.zip:ro" --env DATASET_ARCHIVE=/input/dataset.zip runner python -m src.cli data
else
	$(COMPOSE) run --rm runner python -m src.cli data
endif

docker-inspect-data: ## Inspeciona a integridade dos dados locais em Docker.
	$(COMPOSE) run --rm runner python -m src.cli inspect-data
