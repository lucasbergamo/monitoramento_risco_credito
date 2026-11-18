.DEFAULT_GOAL := help
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
COMPOSE := docker compose

.PHONY: help setup lock check-lock build lint test docker-lint docker-test tracking-up tracking-down status report docker-report demo docker-demo verify-evidence docker-verify-evidence

help: ## Lista os comandos disponíveis.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Prepara .env e diretórios graváveis com o usuário do host.
	@test -f .env || cp .env.example .env
	mkdir -p docs/evidencias data/bronze data/silver data/gold data/scenarios models artifacts/runs state/mlflow
	@for dir in data models artifacts state; do test -w "$$dir" || { echo "Diretório sem permissão de escrita: $$dir"; exit 1; }; done

tracking-up: setup ## Sobe MLflow local com banco e artifact store persistentes.
	sh scripts/wait_tracking.sh $(COMPOSE)

tracking-down: ## Para MLflow sem remover banco ou artefatos.
	$(COMPOSE) stop mlflow

status: ## Confere prontidão e mostra o estado do MLflow.
	$(COMPOSE) ps
	@sh scripts/wait_tracking.sh --status $(COMPOSE)

report: ## Gera summary.json e index.html operacionais no host.
	@test -n "$(CAMPAIGN_ID)" || { echo "Informe CAMPAIGN_ID=<id retornado por demo>"; exit 2; }
	poetry run python -m src.cli report $(if $(CAMPAIGN_ID),--campaign-id "$(CAMPAIGN_ID)") $(if $(filter 1,$(JSON)),--json)

docker-report: ## Gera relatórios pelo runner, usando a URI interna mlflow:5000.
	@test -n "$(CAMPAIGN_ID)" || { echo "Informe CAMPAIGN_ID=<id retornado por demo>"; exit 2; }
	$(COMPOSE) run --rm --no-deps runner python -m src.cli report $(if $(CAMPAIGN_ID),--campaign-id "$(CAMPAIGN_ID)") $(if $(filter 1,$(JSON)),--json)

demo: ## Executa campanha completa e retorna CAMPAIGN_ID ao concluir.
	poetry run python -m src.cli demo $(if $(CAMPAIGN_ID),--campaign-id "$(CAMPAIGN_ID)") $(if $(filter 1,$(JSON)),--json)

docker-demo: ## Executa campanha completa no runner Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli demo $(if $(CAMPAIGN_ID),--campaign-id "$(CAMPAIGN_ID)") $(if $(filter 1,$(JSON)),--json)

verify-evidence: ## Verifica a campanha explicitamente informada por CAMPAIGN_ID.
	@test -n "$(CAMPAIGN_ID)" || { echo "Informe CAMPAIGN_ID=<id retornado por demo>"; exit 2; }
	poetry run python -m scripts.verify_evidence --campaign-id "$(CAMPAIGN_ID)" $(if $(filter 1,$(JSON)),--json)

docker-verify-evidence: ## Verifica evidência da campanha pelo runner Docker.
	@test -n "$(CAMPAIGN_ID)" || { echo "Informe CAMPAIGN_ID=<id retornado por demo>"; exit 2; }
	$(COMPOSE) run --rm --no-deps runner python -m scripts.verify_evidence --campaign-id "$(CAMPAIGN_ID)" $(if $(filter 1,$(JSON)),--json)

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
	$(COMPOSE) run --rm --no-deps ci ruff check --no-cache .
	$(COMPOSE) run --rm --no-deps ci ruff format --check --no-cache .

docker-test: ## Executa testes sem dados ou modelos do host.
	$(COMPOSE) run --rm --no-deps ci python -m pytest -q -p no:cacheprovider --cov=src --cov-report=term-missing --cov-report=xml:/tmp/coverage.xml

.PHONY: data inspect-data docker-data docker-inspect-data

data: ## Adquire, audita e prepara as partições locais.
	poetry run python -m src.cli data $(if $(filter 1,$(JSON)),--json)

inspect-data: ## Verifica hashes locais e mostra somente agregados.
	poetry run python -m src.cli inspect-data $(if $(filter 1,$(JSON)),--json)

docker-data: ## Prepara dados em Docker, com ZIP local opcional em DATASET_ARCHIVE.
ifdef DATASET_ARCHIVE
	$(COMPOSE) run --rm --no-deps --volume "$(abspath $(DATASET_ARCHIVE)):/input/dataset.zip:ro" --env DATASET_ARCHIVE=/input/dataset.zip runner python -m src.cli data $(if $(filter 1,$(JSON)),--json)
