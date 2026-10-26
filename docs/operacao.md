# Operação do tracking e dos relatórios

## Serviço e persistência

`make tracking-up` constrói e inicia o servidor MLflow em Docker Compose. A UI é
servida em `http://127.0.0.1:5000`; apenas o loopback do host recebe a porta. O
servidor usa SQLite em `state/mlflow/tracking.db` e serving de artefatos em
`artifacts/runs/`. O runner acessa `http://mlflow:5000` pela rede Compose. A URI
do host e a URI interna têm configurações independentes no `.env`.

O healthcheck consulta `/health`. `make status` apresenta containers e consulta a
URI do host. `make tracking-down` usa `stop`, sem remover volumes. Após subir de novo,
as runs são consultadas pelo cliente e pela UI. O usuário do host é aplicado ao
serviço e aos diretórios por `HOST_UID`/`HOST_GID`; não é necessário sudo para ler ou
remover os arquivos locais.

## Métricas e recursos

Os experimentos são `credit-baseline` e `credit-monitoring`, com nomes de run
correspondentes. Cada execução registra resultados agregados, run ID, componente,
versão de modelo/cenário quando existente e métricas por etapa ou janela. Não há
autolog. O serializador remove linhas, IDs, scores individuais, caminhos e campos
de usuário antes da publicação. Artefatos são JSON de resumo e alertas agregados.

`resources.cpu_seconds` é o delta de user+system CPU do processo executor. Não inclui
processos filhos nem o processo servidor MLflow. `resources.rss_peak_bytes` é o maior
RSS medido no processo executor, em bytes, entre amostras inicial, final e amostras
com intervalo de 50 ms. Jobs curtos não recebem espera artificial; por isso o pico é
amostrado e pode não capturar picos entre leituras. `resources.duration_seconds` é
tempo monotônico do processo.

## Alertas e falhas

| Tipo | Condição | Severidade | Ação registrada |
|---|---|---|---|
| `rejection` | Contrato de lote rejeitado | warning | Corrigir lote e validar novamente |
| `feature_drift` | PSI categórico ou regra KS com Holm e D mínimo | warning | Investigar coleta, variáveis e desempenho supervisionado |
| `performance_degraded` | Aumento de Brier pareado supera o limiar configurado | critical | Investigar mudança de conceito e revisar desempenho supervisionado |

Cada evento de `feature_drift` inclui feature, janela, método, valor observado,
limiar e condição legível. Os eventos vão a `alerts.json`, ao log JSON e ao artefato
agregado do MLflow. Não
acionam Slack, e-mail ou webhook. Sem avaliação com labels, o estado supervisionado
é indisponível, não um resultado zero.

Se o servidor ficar indisponível, a operação ainda grava seus resultados locais e
emite erro operacional. Para recuperação, confira `make status`, execute
`make tracking-up` e repita o comando da operação. O artefato local contém o
diagnóstico agregado e não é promovido a sucesso de tracking.

## Relatório HTML

`make docker-report` consulta o MLflow pela rede interna, lê os relatórios locais e
gera `artifacts/runs/summary.json` e `artifacts/runs/index.html`. O HTML lista as runs,
os alertas, as métricas de dados/modelo/pipeline/recursos e links relativos para a
execução de drift e a avaliação dos cenários. A tabela compara a última janela de
stable, data_drift, concept_drift e invalid; métricas sem labels ou sem execução
aparecem como `Indisponível`. Se uma fonte ainda não existe ou está desatualizada,
a página também apresenta `Indisponível`.
O gráfico SVG conta os alertas da execução selecionada; amarelo representa warning,
vermelho representa critical e cinza representa tipo sem severidade conhecida.
Ausência de alertas é exibida como indisponível, não como barra de sucesso.

As capturas das execuções locais usadas na conferência visual estão em
`docs/evidencias/relatorio-observabilidade.png` e
`docs/evidencias/mlflow-observabilidade.png`.
