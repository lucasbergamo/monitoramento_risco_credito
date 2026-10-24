# Dataset de crédito: origem, preparação e limitações

## Origem e identificação

Yeh, I. (2009). Default of Credit Card Clients. UCI Machine Learning Repository.
[DOI 10.24432/C55S3H](https://doi.org/10.24432/C55S3H).
[Catálogo e Download](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients),
licença [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Inspeção e preparação executadas em 24/10/2026.

O ZIP oficial tem 5.539.494 bytes e contém somente
`default of credit card clients.xls`, com 5.539.328 bytes. Os hashes foram medidos
após a aquisição e conferidos na execução do pipeline:

| Artefato | SHA-256 |
|---|---|
| ZIP | `56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602` |
| XLS | `30c6be3abd8dcfd3e6096c828bad8c2f011238620f5369220bd60cfc82700933` |
| Split | `5944bc866b7711ccb61ed4f8b32e2531e5665a458929eac14d0c9db9de3b26db` |

`configs/project.yaml` congela os hashes de aquisição e a configuração.
`docs/evidencias/dataset_manifest.json` registra schema, hashes de arquivos,
configuração efetiva, prevalências, contagens, grupos e categorias observadas.
Reexecução não altera automaticamente a origem esperada. Mudança na fonte exige
inspeção e revisão explícita da configuração e da evidência versionadas.

## Cabeçalhos, tipos e mapeamento

A planilha possui 30.002 linhas e 25 colunas: primeira linha com célula vazia,
`X1..X23` e `Y`; segunda linha com os nomes abaixo; demais 30.000 linhas com dados.
O parser valida as duas linhas antes de atribuir nomes. A ingestão converte
explicitamente valores numéricos inteiros finitos para int64. Ausentes, frações,
texto inesperado, IDs repetidos e alvo fora de {0,1} interrompem a preparação.
Não há imputação, agregação de clientes ou exclusão automática de registros.

| Nome no XLS | Nome normalizado | Papel |
|---|---|---|
| ID | record_id | Chave técnica local |
| LIMIT_BAL (X1) | limit_bal | Feature financeira, limite em NT$ |
| SEX (X2) | sex | Auditoria demográfica local |
| EDUCATION (X3) | education | Auditoria demográfica local |
| MARRIAGE (X4) | marriage | Auditoria demográfica local |
| AGE (X5) | age | Auditoria demográfica local, anos |
| PAY_0 (X6) | pay_0 | Status de pagamento em setembro/2005 |
| PAY_2..PAY_6 (X7..X11) | pay_2..pay_6 | Status de agosto a abril/2005 |
| BILL_AMT1..BILL_AMT6 (X12..X17) | bill_amt1..bill_amt6 | Faturas, setembro a abril/2005, NT$ |
| PAY_AMT1..PAY_AMT6 (X18..X23) | pay_amt1..pay_amt6 | Pagamentos, setembro a abril/2005, NT$ |
| default payment next month (Y) | default_next_month | Alvo observado, 1 inadimplência, 0 ausência |

O preditor recebe exatamente `limit_bal`, `pay_0`, `pay_2..pay_6`,
`bill_amt1..bill_amt6` e `pay_amt1..pay_amt6`, nessa ordem. São 19 features.
ID, target e as quatro variáveis demográficas não entram no arquivo de features.
A fonte descreve limite individual e familiar, não renda. Os nomes dos meses não
são datas de produção simulada.

## Achados da inspeção

- 30.000 registros utilizáveis, 30.000 IDs únicos, nenhum ausente e nenhum valor
  não inteiro. Todas as colunas numéricas normalizadas são int64.
- 6.636 rótulos positivos, prevalência global 22,12%; os demais 23.364 são negativos.
- SEX: {1,2}; EDUCATION: {0,1,2,3,4,5,6}; MARRIAGE: {0,1,2,3}.
- PAY_0/PAY_2/PAY_3/PAY_4: {-2,-1,0,1,2,3,4,5,6,7,8}.
  PAY_5/PAY_6 não apresentam 1, mas preservam os outros códigos observados.
- A descrição resumida da UCI não especifica PAY -2/0, EDUCATION 0/5/6 e MARRIAGE 0.
  Esses códigos são preservados como não especificados, sem recodificação ou
  interpretação inventada. O código 9 descrito no catálogo não ocorre neste arquivo.
- Há faturas negativas: 590, 669, 655, 675, 655 e 688 registros, respectivamente
  em BILL_AMT1 a BILL_AMT6. Valores negativos podem representar saldo credor,
  mas essa interpretação não é comprovada individualmente. O sinal é preservado.
- Não há pagamentos negativos ou limites não positivos nesta origem. Máximos
  observados não são adotados como limites universais de domínio.
- 29.944 grupos de vetores dos 23 atributos; 52 grupos têm repetição, abrangendo
  108 registros e 56 repetições além da primeira ocorrência. Há 21 grupos com
  rótulos conflitantes. Todos os registros permanecem na base.

## Partições e prevenção de leakage

Algoritmo completo na [ADR 0002](adr/0002-dados-e-particoes.md). O grupo usa os 23
atributos normalizados, excluindo ID e target; a serialização JSON da lista tem
ordem fixa e SHA-256. O agrupamento inclui demografia, mesmo que ela fique fora do
preditor. Não equivale a deduplicar apenas as 19 features financeiras.

Dados ordenados por ID alimentam StratifiedGroupKFold de 20 folds, shuffle e seed
42. A atribuição dos folds 10/3/3/4 produz as proporções abaixo nesta versão.
A estratificação é aproximada; os grupos são indivisíveis e o algoritmo não promete
percentuais exatos em outra base. Desvio de tamanho observado: 0,00 ponto percentual
em cada partição. Prevalências não são perfeitamente iguais.

| Partição | Registros | Negativos | Positivos | Prevalência | Grupos |
|---|---:|---:|---:|---:|---:|
| Treino | 15.000 | 11.683 | 3.317 | 22,1133% | 14.968 |
| Validação | 4.500 | 3.504 | 996 | 22,1333% | 4.493 |
| Teste | 4.500 | 3.505 | 995 | 22,1111% | 4.494 |
| Produção | 6.000 | 4.672 | 1.328 | 22,1333% | 5.989 |

O pipeline verifica interseções vazias de IDs e grupos entre todas as partições,
duas classes por partição e mínimo de 5.000 linhas. A referência tem 5.000 linhas,
selecionadas estratificadamente apenas no treino, com seed 42 e prevalência 22,12%.
Não participa como teste de generalização. Não há produção na referência.

Uma permutação determinística, com RNG exclusivo de seed 42 sobre produção ordenada,
gera seis janelas disjuntas de 1.000 registros. Restante: zero. Índices 000 a 005
representam tempo simulado, sem alegar sequência histórica real. Não se utiliza
modelo ou resultado de produção para selecionar referência ou janelas.

A conferência das janelas encontrou 210, 218, 231, 209, 233 e 227 positivos,
respectivamente (prevalências de 21,0%, 21,8%, 23,1%, 20,9%, 23,3% e 22,7%).
Não houve seleção de janelas por esses resultados.

## Artefatos e reprodução

Na raiz do projeto, seguir o README: `make setup`, `make build`, `make docker-data`
e `make docker-inspect-data`. Para ZIP local, usar
`make docker-data DATASET_ARCHIVE=/caminho/absoluto/dataset.zip`.
O arquivo deve corresponder aos bytes oficiais, sem recompactação.

- Bronze: ZIP/XLS originais identificados por hash.
- Silver: `normalized.parquet` preserva todos os atributos, alvo, chave e grupo;
  `audit.parquet` mantém somente `record_id` e as quatro variáveis demográficas.
- Gold: diretórios `train`, `validation`, `test`, `production_pool`, `reference`,
  `windows/000..005` e `production_remainder`. Cada um contém `features.parquet`
  com 19 colunas, `keys.parquet` com `record_id/group_id` e `labels.parquet` com
  `record_id/default_next_month`. Os três arquivos têm alinhamento por posição;
  usar chaves e exigir associação 1:1 ao combinar labels. Nenhuma chave fica no
  índice do arquivo de features.
- Manifesto local: `data/gold/dataset_manifest.json`. Cópia pública agregada em
  `docs/evidencias/dataset_manifest.json`, sem caminhos absolutos ou IDs individuais.

O hash do split cobre as associações completas às partições, referência, ordem das
janelas e restante. O manifesto também registra hashes dos bytes parquet e schema.
Os dados locais são excluídos do Git e do contexto de build. Testes usam fixtures
sintéticas próprias, inclusive uma planilha BIFF gerada no teste, sem baixar a base.

## Alcance e limitações

Base histórica de Taiwan, não amostra representativa do mercado brasileiro atual.
Não se deve inferir políticas reais de crédito a partir desta preparação.
A exclusão de demografia não elimina proxies ou garante ausência de discriminação.
O armazenamento de chaves é local; a publicidade da fonte e hashes técnicos não
provam anonimização. As evidências publicadas são agregadas. Não enviar registros,
rótulos ou identificadores individuais a logs ou tracking.
