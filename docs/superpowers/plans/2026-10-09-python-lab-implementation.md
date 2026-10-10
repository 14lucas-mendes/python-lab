# Python Lab Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement the selected subplan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not start all subplans simultaneously.

**Goal:** Evoluir o Lab para assistente local de programação e tutor, preservando as missões existentes.

**Architecture:** CLI e TUI compartilham comandos e serviços. Ferramentas locais produzem evidências; IA opcional produz explicações/propostas, sem executar comandos nem aprovar competências. SQLite guarda estado fora do checkout.

**Tech Stack:** Python >=3.11, Rich, Textual, pytest, sqlite3, argparse, asyncio; extras futuros de SDK OpenAI e ferramentas locais.

**Spec:** [Especificação de produto e contratos](../specs/2026-10-09-python-lab-assistant-design.md).

## Global Constraints

- Python >=3.11; manter rich>=13.7,<15, textual>=0.80,<1 e pytest>=8,<9 na base.
- CLI/TUI local primeiro; preservar lab, python-lab, lab --classic e comandos de missões.
- Dados fora do checkout; migração preserva JSON original e mantém backup.
- IA opcional; testes de provedor sem rede/credenciais.
- Patch exige confirmação e conferência de hash; testes executados são a fonte da verificação.
- Resposta gerada não demonstra competência automaticamente.

## Review Focus

1. Duas instâncias e legado inválido: conflito/migração preservam dados (A1/A2).
2. Entrada vazia, gravação falha e cancelamento: interfaces continuam utilizáveis (A3/A4/B5).
3. Arquivos ignorados, symlinks e limites: contexto permanece selecionado e delimitado (B1).
4. Provider indisponível ou resposta inválida: nada é aplicado/aprovado e modo local continua (B3/B4).
5. Arquivo mudou após sugestão e ajuda completa: patch rejeitado/evidência assistida (C1/D1).

---

## Sequência de entregas

| Release proposta | Plano | Resultado independente | Dependência |
| --- | --- | --- | --- |
| Base de 0.4 | [A — Base confiável](2026-10-09-python-lab-foundation.md) | Persistência, migração, interfaces e runner confiáveis | Commit c6c9fd7; relatório da PR #3 |
| MVP 0.4 | [B — Assistente/tutor](2026-10-09-python-lab-assistant-mvp.md) | Abrir projeto, explicar código, diagnosticar erro; ferramentas locais disponíveis | A completo |
| 0.5 | [C — Revisão e projetos](2026-10-09-python-lab-review-scaffolding.md) | Revisão, patches verificados, templates CLI/FastAPI | B completo |
| 0.6 | [D — Aprendizado e catálogo ampliado](2026-10-09-python-lab-learning.md) | Assistência registrada, recomendações, exercícios revisados, outros templates | C completo |

Versões indicam ordem proposta; não são compromissos de prazo. Separar PRs por tarefa revisável; só iniciar entrega seguinte depois dos aceites da anterior. Cada plano lista arquivos, interfaces, testes RED/GREEN e commits. Estimar calendário depois de executar A e medir o tamanho real da migração.

## Critérios para lançar o MVP

- [ ] A1–A5 e B1–B5 concluídos e revisados.
- [ ] Cobertura dos 123 comportamentos existentes preservada; referências das 11 missões e jornadas 001/006 passam.
- [ ] Ubuntu/Windows, Python 3.11/3.12 e venv sem extra assistant validados.
- [ ] Testes de corrupção, concorrência, descendentes, cancelamento e falha de rede do provider passam.
- [ ] Diagnose/explain funcionam na CLI e TUI com provider simulado; smoke manual separado com provider real.
- [ ] README diferencia capacidade disponível, sugestão de IA e resultado verificado.

## Execução e revisão

O ambiente cloud já é isolado: usar o checkout existente e uma branch por entrega; não criar worktree sem pedido explícito. Criar branch de implementação a partir do commit que contém os planos e a base acordada, preservando qualquer trabalho local. O plano não autoriza merge, publicação ou distribuição automática.

Recomendação: execução sequencial, com revisão independente ao final de cada entrega. A base e os contratos têm dependências fortes; execução simultânea de tarefas adjacentes aumenta risco de migração/incompatibilidade. Se forem usados subagentes, atribuir uma tarefa com interfaces estabilizadas e revisar antes da seguinte.

Não existem alterações de produto nesta entrega de planejamento. Decisões propostas a revisar antes de executar: SQLite, OpenAI como primeiro adapter, limites de contexto e registro de assistência. Configuração do modelo/chave é pré-requisito somente do smoke de IA real; não bloqueia testes offline nem a base.
