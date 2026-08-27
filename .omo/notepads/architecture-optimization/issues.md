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

## 2026-08-27 public projection boundary verification

- Failing-first tests initially failed for the intended reasons: `LocalLibraryService` had no `project_manifest()` and LAN `pull_manifest` accessed `_project_after_mutation()`.
- After the minimal boundary change, targeted application/sync/LAN/container tests passed `137 passed, 1 skipped`; the full suite passed `382 passed, 1 skipped`.
- Real temporary-root smoke paths independently observed Container/library projection, Sync `project_manifest`, and LAN `pull_manifest` plus `push_manifest` success. Temporary roots were removed after each probe.
- `lsp_diagnostics` could not run against this linked worktree because the LSP client rejects paths outside its request cwd; no clean LSP result is claimed.

## 2026-08-27 adversarial checkbox-3 verification

- Review scope used the available linked worktree `C:/Users/abbey/AppData/Local/Temp/opencode/ohmymeme-architecture-optimization-baseline` at `ed9d1c3`; the user-mentioned path without `-baseline` does not exist. The target worktree remained product-clean before this append; GitButler is not configured there, so native Git inspection was used.
- Positive evidence: `mise exec -- python -m pytest tests/application/test_local_library_service.py tests/test_sync.py tests/test_lan.py tests/app/test_container.py tests/integration/test_lan_server.py -q` returned `137 passed, 1 skipped in 6.84s`; full `mise exec -- python -m pytest tests/ -q` returned `382 passed, 1 skipped in 13.80s`; targeted `ruff check` passed; targeted `black --check` reported 6 files unchanged; `git diff --check` passed.
- Positive smoke evidence: a temporary `Container` imported a valid PNG and `library.project_manifest()` returned `True`; direct LAN `_cmd_push_manifest` with an empty version-3 manifest returned exactly `{'ok': True, 'local_count': 1}`. The temporary root was removed after the probe. Public projection failure/recovery was also covered by the existing real-`MemeDB` test and returned `False` while restoring old manifest bytes.
- Static private-call scan found `_project_after_mutation()` only inside `LocalLibraryService`; no `._project_after_mutation()` cross-module access remains in `src` or tests. Public `SyncService.project_manifest()` and `CommandHandlers._cmd_pull_manifest()` paths are correctly wired and their sentinel tests reject private projection bypass.
- **Blocking finding for checkbox acceptance:** `src/ohmymeme/services/lan/commands.py:146-158` still defines callable `_apply_manifest()`. When `_sync_service is None`, it directly calls `sync.service._apply_remote_order()` and `_apply_remote_collections()` at lines 154-155, bypassing the public `LocalLibraryService` apply boundary. Although current dispatch does not call this helper, the requested invariant says LAN metadata/order/collection paths only go through the public local-library boundary; a callable legacy path violates that seam and is not proven dead by a type/interface contract. An adversarial invocation reached the private adapters (the first probe failed only because the monkeypatched lambda arity did not match the adapter's two-argument forwarding; the actual source path and references are directly observable).
- **Coverage gap:** no test exercises LAN `push_manifest` success, malformed manifest, DB/application failure, projection failure/recovery, or exact `local_count` response shape. Existing LAN tests cover `pull_manifest` success and projection-failure envelope only (`tests/test_lan.py:384-413`). Sync pull/push mostly use `_FakeDb`; they do not independently prove real SQLite remote metadata/order/collection mutation through the public boundary.
- **Test-quality risks:** LAN tests use fixed port `17990` and global config/DB/server state (`tests/test_lan.py:25,128-151`), so concurrent worktrees can interfere. `tests/test_lan.py:370-380` treats `socket.timeout` as proof of server closure, making the handshake retry-limit test potentially misleading. These are review observations, not changes made here.
- `lsp_diagnostics` was attempted for all three changed source files and rejected because the LSP client root excludes this linked worktree; no LSP cleanliness is claimed. An initial full-suite attempt failed because the temporary smoke directory was removed during test collection; the follow-up full suite passed after cleanup ordering was corrected, so the first failure is recorded as a stale-state/misleading-success probe rather than a product failure.
- Verdict: **needs-fix / not confirmed**. Public projection replacement and recovery behavior are evidenced, but the callable LAN `_apply_manifest()` private planning bypass and missing LAN `push_manifest` failure/recovery evidence prevent satisfying the checkbox's strict “only public boundary” and adversarial acceptance criteria.

## 2026-08-27 follow-up verification

- Red regression `test_legacy_manifest_apply_uses_public_library_boundary` first failed because the legacy callable `_apply_manifest()` imported private sync helpers; after the fix it passed while those helpers were patched to fail, proving they are not reached.
- `_apply_manifest()` now returns the boolean result of `LocalLibraryService.apply_remote_metadata()` and has no sync-service private-helper import path.
- LAN compatibility tests now exercise real handler behavior: valid `push_manifest` returns `{"ok": True, "local_count": ...}`, malformed payload returns `{"ok": False, "error": "manifest 格式错误"}`, and public apply failure returns `{"ok": False, "error": "本地清单应用失败"}`.
- Serial targeted command `mise exec -- python -m pytest tests/test_lan.py tests/test_sync.py tests/application/test_local_library_service.py tests/integration/test_lan_server.py tests/app/test_container.py -q` passed `140 passed, 1 skipped`; LAN-only passed `37 passed, 1 skipped`; LAN integration passed `4 passed`.
- A deliberately parallel run of fixed-port LAN suites produced unrelated global-state/port races; the required serial rerun passed. No production fix was made for that pre-existing test isolation issue.
- `mise exec -- ruff check ...` passed; `mise exec -- black --check ...` reported both changed Python files unchanged; `git diff --check` passed. LSP remained unavailable because the client rejects this linked worktree path.

## 2026-08-27 follow-up blocker fix

- Red test `test_legacy_manifest_apply_uses_public_library_boundary` initially reached the intended blocker: the callable LAN `_apply_manifest()` imported and invoked private sync helper functions when no SyncService was injected.
- `_apply_manifest()` now delegates directly to `LocalLibraryService.apply_remote_metadata()` and returns its boolean result; no LAN callable path imports or invokes `_apply_remote_order()`/`_apply_remote_collections()`.
- Added real LAN command coverage for push-manifest success (`{"ok": True, "local_count": ...}`), malformed input (`{"ok": False, "error": "manifest 格式错误"}`), and public apply failure (`{"ok": False, "error": "本地清单应用失败"}`).

## 2026-08-27 dependency convergence verification

- First full-suite run exposed the existing `_pull_worker` signature contract in `tests/application/test_import_service.py`; the public four-argument facade was restored, with new explicit dependencies confined to `_pull_worker_core`.
- Targeted verification passed `125 passed, 1 skipped`; full verification passed `389 passed, 1 skipped`. Ruff and black checks passed. LSP diagnostics were rejected for every changed path because the client request cwd is the main worktree, not this linked worktree.
- Scoped diff contains only the four requested production modules, two narrowly required regression test files, and this append-only notepad entry. No schema, manifest format, LAN wire protocol, config semantics, README, AGENTS, or protected dirty file changed.
