# Reprodutibilidade da campanha final

Campanha selecionada: `final20261029`, executada em Docker em 29/10/2026.
Identificadores e fingerprint do código estão em
[evidências](evidencias/campaign.json); hashes dos arquivos selecionados em
[manifesto de publicação](evidencias/publication_manifest.json).
O percurso completo está no README. A seleção mantém dados, modelo e configurações
identificados; recursos e IDs de execução variam entre campanhas.

A campanha gera seis janelas stable, seis data_drift, seis concept_drift e uma
entrada inválida. A rejeição ocorre antes de inferência; não há scores inválidos.
Data_drift não recebe performance com rótulos originais. A detecção realiza
23 comparações e a verificação confere hashes, versões e associação ao MLflow.
Os HTMLs e as imagens são da mesma campanha, sem combinar runs por timestamps.

Verificações finais: build, lint e smoke aprovados; 155 testes aprovados em
255,13 s, cobertura 90% e 12 warnings conhecidos. Checagem de publicação aprovada
no conteúdo atual, index e histórico; oito hashes da seleção conferidos.

As duas campanhas históricas abaixo permanecem como evidência complementar.
A seleção final não afirma uma nova validação manual em outro computador.
Vídeo, ensaio humano e execução independente permanecem pendentes.

# Campanhas históricas de integração

## Ambiente e identificadores

A campanha foi executada em Docker com Python 3.12.15, Docker 29.4.3 e Compose
5.1.3. O código está identificado pelo fingerprint SHA-256 registrado em
[`evidencias/campaign.json`](evidencias/campaign.json), junto dos hashes do
manifesto de dados, modelo, cenários e quatro configurações efetivas.

Duas campanhas completas foram executadas com tracking MLflow ativo. Cada uma
produziu três runs associadas explicitamente à campanha e os mesmos quatro tipos
de cenário: seis janelas `stable`, uma entrada `invalid`, seis janelas
`data_drift` e seis `concept_drift`. Os dois gates passaram. A entrada inválida
foi rejeitada pelo contrato, sem artefato de scores. Labels de `data_drift`
permaneceram indisponíveis. A detecção concluiu 23 comparações.

As duas campanhas têm o mesmo `result_hash`:

`6f5c2c8793d9740aa88d0cae6f4b91fdfad5d361dbf6bd79f0fa829ef734f216`

O hash considera resultados determinísticos e exclui IDs de execução, chaves de
alerta e timestamps. Os IDs de campanha e tracking diferem e as evidências das
duas execuções coexistem. `verify-evidence` confirmou hashes locais, resultados,
integridade da versão imutável dos cenários e associação das runs à respectiva
campanha. O relatório HTML foi gerado para cada campanha por ID explícito.

## Tempo e recursos observados

Na segunda execução, `make docker-demo` levou 51,91 segundos de parede, incluindo
a invocação do Compose. Essa medição pertence a este host, execução e conjunto de
dados; não é promessa de desempenho em outros ambientes.

## Verificações

- `make build`, `make docker-lint` e smoke do runtime aprovados.
- Suíte completa em container CI, sem montar dados, modelos ou estado locais:
  147 testes aprovados, cobertura total de 90% e 12 warnings conhecidos de
  dependências.
- Integração com o serviço MLflow temporário aprovada, usando runs e artefatos
  reais; o serviço foi encerrado sem remover banco ou volumes.
- Relatórios e evidências de ambas as campanhas verificados por seus IDs, sem
  consultar timestamps ou resultados anteriores como substitutos.

Os cenários de drift e os labels de `concept_drift` são simulados. Os resultados
não representam desempenho econômico real nem validam uma política de crédito.
