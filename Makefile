.DEFAULT_GOAL := help
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
COMPOSE := docker compose

.PHONY: help setup lock check-lock build lint test docker-lint docker-test tracking-up tracking-down status report docker-report

help: ## Lista os comandos disponíveis.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Prepara .env e diretórios graváveis com o usuário do host.
	@test -f .env || cp .env.example .env
	mkdir -p docs/evidencias data/bronze data/silver data/gold data/scenarios models artifacts/runs state/mlflow
	@for dir in data models artifacts state; do test -w "$$dir" || { echo "Diretório sem permissão de escrita: $$dir"; exit 1; }; done

tracking-up: setup ## Sobe MLflow local com banco e artifact store persistentes.
	$(COMPOSE) up -d --build mlflow

tracking-down: ## Para MLflow sem remover banco ou artefatos.
	$(COMPOSE) stop mlflow

status: ## Mostra estado do Compose e saúde de MLflow pela URI do host.
	$(COMPOSE) ps
	@for attempt in $$(seq 1 15); do curl --fail --silent --show-error "$${MLFLOW_TRACKING_URI:-http://127.0.0.1:5000}/health" && exit 0; sleep 5; done; exit 1

report: ## Gera summary.json e index.html operacionais no host.
	poetry run python -m src.cli report

docker-report: ## Gera relatórios pelo runner, usando a URI interna mlflow:5000.
	$(COMPOSE) run --rm runner python -m src.cli report

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

.PHONY: validate docker-validate
SCHEMA ?= features

validate: ## Valida BATCH explícito; features e labels exigem KEYS separado.
	poetry run python -m src.cli validate --batch "$(BATCH)" --schema "$(SCHEMA)" $(if $(KEYS),--keys "$(KEYS)")

docker-validate: ## Valida arquivo do host montado somente para leitura.
	$(COMPOSE) run --rm --volume "$(abspath $(BATCH)):/input/batch$(suffix $(BATCH)):ro" $(if $(KEYS),--volume "$(abspath $(KEYS)):/input/keys$(suffix $(KEYS)):ro") runner python -m src.cli validate --batch "/input/batch$(suffix $(BATCH))" --schema "$(SCHEMA)" $(if $(KEYS),--keys "/input/keys$(suffix $(KEYS))")

.PHONY: train evaluate promote docker-train docker-evaluate docker-promote

train: ## Treina HGB/Dummy e congela validação e seleção em staging.
	poetry run python -m src.cli train

evaluate: ## Avalia teste com decisões congeladas e publica evidência agregada.
	poetry run python -m src.cli evaluate

promote: ## Promove staging atomicamente somente com gate de validação aprovado.
	poetry run python -m src.cli promote

docker-train: ## Treina e congela modelo em Docker.
	$(COMPOSE) run --rm runner python -m src.cli train

docker-evaluate: ## Avalia teste e publica evidência agregada em Docker.
	$(COMPOSE) run --rm runner python -m src.cli evaluate

docker-promote: ## Promove modelo aprovado em Docker.
	$(COMPOSE) run --rm runner python -m src.cli promote

.PHONY: simulate evaluate-scenarios docker-simulate docker-evaluate-scenarios

simulate: ## Gera quatro cenários determinísticos com modelo current congelado.
	poetry run python -m src.cli simulate

evaluate-scenarios: ## Associa labels e mede efeito pareado com bootstrap.
	poetry run python -m src.cli evaluate-scenarios

docker-simulate: ## Gera cenários e manifestos em Docker.
	$(COMPOSE) run --rm runner python -m src.cli simulate

docker-evaluate-scenarios: ## Avalia cenários e publica agregados em Docker.
	$(COMPOSE) run --rm runner python -m src.cli evaluate-scenarios

.PHONY: detect docker-detect

detect: ## Compara referência, controles e cenários com Evidently real.
	poetry run python -m src.cli detect

docker-detect: ## Produz snapshots locais e diagnóstico estatístico em Docker.
	$(COMPOSE) run --rm runner python -m src.cli detect
