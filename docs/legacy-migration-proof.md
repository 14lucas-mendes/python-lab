# Prova de migração de estado legado populado

`tests/fixtures/legacy-populated` contém dados representativos gerados pelo próprio
aplicativo legado, não por montagem manual de JSON nem por um perfil pessoal.
A origem é o objeto Git local confiável
`d7a890458ec072aee7ee6ab17d2d24a621f9de2a`. A geração exportou esse objeto com
`git archive` para um `TemporaryDirectory` privado, sem checkout/worktree/reset,
e confirmou que `python_lab.cli.__file__` apontava para esse snapshot antes de
invocar `python <snapshot>/lab.py --classic` duas vezes. `PYTHONPATH` foi removido
somente do ambiente desses subprocessos para evitar importar o checkout atual.

Entrada da primeira sessão:

```text
/start 001
/plan
records
totals
accumulate
empty input
/test
/hint
/status
/exit
```

Entrada da segunda sessão:

```text
/hint
/status
/exit
```

O aplicativo escreveu um progresso com missão 001 iniciada, plano, uma tentativa
real que falhou nos seis testes do starter original e duas pistas; escreveu
também duas sessões fechadas com nove eventos. Nenhuma missão foi declarada
concluída. Os bytes de todos os arquivos Python de missões, inclusive soluções de
referência e learner files, foram iguais antes/depois. Os JSON do fixture são
cópias byte a byte dessas escritas; `provenance.json` registra comandos e SHA-256.
Datas, IDs e caminhos temporários foram mantidos como o legado os escreveu.
Repetir a geração terá outras datas/IDs/caminhos e, portanto, outros hashes.
Não é necessário ter o histórico Git completo para executar a prova no CI.
O atributo Git `-text` é restrito aos JSON desse fixture: impede que um checkout
Windows com `core.autocrlf=true` altere seus bytes e invalide os hashes de origem.

A partir do checkout instalado:

```bash
python scripts/populated_migration_smoke.py --metadata /tmp/migration-proof.json
python scripts/populated_migration_smoke.py --cli .venv/bin/lab
```

No Windows, use `.venv/Scripts/lab.exe` para `--cli`. A prova opera somente em
cópias temporárias, invoca a CLI atual duas vezes e compara todos os campos do
progresso com o legado mais as inferências documentadas (`max_assistance_level=2`,
`attempt_id=legacy:001`). Compara exatamente as sessões/eventos, verifica bytes
dos backups, integridade/chaves estrangeiras SQLite, marcador de importação e
igualdade de todas as linhas/revisões na segunda execução. Também confirma que
os hashes de entrada permanecem iguais. O CI executa o comando com o `lab`
instalado em Ubuntu/Windows × Python 3.11/3.12 e retém log limitado e JSON de
contagens/hashes/resultados junto aos diagnósticos/JUnit existentes. Não retém
os diretórios de estado.

Para conferir um perfil legado preservado localmente, inclusive sem missões:

```bash
python scripts/populated_migration_smoke.py --source /caminho/legado --allow-empty-progress
```

O perfil deve ter `progress.json` e `sessions.json`, ao menos duas sessões e
histórico não vazio. A saída contém somente contagens, hashes e resultado; não
publique os JSON pessoais. O perfil preservado desta sessão foi conferido por
esse caminho com zero missões, duas sessões e cinco eventos. Esse resultado
valida seu histórico real e não substitui a prova populada representativa.

Limites: o fixture exercita uma missão iniciada e pistas, não missão concluída,
referência consultada, retenção de histórico extenso ou mesclagem com banco já
populado. Esses casos permanecem cobertos pelos testes específicos de estado e
migração; o comando recusa divergências de hashes no fixture com proveniência.
