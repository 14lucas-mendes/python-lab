# C1 fix round 1 — review findings

Base: `0a67743`. Review: `C1-review-report.md` (I1, I2, I3).

The preview now inserts line boundaries and `\ No newline at end of file` markers when a removed or added line has no final newline. The replacement still writes the exact original `after_text` bytes. Saved proposals are written to a private temporary file, synced, then published by a no-clobber hard link; a failed partial write leaves no record and the same ID can be retried. Proposal and backup directories have mode 0700, and files have mode 0600 on POSIX, independent of permissive or restrictive umask. A newly created `data_dir` is 0700; an existing caller-owned `data_dir` keeps its mode, while the service-owned children remain private. Existing symlinks at those children are rejected. Destination permission preservation and exact-byte backups remain covered.

## Test evidence

- RED: `.venv/bin/python -m pytest tests/test_patches.py -q` — 3 failed as expected: concatenated no-final-newline diff, permissive state directory mode, and retry blocked by partial JSON.
- Additional RED: the existing caller-owned state-directory mode and restrictive-umask checks failed before adjustment; symlink redirection checks failed for both `proposals` and `backups` before rejection was added.
- GREEN: `.venv/bin/python -m pytest tests/test_patches.py -q` — 19 passed.
- Final scoped regression: `.venv/bin/python -m pytest tests/test_patches.py tests/test_assistant_models.py tests/test_workspace.py -q` — 195 passed.
- `.venv/bin/python -m ruff check python_lab/assistant/patches.py tests/test_patches.py` — passed.
- `git diff --check` — passed.

The two permission-mode tests explicitly skip outside POSIX, where permission mode semantics differ. No full-suite repeat was run for this isolated patch module. Self-review checked atomic no-clobber proposal publication, cleanup of only the temporary proposal, exact-byte backup and replacement, same-directory destination replacement, and source mode preservation. The documented final-check-to-rename race with external editors remains; no external-editor lock is claimed.
