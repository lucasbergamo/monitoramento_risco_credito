# ADR 0005: drift por feature e decisão operacional

Estado: implementado, verificação de execução registrada em [métricas](../metricas.md).

## Problema e decisão

A comparação de distribuições precisa manter métodos, tipos e limites explícitos.
Usar Evidently 0.7.23 com `Report`, `ValueDrift`, `Dataset` e `DataDefinition`.
PAY é categórico, mesmo quando armazenado como inteiro. As outras 13 features
financeiras são numéricas. O preditor mantém sua representação ordinal de PAY.
Não inserir ID, alvo, scores, U, r, demografia ou índice da janela no detector.

PSI com limite 0,25 nas seis PAY; KS bilateral com p <0,01 nas 13 numéricas.
O relatório da biblioteca e a decisão operacional são campos separados.
Para numéricas, exigir p ajustado por Holm <0,01 e D >=0,10. A família contém
todas as 13 features numéricas da comparação, inclusive constantes. Para PAY,
o alerta operacional coincide com PSI >=0,25. Não corrigir PSI como p-valor.

`configs/monitoring.yaml` é estrito e não aceita alteração implícita pelo ambiente.
Exigir ao menos 20 observações em cada conjunto é uma proteção de execução,
sem garantia de poder estatístico. Amostra insuficiente retorna erro explícito,
sem registrar ausência de drift. Dados financeiros inválidos são rejeitados.

## API, persistência e privacidade

O snapshot retornado por `Report.run` gera HTML e JSON. A extração percorre
`metrics` e valida `config.type`, `column`, `method` e `threshold`. Não depende
de índices, nomes visuais ou IDs opacos. Mudança incompatível de schema falha
explicitamente. O KS adicional do SciPy verifica o p bruto do Evidently e fornece D.

Cada chamada da CLI cria UUID e diretório novo em `artifacts/runs/`, com snapshots,
saída normalizada, `summary.json` e `alerts.json`. Evidências anteriores permanecem.
Eventos têm severidade warning e ação de investigação, deduplicados por execução,
janela, tipo e feature. Nova execução produz novos eventos. Não há envio externo
nem mudança automática de modelo.

Os snapshots ficam ignorados pelo Git. Somente uma seleção agregada revisada pode
ser publicada em `docs/evidencias/`. Histogramas podem revelar valores observados
mesmo sem IDs; excluir colunas pessoais não comprova anonimização do HTML.

## Controles e limitações

Executar referência idêntica, quatro janelas completas de validação, referência
versus controle/perturbação de produção e controle versus concept pareados.
Amostras de validação seguem a ordem congelada e tamanho 1.000; o restante é
registrado. Contar falsos alertas sem ajustar limites automaticamente. Nenhuma
ausência de alerta prova igualdade. Comparações repetidas e PAY não recebem
correção global: Holm controla somente a família numérica de uma janela.

Features idênticas em concept não demonstram estabilidade de P(Y|X). O diagnóstico
supervisionado permanece no avaliador de labels. Não reutilizar os labels originais
após perturbar X.

Alternativas: métodos automáticos da biblioteca mudariam com tamanho/tipo; um único
limite sobre p bruto ignoraria magnitude e múltiplos testes. Escolher apenas as duas
features simuladas esconderia mudanças nas demais. O adaptador compara as 19.

Fontes: [Report](https://docs.evidentlyai.com/docs/library/report),
[customização de drift](https://docs.evidentlyai.com/metrics/customize_data_drift).
Assinaturas e regra de zeros PSI conferidas também no código instalado da versão fixada.
