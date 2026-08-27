# Issues — architecture-optimization

Problems and gotchas encountered during work on this plan.

---

## 2026-08-27 baseline

- `but status -fv --no-hint` cannot run in the native isolated worktree because GitButler is not configured there; it returned `No GitButler project found at .`. Main-worktree GitButler status was captured separately and remained unchanged.
- `mise run setup` failed at `python -m pip install --upgrade pip` because the auto-created uv venv has no pip. This was resolved with managed `uv pip` installation in the isolated venv only.

## 2026-08-27 adversarial verification — local projection invariants

- Verdict: `needs-fix`.
- The targeted tests pass: `mise exec -- python -m pytest tests/application/test_local_library_service.py tests/core/test_assets.py -q` reports `28 passed in 0.43s`; the wider application/core slice reports `50 passed in 1.11s`; ten sequential targeted runs each report `28 passed` with no timing or shared-path flake.
- `mise exec -- ruff check tests/application/test_local_library_service.py tests/core/test_assets.py` passes, and `mise exec -- black --check tests/application/test_local_library_service.py tests/core/test_assets.py` reports both files unchanged. The requested LSP diagnostic calls were rejected because the LSP client is rooted at the main worktree and refuses paths outside its request cwd; no target-worktree LSP result is claimed.
- Commit `bee830f` changes only `.omo/notepads/architecture-optimization/learnings.md`, `tests/application/test_local_library_service.py`, and `tests/core/test_assets.py`; native target-worktree status is clean. The protected main worktree still has only its four pre-existing unrelated files: `src/ohmymeme/presentation/desktop/window_manager.py`, `src/ohmymeme/presentation/frontend/settings/core/init.js`, `src/ohmymeme/presentation/frontend/settings/features/sync/settings.js`, and `src/webui/settings.js`.
- Defect: `tests/application/test_local_library_service.py:299-327` monkeypatches `_restore_manifest` and calls the private `_project_after_mutation()` directly. It never invokes `rename_meme()` or any other database mutation, so `db.get_by_id(meme_id)["original_name"] == "old"` only proves that no mutation occurred. The test therefore does not lock the required invariant that a successful SQLite mutation followed by projection failure and recovery failure is explicitly reported and not returned as success. The test should trigger a real mutation first and assert the resulting public return/exception plus the committed DB state and unrecovered manifest bytes.
- Cleanup receipt: all test-created SQLite databases and manifest files were under pytest `tmp_path` or a one-shot temporary directory; the failed one-line manual probe created no repository files. No production, plan, README, AGENTS, or protected files were modified.

## 2026-08-27 recovery-failure test correction

- Replaced the private `_project_after_mutation()` invocation with public `rename_meme()`. The test now proves the SQLite row changes to `renamed` before a `ValueError` projection failure, then surfaces that same exception with deterministic `OSError("restore failed")` as its cause while the unrecovered manifest bytes remain `new`.
