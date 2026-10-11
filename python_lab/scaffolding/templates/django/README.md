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
.venv/bin/python -m __package__.main
```

## Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m __package__.main
```

O servidor local em `127.0.0.1:8000` expõe `GET /health` com status 200 e JSON
`{"status": "ok"}`. O teste usa o cliente Django em memória, sem HTTP externo.
Não há banco de dados nem credenciais a configurar.
`DEBUG` e `SECRET_KEY` em `settings.py` são apenas para desenvolvimento local;
configure segurança e uma chave própria antes de publicar o projeto.
