# B3 implementation report

Base: `09673ba` on `feat/local-assistant-tutor`. Scoped files: `python_lab/assistant/{settings,provider,openai_provider}.py`, `pyproject.toml`, `constraints/assistant.txt`, `tests/{__init__,helpers/__init__,helpers/assistant,test_assistant_provider,test_assistant_settings}.py`, the two existing helper imports in `tests/test_analysis.py` and `tests/test_tui.py`, and this report. Core constraints, mission files, B1 models, B2 analysis code, and application startup code were not changed.

## Behavior and boundaries

- `load_settings(data_dir)` reads explicit top-level TOML, returns disabled settings when the file is absent, rejects invalid numbers and unknown fields without echoing values, and has no model default. `LAB_API_KEY` is read only when `OpenAIProvider` is constructed; it is never read from TOML or included in model input and errors.
- The `assistant` extra installs the official OpenAI SDK lazily. The client sets `max_retries=0` and a 30-second timeout by default. `generate` sends one structured Responses API request with a strict JSON schema, selected B1 source snapshots and traceback, and no tools. It validates the result and source references using B1 `validate_answer`.
- A session `UsageBudget` reserves output tokens before each actual send, accounts for concurrent sends, charges trusted SDK output usage even when the answer is invalid, and holds the reservation when usage is unknown or a post-send failure, timeout, or cancellation occurs. Cancellation propagates. Provider recreation can reuse the same budget; a new provider without a supplied budget starts a new one-shot session. Input usage is reported separately and is not part of the output budget.
- `BudgetedStructuredTransport` accepts a schema and validator so future review and exercise adapters can share the same send, usage, and validation boundary. This task does not add those product actions or session persistence. A future runtime that restores a conversation must also restore its budget, per R9.
- Test helpers use a real line-1 reference from the selected snapshot. No project writes, tool calls, mission completion, or real model calls are part of this adapter.

## Actual verification

All commands ran in `/workspace/python-lab` on Linux. `/tmp/B3-*.txt` logs are local execution evidence.

1. Before implementation, `.venv/bin/python -m pytest tests/test_assistant_provider.py tests/test_assistant_settings.py -q` had **72 failing cases** because B3 modules did not exist (`/tmp/B3-red.txt`). The subsequent focused suite passed **84 cases** with the fake SDK; its exact output was not retained in the handoff logs, so the final whole-suite runs below provide the retained GREEN evidence.
2. `.venv/bin/python -m pip install -e '.[assistant]' -c constraints/dev.txt -c constraints/assistant.txt` succeeded (`/tmp/B3-extra-install.txt`). The official SDK is **openai 3.28.0**, with `httpx2 2.13.1`. The binding 14 core pins in `constraints/dev.txt` were unchanged. `.venv/bin/python -m pip check` reported no broken requirements.
3. The official SDK integration test used `httpx2.MockTransport` and a local response. It verified actual Responses API request serialization, strict schema, usage parsing, no tools, and one request. It made no network model call. Other provider tests used a fake SDK for timeout, cancellation, 429/authentication sanitization, invalid payloads/references, usage accounting, action reuse, and budget sharing.
4. `/tmp/python-lab-b3-base/bin/python -m pip install -e '.[dev]' -c constraints/dev.txt` succeeded (`/tmp/B3-base-install.txt`). This genuine base environment has no `openai`, `ruff`, or `mypy` modules; its `pip check` reported no broken requirements. Its `lab --help` output is in `/tmp/B3-base-help.txt` and confirms normal CLI startup without the assistant extra.
5. Initial whole-suite runs found two tests unable to import `test_process_runner` after the required `tests/__init__.py` made tests a package: extra **2 failed, 583 passed, 4 skipped** (`/tmp/B3-extra-suite.txt`); base **2 failed, 580 passed, 7 skipped** (`/tmp/B3-base-suite.txt`). Only those two existing imports were changed to `tests.test_process_runner`; the test assertions and runtime behavior were untouched. Both affected tests then passed in each environment.
6. Final `.venv/bin/python -m pytest -q` exited **0**, with observed completion at 100%, no failures, and four skip markers (`/tmp/B3-extra-suite-final.txt`). The repository's default `addopts=-q` makes this double-quiet run omit the numeric success summary; **585 passed is an inferred total**, calculated from the initial 583 passes plus the two repaired tests, not a directly printed result. Final `/tmp/python-lab-b3-base/bin/python -m pytest -o addopts='' -q` reported **582 passed, 7 skipped in 48.83 s** (`/tmp/B3-base-suite-final.txt`).
7. `git diff --check` passed. No optional real-model smoke was run; it would require a user-selected model and a secure key, and the local mock covers the SDK API shape without network access.

No remaining implementation blocker found in self-review. The untested boundary is a live service response, including provider-side policy and billing behavior; B3 intentionally verifies the official SDK against a local mock instead.

## Review fix round 1 — explicit provider in present config

Review base: `dfe01af`. The important finding in `B3-review-report.md` was reproduced: a present `config.toml` with only `model` silently returned disabled settings. `load_settings` now requires a top-level `provider` whenever the file exists; only a missing file selects disabled settings. The error contains no TOML values, and an explicit `provider="openai"` with no model still defers the required-model guidance to provider construction.

Actual verification in `/workspace/python-lab`:

- RED: `.venv/bin/python -m pytest -o addopts='' tests/test_assistant_settings.py -q -k 'present_config_requires_explicit_provider'` — **3 expected failures** (`/tmp/B3-fix1-red.txt`): empty, model-only, and numeric-only present files did not raise.
- GREEN: `.venv/bin/python -m pytest -o addopts='' tests/test_assistant_settings.py tests/test_assistant_provider.py -q` — **87 passed in 2.08 s** (`/tmp/B3-fix1-extra-green.txt`). The official SDK case still uses only local `MockTransport`.
- Genuine base without the assistant extra: `/tmp/python-lab-b3-base/bin/python -m pytest -o addopts='' tests/test_assistant_settings.py tests/test_assistant_provider.py -q` — **86 passed, 1 skipped in 1.18 s** (`/tmp/B3-fix1-base-green.txt`); the SDK integration is the skipped case.
- `git diff --check` passed. The full suites were not repeated because this change is confined to TOML presence validation and both focused settings/provider suites passed.

Self-review: unknown-field and malformed-TOML errors remain sanitized; the missing-file branch returns before the new check; present files must identify a provider, and existing explicit-provider paths retain their validation. No further B3-specific blocker found.
