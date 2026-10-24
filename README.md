# Monitoramento de Risco de Crédito

Camada de confiabilidade para um classificador de crédito, com contratos de dados,
detecção de drift, observabilidade de pipelines e documentação de governança.

Projeto acadêmico da Fase 4 de Machine Learning Engineering da FIAP.

## Estado

Fundação implementada e verificada em Docker com Python 3.12.15. O lockfile foi
gerado com Poetry 2.5.1. Os 31 testes passaram, incluindo integração real entre
Pandera, scikit-learn, Evidently e MLflow. Lint, build e smoke do runtime passaram.
A aquisição e preparação de dados estão implementadas, com partições por grupos,
referência de treino e janelas de produção simulada. O classificador de crédito,
sua avaliação e a promoção local estão implementados.
Os quatro cenários reproduzíveis e a avaliação pareada estão implementados.
A detecção estatística por feature, os relatórios Evidently e os alertas de drift
também estão implementados.
O pipeline integrado de monitoramento permanece pendente. A preparação foi validada
em Docker com dados reais. A suíte usa fixtures próprias, incluindo treino durante os testes e
falhas de promoção, sem depender de modelos ou dados preparados no host.

Contratos de origem, features e labels e a CLI de validação estão implementados.
Lotes rejeitados bloqueiam o consumidor e produzem somente diagnóstico agregado.

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

## Contratos e rejeição de lotes

Após `make build`, valide a janela preparada, sem alvo nas features:

```bash
make docker-validate BATCH=data/gold/windows/000/features.parquet KEYS=data/gold/windows/000/keys.parquet
make docker-validate SCHEMA=labels BATCH=data/gold/windows/000/labels.parquet KEYS=data/gold/windows/000/keys.parquet
```

O caminho de `BATCH` é explícito. Features e labels exigem `KEYS` separado. O Make
monta cada arquivo do host somente para leitura, inclusive caminhos externos ao
repositório. `SCHEMA=source` recebe a origem normalizada antes de `group_id`, sem
arquivo de chaves adicional. Formatos aceitos: `.csv` e `.parquet`.
No ambiente Poetry, usar os mesmos argumentos com `make validate`.

A demonstração abaixo usa exclusivamente os exemplos sintéticos versionados e não
depende da aquisição da UCI:

```bash
make docker-validate BATCH=docs/examples/valid.csv KEYS=docs/examples/keys.csv
make docker-validate BATCH=docs/examples/invalid.csv KEYS=docs/examples/duplicate_keys.csv
```

O primeiro comando retorna sucesso e evento JSON `contract_accepted`, com três
linhas aceitas. O segundo falha, com evento `contract_rejected`, três linhas
rejeitadas e todas as violações: `not_null` em `limit_bal`, `unique_id` nas chaves
e `nonnegative_payment` em `pay_amt6`. A contagem de duplicidade inclui as duas
ocorrências do ID. Nenhuma linha é corrigida ou descartada. Não são gerados scores.

O processo Python retorna **0** para válido, **2** para rejeitado e **1** para erro
operacional. O próprio GNU Make retorna 2 quando qualquer receita falha, inclusive
erro operacional. Para verificar especificamente o código da CLI em Docker:

```bash
docker compose run --rm --volume "$PWD/docs/examples:/input:ro" runner python -m src.cli validate --batch /input/invalid.csv --keys /input/duplicate_keys.csv
code=$?
test "$code" -eq 2

docker compose run --rm runner python -m src.cli validate --batch /app/data/arquivo-ausente.csv --keys /app/data/chaves-ausentes.csv
code=$?
test "$code" -eq 1
```

Execute essas verificações em um shell sem `set -e`; o código é capturado logo após
o comando esperado falhar. No ambiente Poetry: `poetry run python -m src.cli validate
--batch ... --keys ...` mantém os mesmos códigos.

Os contratos exigem tipos, ausência de nulos, finitude, colunas conhecidas e IDs
únicos. Limite deve ser positivo, pagamentos não negativos, PAY pertence ao domínio
versionado e labels são binários com associação 1:1. Faturas negativas e montantes
raros passam, sem teto estatístico arbitrário. Inferência não exige labels e rejeita
target como coluna extra. Diagnósticos contêm somente regras e contagens; não incluem
valores, índices, nomes inesperados ou linhas do lote. Detalhes e limites na
[ADR 0003](docs/adr/0003-contratos-e-bloqueio.md).

