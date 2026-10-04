def ler_historico(texto: str) -> list[dict]:
    """Leia git log --oneline e devolva [{hash, mensagem}, ...]."""
    raise NotImplementedError("Implemente ler_historico")


def contar_prefixos(commits: list[dict]) -> dict[str, int]:
    """Some commits cuja mensagem começa com prefixo:."""
    raise NotImplementedError("Implemente contar_prefixos")
