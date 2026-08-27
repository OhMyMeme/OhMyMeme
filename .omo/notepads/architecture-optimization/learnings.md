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
- QQNT managed binding must validate `job_manager.active("import.qqnt").id` while holding `_QQNT_LOCK` both before publishing and before clearing its global bridge references; checking only activity permits a completed task to overwrite the current task's cancellation target.
- ADB's shared temporary directory is tracked at creation and reclaimed in the worker wrapper's `finally`, so unexpected ordinary exceptions cannot leave partial pull/processing files behind while preserving the existing UI progress dictionary and JobManager terminal mapping.

## 2026-08-27 importer lifecycle contracts

- Importer entrypoints keep their existing module progress dictionaries as the UI compatibility layer, while `JobManager` owns the external task snapshot. `JobContext.snapshot()` projects phase, normalized 0-1 progress, message, error code, and error without exposing subprocesses, executors, or temporary paths.
- `JobManager.try_start()` supplies atomic admission without changing legacy `start()` duplicate-return semantics. Telegram, Douyin, WeChat, mobile QQ ADB, and QQNT declare stable `import.*` task types and one resource tuple each; `job_manager=None` continues to use the original daemon-thread path.
- Cancellation is a terminal precedence rule: once a JobManager cancellation event is set, a late explicit completion cannot publish `completed`. BaseException handling is limited to `KeyboardInterrupt` and `SystemExit` at the worker boundary so the active slot is always released without broad exception swallowing. ADB's public cancel operation only transitions active phases and returns false for terminal/repeated cancellation.
- Legacy ADB admission must reserve the module-level active phase while holding `_QQ_LOCK`, before creating its daemon thread. This preserves the old no-manager ABI while preventing two workers from sharing `_QQ_STATE` and `_QQ_CANCEL`.
- QQNT legacy admission similarly reserves `running` under `_QQNT_LOCK` before spawning; managed post-start binding must check JobManager activity before publishing a job ID, preventing a fast worker's cleanup from being overwritten.
- Cancellation binding belongs in the JobManager admission transaction, before the worker thread is started. This avoids a public cancel racing between record creation and importer-local `_JOB_CANCEL` initialization while preserving each adapter's legacy progress dictionary.
- Managed ADB uses its admission-bound cancellation event as activity proof before `_qq_worker` publishes its first phase; this permits immediate cancel while retaining active-only terminal state protection.
- A JobManager thread is an isolated task boundary: ordinary `Exception` keeps its historical `str(error)` mapping, while any `BaseException` escaping the worker is finalized there so thread exit cannot orphan an active slot. Cancellation event state determines whether that exceptional exit is externally `cancelled` or `error`.

## 2026-08-27 explicit pull metadata boundary

- `pull()` must distinguish an actually explicit resource graph from an all-legacy invocation before calling `_default_library()`; otherwise passing internally resolved defaults changes legacy callback behavior.
- For explicit resources with `library=None`, the compatibility metadata callback is bound to the supplied DB through `planning._apply_remote_metadata(remote_data, db)`, while the no-argument facade retains `_apply_remote_metadata` and singleton behavior.

## 2026-08-27 dependency ownership test coverage

- Added test-only coverage for `Container.start_lan()` reusing its owned server, Sync retaining the Container-owned library identity, LAN command handlers retaining the supplied config/db/assets/manifest/library graph, and a real LAN `push_manifest` writing only beneath the Container temporary root.
- Added a real `ImageImportService` temporary-root import with singleton config/DB factories patched to fail; the imported row, cache, and manifest are all observed through the supplied graph. Added explicit no-resource Sync facade coverage proving `_default_library()` remains singleton-compatible and invokes the legacy metadata callback.
- Baseline targeted LAN runs were intentionally recorded with known fixed-port/global-state races (`4` and `7` LAN failures in separate runs); the corrected serial targeted suite passed `154 passed, 1 skipped`, with Sync/Container/local-library subset `112 passed` and LAN/integration subset `42 passed, 1 skipped`. LSP remains unavailable for the linked worktree because the client request cwd excludes it.
## 2026-08-27 terminal state reconciliation

- Importer-local UI dictionaries must be finalized at the adapter worker boundary before JobManager handles an escaping `BaseException`; otherwise the external snapshot becomes `error` while the bridge still reports an active phase.
- Managed admission is the QQNT UI commit point. Publishing `running` before `try_start()` lets a closed manager leave stale UI and binding state; binding and initialization inside `on_admit`, with rollback around admission, preserves legacy state while making failed admission inert.
- Re-raising the adapter `BaseException` after UI reconciliation preserves JobManager's typed terminal snapshot and active-slot release; the adapter supplies only the compatibility projection.

## 2026-08-27 task lifecycle regression coverage

- Deterministic JobManager coverage uses barriers for concurrent admission and events for worker release, cancellation observation, terminal snapshot retention, closed-manager rejection, and post-terminal restart; no wall-clock sleeps are needed in the new lifecycle cases.
- Telegram conversion lifecycle coverage locks the bounded `min(cpu_count, 4)` executor and requires `shutdown(wait=True, cancel_futures=True)`. The process reap regression also proves a still-running process remains registered after bounded kill/wait attempts, preventing premature resource loss.
- Douyin and WeChat managed cancellation tests create partial worker directories through their real worker entrypoints, signal cancellation at the controlled boundary, wait for worker termination, and assert the temporary roots are reclaimed.

## 2026-08-28 importer ownership

- QQNT extraction keeps the user-selected output directory user-owned: the desktop worker never deletes or rescans it as application cache. After extraction succeeds, the bridge passes supported files once to the Container-owned library import boundary, which owns cache, SQLite, and manifest projection.
- Telegram, Douyin, WeChat, and mobile QQ retain importer-owned temporary decrypt/download/pull directories until their worker reaches its terminal cleanup boundary; existing lifecycle tests cover cancellation and worker exceptions without changing bridge shapes.
- QQNT cancellation must be checked after the canonical callback returns as well as before it starts. If the callback committed IDs before observing cancellation, the desktop adapter compensates through the bound library's delete boundary while leaving the user-owned QQNT output untouched.
- Telegram temporary-directory removal is part of the worker result contract: a removal `OSError` changes the compatibility state to `error` with `cleanup_failed` instead of allowing a prior `done` state to stand while the directory remains.
- Mid-callback cancellation is owned by the canonical import boundary, not by a post-callback bridge check: `ImageImportService.import_batch` checks the supplied event during the batch and after projection, then restores its manifest snapshot and compensates only IDs/files created by that batch.
