# Métricas de mudança nas entradas

O detector compara as 19 variáveis financeiras. PAY usa categorias explícitas;
montantes usam valores em NT$. Estatísticas abaixo são adimensionais e não
quantificam prejuízo financeiro, risco individual ou efeito causal econômico.

| Campo | Semântica e unidade | Regra |
|---|---|---|
| PSI, `score` categórico | Soma de (q-p) ln(q/p), sem unidade; não é p-valor | >=0,25 |
| KS, `score` numérico e `p_raw` | p-valor bilateral, em [0,1] | Relatório: p <0,01 |
| `ks_d` | Máxima distância entre CDFs empíricas, em [0,1] | Magnitude mínima 0,10 |
| `p_adjusted` | p ajustado por Holm na família das 13 numéricas | Operacional: p ajustado <0,01 e D >=0,10 |
| `reference_n`, `current_n` | Quantidades de linhas utilizadas | Ambas >=20 |
| `report_drift` | Flag reconstruída do método/limite fixado do Evidently | PSI ou KS bruto |
| `operational_alert` | Decisão que gera feature_drift | PSI ou Holm com magnitude |

Holm ordena p-valores, multiplica por m-rank e aplica máximo acumulado limitado
a 1. Inclui constantes e empates com desempate por nome. Corrige a família
numérica da janela, sem corrigir PAY, múltiplas janelas ou comparações da campanha.
KS é calculado pelo SciPy 1.15.3, bilateral, método auto. Valores discretos e
empates limitam a interpretação do p-valor contínuo do KS. Significância não mede
relevância prática; a magnitude é registrada separadamente. PSI não tem essa
interpretação probabilística.

## Categorias, zeros e amostras

No PSI categórico da versão instalada do Evidently, cada categoria da união dos
dois conjuntos é um bin. Não há discretização numérica nem quantidade de bins
ajustada ao dado para PAY. Frequência é contagem dividida pelo n de cada conjunto.
Cada zero é substituído por 0,0001, exceto quando a menor frequência positiva
daquela distribuição é <=0,0001: nesse caso, usa-se essa frequência /1.000.000.
As frequências não são renormalizadas após substituir zeros. Categoria nova ou
ausente pode dominar PSI. O teste de categorias disjuntas fixa essa semântica.
Constantes idênticas têm PSI 0 ou KS p=1, D=0. Não remover constantes da família.

Menos de 20 linhas em qualquer conjunto causa erro de amostra insuficiente;
não é resultado sem drift. O piso é uma proteção de execução, sem promessa de
poder. A execução de aceite utiliza referência de 5.000 e janelas de 1.000.

## Operação e leitura dos resultados

`make docker-detect` escreve `artifacts/runs/<run_id>/summary.json`, `alerts.json`
e subdiretórios por comparação/janela com `evidently.html`, `evidently.json` e
`normalized.json`. A CLI informa UUID, quantidade de comparações e resultado do
gate. A saída normalizada registra versão, configuração efetiva/hash, método,
score, amostras, limites, p bruto/ajustado quando aplicável e flags distintas.

Cada feature_drift tem severidade warning, regra, valor, limite, janela, execução
e ação de investigar coleta, variáveis e desempenho quando labels estiverem
disponíveis. A chave impede duplicação no mesmo conjunto de eventos; outra execução
tem novo UUID. Nenhuma mensagem externa ou promoção de modelo é disparada.

Controle idêntico e pares stable/concept precisam ficar sem feature_drift.
As duas features selecionadas na validação precisam alertar na última perturbação.
As janelas estáveis de validação medem alertas sob o controle, sem ajuste automático
de limites. Falsos alertas são possíveis; ausência não comprova igualdade.
As janelas são simuladas, não uma série histórica temporal observada.

Os snapshots são locais e ignorados. Revisar conteúdo antes de qualquer publicação:
gráficos podem incluir distribuições de valores reais. A evidência publicada deve
conter somente agregados selecionados. Detalhes na [ADR 0005](adr/0005-monitoramento-estatistico.md).


## Aceite medido em 24/10/2026

Execução `6b613fd0-6cf6-404e-a554-b0f1407a87f7`. Evidência agregada: [deteccao.json](evidencias/deteccao.json).

23 comparações reais; referência com 5.000 registros, janelas de 1.000.
Quatro janelas completas de validação e 500 registros restantes não utilizados.
Métodos e limiares originais preservados.

| Comparação | Janela | Flags do relatório | Alertas operacionais |
|---|---:|---:|---:|
| identical | 000 | 0 | 0 |
| validation | 000 | 2 | 0 |
| validation | 001 | 1 | 0 |
| validation | 002 | 1 | 0 |
| validation | 003 | 1 | 1 |
| stable | 000 | 0 | 0 |
| data_drift | 000 | 0 | 0 |
| stable_vs_concept | 000 | 0 | 0 |
| stable | 001 | 0 | 0 |
| data_drift | 001 | 2 | 2 |
| stable_vs_concept | 001 | 0 | 0 |
| stable | 002 | 0 | 0 |
| data_drift | 002 | 2 | 2 |
| stable_vs_concept | 002 | 0 | 0 |
| stable | 003 | 0 | 0 |
| data_drift | 003 | 2 | 2 |
| stable_vs_concept | 003 | 0 | 0 |
| stable | 004 | 0 | 0 |
| data_drift | 004 | 2 | 2 |
| stable_vs_concept | 004 | 0 | 0 |
| stable | 005 | 0 | 0 |
| data_drift | 005 | 2 | 2 |
| stable_vs_concept | 005 | 0 | 0 |

Na validação houve cinco flags brutas em 76 comparações feature/janela e um
alerta operacional, em pay_amt3 na janela 003 (p bruto 9,40360e-08,
p ajustado 1,22247e-06, D=0,1004). São 1/76 comparações e 1/4 janelas com
falso alerta no controle estável. Essas frações são descritivas, sem estimar
uma taxa universal de erro; comparações são dependentes. Nenhum limiar foi alterado.
As seis janelas stable de produção não geraram alertas; os seis pares
stable/concept e o controle idêntico também não.

| Feature alterada, última janela | Método | Score | p ajustado | D | Alerta |
|---|---|---:|---:|---:|---|
| pay_0 | PSI | 9,110350581 | não aplicável | não aplicável | sim |
| limit_bal | KS | 2,505074911e-153 | 3,256597384e-152 | 0,45 | sim |

Gate aprovado. Nenhuma métrica de labels foi usada para produzir alerta de X.
A abertura do HTML em Chromium renderizou os 19 gráficos sem erro JavaScript.
O JSON nativo foi interpretado e contém 19 métricas com configuração semântica.
A UI arredonda p muito pequeno para 0,0; o JSON e a saída normalizada
preservam o valor numérico. Não interpretar o arredondamento como probabilidade zero.

Inspeção de privacidade: JSON nativo contém métricas/configurações, sem linhas.
HTML contém gráficos de distribuições e agregados por índice; foi mantido local
porque exibe valores derivados dos dados reais. Nenhum HTML foi selecionado para Git.
A evidência publicada contém somente métodos, tamanhos, estatísticas e flags.
Duas execuções independentes preservaram os 437 resultados por feature (23 x 19).
Os 136 arquivos locais de dados/modelos anteriores permaneceram byte a byte.

Validação em Docker: build, lint, formatação e smoke aprovados; 134 testes,
12 warnings conhecidos de dependências, cobertura total 94%. Fixtures próprias,
sem dataset, modelo preparado ou tracking ativo do host.
