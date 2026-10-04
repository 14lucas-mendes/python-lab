def test_ler_historico_separa_hash_e_mensagem(solution):
    texto = "a1b2c3d feat: consolidar falhas\ne4f5g6h fix: guardar lista vazia\n"
    assert solution.ler_historico(texto) == [
        {"hash": "a1b2c3d", "mensagem": "feat: consolidar falhas"},
        {"hash": "e4f5g6h", "mensagem": "fix: guardar lista vazia"},
    ]


def test_linhas_em_branco_sao_ignoradas(solution):
    texto = "\na1b2c3d feat: um\n\n  \ne4f5g6h fix: dois\n"
    commits = solution.ler_historico(texto)
    assert [item["hash"] for item in commits] == ["a1b2c3d", "e4f5g6h"]


def test_contar_prefixos_soma_conhecidos(solution, git_log):
    commits = solution.ler_historico(git_log)
    assert solution.contar_prefixos(commits) == {
        "feat": 2,
        "fix": 1,
        "docs": 1,
        "chore": 1,
    }


def test_mensagem_sem_dois_pontos_nao_entra_na_contagem(solution):
    commits = [{"hash": "abc", "mensagem": "ajuste de nomenclatura"}]
    assert solution.contar_prefixos(commits) == {}
