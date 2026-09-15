# Python Lab v0.1 — Especificação de design

## 1. Visão do produto

Python Lab é um ambiente pessoal de prática deliberada que treina o usuário a compreender problemas, planejar soluções, implementar, testar, depurar e explicar software em Python. A primeira versão atende exclusivamente Lucas e valida o ciclo de aprendizagem antes de qualquer expansão para outros usuários.

O produto não mede conteúdo consumido. Ele registra competências demonstradas por meio de missões práticas.

## 2. Tripé central

### Goal — Onde quero chegar?

> Desenvolver competência demonstrável em Python, automação e integrações para conquistar uma oportunidade profissional, criando base para evoluir posteriormente até engenharia de IA.

O Goal será pessoal e fixo na v0.1, porém armazenado separadamente do motor para permitir metas configuráveis no futuro.

### Skills — O que preciso dominar?

O mapa completo poderá representar toda a trajetória profissional, mas a v0.1 ativará apenas as competências necessárias às cinco primeiras missões.

Pensamento e produto:

- compreensão do problema;
- identificação de entradas e saídas;
- decomposição;
- identificação de casos extremos;
- explicação técnica.

Python:

- funções;
- listas e dicionários;
- strings e validação de dados;
- arquivos;
- CSV e JSON;
- exceções.

Engenharia:

- debugging;
- testes com pytest;
- organização básica em módulos;
- leitura crítica de código gerado por IA.

SQL, APIs REST, Git aplicado, Selenium e sistemas com IA serão registrados como etapas futuras, mas não serão introduzidos superficialmente na v0.1.

### Missions — Que problemas demonstram essas habilidades?

Cada Mission será um problema contextualizado, com contrato verificável, testes automatizados, pistas progressivas e reflexão final. Uma missão somente será concluída quando houver planejamento, aprovação em todos os testes e explicação final.

## 3. Escopo

### Incluído na v0.1

- CLI local em Python;
- Goal pessoal fixo;
- mapa inicial de Skills;
- cinco Missions progressivas;
- planejamento obrigatório antes da implementação;
- testes automatizados com pytest;
- pistas progressivas pré-escritas;
- solução de referência liberada mediante confirmação;
- explicação final obrigatória;
- registro local de progresso e evidências;
- recomendação sequencial simples da próxima missão;
- apresentação com Rich.

### Fora da v0.1

- interface web ou editor embutido;
- autenticação, múltiplos usuários ou nuvem;
- banco de dados;
- geração automática de currículo ou missões;
- tutor conversacional com IA;
- gamificação;
- algoritmo adaptativo avançado;
- réplica completa das interfaces de Claude Code ou OpenCode.

## 4. Experiência principal

1. O usuário executa `python lab.py`.
2. A CLI mostra o Goal, a missão atual e o estado da sessão.
3. O Lab recomenda uma missão desbloqueada.
4. O usuário lê o problema e registra entrada, saída, etapas e possíveis erros.
5. O Lab informa o arquivo inicial, que será editado no VS Code.
6. O usuário executa os testes pela CLI.
7. Em caso de dificuldade, solicita pistas progressivas.
8. Quando todos os testes passam, registra uma explicação final.
9. O Lab conclui a missão e cria evidências para as Skills relacionadas.
10. A missão seguinte é desbloqueada.

## 5. Interface de linha de comando

A CLI terá um prompt contínuo inspirado na ergonomia de coding agents, sem implementar uma TUI complexa.

Comandos:

| Comando | Responsabilidade |
|---|---|
| `/goal` | Exibir objetivo e critérios de sucesso |
| `/skills` | Exibir mapa de competências e evidências |
| `/missions` | Listar missões e estados |
| `/start <id>` | Iniciar uma missão desbloqueada |
| `/plan` | Registrar ou revisar o planejamento |
| `/test` | Executar os testes da missão atual |
| `/hint` | Liberar a próxima pista |
| `/explain` | Registrar a explicação final |
| `/status` | Exibir estado da sessão |
| `/help` | Listar comandos disponíveis |
| `/exit` | Salvar e encerrar com segurança |

Rich será usado para painéis, tabelas, cores e mensagens. Cada comando terá um manipulador isolado, separando interface, regras de domínio e persistência.

## 6. Modelo de Skills

Não serão exibidos percentuais de domínio. Cada Skill terá um estado sustentado por evidências:

| Estado | Definição |
|---|---|
| Não avaliada | Ainda não apareceu em uma missão concluída |
| Em prática | Foi utilizada, mas houve dificuldade ou consulta à solução |
| Demonstrada | Foi aplicada corretamente sem solução pronta |
| Consolidada | Foi demonstrada novamente em contexto diferente |

Usar pistas não representa fracasso. Entretanto, consultar a solução de referência impede que a tentativa atual marque a Skill como demonstrada.

Cada evidência registrará no mínimo:

- identificador da Skill;
- identificador da Mission;
- estado produzido;
- maior nível de ajuda utilizado;
- resultado dos testes;
- conclusão da reflexão;
- data e hora.

## 7. Sistema de ajuda

As pistas serão pré-escritas e liberadas em sequência:

