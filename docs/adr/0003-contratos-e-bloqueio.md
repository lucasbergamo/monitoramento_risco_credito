# ADR 0003: contratos estritos e rejeição integral de lotes

Estado: implementado em 24/10/2026.

## Problema e decisão

Entradas financeiras inválidas precisam ser rejeitadas antes de qualquer consumidor.
Pandera valida com `lazy=True`, schema estrito, sem coerção ou descarte de linhas.
Uma rejeição bloqueia o lote inteiro. Não há modelo ou inferência nesta entrega.

`validate_table(table, scope)` oferece os schemas isolados: origem numérica
normalizada antes de `group_id`, features e labels. A conversão do XLS continua
pertencendo à preparação explícita. `validate_batch(features, keys)` valida as
19 features e as chaves separadas, incluindo unicidade de `record_id`, igual
comprimento e índice alinhado por posição. A correspondência entre esses arquivos
pressupõe o exportador de dados; sem ID nas features não é possível detectar uma
permutação independente dos valores com o mesmo índice.

`validate_labels(labels, keys)` exige labels binários e associação 1:1 com o mesmo
conjunto de IDs. A ordem dos labels pode diferir; o consumidor deve associá-los por
ID após produzir scores. Labels, IDs e demografia não são features. Chaves podem
conter `group_id`, como os arquivos produzidos pela preparação.

Tipos monetários aceitam dtypes inteiros ou de ponto flutuante reais, sem texto,
booleanos, complexos, nulos ou infinitos. PAY, IDs, alvo e demografia exigem dtype
inteiro. Limite deve ser positivo e pagamentos não negativos. Faturas admitem sinal
negativo. Não há teto de valor baseado nos extremos estatísticos observados.

`configs/contracts.yaml` versiona os domínios. PAY aceita -2 a 9: os códigos -2/0
foram observados, e 9 está documentado pela fonte mesmo sem ocorrência no arquivo.
O código 1 continua permitido em PAY_5/PAY_6 apesar de sua ausência na amostra.
EDUCATION e MARRIAGE preservam os códigos não especificados observados.
Essas escolhas e sua origem estão em [dataset](../dataset.md).

## Diagnóstico e falhas

`ValidationResult` contém versão, registros recebidos/aceitos/rejeitados e tuplas
de `Violation`: escopo, campo autorizado, código estável e contagem. Colunas
inesperadas são representadas por `column: null`; seu nome também pode ser sensível.
Não são serializados `failure_cases`, valores, índices, IDs, caminhos ou exceções
do backend. Contagens de violações se sobrepõem; não equivalem a linhas distintas.
Rejeição de qualquer regra deixa `rows_accepted=0` e rejeita todas as linhas.
Lote vazio também é rejeitado, com regra `nonempty`.

`validate_batch` e `validate_labels` retornam resultado válido ou lançam
`ContractRejected` com diagnóstico seguro. O chamador deve completar a validação
antes de invocar qualquer consumidor. Um espião nos testes comprova o bloqueio.
Não existe callback de inferência ou consumidor fictício no produto.

A CLI retorna 0 no sucesso, 2 na rejeição e 1 na falha operacional, incluindo arquivo
ausente, formato não suportado, argumento ou configuração inválidos. Erro inesperado
do backend permanece operacional. Make conserva sua convenção: receita com falha
faz o próprio Make retornar 2. Para distinguir 1 de 2, chamar a CLI diretamente,
conforme o README. Nenhum comando captura qualquer erro como rejeição esperada.

## Alternativas e limites

Corrigir ou filtrar silenciosamente defeitos ocultaria a evidência de rejeição.
Publicar o relatório bruto do backend exporia registros individuais. Um schema
único com alvo obrigatório inviabilizaria inferência sem labels e permitiria leakage.
Foram escolhidos schemas separados e agregação por códigos estáveis.

CSV usa a inferência de dtypes do pandas durante a leitura. Para preservar dtypes
exatamente, utilizar parquet. Nenhuma validação transforma valores de texto numérico
em números; os schemas trabalham sobre o DataFrame já lido. Alterar política exige
revisão de configuração, testes e versão do contrato.
