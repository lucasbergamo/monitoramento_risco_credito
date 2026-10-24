# Monitoramento de Risco de Crédito

Camada de confiabilidade para um classificador de crédito, com contratos de dados,
detecção de drift, observabilidade de pipelines e documentação de governança.

Projeto acadêmico da Fase 4 de Machine Learning Engineering da FIAP.

## Estado

Fundação implementada e verificada em Docker com Python 3.12.15. O lockfile foi
gerado com Poetry 2.5.1. Os 31 testes passaram, incluindo integração real entre
Pandera, scikit-learn, Evidently e MLflow. Lint, build e smoke do runtime passaram.
A aquisição e preparação de dados estão implementadas, com partições por grupos,
referência de treino e janelas de produção simulada. O modelo de crédito e o
pipeline de monitoramento permanecem pendentes. A preparação foi validada em Docker
com dados reais; a suíte atual tem 56 testes aprovados e 97% de cobertura de `src`.

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

## Aquisição e preparação dos dados

Após `make setup` e `make build`, execute:

```bash
make docker-data
make docker-inspect-data
```

`docker-data` baixa o ZIP oficial da UCI na primeira execução, com timeout de 60
segundos por operação de rede e limite de 20 MB. Verifica os hashes congelados do
ZIP e do XLS e cria `data/bronze/`, `data/silver/` e `data/gold/`. Nas reexecuções,
reutiliza o cache bruto verificado. `docker-inspect-data` verifica os hashes de
todos os arquivos gerados e apresenta somente estatísticas agregadas.

Resultado esperado: 30.000 registros utilizáveis, duas classes em cada partição,
19 features financeiras, referência fixa extraída do treino e pelo menos quatro
janelas completas de 1.000 registros de produção. O manifesto local fica em
`data/gold/dataset_manifest.json`; a cópia agregada para revisão fica em
`docs/evidencias/dataset_manifest.json`. O comando pode sobrescrever essa cópia
com uma nova execução válida, preservando o hash congelado da origem. Revisar o
diff antes de versionar evidências.

Se o download estiver indisponível, obtenha o ZIP pelo botão Download da
[página UCI](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)
e informe seu caminho absoluto. O arquivo passa pelas mesmas verificações:

```bash
make docker-data DATASET_ARCHIVE=/caminho/absoluto/dataset.zip
```

O Make monta esse arquivo somente para leitura no container. Não use um XLS solto
ou um ZIP recompactado: ambos diferem do arquivo identificado. Hash inesperado
retorna erro e preserva o manifesto anterior. Não existe opção para ignorar o hash.
O evento `data_command_failed` informa a classe do erro sem expor valores pessoais.

No ambiente Poetry opcional, os comandos equivalentes são `make data` e
`make inspect-data`. Para usar ZIP local: `DATASET_ARCHIVE=/caminho/dataset.zip make data`.
A CLI oferece `python -m src.cli data --archive ... --data-dir ...` e
`python -m src.cli inspect-data --data-dir ...`. Argumentos explícitos prevalecem
sobre os caminhos do ambiente. A configuração dos dados vem de
`configs/project.yaml`, com chaves desconhecidas rejeitadas. `SEED` do ambiente
não altera a seed 42 do split nem as regras versionadas de dados.

Fonte: Yeh, I. (2009). Default of Credit Card Clients. UCI Machine Learning
Repository. [DOI 10.24432/C55S3H](https://doi.org/10.24432/C55S3H), licença
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). A transformação realiza
normalização de nomes/tipos e partições; os arquivos individuais ficam locais.
Valores monetários estão em NT$, em uma base histórica de Taiwan, com pagamentos
de abril a setembro de 2005. Essa população não representa automaticamente o
mercado brasileiro atual. A licença aberta não constitui garantia de anonimização.

Dados individuais, ZIP, XLS e parquet ficam ignorados pelo Git. O manifesto
versionado contém apenas agregados, schema e hashes. Não enviar tabelas individuais
ou IDs para repositório, logs ou tracking. Códigos especiais e duplicatas são
preservados e documentados em [dataset](docs/dataset.md). O algoritmo e suas
limitações estão na [ADR 0002](docs/adr/0002-dados-e-particoes.md).
