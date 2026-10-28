# Model card: baseline de inadimplência

Estado: treinado, avaliado e promovido localmente em 24/10/2026. Finalidade acadêmica.

## Dados, modelo e fronteiras

UCI Default of Credit Card Clients, 30.000 registros históricos de Taiwan. Treino:
15.000; validação: 4.500; teste: 4.500; produção reservada: 6.000. Split por grupos,
seed 42. Referência de drift de 5.000 linhas extraída somente do treino; seus hashes
estão congelados no manifesto. Produção fica fora de treino, seleção e avaliação final.

Preditor HGB sobre as 19 variáveis financeiras ordenadas, sem ID, alvo ou demografia.
PAY ordinal, incluindo códigos especiais. Não há imputação, normalização, tuning
ou calibração. Comparador Dummy com prior do treino. Parâmetros exatos:

```json
{
  "categorical_features": null,
  "early_stopping": false,
  "l2_regularization": 1.0,
  "learning_rate": 0.1,
  "max_iter": 150,
  "max_leaf_nodes": 15,
  "random_state": 42
}
```

Threads limitadas a 1 e seed global 42 antes do ajuste. Configuração efetiva e
versões de Python, sklearn, NumPy, pandas e joblib estão na evidência agregada.

## Métricas observadas

Limiar fixo 0,5; classe positiva 1 (inadimplência no mês seguinte). O teste foi
avaliado depois do congelamento das decisões, sem selecionar parâmetros por ele.

| Métrica | Validação HGB | Validação Dummy | Teste HGB | Teste Dummy |
|---|---:|---:|---:|---:|
| n | 4500 | 4500 | 4500 | 4500 |
| Prevalência | 0.221333 | 0.221333 | 0.221111 | 0.221111 |
| ROC-AUC | 0.778865 | 0.500000 | 0.765970 | 0.500000 |
| Average precision | 0.555638 | 0.221333 | 0.528166 | 0.221111 |
| Brier | 0.134739 | 0.172345 | 0.138089 | 0.172221 |
| Log loss | 0.430179 | 0.528590 | 0.440390 | 0.528311 |
| Precision | 0.677903 | 0.000000 | 0.660617 | 0.000000 |
| Recall | 0.363454 | 0.000000 | 0.365829 | 0.000000 |
| F1 | 0.473203 | 0.000000 | 0.470893 | 0.000000 |

Matrizes de confusão com linhas verdadeiras e colunas preditas, na ordem 0/1:

| Partição | HGB | Dummy |
|---|---|---|
| Validação | `[[3332, 172], [634, 362]]` | `[[3504, 0], [996, 0]]` |
| Teste | `[[3318, 187], [631, 364]]` | `[[3505, 0], [995, 0]]` |

Gate aprovado exclusivamente na validação: AUC >=0,65 e Brier estritamente melhor
que Dummy. Valores integrais em [baseline.json](evidencias/baseline.json). Teste
é medida de generalização; não é critério de promoção. Nenhuma métrica de produção
foi calculada para selecionar o modelo ou suas variáveis.

## Seleção para perturbação controlada

Permutation importance em ROC-AUC na validação, cinco repetições, seed 42. A regra
usa médias positivas, ordem decrescente e desempate por nome entre as 19 features
financeiras suportadas. A dupla congelada é:

| Feature | Queda média de ROC-AUC | Desvio entre permutações |
|---|---:|---:|
| pay_0 | 0.083216 | 0.006282 |
| limit_bal | 0.018396 | 0.002301 |

As 19 médias, desvios e cinco quedas individuais por feature constam do manifesto.
O desvio entre cinco permutações não é intervalo de confiança populacional.
Importância mede dependência do modelo e pode ser diluída por correlação; não é
efeito causal nem justificativa de política de crédito.

## Identidade e reprodução

