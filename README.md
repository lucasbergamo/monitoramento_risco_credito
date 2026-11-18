# Monitoramento de Risco de Crédito

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Pandera](https://img.shields.io/badge/Pandera-0.34.1-4B8BBE?style=flat-square)
![Evidently](https://img.shields.io/badge/Evidently-0.7.23-6C47FF?style=flat-square)
![MLflow](https://img.shields.io/badge/MLflow-3.16.1-0194E2?style=flat-square&logo=mlflow&logoColor=white)
![Ruff](https://img.shields.io/badge/linting-ruff-FCC21B?style=flat-square)

Camada de confiabilidade para um classificador de crédito, com contratos de dados,
detecção de drift, observabilidade de pipelines e governança.

Tech Challenge 04 da pós-graduação em Machine Learning Engineering da FIAP.

## Sumário

- [Contexto](#contexto)
- [Stack Tecnológica](#stack-tecnológica)
- [Dataset](#dataset)
- [Resultados](#resultados)
- [Critérios de Avaliação](#critérios-de-avaliação)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Arquitetura](#arquitetura)
- [Configuração e Execução](#configuração-e-execução)
- [Governança, privacidade e limites do score](#governança-privacidade-e-limites-do-score)
- [Referência e demonstrações complementares](#referência-e-demonstrações-complementares)
- [Documentação](#documentação)
- [Desenvolvimento local opcional](#desenvolvimento-local-opcional)

## Contexto

O projeto avalia a confiabilidade de um classificador de crédito em processamento
batch. Contratos bloqueiam lotes inválidos antes da inferência; cenários simulados
permitem observar mudanças de dados e de desempenho. Logs, métricas e alertas
apoiam a investigação, com documentação de privacidade, retenção e limitações.

A finalidade é educacional. O sistema não concede crédito nem toma decisões sobre
pessoas. Vídeo e validação manual em outro computador permanecem pendentes; não há
submissão declarada.

## Stack Tecnológica

| Tecnologia | Função |
|---|---|
| Pandera | Contratos de qualidade e rejeição de dados inválidos |
| Scikit-learn | Baseline HistGradientBoosting e modelo Dummy |
| Evidently | Comparação estatística e relatórios de drift |
| MLflow | Tracking de métricas, artefatos e execução |
| Docker Compose | Ambiente local de execução e serviço de tracking |
| Pytest e Ruff | Testes automatizados e verificação de código |

## Dataset

O [Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default%2Bof%2Bcredit%2Bcard%2Bclients),
de Yeh (2009), é uma base histórica de Taiwan com 30.000 registros utilizáveis.
O preditor usa 19 variáveis financeiras; atributos demográficos ficam separados
para auditoria. A origem é conferida por hash e os dados individuais permanecem
locais. A fonte é distribuída sob [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/);
a preparação normaliza nomes e tipos e cria partições. Consulte [dataset](docs/dataset.md)
para origem, transformações e limites de representatividade.

## Resultados

| Avaliação | Resultado medido | Interpretação |
|---|---|---|
| Validação do baseline | AUC 0,7789; Brier 0,1347, contra 0,1723 do Dummy | Gate aprovado; seleção anterior ao teste |
| Teste retido | AUC 0,7660; Brier 0,1381; recall 0,3658 com limiar 0,5 | Avaliação após congelamento, sem uso na promoção |
| Cenário sintético de concept drift | Aumento de Brier 0,177789; IC95% pareado [0,157599; 0,199006] | Efeito do simulador, não de uma intervenção econômica real |
| Campanha integrada | 19 lotes, 23 comparações e rejeição do lote inválido sem scores | Evidências e proveniência em [evidências](docs/evidencias/README.md) |

Os resultados do modelo e dos cenários têm populações e propósitos distintos.
Detalhes e limitações estão no [model card](docs/model_card.md) e em
[causalidade](docs/causalidade.md).

## Critérios de Avaliação

| Critério | Peso | Comando e evidência |
|---|---:|---|
| Validação de dados | 25% | `make docker-demo`; [contratos](docs/adr/0003-contratos-e-bloqueio.md) e rejeição sem scores em [campanha](docs/evidencias/campaign.json) |
| Detecção de drift | 25% | `make docker-demo`; [cenários](docs/evidencias/scenarios.json), [detecção](docs/evidencias/deteccao.json) e [causalidade](docs/causalidade.md) |
| Observabilidade e logs | 20% | `make docker-report CAMPAIGN_ID=...`; [campanha](docs/evidencias/campaign.json), MLflow e [operação](docs/operacao.md) |
| Governança | 15% | `make docker-governance`; [diagnóstico agregado](docs/evidencias/governanca.json) e [governança](docs/governanca.md) |
| Vídeo STAR | 15% | Pendente de gravação; duração até cinco minutos e acesso externo a verificar |

As evidências não substituem o vídeo nem a execução manual independente.

## Estrutura do Projeto

```text
monitoramento_risco_credito/
├── configs/              # políticas de dados, modelo, cenários e monitoramento
├── docs/                 # documentação, decisões e evidências agregadas
├── scripts/              # verificação e manutenção operacional
├── src/                  # implementação do pipeline
├── tests/                # testes automatizados
├── Dockerfile            # imagens de desenvolvimento e runtime
├── docker-compose.yml    # runner, CI e MLflow
├── Makefile              # interface de comandos
├── pyproject.toml        # dependências e ferramentas
└── poetry.lock           # versões resolvidas
```

Dados, modelos, artefatos operacionais e estado do MLflow são gerados localmente
em `data/`, `models/`, `artifacts/` e `state/`, ignorados pelo Git.

## Arquitetura

```mermaid
flowchart LR
    U[UCI: origem verificada] --> D[Partições por grupos]
    D --> T[Treino e validação]
    T --> M[Modelo congelado]
    D --> P[Produção reservada]
    P --> C[Quatro cenários]
    M --> V[Contrato antes da inferência]
    C --> V
    V --> E[Evidently e avaliação com labels separados]
    E --> L[MLflow: logs, recursos e alertas]
    L --> R[Relatório por campanha e verificação de hashes]
```

## Configuração e Execução

Siga esta trilha na ordem, executando um comando por vez e conferindo o resultado
antes de continuar. Se houver falha, registre a saída e investigue a causa.
A campanha integrada executa os quatro cenários; os comandos isolados e exemplos
negativos ficam na [referência complementar](#referência-e-demonstrações-complementares).

Os comandos abaixo baixam o repositório e entram na pasta do projeto. Enquanto o
repositório estiver privado, o acesso exige autenticação no GitHub:

```bash
git clone https://github.com/lucasbergamo/monitoramento_risco_credito.git
cd monitoramento_risco_credito
```

### 1. Conferir o ambiente

Linux ou WSL2, Git, GNU Make, Docker Engine/Desktop com daemon acessível e Docker
Compose v2 ou posterior, filesystem POSIX gravável e porta local 5000 disponível.
O percurso Docker não exige Python nem Poetry no host.
É necessário acesso ao Docker Hub e ao PyPI no primeiro build e na geração do lock.

`docker info` verifica se o cliente consegue acessar o daemon; `docker compose
version` mostra a versão instalada do Compose. O primeiro deve apresentar os dados
do servidor sem erro, e o segundo deve indicar Compose v2 ou posterior:

```bash
docker info
docker compose version
```

Se `docker info` falhar por permissão, confira a integração da distribuição WSL com
Docker Desktop e as permissões do usuário local para acessar o socket.
Não use `chmod 777` no socket ou nos volumes.

### 2. Preparar e verificar o ambiente Docker

Execute na raiz deste repositório:

```bash
make help
make setup
```

`make help` lista os comandos disponíveis, sem executar o pipeline.
`make setup` copia `.env.example` somente se `.env` estiver ausente e cria diretórios
locais de dados, modelos, artefatos e estado como o usuário do host, sem sudo.
Não substitui configurações ou arquivos existentes.

Com os diretórios preparados, construa as imagens, inicie o tracking, confira a
saúde do serviço e execute as verificações de qualidade, nesta ordem:

```bash
make build
make tracking-up
# Aguarde o MLflow ficar pronto; repita make status até retornar OK.
make status
make docker-lint
make docker-test
docker run --rm monitoramento-risco-credito:runtime
```

Resultados esperados:

- `make build`: constrói as imagens `monitoramento-risco-credito:dev` e `:runtime`, sem dados do host.
- `make tracking-up`: inicia o servidor MLflow, mas pode retornar antes de ele estar pronto.
- `make status`: confere o serviço e deve responder `OK`. Durante a primeira
  inicialização podem ocorrer mensagens transitórias de conexão. Aguarde e repita
  a consulta; prossiga somente após `OK`. Se o erro persistir, examine
  `docker compose logs --tail=80 mlflow`, que mostra as últimas mensagens do serviço,
  antes de repetir as etapas dependentes.
- `make docker-lint`: verifica o código e a formatação; resultado esperado sem erros.
- `make docker-test`: executa os testes com fixtures e cobertura; nesta versão,
  são 155 testes, incluindo HTML/JSON Evidently e tracking real. Deve terminar sem
  falhas. O tempo varia com o hardware, e os pontos indicam testes concluídos.
- `docker run --rm monitoramento-risco-credito:runtime`: executa o smoke da imagem
  de produção e remove esse container ao terminar. Deve emitir o evento
  `foundation_ready` com seed 42.

Os testes usam dados e modelos temporários, sem dataset ou treino anterior. O serviço
MLflow é necessário para a execução pelo Compose; a porta 5000 fica restrita ao host.

`make lock` é um comando de manutenção: resolve dependências em container com
Python 3.12 e Poetry 2.5.1. Use somente ao atualizar deliberadamente dependências;
revise o lock gerado antes de versioná-lo. Build e CI não o regeneram.

### 3. Adquirir e conferir os dados

Após concluir a preparação e confirmar `OK` no tracking, execute a aquisição e,
em seguida, a inspeção dos dados:

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
19 features financeiras, partições de 15.000/4.500/4.500/6.000 para
treino/validação/teste/produção, referência de 5.000 extraída do treino e seis
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

### 4. Treinar, avaliar e promover o modelo

Com os dados conferidos, execute o treino, a avaliação no teste separado e a
promoção do modelo aprovado, nesta ordem:

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

### 5. Executar a campanha e verificar as evidências

Depois de `make docker-data`, `make docker-train`, `make docker-evaluate` e
`make docker-promote`, com o tracking pronto conforme a etapa de preparação,
execute uma campanha completa:

```bash
make docker-demo
```

`docker-demo` valida os dados antes da inferência, gera os cenários, associa labels
somente depois dos scores, executa o detector e grava um manifesto em
`artifacts/campaigns/<campaign_id>/manifest.json`. A saída JSON retorna o
`campaign_id`, os IDs das runs e quatro cenários. O cenário `invalid` precisa ser
rejeitado sem produzir scores; essa rejeição esperada não interrompe os demais.
Qualquer falha de dados, modelo, detector ou tracking termina com erro operacional
e deixa a campanha como `failed` ou incompleta, sem reutilizar uma campanha anterior.

Copie o `campaign_id` retornado e substitua `<campaign_id>` nos comandos abaixo.
Não procure arquivos pela data de modificação:

```bash
# Gera o sumário JSON e o relatório HTML dessa campanha.
make docker-report CAMPAIGN_ID=<campaign_id>
# Confere hashes, resultados e vínculos das runs no MLflow.
make docker-verify-evidence CAMPAIGN_ID=<campaign_id>
```

O relatório fica em `artifacts/campaigns/<campaign_id>/index.html` e o sumário em
`summary.json`. O comando de relatório deve indicar três runs e tracking
`available`; o de verificação deve retornar `status: verified`.
A verificação confirma os hashes locais, resultados dos quatro
cenários e runs MLflow finalizadas com a mesma tag `campaign_id`. Uma nova execução
cria outro diretório e preserva as campanhas anteriores. Os resultados determinísticos
são comparáveis pelo hash de resultado; IDs e medições operacionais mudam por execução.
As limitações e medições reais estão em [reprodutibilidade](docs/reproducibilidade.md).

Para recuperar uma falha operacional, confira `make status`, corrija a origem
indicada no log agregado e execute `make docker-demo` novamente. A campanha anterior
permanece para diagnóstico. `make tracking-down` interrompe o serviço sem remover
banco ou artefatos; não use comandos de remoção de volumes para encerrar a demonstração.

### 6. Gerar as evidências de governança

Com os dados preparados e o modelo promovido, gere o diagnóstico por grupo:

```bash
make docker-governance
```

Resultado esperado: evidência em `docs/evidencias/governanca.json`, partição `test`,
4.500 registros e a mesma versão do modelo promovido. Os valores são agregados;
AGE e SEX são usados para auditoria, sem entrar nas features do preditor.

### 7. Inspecionar as telas e encerrar

Abra `artifacts/campaigns/<campaign_id>/index.html` e a UI
[MLflow local](http://127.0.0.1:5000). Confira as três runs da campanha, métricas,
alertas e artefatos. Para inspecionar o HTML nativo do detector, use o `drift_run_id`
do manifesto da campanha em
`artifacts/runs/<drift_run_id>/data_drift/005/evidently.html`.

Os resultados esperados são 19 lotes de cenários, rejeição do inválido sem scores,
23 comparações e gates aprovados; a verificação deve retornar `verified`.
Os HTMLs nativos permanecem locais. Apenas agregados revisados são versionados.

Para conferir conteúdo publicável, em checkout com Git e Python 3 disponíveis:

```bash
make check-publication
```

Essa checagem de publicação inspeciona arquivos atuais, index e histórico e deve
retornar `passed`, sem ocorrências. Ela usa Python 3 no host, além do percurso Docker,
e não é necessária para executar os modelos; é uma verificação do conteúdo antes
de publicá-lo. Ela complementa a inspeção visual de imagens e HTML; não a substitui.

Após conferir as telas, encerre o tracking sem remover banco ou artefatos:

```bash
make tracking-down
```

O comando para o container MLflow e mantém banco, dados e artefatos para consulta
posterior. `make tracking-up` pode iniciar novamente o mesmo serviço. Ao final,
a trilha terá preparado dados, avaliado e promovido o modelo, executado a campanha,
verificado suas evidências e gerado o diagnóstico de governança.

## Governança, privacidade e limites do score

O projeto reproduz, para fins acadêmicos, um classificador sobre o conjunto UCI
Default of Credit Card Clients, publicado por Yeh em 2009. A licença indicada pela
UCI é CC BY 4.0: a redistribuição exige atribuição, link para a licença e indicação
de alterações. Essa licença trata dos direitos concedidos sobre o material; por si
só não comprova consentimento dos titulares, anonimização ou autorização irrestrita
para qualquer tratamento. A base é histórica, de Taiwan, com valores em NT$.

O estudo não concede crédito nem produz decisões sobre pessoas. A hipótese de uma
fintech que avalia proteção do crédito é separada deste uso acadêmico. Em uma
operação real, o art. 7º, X, da LGPD prevê a hipótese de proteção do crédito; sua
aplicação depende do contexto e dos requisitos legais. O art. 20 disciplina a
solicitação de revisão de decisões tomadas unicamente com base em tratamento
automatizado que afetem os interesses do titular. O art. 7º, IV, refere-se a
estudos por órgão de pesquisa. Este projeto não declara que sua equipe se enquadra
nessa definição, que existe consentimento ou que qualquer hipótese legal foi
validada para a atividade. Não se declara conformidade jurídica certificada.

A preparação local mantém origem, `record_id`, rótulo e tabela de auditoria com SEX,
AGE, EDUCATION e MARRIAGE. O preditor recebe somente 19 variáveis financeiras;
demografia não é concatenada às features. A tabela de auditoria é associada por ID
somente depois de carregar as features, labels e previsões do teste. O ID e os
arquivos individuais ficam em `data/`, ignorados pelo Git. O diagnóstico por grupo
publica apenas contagens, denominadores, métricas agregadas e hashes em
`docs/evidencias/governanca.json`. Métricas com n<100 ou denominador relevante
inferior a 20 são suprimidas, sem completar grupos ausentes.

No teste original, todos os grupos observados excederam os pisos, com 4.500
registros e limiar 0,5. Os resultados são descritivos:

| Grupo | n | Prevalência | Recall | FPR | Brier |
|---|---:|---:|---:|---:|---:|
| AGE 21 a 34 | 2334 | 0,2112 | 0,3732 | 0,0549 | 0,134671 |
| AGE 35 a 49 | 1749 | 0,2196 | 0,3724 | 0,0498 | 0,134003 |
| AGE 50+ | 417 | 0,2830 | 0,3136 | 0,0602 | 0,174360 |
| SEX código 1 | 1800 | 0,2322 | 0,3995 | 0,0622 | 0,141794 |
| SEX código 2 | 2700 | 0,2137 | 0,3414 | 0,0476 | 0,135619 |

Modelo `3a1a313f639fbbf23388c90a0227bc9d29936aec574d27ca471cf52de7ed293c`,
SHA-256 do artefato `b2982bacacd984cbc942c600d39f44423e040500fed277a439ad6c97eb4e7838`,
manifesto de dados `18f2f7e2eed2a21134dc54541e62d14d17c08c34f69245616360ffc58eba0bbf`.
O SHA-256 da evidência é `a2e87c1b29fff1c8036ec5256d6f1a437fecf3010319f3172eeb7b0879a1b3db`.
Os denominadores por métrica e os hashes das entradas de auditoria estão no JSON.

O score é uma probabilidade estimada pelo baseline, não uma decisão, limite de
aprovação ou medida de justiça. A avaliação por SEX e faixas de AGE é descritiva
do teste retido e tem amostras menores após segmentação. Recall/FPR dependem do
limiar demonstrativo 0,5; diferenças entre grupos não identificam causa nem provam
discriminação. Remover atributos explícitos não elimina proxies. A mitigação prevista
é investigar coleta e representação, ampliar evidência, revisar variáveis e comparar
alternativas antes de qualquer mudança de limiar ou modelo.

A análise causal permanece limitada ao mecanismo sintético de `concept_drift`: para
os mesmos IDs, features, modelo e scores, o simulador sorteia U independentemente
por construção e aplica `Y(r)=Y(0) OR ((Y(0)=0) AND (U<r))`. A última janela
observada aumentou o Brier em 0,177789, com IC95% pareado [0,157599; 0,199006],
em 1.000 reamostragens. Isso mede o simulador, não o efeito de inflação, desemprego,
limite de crédito ou outra intervenção econômica. Importância por permutação mede
dependência preditiva do modelo e não é evidência causal.

Dados locais e artefatos operacionais permanecem no host. `make docker-retention`
apenas lista execuções de `artifacts/runs` com mais de 30 dias; a exclusão exige
`make docker-retention DELETE=1` e alcança somente diretórios diretos dessa área.
O comando não remove dados, modelos, evidências versionadas nem o banco/artefatos
do MLflow em `state/mlflow`. Após confirmação do arquivamento, a eliminação dos
dados de entrega continua manual. O prazo de 30 dias é uma política operacional
deste projeto, não prazo legal universal. Consulte [governança](docs/governanca.md),
[métricas por grupo](docs/metricas.md) e [operação](docs/operacao.md).

## Referência e demonstrações complementares

As seções abaixo explicam configuração, operação e comandos isolados. Não são
etapas adicionais obrigatórias após a trilha principal. Os exemplos de rejeição
produzem falhas esperadas e devem ser executados separadamente.

### Configuração e estado local

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

### Contratos e rejeição de lotes

Demonstração complementar. O exemplo inválido abaixo deve falhar por rejeição de
contrato; isso não é falha de instalação. A campanha integrada também demonstra
a rejeição, sem exigir a execução manual destes exemplos.

Com o tracking pronto e os dados preparados na trilha principal, os dois comandos
abaixo validam, respectivamente, features e labels da primeira janela. Ambos devem
ser aceitos, sem gerar novas predições:

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
erro operacional. Os testes manuais abaixo chamam diretamente a CLI para distinguir
rejeição de contrato e arquivo ausente. `code=$?` captura o retorno imediatamente;
`test` confirma o valor esperado e não imprime nada quando a confirmação passa:

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

### Demonstração dos cenários e avaliação pareada

Comandos isolados opcionais: `make docker-demo`, na campanha integrada abaixo,
também executa a geração e a avaliação dos cenários.

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

### Detecção estatística e relatórios

Comando isolado opcional: a campanha `make docker-demo` também executa a detecção.

Após preparar os dados e gerar os cenários com o modelo promovido, execute:

```bash
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

### Tracking e operação

O serviço é iniciado na etapa de preparação. A UI real fica em
[http://127.0.0.1:5000](http://127.0.0.1:5000). O host usa
`MLFLOW_TRACKING_URI=http://127.0.0.1:5000`; o runner Compose usa
`MLFLOW_RUNNER_TRACKING_URI=http://mlflow:5000`, pois `localhost` dentro do
container aponta para o próprio container. A porta do servidor fica limitada ao
loopback. O serviço usa SQLite em `state/mlflow/` e artefatos em `artifacts/runs/`.
`make tracking-down` para o serviço sem remover os volumes, e `make tracking-up`
recupera as mesmas runs e artefatos.

Os experimentos `credit-baseline` e `credit-monitoring` registram métricas agregadas,
etapa/janela, tags sanitizadas e amostras de recursos do processo executor. CPU é
delta acumulado de user+system em segundos. RSS é pico das amostras do processo em
bytes, com intervalo de 50 ms; processos filhos e consumo do daemon MLflow ficam fora
do escopo. O valor de pico é amostrado e pode perder picos entre leituras. Não há
autolog nem envio de linhas, IDs, predições ou modelos individuais.

Cada detecção preserva `summary.json` e `alerts.json` no diretório da execução e
publica somente esses agregados no MLflow. Eventos de rejeição, feature drift e
degradação supervisionada registram condição, severidade e ação. A avaliação de
performance não é inferida quando não há labels. Se o MLflow estiver indisponível,
os artefatos locais permanecem, o log registra a falha e o comando termina com erro
operacional, sem marcar tracking como completo.

A trilha principal gera o relatório e verifica as evidências da campanha.
O equivalente no ambiente Poetry é `make report CAMPAIGN_ID=<campaign_id>`.

## Documentação

- [Dataset](docs/dataset.md), origem, preparação e limitações.
- [Model card](docs/model_card.md), avaliação e limites do modelo.
- [Causalidade](docs/causalidade.md), hipóteses e resultados dos cenários.
- [Métricas](docs/metricas.md), definições e análise por grupo.
- [Operação](docs/operacao.md) e [governança](docs/governanca.md), procedimentos e retenção.
- [Reprodutibilidade](docs/reproducibilidade.md), medições e condições de execução.
- [Evidências](docs/evidencias/README.md) e [decisões arquiteturais](docs/adr/), registros de suporte.

Fontes: [Lei nº 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm), [dataset na UCI](https://archive.ics.uci.edu/dataset/350/default%2Bof%2Bcredit%2Bcard%2Bclients) e [licença CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Desenvolvimento local opcional

Alternativa para desenvolver e verificar o código diretamente no computador, com
Python 3.12 e Poetry 2.5.1 instalados. Esta seção é independente da trilha Docker;
quem segue a execução em Docker pode desconsiderá-la.

```bash
poetry check --lock
poetry sync --with dev
make lint
make test
```

`poetry check --lock` confere a configuração e o lockfile; `poetry sync --with dev`
instala as dependências de produção e desenvolvimento no ambiente Poetry.
`make lint` e `make test` executam as verificações nesse ambiente local.
As versões de Python e bibliotecas precisam respeitar os requisitos do projeto.