else
	$(COMPOSE) run --rm --no-deps runner python -m src.cli data $(if $(filter 1,$(JSON)),--json)
endif

docker-inspect-data: ## Inspeciona a integridade dos dados locais em Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli inspect-data $(if $(filter 1,$(JSON)),--json)

.PHONY: validate docker-validate
SCHEMA ?= features

validate: ## Valida BATCH explícito; features e labels exigem KEYS separado.
	poetry run python -m src.cli validate --batch "$(BATCH)" --schema "$(SCHEMA)" $(if $(KEYS),--keys "$(KEYS)") $(if $(filter 1,$(JSON)),--json)

docker-validate: ## Valida arquivo do host montado somente para leitura.
	$(COMPOSE) run --rm --no-deps --volume "$(abspath $(BATCH)):/input/batch$(suffix $(BATCH)):ro" $(if $(KEYS),--volume "$(abspath $(KEYS)):/input/keys$(suffix $(KEYS)):ro") runner python -m src.cli validate --batch "/input/batch$(suffix $(BATCH))" --schema "$(SCHEMA)" $(if $(KEYS),--keys "/input/keys$(suffix $(KEYS))") $(if $(filter 1,$(JSON)),--json)

.PHONY: train evaluate promote docker-train docker-evaluate docker-promote

train: ## Treina HGB/Dummy e congela validação e seleção em staging.
	poetry run python -m src.cli train $(if $(filter 1,$(JSON)),--json)

evaluate: ## Avalia teste com decisões congeladas e publica evidência agregada.
	poetry run python -m src.cli evaluate $(if $(filter 1,$(JSON)),--json)

promote: ## Promove staging atomicamente somente com gate de validação aprovado.
	poetry run python -m src.cli promote $(if $(filter 1,$(JSON)),--json)

docker-train: ## Treina e congela modelo em Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli train $(if $(filter 1,$(JSON)),--json)

docker-evaluate: ## Avalia teste e publica evidência agregada em Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli evaluate $(if $(filter 1,$(JSON)),--json)

docker-promote: ## Promove modelo aprovado em Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli promote $(if $(filter 1,$(JSON)),--json)

.PHONY: simulate evaluate-scenarios docker-simulate docker-evaluate-scenarios

simulate: ## Gera quatro cenários determinísticos com modelo current congelado.
	poetry run python -m src.cli simulate $(if $(filter 1,$(JSON)),--json)

evaluate-scenarios: ## Associa labels e mede efeito pareado com bootstrap.
	poetry run python -m src.cli evaluate-scenarios $(if $(filter 1,$(JSON)),--json)

docker-simulate: ## Gera cenários e manifestos em Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli simulate $(if $(filter 1,$(JSON)),--json)

docker-evaluate-scenarios: ## Avalia cenários e publica agregados em Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli evaluate-scenarios $(if $(filter 1,$(JSON)),--json)

.PHONY: detect docker-detect governance docker-governance retention docker-retention

detect: ## Compara referência, controles e cenários com Evidently real.
	poetry run python -m src.cli detect $(if $(filter 1,$(JSON)),--json)

docker-detect: ## Produz snapshots locais e diagnóstico estatístico em Docker.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli detect $(if $(filter 1,$(JSON)),--json)

governance: ## Mede desempenho agregado por grupos no teste congelado.
	poetry run python -m src.cli governance $(if $(filter 1,$(JSON)),--json)

docker-governance: ## Mede grupos com dados locais montados no runner.
	$(COMPOSE) run --rm --no-deps runner python -m src.cli governance $(if $(filter 1,$(JSON)),--json)

retention: ## Lista execuções operacionais vencidas; DELETE=1 permite exclusão explícita.
	poetry run python -m scripts.retention $(if $(filter 1,$(DELETE)),--delete)

docker-retention: ## Lista execuções vencidas no container; DELETE=1 permite exclusão explícita.
	$(COMPOSE) run --rm --no-deps runner python -m scripts.retention $(if $(filter 1,$(DELETE)),--delete)

.PHONY: check-publication
check-publication: ## Inspeciona working tree, index e blobs históricos publicáveis.
	python3 scripts/check_publication.py
	python3 scripts/check_publication.py --cached
	python3 scripts/check_publication.py --history

.PHONY: tracking-ready
tracking-ready:
	@sh scripts/wait_tracking.sh $(COMPOSE)

docker-test docker-data docker-inspect-data docker-validate docker-train docker-evaluate docker-promote docker-simulate docker-evaluate-scenarios docker-detect docker-demo docker-report docker-verify-evidence: tracking-ready