| Identificador | SHA-256 |
|---|---|
| Versão | `3a1a313f639fbbf23388c90a0227bc9d29936aec574d27ca471cf52de7ed293c` |
| Artefato joblib | `b2982bacacd984cbc942c600d39f44423e040500fed277a439ad6c97eb4e7838` |
| Manifesto do dataset | `18f2f7e2eed2a21134dc54541e62d14d17c08c34f69245616360ffc58eba0bbf` |
| Split | `5944bc866b7711ccb61ed4f8b32e2531e5665a458929eac14d0c9db9de3b26db` |
| Configuração do modelo | `9e83cff94346877866e68d0c2cd3c0ae0924346eea34f89bf7417f52daeb2b32` |
| Origem ZIP | `56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602` |

Executar o percurso `setup`, `build`, `docker-data`, `docker-train`,
`docker-evaluate`, `docker-promote` do README. No ambiente fixado, a reexecução
do treino preservou versão, hashes, métricas e seleção. A versão inclui os hashes
do artefato e do manifesto de treino. Não se promete igualdade de bytes entre
versões de bibliotecas, plataformas ou ambientes diferentes.

Bundles e scores individuais ficam locais. A evidência versionada contém apenas
agregados, nomes de features, políticas e hashes. `current` é trocado atomicamente
após aprovação do gate. Carregar somente joblib produzido no armazenamento confiável
do projeto. Detalhes na [ADR 0004](adr/0004-modelo-e-avaliacao.md).

## Limitações e usos

O recall de aproximadamente 0,366 no teste demonstra que o limiar 0,5 deixa de
detectar grande parte dos positivos. O baseline não define custo de erros, limiar
ótimo, política econômica, concessão real ou garantia de segurança financeira.
Não há validação temporal ou externa; partições aleatórias por grupos não demonstram
estabilidade ao longo do tempo. O comparador trivial fornece referência mínima.

Base de 2005, valores em NT$ e população de Taiwan, sem representatividade
automática do Brasil atual. PAY inclui códigos especiais como ordinais, uma
simplificação de modelagem. Remover demografia não remove proxies nem comprova
ausência de discriminação. O diagnóstico descritivo de grupos no teste está em
[métricas por grupo](metricas.md); não é certificação de justiça ou governança.
Não se afirma calibração, justiça, conformidade jurídica ou adequação produtiva.
O pipeline de cenários e detectores usa o bundle congelado e não retreina o modelo
durante a demonstração de drift.

## Diagnóstico descritivo por grupo

No teste original, com modelo congelado `3a1a313f`, limiar 0,5 e 4.500 registros,
foram calculados n, prevalência, recall, taxa de falso positivo e Brier por código
de SEX e faixa de AGE. Os valores agregados e hashes reproduzíveis estão em
[governanca.json](evidencias/governanca.json). AGE/SEX não entraram no estimador.
As diferenças observadas são descritivas dessa partição histórica e não identificam
causas, não medem desempenho futuro e não demonstram discriminação ou equidade.

| Grupo | n | Prevalência | Recall | FPR | Brier |
|---|---:|---:|---:|---:|---:|
| AGE 21 a 34 | 2334 | 0,2112 | 0,3732 | 0,0549 | 0,134671 |
| AGE 35 a 49 | 1749 | 0,2196 | 0,3724 | 0,0498 | 0,134003 |
| AGE 50+ | 417 | 0,2830 | 0,3136 | 0,0602 | 0,174360 |
| SEX código 1 | 1800 | 0,2322 | 0,3995 | 0,0622 | 0,141794 |
| SEX código 2 | 2700 | 0,2137 | 0,3414 | 0,0476 | 0,135619 |

Identidade da evidência: versão do modelo
`3a1a313f639fbbf23388c90a0227bc9d29936aec574d27ca471cf52de7ed293c`, artefato
`b2982bacacd984cbc942c600d39f44423e040500fed277a439ad6c97eb4e7838`, manifesto
do dataset `18f2f7e2eed2a21134dc54541e62d14d17d08c34f69245616360ffc58eba0bbf`.
SHA-256 de `governanca.json`:
`a2e87c1b29fff1c8036ec5256d6f1a437fecf3010319f3172eeb7b0879a1b3db`.