1. pergunta de investigação;
2. pista conceitual;
3. orientação mais específica;
4. pseudocódigo;
5. solução de referência.

A primeira tentativa ocorre sem ajuda. A solução de referência exige confirmação explícita e sua consulta é registrada.

## 8. Catálogo inicial de Missions

| ID | Missão | Problema | Skills principais |
|---|---|---|---|
| 001 | Consolidar falhas | Somar indisponibilidade por equipamento e identificar o mais crítico | funções, loops, dicionários, decomposição |
| 002 | Limpar relatório CSV | Ler registros, rejeitar linhas inválidas e produzir um resumo confiável | arquivos, CSV, validação, exceções |
| 003 | Validar inventário JSON | Verificar campos obrigatórios e separar equipamentos válidos dos inconsistentes | JSON, coleções, validação, casos extremos |
| 004 | Recuperar script defeituoso | Investigar código existente que falha em casos específicos | leitura de código, debugging, pytest, julgamento sobre IA |
| 005 | Gerar relatório operacional | Integrar as capacidades anteriores em um programa modular | decomposição, CSV/JSON, exceções, testes, módulos |

A Mission 005 será integradora e não introduzirá tecnologia nova.

## 9. Estrutura proposta

```text
python-lab/
├── lab.py
├── pyproject.toml
├── python_lab/
│   ├── cli.py
│   ├── commands/
│   ├── domain/
│   ├── services/
│   └── storage/
├── data/
│   ├── goal.json
│   ├── skills.json
│   └── progress.json
├── missions/
│   ├── 001-consolidar-falhas/
│   │   ├── mission.json
│   │   ├── README.md
│   │   ├── starter.py
│   │   ├── data/
│   │   ├── tests/
│   │   ├── hints.json
│   │   └── reference_solution.py
│   └── ...
└── tests/
```

Os arquivos JSON descrevem Goal, Skills, metadados das Missions e progresso. O motor Python interpreta esses dados; adicionar conteúdo não deve exigir alterar as regras centrais.

## 10. Recomendação e progressão

O algoritmo da v0.1 será determinístico:

1. recomendar a missão já iniciada e incompleta;
2. caso não exista, recomendar a primeira missão desbloqueada e não concluída;
3. considerar todas concluídas quando não houver outra missão elegível.

Não haverá adaptação automática baseada em IA nesta versão.

## 11. Persistência e erros

- O progresso será salvo em JSON local.
- A gravação usará arquivo temporário e substituição atômica.
- JSON inválido produzirá mensagem acionável e não será sobrescrito automaticamente.
- Falhas dos testes serão apresentadas sem encerrar a CLI.
- Missões inexistentes ou bloqueadas gerarão mensagens claras.
- Interrupção por teclado preservará o último estado confirmado.
- A conclusão será rejeitada enquanto planejamento, testes ou explicação estiverem pendentes.

## 12. Estratégia de testes

Testes do motor verificarão:

- leitura e validação dos arquivos JSON;
- seleção da próxima missão;
- pré-requisitos e desbloqueio;
- progressão das pistas;
- execução e interpretação do pytest;
- regras de conclusão;
- geração de evidências;
- persistência e recuperação do progresso;
- comportamento dos comandos da CLI.

Cada Mission terá testes próprios, cobrindo caminho principal e casos extremos. A solução de referência deverá passar integralmente nesses testes.

## 13. Critérios de aceite técnico

A v0.1 estará pronta quando:

- os comandos essenciais funcionarem;
- as cinco Missions puderem ser percorridas do início ao fim;
- o progresso sobreviver ao reinício da aplicação;
- nenhuma missão puder ser concluída sem plano, testes e explicação;
- a consulta à solução afetar corretamente as evidências;
- todos os testes do Lab e das soluções de referência estiverem verdes.

## 14. Validação do produto

A implementação pronta não valida o produto. O teste inicial será:

> Realizar pelo menos cinco sessões, concluir as cinco Missions e comparar a autonomia obtida com o estudo direto no Cursor.

Serão observados:

- missões concluídas;
- tentativas por missão;
- maior nível de ajuda utilizado;
- erros recorrentes;
- qualidade das explicações;
- reaplicação de uma Skill em novo contexto;
- disposição real de retornar para outra sessão.

## 15. Evolução prevista

### v0.2 — CLI polida

- melhor ergonomia visual;
- navegação e atalhos mais fluidos;
- histórico de sessão;
- mensagens e feedback mais refinados;
- inspiração em Claude Code e OpenCode sem copiar complexidade desnecessária.

### Integração futura com ai-tutor

A `ai-tutor` poderá atuar como camada pedagógica sobre o motor do Python Lab para:

- gerar perguntas socráticas contextualizadas;
- adaptar pistas ao histórico de tentativas;
- avaliar a clareza da explicação final;
- recomendar revisões espaçadas;
- propor variações de uma Mission em outro contexto.

Essa integração deverá consumir os contratos de Goal, Skills, Missions e evidências sem substituir as regras determinísticas do núcleo. Ela só será considerada depois da validação da v0.1.

### Possível interface web

Uma versão web somente será construída se o uso revelar necessidades concretas que a CLI não atende. A CLI pode permanecer como interface principal do produto.
