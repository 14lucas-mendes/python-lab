# C1 fix round 2 — portable replacement mode

Base: `a49da0a`. The actual Windows Python 3.11 native run 38076209452 (job 114283565686) failed at `python_lab/assistant/patches.py:174`: `os.fchmod` is absent. Evidence is in `C1-native-failure.json`.

`PatchService` now uses one `_set_file_mode(fd, path, mode)` helper for saved proposals, backups, and the temporary replacement. It uses `os.fchmod` where available and `Path.chmod` otherwise. Proposal and backup mode requests remain 0600; replacement mode comes from the existing destination. Backup bytes, same-directory atomic replacement, rechecks, and recovery handling are unchanged.

## Evidence

- RED: `.venv/bin/python -m pytest tests/test_patches.py -q` — 19 passed, 1 failed as expected when the test removed `os.fchmod`; the failure was in backup mode setting before replacement.
- GREEN: `.venv/bin/python -m pytest tests/test_patches.py -q` — 20 passed.
- `.venv/bin/python -m ruff check python_lab/assistant/patches.py tests/test_patches.py` — passed.
- `git diff --check` — passed.

The regression checks exact replacement and backup bytes without `os.fchmod`, and checks destination mode and private backup mode on POSIX. Native Windows verification remains with the controller's CI rerun; this workspace cannot claim that run has passed. The documented external-editor race remains unchanged. Existing dirty C2 files were not edited, staged, or included in this fix.
