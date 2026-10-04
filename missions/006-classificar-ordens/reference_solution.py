def classificar_ordem(ordem: dict) -> str:
    itens = ordem.get("itens")
    if not itens:
        raise ValueError("A ordem precisa de pelo menos um item")
    primeiro = itens[0]
    if primeiro.get("bloqueado"):
        return "bloqueada"
    tipo = ordem.get("tipo")
    prioridade = ordem.get("prioridade")
    if tipo == "falha" and prioridade == "urgente":
        return "emergencia"
    if tipo == "falha":
        return "corretiva"
    if tipo == "preventiva":
        return "preventiva"
    return "administrativa"
