# Evidências selecionadas

## Proveniência e reprodução

A seleção final pertence à campanha `final20261029`. `campaign.json` identifica
as três runs de tracking, fingerprints de código, dados, modelo, configurações e
resultado. `publication_manifest.json` contém SHA-256 dos arquivos selecionados.
Não contém dados individuais nem os snapshots nativos do Evidently.

Para reproduzir, seguir integralmente o percurso Docker do README. Usar o novo
ID retornado por `docker-demo` nos comandos `docker-report` e
`docker-verify-evidence`; IDs de tracking mudam entre execuções. O hash de resultado
exclui identificadores e recursos variáveis. Não reutilizar um relatório antigo
para representar outra campanha.

| Arquivo | Conteúdo e origem |
|---|---|
| dataset_manifest.json | Schema, contagens e hashes da preparação verificada |
| baseline.json | Avaliação congelada de validação e teste, anterior aos cenários |
| scenarios.json | Agregados e bootstrap pareado copiados da campanha final |
| deteccao.json | Agregados do detector executado na campanha final |
| governanca.json | Diagnóstico descritivo por grupos no teste, mesmo modelo/dados |
| campaign.json | Identidade e aceite da campanha final |
| relatorio-observabilidade.png | Captura do sumário da campanha final |
| mlflow-observabilidade.png | Captura da run de detecção vinculada à campanha final |

Os artefatos de baseline e governança usam o mesmo modelo e manifesto de dados,
mas não são novas avaliações de produção. HTMLs Evidently, scores, labels,
parquet, modelos e banco permanecem ignorados. Os HTMLs foram inspecionados
localmente; histogramas podem revelar valores e não são selecionados para Git.
Imagens exigem revisão visual e JSON exige inspeção de conteúdo, além do scanner.

A checagem automática não certifica ausência de toda informação pessoal ou secret.
As autorias normais do histórico Git são metadados públicos intencionais; a
verificação de conteúdo não remove autores nem reescreve o histórico.
