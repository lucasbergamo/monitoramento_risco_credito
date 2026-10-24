# ADR 0001: Execução local reproduzível

Status: decisão adotada, fundação validada em Docker em 24/10/2026.

## Contexto

A avaliação precisa repetir a preparação e os testes sem instalação de Python ou
Poetry no computador do avaliador. Dados e modelos não devem acompanhar a imagem.

## Decisão

Usar Docker e Compose com Python 3.12, Poetry 2.5.1 e dependências resolvidas em
lockfile gerado pela ferramenta. Make é a interface pública. Imagens runtime e dev
compartilham a base e as dependências de produção; apenas dev inclui ferramentas
de qualidade e testes. O build exige o lock e nunca o regenera implicitamente.

O setup cria diretórios com o usuário do host. Containers usam o mesmo UID/GID e
não exigem sudo ou permissões abertas nos volumes. O serviço ci não monta estado
do host. Nenhuma porta é publicada nesta etapa.

## Consequências

A primeira resolução e o primeiro build exigem rede. O lock e a execução real dos
testes são condições para comprovar compatibilidade. A imagem base é fixada por
patch e digest verificado no pull, evitando alterações silenciosas da base Debian.
Isso não implica imagens finais idênticas byte a byte, pois o build inclui metadados
e a instalação do próprio Poetry tem transitivas fora do lock da aplicação.

Python/Poetry locais são opcionais e precisam respeitar as versões do projeto.
A instalação isolada do Poetry no Docker evita dependências globais no host.
O pipeline de negócio, os dados reais e o serviço de observabilidade serão
implementados nas etapas correspondentes.
