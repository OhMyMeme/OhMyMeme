# Learnings — architecture-optimization

Conventions and successful approaches discovered during work on this plan.

---

## 2026-08-27 baseline

- Native `git worktree add -b` safely created a separate physical worktree from committed `HEAD` without carrying main-worktree dirty content.
- The isolated worktree must install dependencies into its own `.venv`; the project's `mise run setup` assumes pip exists and failed before installation, so `mise exec -- uv pip install --python .venv\Scripts\python.exe ...` was used without changing repository files.

## 2026-08-27 local projection invariants

- `LocalLibraryService` deliberately keeps a successful SQLite mutation when manifest projection fails; a recoverable projection failure returns `False` after restoring the prior manifest, while restore failure re-raises the projection error with the restore error as its cause.
- `ManifestBuilder.build()` writes version 3 before deleting empty collections, and nested collection membership is serialized by filename rather than database ID; direct tests now assert both database rows and manifest JSON.

## 2026-08-27 public projection boundary

- `LocalLibraryService.project_manifest()` now exposes the existing snapshot, projection, and recovery semantics without exposing `_project_after_mutation()` to service callers.
- `LocalLibraryService.apply_remote_manifest_operation()` names the sync planning seam explicitly; `apply_remote_operation()` remains as a compatibility alias with the same boolean result shape.
- Sync upload/push fallback and LAN `pull_manifest` now call only public library projection methods. Public-boundary sentinels fail if `_project_after_mutation` is accessed.

## 2026-08-27 dependency convergence

- Container-owned SyncService now forwards its config, db, assets, manifest, and library through the existing module-level operation seam; legacy calls without those arguments still resolve singleton config/db/assets.
- Sync internal worker arguments were extended only behind `_pull_worker_core`; the public `_pull_worker(entries, remote_root, cache_dir, db)` signature remains unchanged for import/bridge compatibility.
- Planning and LAN optional dependencies now distinguish an explicitly supplied falsey value from a missing dependency by checking `is not None`; standalone facades retain singleton fallback behavior.
- Real temporary-root smoke confirmed Container Sync/LAN identity and manifest writes stayed under the temporary root while global singleton references were replaced with sentinels.

## 2026-08-27 importer lifecycle contracts

- Importer entrypoints keep their existing module progress dictionaries as the UI compatibility layer, while `JobManager` owns the external task snapshot. `JobContext.snapshot()` projects phase, normalized 0-1 progress, message, error code, and error without exposing subprocesses, executors, or temporary paths.
- `JobManager.try_start()` supplies atomic admission without changing legacy `start()` duplicate-return semantics. Telegram, Douyin, WeChat, mobile QQ ADB, and QQNT declare stable `import.*` task types and one resource tuple each; `job_manager=None` continues to use the original daemon-thread path.
- Cancellation is a terminal precedence rule: once a JobManager cancellation event is set, a late explicit completion cannot publish `completed`. BaseException handling is limited to `KeyboardInterrupt` and `SystemExit` at the worker boundary so the active slot is always released without broad exception swallowing. ADB's public cancel operation only transitions active phases and returns false for terminal/repeated cancellation.
- Legacy ADB admission must reserve the module-level active phase while holding `_QQ_LOCK`, before creating its daemon thread. This preserves the old no-manager ABI while preventing two workers from sharing `_QQ_STATE` and `_QQ_CANCEL`.
- A JobManager thread is an isolated task boundary: ordinary `Exception` keeps its historical `str(error)` mapping, while any `BaseException` escaping the worker is finalized there so thread exit cannot orphan an active slot. Cancellation event state determines whether that exceptional exit is externally `cancelled` or `error`.

## 2026-08-27 explicit pull metadata boundary

- `pull()` must distinguish an actually explicit resource graph from an all-legacy invocation before calling `_default_library()`; otherwise passing internally resolved defaults changes legacy callback behavior.
- For explicit resources with `library=None`, the compatibility metadata callback is bound to the supplied DB through `planning._apply_remote_metadata(remote_data, db)`, while the no-argument facade retains `_apply_remote_metadata` and singleton behavior.

## 2026-08-27 dependency ownership test coverage

- Added test-only coverage for `Container.start_lan()` reusing its owned server, Sync retaining the Container-owned library identity, LAN command handlers retaining the supplied config/db/assets/manifest/library graph, and a real LAN `push_manifest` writing only beneath the Container temporary root.
- Added a real `ImageImportService` temporary-root import with singleton config/DB factories patched to fail; the imported row, cache, and manifest are all observed through the supplied graph. Added explicit no-resource Sync facade coverage proving `_default_library()` remains singleton-compatible and invokes the legacy metadata callback.
- Baseline targeted LAN runs were intentionally recorded with known fixed-port/global-state races (`4` and `7` LAN failures in separate runs); the corrected serial targeted suite passed `154 passed, 1 skipped`, with Sync/Container/local-library subset `112 passed` and LAN/integration subset `42 passed, 1 skipped`. LSP remains unavailable for the linked worktree because the client request cwd excludes it.
