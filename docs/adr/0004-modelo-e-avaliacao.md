# ADR 0004: baseline congelado e promoção por validação

Estado: implementado em 24/10/2026. Resultados em [model card](../model_card.md)
e [evidência agregada](../evidencias/baseline.json).

## Problema e decisão

A demonstração de degradação exige um modelo congelado, com ganho verificável em
relação a um preditor trivial. Treinar `HistGradientBoostingClassifier` somente no
treino com `max_iter=150`, `max_leaf_nodes=15`, `learning_rate=0.1`,
`l2_regularization=1.0`, `early_stopping=False`, `categorical_features=None` e
`random_state=42`. Comparar com `DummyClassifier(strategy='prior')` ajustado no mesmo
treino. Não há imputação, normalização, tuning ou calibração de probabilidades.

Seed global 42 antes do treino, uma thread via `threadpoolctl` em treino/inferência
e `n_jobs=1` na permutação. Docker também fixa as variáveis de threads antes do
processo. Features são as 19 financeiras na ordem versionada; PAY é ordinal,
incluindo códigos especiais. Não usar alvo, ID, demografia ou produção no ajuste.

Validar manifesto de preparação, schema, configuração e hashes dos arquivos antes
de consumir cada partição. Validar contratos de features, chaves e labels. Associar
labels por ID, mesmo quando sua ordem difere. Verificar interseções de IDs e grupos
entre treino e validação. As demais separações são estabelecidas pela preparação.

## Avaliação e seleção

Gate exclusivo de validação: ROC-AUC >=0,65 e Brier estritamente menor que o Dummy.
Piso e limiar de decisão 0,5 são escolhas do projeto, sem política econômica real.
Configuração rejeita parâmetros fora do contrato e piso inferior a 0,65. Um piso
1,1 só é passado explicitamente à fixture de teste para comprovar a rejeição.

Medir ROC-AUC, average precision, Brier, log loss, precision, recall, F1 e matriz de
confusão com classe positiva 1. Matriz tem linhas verdadeiras e colunas preditas,
na ordem 0/1. Registrar contagem e prevalência; AP não é área trapezoidal PR.

Na validação, executar permutation importance em ROC-AUC, cinco repetições e seed
42. Selecionar as duas maiores médias positivas entre features com transformação
definida (as 19 financeiras); empate por nome crescente. Congelar médias, desvios,
repetições, dupla e hashes da referência de treino no manifesto. Importância mede
dependência preditiva do modelo, sem interpretação causal. Correlações podem diluí-la.

Avaliar o teste apenas com as decisões congeladas em staging. Guardar relatório
separado do bundle imutável. Promoção não lê teste nem seu relatório; métricas ruins
no teste exigem relato, sem trocar automaticamente o critério de promoção.

## Persistência e falhas

Bundles locais em `models/bundles/<version>/` contêm `model.joblib` (HGB e Dummy) e
`manifest.json`. A versão é SHA-256 do manifesto canônico sem o próprio campo de
versão, incluindo SHA-256 do artefato, hashes de dados e configuração. Não usar mtime.
O manifesto registra versões de Python/bibliotecas e metadados da preparação.

`staging` é um symlink relativo atualizado por `os.replace` após escrita e leitura
verificada de todo o bundle. Artefato reprovado pode ficar em staging para diagnóstico,
mas a CLI retorna 2 e a promoção é bloqueada. Promoção recalcula o gate, copia o
bundle aprovado para `models/approved/<version>/` em diretório temporário, verifica
novamente e troca `current` por rename atômico do symlink. Um leitor resolve o
ponteiro uma vez, carregando a versão anterior ou a nova por inteiro.

Diretórios vazios criados pelo setup anterior são convertidos no primeiro uso.
Diretório não vazio é preservado e causa erro. Falhas de gate, cópia ou replace não
substituem um modelo aprovado anterior. Temporários são removidos; bundles completos
podem permanecer para diagnóstico. Não há coleta automática de versões antigas.
Atomicidade depende de filesystem POSIX local e rename no mesmo filesystem. Não
há promessa de recuperação após perda física de energia, fsync ou transação distribuída.

Carregamento verifica versão/hash, política, gate, seleção e features do manifesto
antes do joblib; depois confere classes, nomes/ordem de features e parâmetros dos
estimadores. Inferência valida o lote antes de carregar o modelo. Hashes detectam
corrupção, sem autenticar arquivos externos: joblib deve vir exclusivamente do
armazenamento confiável do projeto, por permitir execução de código na leitura.

## Alternativas e verificações

Sobrescrever modelo e manifesto separadamente exporia versões parciais; mover um
diretório não vazio sobre outro também não fornece a troca exigida. Bundles imutáveis
com ponteiro atômico mantêm a leitura consistente. Selecionar features a priori ou
na produção esconderia a origem da decisão. Teste não participa da promoção.

Fixtures são geradas e treinadas em diretórios temporários, sem dataset UCI ou
`make train` prévio. Cobrem gate impossível, falhas de cópia/replace, integridade,
nomes e ordem de features, labels permutados por ID, rejeição antes do consumidor,
reexecução determinística e independência do treino em relação aos dados de teste.

Fontes: [HistGradientBoostingClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html),
[permutation importance](https://scikit-learn.org/stable/modules/permutation_importance.html)
e [persistência sklearn](https://scikit-learn.org/stable/model_persistence.html).
