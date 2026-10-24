# Reprodução do percurso inicial

Data: 24/10/2026. Commit verificado:
`798fc7adf7493aec4a0e0b3e16b9734e535e8af9`.

## Resultado e alcance

O percurso Docker do [README](../README.md) passou em um clone novo no mesmo
computador de desenvolvimento. Esse resultado é complementar: o daemon Docker já
continha imagens e cache de build, e etapas de instalação foram reutilizadas.
Não constitui validação em máquina limpa nem prova de instalação das dependências
a partir de um ambiente sem cache.

O clone foi obtido do remoto, sem copiar .env, dados, modelos, volumes de aplicação
ou banco do checkout anterior. A primeira preparação dos dados usou download da
UCI. O produto foi executado somente pelos comandos Docker documentados, sem
instalação de Python ou Poetry no host para atender ao percurso.

## Ambiente

Ubuntu 24.04.4 LTS em WSL2, kernel Linux 6.6.114.1-microsoft-standard-WSL2,
arquitetura x86_64; Docker Desktop/Engine 29.4.3 e Compose 5.1.3.
18 processadores lógicos visíveis e aproximadamente 9,7 GiB de memória no ambiente.
Artefatos acessíveis ao usuário do host, diretórios locais com modo 755.

## Comandos e resultados

Tempos de parede aproximados, incluindo a inicialização dos containers.
Não representam benchmark de uma instalação sem cache.

| Comando | Resultado | Segundos |
|---|---|---:|
| `make help` | Aprovado | 0.019 |
| `make setup` | Aprovado | 0.018 |
| `make setup` | Aprovado na reexecução | 0.008 |
| `make build` | Aprovado | 5.104 |
| `make docker-lint` | Aprovado | 3.162 |
| `make docker-test` | Aprovado | 285.860 |
| `docker run --rm monitoramento-risco-credito:runtime` | Aprovado | 3.534 |
| `make docker-data` | Aprovado | 47.008 |
| `make docker-data` | Aprovado na reexecução | 33.366 |
| `make docker-inspect-data` | Aprovado | 8.234 |

A suíte aprovou 56 testes, com cobertura de 97% de src e 12 warnings de
bibliotecas, sem falhas. O smoke do runtime emitiu foundation_ready com seed 42.
A reexecução de setup preservou o .env. Não houve ajuste manual de permissões,
instalação complementar de dependências ou alteração de código para completar o percurso.

## Dados e idempotência

Foram preparados 30.000 registros, 19 features financeiras e partições de
15.000/4.500/4.500/6.000 registros. Referência de 5.000 linhas do treino e seis
janelas completas de produção. O manifesto da execução corresponde byte a byte
ao manifesto versionado do commit verificado.

A segunda execução preservou o manifesto completo e todos os arquivos de dados,
conferidos por SHA-256. A inspeção documentada verificou os 40 hashes do manifesto.

- ZIP: `56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602`.
- XLS: `30c6be3abd8dcfd3e6096c828bad8c2f011238620f5369220bd60cfc82700933`.
- Split: `5944bc866b7711ccb61ed4f8b32e2531e5665a458929eac14d0c9db9de3b26db`.

Nenhum identificador ou registro individual compõe este relato. Os arquivos
individuais permanecem no clone temporário local, ignorados pelo Git.

## Verificações pendentes

A validação manual final será realizada em outro notebook após a implementação
completa, seguindo exclusivamente todo o README. Registrar o ambiente e eventuais
dependências existentes; não copiar .env, dados, modelos, banco ou volumes do
ambiente de desenvolvimento. Incluir download, reexecução dos dados e todos os
passos de treino, operação e relatórios que estiverem documentados na versão final.
Essa validação permanece pendente.

O README desta versão não produz relatório visual persistente para inspeção
manual. A geração de HTML/JSON Evidently foi exercitada pelos testes de integração;
não foi realizada inspeção manual de HTML temporário de teste em navegador.
