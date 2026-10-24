# Monitoramento de Risco de Crédito

Camada de confiabilidade para um classificador de crédito, com contratos de dados,
detecção de drift, observabilidade de pipelines e documentação de governança.

Projeto acadêmico da Fase 4 de Machine Learning Engineering da FIAP.

## Estado

Fundação implementada e verificada em Docker com Python 3.12.15. O lockfile foi
gerado com Poetry 2.5.1. Os 31 testes passaram, incluindo integração real entre
Pandera, scikit-learn, Evidently e MLflow. Lint, build e smoke do runtime passaram.
Não há dataset adquirido, modelo de crédito treinado ou pipeline de negócio.

## Objetivos

- Validar entradas e bloquear lotes que violem contratos de qualidade.
- Comparar dados de referência com cenários simulados de produção.
- Identificar mudanças estatísticas e acompanhar a qualidade do modelo.
- Consolidar logs, métricas e alertas operacionais.
- Documentar privacidade, retenção e limitações do uso dos dados.

O projeto tem finalidade educacional e não é um serviço de decisão de crédito.

## Requisitos de ambiente

Linux ou WSL2, Git, GNU Make, Docker Engine/Desktop com daemon acessível e Docker
Compose v2 ou posterior. O percurso Docker não exige Python nem Poetry no host.
É necessário acesso ao Docker Hub e ao PyPI no primeiro build e na geração do lock.

Confira o acesso antes de executar:

```bash
docker info
docker compose version
```

Se `docker info` falhar por permissão, confira a integração da distribuição WSL com
Docker Desktop e as permissões do usuário local para acessar o socket.
Não use `chmod 777` no socket ou nos volumes.

## Preparação e execução em Docker

Execute na raiz deste repositório:

```bash
make help
make setup
```

`setup` copia `.env.example` somente se `.env` estiver ausente e cria diretórios
locais de dados, modelos, artefatos e estado como o usuário do host, sem sudo.
Não substitui configurações ou arquivos existentes.

Com os diretórios preparados, execute:

```bash
make build
make docker-lint
make docker-test
docker run --rm monitoramento-risco-credito:runtime
```

Resultados esperados e verificados em 24/10/2026:

- `build`: imagens `monitoramento-risco-credito:dev` e `:runtime`, sem dados do host.
- `docker-lint`: Ruff sem erros de lint ou formatação.
- `docker-test`: todos os testes aprovados, incluindo HTML/JSON Evidently e gravação/
  recuperação de run e artefatos em SQLite pelo MLflow real, usando dados sintéticos.
- `runtime`: uma linha JSON com evento `foundation_ready` e seed 42.

Os testes usam diretórios temporários, sem dataset, treino anterior ou servidor de
tracking ativo. HTML/JSON, banco e artefatos de teste são descartáveis. Nenhum serviço
é iniciado em segundo plano e nenhuma porta é publicada nesta fundação.

`make lock` é um comando de manutenção: resolve dependências em container com
Python 3.12 e Poetry 2.5.1. Use somente ao atualizar deliberadamente dependências;
revise o lock gerado antes de versioná-lo. Build e CI não o regeneram.

## Desenvolvimento local opcional

Com Python 3.12 e Poetry 2.5.1 já disponíveis:

```bash
poetry check --lock
poetry sync --with dev
make lint
make test
```

O teste de ambiente confere a versão do Python e os pins das bibliotecas. Executá-lo
com outro ambiente não substitui a prova de compatibilidade do projeto.

## Configuração e estado local

Settings deriva os caminhos da raiz do projeto, independentemente do diretório
corrente. Argumentos explícitos prevalecem sobre ambiente, `.env` e defaults.
Chaves desconhecidas no `.env` são rejeitadas. A URI de tracking não aceita senha
embutida. `SEED` e `LOG_LEVEL` inválidos geram erro de validação.

O Make passa o UID/GID do host ao build e ao Compose. `data/`, `models/`, `artifacts/`
e `state/` ficam locais e ignorados pelo Git. `.env` também não é versionado.
Logs JSON aceitam campos operacionais definidos no código e descartam payloads,
credenciais e exceções completas. Mensagens de evento devem ser estáticas.

Detalhes e limites da validação em [ambiente](docs/ambiente.md).
Decisão de execução em [ADR 0001](docs/adr/0001-execucao-local.md).