## Treino, avaliação e promoção do modelo

Após preparar os dados com `make docker-data` e construir a imagem atual:

```bash
make docker-train
make docker-evaluate
make docker-promote
```

`docker-train` verifica o manifesto e hashes de treino/validação, ajusta HGB e Dummy
somente no treino e congela a validação em `models/staging/manifest.json` junto do
artefato local. O gate exige AUC >=0,65 e Brier menor que o Dummy na validação.
Reprovação retorna código 2 na CLI e preserva staging para diagnóstico; current
permanece intacto. Não reduzir o piso nem alterar parâmetros para contornar falhas.

Resultado medido em 24/10/2026: gate aprovado, AUC 0,7789 e Brier 0,1347, contra
Brier 0,1723 do Dummy. A permutação na validação (cinco repetições, ROC-AUC, seed 42)
selecionou `pay_0` e `limit_bal` com médias positivas. Teste e produção não participam
da escolha. Parâmetros e regras ficam em `configs/model.yaml`, sem sobrescrita
implícita por `SEED` do ambiente.

`docker-evaluate` carrega o staging congelado e somente então avalia o teste. Salva
`models/evaluations/<version>.json` e a cópia agregada
[baseline.json](docs/evidencias/baseline.json), com métricas separadas por partição,
modelo e Dummy. Resultado no teste: AUC 0,7660, Brier 0,1381 e recall 0,3658 no
limiar 0,5. O limiar é demonstrativo, sem política econômica real.

`docker-promote` recalcula o gate de validação, verifica integridade, copia o bundle
completo e troca o symlink `models/current` atomicamente. Não consulta métricas de
teste. Reexecutar os três comandos no ambiente fixado preservou hashes e resultados.
A versão é hash do manifesto canônico incluindo hash do artefato e configuração;
`staging` e `current` são ponteiros relativos para versões completas locais.
`make setup` pode ser repetido depois da promoção sem modificar esses ponteiros.

No ambiente Poetry opcional, os equivalentes são `make train`, `make evaluate` e
`make promote`. A CLI aceita `--data-dir` e `--models-dir` nesses comandos;
argumentos explícitos prevalecem sobre caminhos do ambiente. Treino, avaliação,
promoção e inferência limitam threads pelo código, inclusive fora do Docker.

A função `predict_batch(features, keys, model_dir)` em `src/models/predict.py`
valida antes de predizer, exige as 19 features na ordem do manifesto e devolve
scores por ID sem gravá-los. Labels e demografia são rejeitados como colunas extras.
Carregamento verifica hashes, política, ordem de features e classes. Não carregar
joblib recebido de terceiros; hashes detectam corrupção, sem autenticar sua origem.

Os testes geram seus próprios dados/modelos em diretórios temporários. Um piso AUC
1,1 passado somente à fixture impede a promoção e comprova que a versão atual não
muda. Também são exercitadas falhas na cópia e na troca atômica, corrupção, ordem
de features e associação de labels por ID. A política padrão continua em 0,65.
Bundles locais antigos não são apagados automaticamente.

Resultados, hashes e limitações no [model card](docs/model_card.md).
Detalhes de integridade e atomicidade na [ADR 0004](docs/adr/0004-modelo-e-avaliacao.md).

## Demonstração dos cenários e avaliação pareada

Após preparar os dados, treinar, avaliar e promover o modelo, execute:

```bash
make docker-simulate
make docker-evaluate-scenarios
```

`docker-simulate` usa o modelo congelado em `models/current` e as seis janelas
reservadas de 1.000 registros. Gera `stable`, `data_drift` e `concept_drift` em
cada janela e `invalid` somente na primeira. Dados, modelo, treino e referência
originais são preservados. A versão local fica em
`data/scenarios/versions/<hash>/`, apontada por `data/scenarios/current`.
Uma falha de geração preserva o ponteiro anterior; versões antigas não são apagadas.

Cada janela tem features e chaves separadas, manifesto, scores quando válidos e
labels quando disponíveis. O manifesto inclui seeds, hashes, transformações,
intensidades, versão do modelo e origem dos rótulos. U fica em `latent.parquet`
local. Dados individuais não são publicados. Reexecutar os comandos com as mesmas
entradas/configuração preserva a geração e os agregados byte a byte.

Resultados esperados e medidos em 24/10/2026:

- `invalid`: rejeição por nulo, ID duplicado e pagamento negativo; nenhum score.
  A rejeição esperada faz parte da geração e não interrompe os demais cenários.
- `data_drift`: contrato aceito e predições disponíveis; só `pay_0` e `limit_bal`
  transformadas. Performance `null`, status `labels_unavailable`, pois os labels
  originais não são reutilizados após alterar X.
- `concept_drift`: features e scores idênticos ao controle por janela. Labels
  sintéticos separados, choque de 0 a 0,35. Em r=0, o controle é reproduzido.

`docker-evaluate-scenarios` confere hashes, associa labels por ID e salva
`data/scenarios/evaluation.json` e a evidência agregada
[scenarios.json](docs/evidencias/scenarios.json). AUC, AP, Brier, recall e demais
métricas ficam separadas por janela/cenário. Ausência de labels é explícita.
Na última janela, o Brier aumentou 0,177789, IC95% pareado
[0,157599; 0,199006], com 1.000 reamostragens e seed 42. O critério >0,02 com limite
inferior >0 foi atendido. O default adicional foi 0,272, contra 0,27055 esperado.

A CLI devolve 0 para geração/avaliação aceita, 2 para critério de degradação
reprovado e 1 para erro operacional. GNU Make devolve 2 para receita com falha;
consulte o JSON para distinguir reprovação de erro operacional. Um critério
reprovado permanece registrado, sem alterar seeds ou limiares automaticamente.

Os equivalentes Poetry são `make simulate` e `make evaluate-scenarios`.
A CLI aceita `--data-dir` e `--models-dir` nos dois comandos. Seed ambiental não
altera as seeds da simulação; a política está em `configs/scenarios.yaml`.

O efeito medido pertence exclusivamente ao mecanismo do simulador, sem inferência
causal econômica real ou garantia de anonimato. Hipóteses, diagrama, estimandos,
incerteza e resultados em [causalidade](docs/causalidade.md).


## Detecção estatística e relatórios

Após preparar os dados e gerar os cenários com o modelo promovido, execute:

```bash
make build
make docker-detect
```

O comando compara as 19 features financeiras com Evidently 0.7.23 real. PAY usa
PSI >=0,25; montantes usam KS bilateral com p <0,01 no relatório. O alerta
operacional numérico exige p ajustado por Holm <0,01 e D >=0,10, na família das
13 numéricas da janela. PSI não é p-valor. IDs, labels, demografia, scores e
metadados do simulador ficam fora da comparação. A configuração estrita está em
`configs/monitoring.yaml` e não muda com a seed do ambiente.

São executados controle idêntico, quatro janelas completas da validação (restante
registrado), referência versus stable/data_drift por janela e stable versus
concept pareados. A CLI informa `run_id`, `comparison_count` e `gate_passed`.
O gate exige ausência de feature_drift nos controles idênticos/pareados e detecção
das duas features alteradas na última janela. Alertas em validação são contados
como falsos alertas do controle, sem ajustar limiares automaticamente.

Cada execução cria `artifacts/runs/<run_id>/summary.json` e `alerts.json`.
Subdiretórios `<comparação>/<janela>/` contêm `evidently.html`, `evidently.json`
e `normalized.json`. Abra, por exemplo,
`artifacts/runs/<run_id>/data_drift/005/evidently.html` no navegador para as seis
janelas da base atual. O JSON nativo usa `config` para identificar cada métrica;
o normalizado distingue `report_drift` de `operational_alert`, com método, score,
amostras, limite, D e p bruto/ajustado quando aplicável.

Snapshots ficam locais e ignorados. Não enviá-los ao Git automaticamente:
histogramas podem revelar valores reais. Apenas a evidência agregada revisada em
[detecção](docs/evidencias/deteccao.json) e as tabelas em
[métricas](docs/metricas.md) são selecionadas para publicação.

A CLI retorna 0 em execução válida, inclusive com feature_drift; 2 se o gate da
demonstração falhar; 1 para erro operacional ou amostra insuficiente (<20).
GNU Make retorna 2 para qualquer receita com falha. Nenhum alerta envia mensagens
externas ou promove modelo. Sem labels, não há conclusão supervisionada sobre
concept drift. O equivalente Poetry é `make detect`; a CLI aceita `--data-dir`
e `--models-dir`, além de `ARTIFACTS_DIR` pelas Settings.
