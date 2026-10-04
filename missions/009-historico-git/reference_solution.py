def ler_historico(texto: str) -> list[dict]:
    commits = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        hash_curto, mensagem = linha.split(" ", 1)
        commits.append({"hash": hash_curto, "mensagem": mensagem})
    return commits


def contar_prefixos(commits: list[dict]) -> dict[str, int]:
    totais: dict[str, int] = {}
    for commit in commits:
        mensagem = commit["mensagem"]
        if ":" not in mensagem:
            continue
        prefixo = mensagem.split(":", 1)[0].strip()
        if not prefixo or " " in prefixo:
            continue
        totais[prefixo] = totais.get(prefixo, 0) + 1
    return totais
