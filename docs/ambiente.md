# Ambiente e compatibilidade

## Contrato preparado

Python 3.12.15, Poetry 2.5.1 e imagem `python:3.12.15-slim-bookworm`, fixada por digest.
O patch consta na [fonte oficial da imagem Python](https://github.com/docker-library/python/blob/master/3.12/slim-bookworm/Dockerfile)
e no [catálogo Docker Hub](https://hub.docker.com/_/python). Consulta documental
em 24/10/2026. Pull e build verificados em linux/amd64. Digest usado no Dockerfile:
`sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70`.

Dependências principais fixadas no `pyproject.toml`: scikit-learn 1.9.1,
Pandera 0.34.1, Evidently 0.7.23, MLflow 3.16.1, pandas 2.3.3,
NumPy 2.2.6 e SciPy 1.15.3. Complementos e transitivas congelados pelo
`poetry.lock` gerado com `make lock`, 148 pacotes. Ferramentas resolvidas:
pytest 9.1.1, pytest-cov 7.1.0 e Ruff 0.17.2. Não houve mudança dos pins principais.

## O que os testes verificam

`tests/test_environment.py` usa fixtures próprias, seed 42 e bibliotecas reais:

1. Confere Python e pins, além das importações complementares.
2. Valida DataFrame com Pandera e agrega duas violações independentes com `lazy=True`.
3. Treina HistGradientBoostingClassifier e confere probabilidades finitas e sinal aprendido.
4. Executa Evidently, exporta HTML/JSON e verifica os arquivos gerados.
5. Cria experimento, run, parâmetro, métrica e artefatos MLflow em SQLite temporário.
6. Recupera run com novo cliente e compara bytes dos dois artefatos baixados.

Não há mocks dessas bibliotecas, download de dataset ou autolog de dados individuais.
O tracking embutido e o teste HTTP usam runs reais. UI e persistência do serviço
Compose também integram o percurso executável descrito no README.

As chamadas seguem [Report](https://docs.evidentlyai.com/docs/library/report),
[exportação de resultados](https://docs.evidentlyai.com/docs/library/output_formats)
e [API MLflow](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.client.html).
Documentação consultada não comprova compatibilidade da instalação conjunta.

`tests/test_utils.py` verifica precedência de configuração, caminhos independentes
do diretório corrente, erros de validação, descarte de campos sensíveis em logs e
repetição de geradores aleatórios. Limites de threads e PYTHONHASHSEED são definidos
antes do processo nos containers. No percurso local opcional, o chamador deve
defini-los se precisar da mesma limitação operacional.

## Histórico da primeira preparação, 24/10/2026

- Host disponível: Python 3.11.9 e Poetry 2.4.1. Não atendem ao ambiente do projeto.
- `docker info`: acesso negado ao socket do daemon na preparação inicial.
- Acesso ao PyPI no shell: falha de resolução DNS.
- Acesso à API GitHub no shell: falha de conexão.
- Naquele momento, lock, build e prova conjunta ficaram pendentes.

Os checks iniciais do host eram diagnósticos parciais. Após habilitar rede e acesso
ao Docker, o percurso containerizado foi executado com os resultados abaixo.

## Validação em Docker, 24/10/2026

Docker Engine 29.4.3, Compose 5.1.3, Linux amd64, UID/GID 1000:1000.
Poetry foi instalado somente no container de ferramentas, sem instalação global no host.

| Verificação | Resultado observado |
|---|---|
| `make setup` | Passou; reexecução preservou .env e diretórios com modo 755 |
| `make lock` | Passou; lock gerado com Poetry 2.5.1 e Python 3.12.15 |
| `make build` | Passou para imagens dev e runtime |
| `make docker-lint` | Ruff e formatação aprovados na imagem dev |
| `make docker-test` | 31 aprovados em 22,82 s; cobertura 100% dos utilitários atuais |
| `docker run --rm monitoramento-risco-credito:runtime` | Log JSON foundation_ready, seed 42, saída 0 |
| `python -m pip check` no runtime | No broken requirements found |
| Runner com bind mount de artifacts | Arquivo temporário criado e removido com UID/GID 1000:1000 |
| Runtime com SEED=-1 | Saída 1 e ValidationError legível, sem repetir valor de entrada |

O teste integrado gerou HTML/JSON reais, persistiu run/métrica/parâmetro/artefatos
MLflow em SQLite temporário e recuperou os dois arquivos com novo cliente, com
igualdade de bytes. Os arquivos de teste não são evidências de dados reais de crédito.

Houve 12 warnings de dependências (Evidently/NumPy, Litestar e SQLAlchemy/MLflow).
Não foram ocultados nem transformados em falhas ignoradas. Não impediram os testes;
o uso das APIs do projeto passou com as versões fixadas. Os testes não comprovam
APIs de negócio ainda não implementadas nem substituem futura validação em outra máquina.
O caminho Poetry local não foi validado porque o host disponível usa Python 3.11.9.
