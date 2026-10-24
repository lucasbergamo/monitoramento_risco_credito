# ADR 0002: Origem identificada e partições por grupos

Status: implementada, verificação de execução em `docs/dataset.md`.

## Contexto

A base histórica UCI contém clientes distintos com vetores de atributos idênticos,
inclusive com rótulos diferentes. Uma divisão por linha permitiria que o mesmo
vetor fosse visto no treino e na avaliação. Também é necessário separar a referência
de drift e a produção simulada antes de treinar qualquer modelo.

## Decisão

Identificar ZIP e XLS por SHA-256 congelado em `configs/project.yaml` após inspeção.
Verificar ambos antes da preparação. Rejeitar arquivo incompatível, membro inseguro,
planilha com cabeçalhos diferentes, ID repetido, número não inteiro, ausente ou não
finito e alvo fora das duas classes. Não atualizar checksums automaticamente.

Mapear explicitamente os nomes das duas linhas de cabeçalho da planilha. Preservar
os 23 atributos, sem descartar códigos pouco documentados ou faturas negativas.
Agrupar pelo SHA-256 da lista ordenada dos 23 atributos normalizados, sem ID ou
rótulo. Grupos com rótulos conflitantes permanecem inteiros, sem remoção silenciosa.
A chave de grupo é local e não representa garantia de anonimização.

Ordenar por ID antes de `StratifiedGroupKFold(n_splits=20, shuffle=True,
random_state=42)`. Atribuir folds 0 a 9 ao treino, 10 a 12 à validação, 13 a 15 ao
teste e 16 a 19 à produção. Os percentuais desejados são 50/15/15/20; o tamanho dos
grupos e a estratificação aproximada impedem prometer proporções exatas.

A referência de até 5.000 linhas usa `train_test_split` estratificado, seed 42,
exclusivamente dentro do treino ordenado por ID. Ordenar novamente a referência
por ID. Permutar a produção ordenada com um `numpy.random.default_rng(42)` exclusivo
e usar todas as janelas completas de 1.000 registros, preservando o restante local.
Exigir ao menos quatro janelas. O índice representa tempo simulado.

Exportar features financeiras, chaves e rótulos em arquivos separados, com a mesma
ordem de linhas por conjunto. As 19 features excluem ID, alvo e SEX, EDUCATION,
MARRIAGE e AGE. A tabela de auditoria demográfica mantém apenas chave e demografia,
em armazenamento local. Não há resultados de modelo na seleção.

## Consequências

A estratificação é aproximada e seus desvios são publicados. As partições são
reproduzíveis com as versões fixadas no lock. O hash do split cobre a associação de
IDs e grupos às partições, a referência, a ordem das janelas e o restante. Apenas
o digest é publicado; as listas individuais permanecem locais.

A exclusão de demografia reduz atributos diretos no preditor, mas não remove proxies
nem demonstra ausência de discriminação. A referência compartilha dados de treino,
portanto não é evidência de generalização. A produção não participa de referência,
seleção de modelo ou calibração.

Uma troca de bytes na UCI exige inspeção e atualização explícita da configuração e
da evidência versionada. Cache alterado falha, mesmo quando há outro ZIP válido.
A inspeção verifica todos os hashes dos arquivos locais; não depende da data de modificação.
