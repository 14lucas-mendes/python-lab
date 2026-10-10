# C1 report — versioned single-file patches

Implemented `FileChange` and `PatchProposal` in `python_lab.assistant.models` and `PatchService` in `python_lab.assistant.patches`. The public models validate canonical relative POSIX paths, SHA-256 syntax, UTF-8 output, the 32768-byte source bound, and destination membership in the selected paths. `PatchService` captures all selected sources with `Workspace.snapshot` at preview, save, and apply; this reuses root, symlink, Git ignore, exclusion, type, UTF-8, and byte checks and compares the target's current hash with `before_sha256`.

Preview returns a literal unified diff without filesystem writes. Save stores a workspace-root-bound proposal under a SHA-256-derived opaque ID key; load rejects unknown and foreign records. Confirmed apply writes an exact-byte backup under `data_dir`, writes the replacement to a temporary file in the destination directory, preserves mode bits, rechecks the selected sources and hash, and atomically replaces one existing source. Errors during replacement include the backup path for recovery. No compensating rollback overwrites a possible newer external edit.

## Commands and results

- RED: `.venv/bin/python -m pytest tests/test_patches.py -q` — collection failed because `FileChange` was absent.
- GREEN: `.venv/bin/python -m pytest tests/test_patches.py -q` — 12 passed. A later post-replacement error test failed as expected against an incorrect “original preserved” message; after repair the focused run passed 13 tests.
- `.venv/bin/python -m pytest tests/test_patches.py tests/test_assistant_models.py tests/test_workspace.py -q` — 189 passed.
- `.venv/bin/python -m ruff check python_lab/assistant/models.py python_lab/assistant/patches.py tests/test_patches.py` — passed.
- `git diff --check` — passed.

Tests cover literal preview without writes, exact replacement and backup bytes, permissions, stale edits, missing confirmation, unselected/traversal/external symlink destinations, symlink retargeting, invalid UTF-8 and output byte limit, backup failure, replace failure, recovery after an injected post-replacement error, and saved proposal scope.

## Interface and limits

`PatchService(workspace, data_dir)` exposes `preview(proposal) -> str`, `save(proposal) -> None`, `load(proposal_id) -> PatchProposal`, and `apply(proposal, *, confirmed) -> Path`. Callers must create IDs and `selected_paths` from the local snapshot; C2 provider integration must never accept those fields from model output. A raw in-memory proposal can be previewed and applied without first saving it, as required by the C1 direct-apply example; persistent foreign-ID detection applies to saved records in the same `data_dir`. No lock is held against external editors between the final check and rename, so concurrent external edits in that interval cannot be guaranteed safe.
