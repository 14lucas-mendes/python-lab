# C1 fix round 3 — portable permission assertion

Base: `b56847a`. The existing apply test now records the source's actual mode immediately after `chmod(0o640)` and asserts that apply preserves that observed mode. On POSIX it also checks that the requested 0640 mode was set. The exact replacement and backup byte assertions still run on every platform. No production code changed.

Verification: `.venv/bin/python -m pytest tests/test_patches.py -q` — 20 passed; `.venv/bin/python -m ruff check tests/test_patches.py` — passed; `git diff --check` — passed. Native Windows CI is pending with the controller. Dirty C2 files were not edited or staged.
