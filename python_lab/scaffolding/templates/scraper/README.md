# __distribution__

Projeto Python com layout `src`, teste inicial e instalação editável.
A geração só copia arquivos. Execute os comandos abaixo quando quiser instalar,
testar e iniciar o projeto. As dependências são declaradas em `pyproject.toml`.
A instalação pode acessar o índice de pacotes; os testes e a funcionalidade
inicial não precisam de rede nem de chaves.

Execute a partir desta pasta (`__distribution__`).

## Linux / macOS

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m __package__.main tests/fixtures/page.html
```

## Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m __package__.main tests/fixtures/page.html
```

A CLI lê um arquivo HTML local como UTF-8 e imprime o primeiro título:
`Olá & Python` para a fixture incluída. Entidades HTML são decodificadas.
Importe `extract_title(html: str) -> str` de `__package__.main` para usar a função.
Quando não há título, o resultado é uma string vazia.
Não há fetch HTTP, API, credenciais nem dependências de runtime.
