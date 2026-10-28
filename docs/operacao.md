# Runbooks operacionais

As ações abaixo pressupõem uma equipe que controla a execução do demonstrador.
No exercício acadêmico, os dados e cenários são locais e não acionam decisões de
crédito nem comunicações externas. Preservar manifestos e diagnósticos antes de
alterar dados, configuração ou modelo.

## Serviço e persistência

`make tracking-up` constrói e inicia o servidor MLflow em Docker Compose. A UI é
servida em `http://127.0.0.1:5000`; apenas o loopback do host recebe a porta. O
servidor usa SQLite em `state/mlflow/tracking.db` e serving de artefatos em
`artifacts/runs/`. O runner acessa `http://mlflow:5000` pela rede Compose. A URI
do host e a URI interna têm configurações independentes no `.env`.

O healthcheck consulta `/health`. `make status` apresenta containers e consulta a
URI do host. `make tracking-down` usa `stop`, sem remover volumes. Após subir de novo,
as runs são consultadas pelo cliente e pela UI. O UID/GID configurado precisa ter
acesso de escrita aos diretórios locais montados pelo Compose.

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
agregado do MLflow. Não acionam Slack, e-mail ou webhook. Sem avaliação com labels,
o estado supervisionado é indisponível, não um resultado zero.

Se o servidor ficar indisponível, a operação ainda grava seus resultados locais e
emite erro operacional. Para recuperação, confira `make status`, execute
`make tracking-up` e repita o comando da operação. O artefato local contém o
diagnóstico agregado e não é promovido a sucesso de tracking.

## Relatório HTML

`make docker-report` consulta o MLflow pela rede interna, lê os relatórios locais e
gera `artifacts/runs/summary.json` e `artifacts/runs/index.html`. O HTML lista runs,
alertas, métricas de dados/modelo/pipeline/recursos e links relativos para a execução
de drift e a avaliação dos cenários. A tabela compara stable, data_drift,
concept_drift e invalid; métricas sem labels ou sem execução aparecem como
indisponíveis. O gráfico SVG conta alertas da execução selecionada; warning e
critical têm cores distintas. Ausência de alertas aparece como indisponível, não
como barra de sucesso.

As capturas das execuções locais usadas na conferência visual estão em
`docs/evidencias/relatorio-observabilidade.png` e
`docs/evidencias/mlflow-observabilidade.png`.

## Lote rejeitado

**Responsável:** pessoa que mantém a ingestão; a equipe de dados investiga a origem.

1. Guardar o código de saída e o evento agregado `contract_rejected`.
2. Conferir schema, contagens por regra e versão do contrato. Não copiar linhas,
   valores ou IDs para logs ou tickets públicos.
3. Corrigir a extração na origem ou preparar novamente o lote; não relaxar regras
   para aceitar dados inesperados sem análise.
4. Reexecutar `make docker-validate` com features e chaves separadas. Confirmar
   rejeição antes de qualquer consumidor ou predição.
5. Se o contrato estiver errado para uma fonte aprovada, propor mudança com caso
   reproduzível e teste negativo. Não tratar falha de validação como incidente do
   modelo nem executar retreino.

## Alerta de drift

**Responsável:** operação de dados investiga aquisição, extração, schema e janela.

1. Registrar run, comparação, janela, feature, método, estatística, limite e n.
2. Verificar se a comparação é estável, pareada ou perturbada; PSI não é p-valor.
   Distinguir a flag do relatório do alerta operacional ajustado por Holm.
3. Comparar manifesto/hash, qualidade e comportamento da origem. Não publicar
   snapshot HTML sem inspeção; histogramas podem expor valores do dataset.
4. Corrigir primeiro coleta, transformação ou particionamento quando a falha
   estiver no pipeline. Repetir validação com a mesma política e registrar o
   resultado, inclusive falso alerta.
5. Sem labels válidos, registrar performance como indisponível. Drift isolado não
   autoriza retreino nem promoção.

## Degradação de performance

**Responsável:** governança/model risk revisa a evidência supervisionada; dados
confirma origem e integridade dos labels.

1. Confirmar associação de labels por ID, hashes, versão do modelo e período ou
   janela simulada. Distinguir label observado de label sintético.
2. Recalcular métricas no conjunto correto e verificar prevalência, denominadores
   e limiar. Comparar pares quando o desenho do experimento permitir.
3. Investigar mudança de população, qualidade do label, contrato, features e
   limites do simulador. Registrar explicações concorrentes.
4. Propor revisão do modelo somente após análise de dados e validação independente.
   Treino, avaliação e promoção continuam comandos explícitos e separados.
5. Não mudar seed, limiar ou gate para fazer a campanha passar; não usar o teste
   repetidamente para selecionar parâmetros.

## Falha operacional ou de tracking

**Responsável:** pessoa de operação do ambiente; engenharia corrige a falha técnica.

1. Registrar evento, etapa, código de saída e tipo da exceção. Os logs são
   intencionalmente limitados e não substituem o diagnóstico local.
2. Verificar daemon Docker, permissões UID/GID, espaço, configuração e saúde de
   MLflow, preservando volumes e diretórios existentes.
3. Conferir manifestos e artefatos locais. Tracking indisponível não equivale a
   campanha concluída; a execução deve ser retomada ou repetida conforme o estado.
4. Corrigir serviço, configuração ou código, adicionar regressão e reexecutar o
   aceite afetado. Não converter exceção em sucesso nem apagar estado para limpar
   uma falha.

## Revisão e descarte

`make docker-retention` lista candidatos com mais de 30 dias em `artifacts/runs`.
Inspecionar a lista antes de `make docker-retention DELETE=1`; o script só remove
diretórios diretos dessa área. Não executar limpeza de dados, modelos ou estado
MLflow neste runbook. O descarte dos dados de entrega ocorre manualmente após o
arquivamento confirmado.
