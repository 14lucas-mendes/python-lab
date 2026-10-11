# Tutor release scenarios

Deterministic checks exercise local code and fake providers without model calls.
They establish adapter behavior and Python/pytest diagnostics. They do not measure
real model quality or teaching effectiveness.

## Deterministic evidence

Command from the editable checkout:

```sh
.venv/bin/python -m pytest tests/test_learning_cli.py::test_deterministic_tutor_scenarios -o addopts= -q
.venv/bin/python -m pytest tests/test_learning_cli.py tests/test_learning_tui.py -o addopts= -q
```

The six diagnostic scenarios each write isolated learner code and a test contract,
then execute the actual public `run_tests` service and pytest. Each must report a
failed test run, return code 1, and the specified diagnostic. Six cases passed in
the recorded local evaluation run (Linux Python 3.12). These failures are expected
learner evidence, rather than six failed release tests.

| Scenario | Learner trigger | Observed deterministic evidence |
|---|---|---|
| Syntax | `def value(:` | `SyntaxError`; invalid source fails fixture loading |
| Names | Return `missing_name` | `NameError` in the test call |
| Types | Return `"2" + 1` | Runtime `TypeError`; this is not static type checking |
| Import | Import a deliberately nonexistent module | `ModuleNotFoundError` during solution loading |
| Logic | Return 3 when the contract requires 2 | `AssertionError` from the contract |
| pytest | Correct function, test expectation deliberately set to 999 | `AssertionError`; executed failing test is retained as evidence |

The fake-provider assisted journey separately executes a failing attempt, a level 1
hint with captured source references, a corrected attempt, and a learner explanation.
Plan + fresh tests + explanation produce demonstrated evidence. Repeating the
journey with an explicitly requested level 4 response produces practicing evidence.
The provider cannot supply the learner's explanation, complete a mission, or
approve competence. Responses display their actual assistance level and remain
literal text, including Rich-looking markup.

CLI and TUI checks also cover read-only practice, unavailable provider, draft review
without reference disclosure, separate execution/publication gates, fingerprint
staleness, local ID rejection, composed catalog conflicts, confirmation cancellation,
reference access bound to the captured attempt, persistent classic loop/provider,
and TUI validation cancellation with actual descendant process termination before
restoring the action slot. Cancelled technical validation may retain an unsuccessful
record; it cannot authorize publication. The installed 11 mission references and
actual 001/006 journeys remain part of the full release suite.

## Optional real-model evaluation

Status: **NOT_RUN**. `LAB_API_KEY` is absent in this environment. No remote request
was made and no real model quality observation, SDK remote success, or prompt
quality improvement is claimed. There is no suggested/default model or fabricated
key; an explicit model and securely configured credentials are prerequisites.

When available, run the six source scenarios with the selected configured model
and record the actual model identifier, requested/returned help levels, source
references, response clarity, hint progression, and unsupported claims of execution.
Request full solutions explicitly at level 4. Record every model failure separately
from deterministic release tests and adjust prompts only from those observations.
Passing generated exercise tests is technical evidence, not didactic approval or
competence. Existing fake-provider results cannot substitute for this evaluation.

## Scope of release evidence

The local full suite and nine clean-venv template smokes validate the supported
editable checkout. Core/dev-only checks use a genuinely isolated venv with no SDK,
Ruff, or Mypy. Actual Ubuntu/Windows × Python 3.11/3.12 outcomes must come from the
controller's run at the final candidate SHA; workflow configuration and earlier
parent runs do not establish that this candidate ran on those platforms.

Templates are initial scaffolds. The bot is a local echo/CLI, and the scraper reads
local HTML. They do not provide hosted applications, Telegram/Discord integrations,
HTTP crawling, deployment, or evidence of production readiness.
