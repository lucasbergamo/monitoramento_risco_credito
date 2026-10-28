# Governança e privacidade

## Finalidade e base de dados

O sistema é uma demonstração acadêmica de validação, modelagem e monitoramento.
Não oferece crédito, não classifica solicitantes reais e não deve ser conectado a
um processo de concessão. O dataset Default of Credit Card Clients foi publicado
por Yeh em 2009 e representa clientes de cartão em Taiwan, com valores históricos
em NT$. A UCI informa licença CC BY 4.0. A atribuição, o link da licença e a
indicação das transformações são mantidos na documentação do dataset.

A licença do conjunto de dados não comprova consentimento, anonimização ou
autorização irrestrita para tratar dados pessoais. A documentação da UCI também
não comprova as condições da coleta original. O projeto não recebeu evidência de
consentimento dos titulares nem realizou teste formal de anonimização. IDs,
linhas, rótulos e predições individuais permanecem locais.

## Contexto jurídico

O art. 7º, IV, da Lei nº 13.709/2018 trata de estudos por órgão de pesquisa e
prevê anonimização sempre que possível. A lei define órgão de pesquisa no art. 5º,
XVIII. A finalidade acadêmica deste repositório não basta para afirmar que seu
autor, grupo ou instituição satisfaz a definição ou os requisitos dessa hipótese.
Este documento não escolhe nem certifica uma base legal para o tratamento
realizado; registra apenas finalidade, controles técnicos e limites conhecidos.

Proteção do crédito é uma hipótese distinta: o art. 7º, X, da LGPD a prevê para
tratamento necessário a essa finalidade. Em uma fintech hipotética, sua invocação
dependeria do tratamento real, dos princípios aplicáveis, da finalidade e da
necessidade. O art. 20 dispõe sobre o direito de solicitar revisão de decisões
tomadas unicamente com base em tratamento automatizado que afetem os interesses
do titular. Nada disso transforma o score acadêmico em decisão de concessão ou
comprova conformidade de uma futura operação.

## Inventário técnico do tratamento

| Campo ou conjunto | Uso implementado | Minimização e local |
|---|---|---|
| 19 variáveis financeiras | Treino, predição e monitoramento | Somente features declaradas pelo schema |
| `default_next_month` | Treino e avaliação supervisionada | Associado por chave após a predição |
| `record_id` | Chave de associação e integridade | Não é feature; arquivos individuais ficam locais |
| SEX, AGE, EDUCATION, MARRIAGE | Partição e diagnóstico agregado por grupo | Separados das features; sem publicação de linhas |
| Seeds, configurações e hashes | Reprodutibilidade | Manifestos agregados versionados |
| Logs operacionais | Estado, contagens e tipo de erro | Logger remove campos fora da lista permitida |
| Relatórios MLflow | Métricas, alertas e campanha | Artefatos passam pelo filtro de campos; não enviar lote individual |

O módulo de governança lê features, chaves e labels do teste por meio dos
carregadores existentes. Em outro fluxo, carrega AGE/SEX da tabela local de
auditoria e alinha a tabela ao teste por `record_id`. O estimador recebe somente
as 19 features financeiras. A publicação contém métricas agregadas, n,
denominadores, política de supressão, versões e hashes. Não publica IDs, scores,
features, labels ou subgrupos individuais.

## Acesso, retenção e descarte

O projeto foi desenhado para uso local. `data/`, `models/`, `artifacts/`, `state/`
e `.env` são ignorados pelo Git. Docker executa com UID/GID do host. Não há
autenticação multiusuário nem controle de acesso em nível de aplicação; o acesso
ao host e aos arquivos depende das permissões e controles administrados pelo
ambiente que executa o projeto. Essas propriedades não equivalem a certificação
de segurança.

O cache bruto e os dados derivados ficam locais até o aceite da entrega. Após
confirmação de arquivamento, a eliminação desses dados é manual. `scripts/retention.py`
lista, por padrão, somente diretórios de primeiro nível de `artifacts/runs` cujo
último arquivo foi modificado há mais de 30 dias. `--delete` é necessário para
excluir os candidatos e a contenção é revalidada. O script não toca em `data/`,
`models/`, `state/mlflow` ou evidências versionadas. A retenção automática do
banco e do artifact store do MLflow não está implementada; devem ser administrados
separadamente, sem apagar seus arquivos enquanto o serviço estiver ativo.

Os 30 dias são uma regra operacional local para snapshots de diagnóstico, não um
prazo da LGPD nem uma recomendação universal. Evidências agregadas revisadas
permanecem versionadas para explicar a entrega.

## Vieses, métricas e resposta

AGE e SEX são avaliados no teste original. Faixas: 21 a 34, 35 a 49 e 50+; categorias
de idade fora dessas faixas são reportadas se existirem. Não são inventados grupos
sem observações. Grupos com menos de 100 registros têm prevalência, recall, FPR e
Brier suprimidos. Recall também é suprimido com menos de 20 positivos; FPR, com
menos de 20 negativos. Cada razão disponível informa numerador e denominador.

O limiar 0,5 é demonstrativo. Diferenças observadas entre grupos não estabelecem
causalidade ou discriminação, e a ausência de diferenças não prova equidade.
Excluir atributos demográficos não elimina proxies. Mitigações futuras devem
começar por investigar origem e qualidade dos dados, suporte amostral e variáveis
correlacionadas; qualquer alteração de coleta, modelo ou limiar requer nova
avaliação e evidência, sem retreino automático.

## Fontes primárias

- [LGPD, Lei nº 13.709/2018, texto oficial consolidado](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm), em especial arts. 5º, XVIII, 7º, IV e X, e 20.
- [UCI Machine Learning Repository, Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default%2Bof%2Bcredit%2Bcard%2Bclients), DOI 10.24432/C55S3H.
- [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) e [texto da licença](https://creativecommons.org/licenses/by/4.0/legalcode).

As fontes foram consultadas em 28/10/2026. Esta documentação descreve o projeto
e não constitui parecer jurídico ou declaração de conformidade.
