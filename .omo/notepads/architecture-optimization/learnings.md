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

## 2026-08-28 Task 10 bridge ABI contracts

- Added behavior-level bridge coverage for main/settings façade calls: exact positional arguments, defaults, representative return types, importer/update/sync envelopes, and settings refresh JavaScript expressions are asserted through recording handlers and deterministic module fakes.
- Added platform failure coverage proving non-Windows and missing pythonnet/WinForms native drag return `False` without scheduling hotkey-session hide; missing dynamic methods retain the established `None` failure shape.
- Task 9 remains structurally blocked and unconfirmed; these tests intentionally guard façade contracts before and after any future decomposition without changing the blocked implementation.

## 2026-08-28 shared catalog query predicates

- `MemeDB._build_meme_filters()` is the single predicate/parameter construction seam for `search()` and `count()`; query-specific SELECT, ordering, and pagination remain in their callers.
- `Catalog._query_collection()` centralizes `-2` favorite, `-3` recent, `-4` uncategorized, and positive descendant expansion while recent search/count remain independent paths.
- Real SQLite coverage confirms combined keyword/tag/descendant filters, favorite and uncategorized virtual collections, stego carrier exclusion, invalid tags/collections, pagination boundaries, sorting, and `get_collections()` recent counts.

## 2026-08-28 independent Task 12 verification after `fac8ffb`

- Verification ran only in the linked worktree `C:/Users/abbey/AppData/Local/Temp/opencode/ohmymeme-architecture-optimization-baseline`; main worktree remained separate with its pre-existing protected dirty files. `fac8ffb` is exactly `refactor: share catalog query predicates` and its tracked scope is the four architecture notepads, `src/ohmymeme/app/catalog.py`, `src/ohmymeme/core/database.py`, and `tests/test_catalog_queries.py`. No schema, manifest, protocol, config, dependency, protected-hash, or generated-artifact file is in the commit.
- Source audit confirmed `MemeDB._build_meme_filters()` owns one ordinary WHERE/parameter builder used by both `search()` and `count()`; `search()` appends only collection-order/limit/offset parameters, while `get_recent()`/`count_recent()` retain independent JOIN, stego filter, stable recent ordering, and count behavior. `Catalog._query_collection()` centralizes favorite `-2`, recent `-3`, uncategorized `-4`, and recursive positive collection routing.
- Required targeted serial command `mise exec -- python -m pytest tests/test_catalog_queries.py tests/test_core.py -q` passed `39 passed in 1.37s`. Two unchanged serial full-suite runs `mise exec -- python -m pytest tests/ -q` passed `460 passed, 1 skipped` in `14.20s` and `13.94s`.
- Static gates passed: `mise exec -- ruff check src/ohmymeme/core/database.py src/ohmymeme/app/catalog.py tests/test_catalog_queries.py` returned `All checks passed`; `mise exec -- black --check ...` reported `3 files would be left unchanged`; `git diff --check fac8ffb^ fac8ffb` passed. Linked-worktree `lsp_diagnostics` was attempted for all three changed Python files and rejected because the LSP request cwd excludes the linked worktree; no LSP-clean claim is made.
- Independent temporary SQLite matrix passed after correcting an initially malformed verifier expectation (the first harness incorrectly expected an item placed in a sibling/uncategorized state; its AssertionError was recorded and not treated as product evidence). The corrected matrix asserted mixed ordinary/stego/classified/uncategorized/favorite/recent data, combined keyword plus two-tag descendant filtering, exact independent counts, recent ordering and count, global ordering and pagination, empty/missing tags, invalid collection, recent out-of-range pagination, and stego exclusion; it printed `TASK12_SQLITE_MATRIX_OK` and removed its temporary root.
- Adversarial classes: `dirty_worktree` passed (linked worktree had only pre-existing unrelated dirty `handlers.py`, `window_manager.py`, and `src/webui/settings.js`; no verifier source/test edits); `stale_state` passed via repeated status and commit-scope checks; `misleading_success_output` was exercised by rejecting the malformed first matrix harness and checking exit codes; `malformed_input` passed for empty/missing tags, invalid collection, and pagination boundaries; `flaky_tests` passed across repeated serial targeted/full runs. Prompt injection was ruled out because repository/notepad text was treated as untrusted data; cancel/resume, hung-command, and repeated-interruption classes were not applicable to this read-only SQLite/query verification.
- Residual coverage observations are non-blocking: the committed tests' stego and uncategorized negative assertions are partly masked by their fixture membership, and several `count == len(search_page)` assertions are not fully independent. The verifier's mixed fixture closed the behavioral gap without changing source/tests. Recursive collection ordering for child-only members continues the pre-existing `NULL`-sort behavior and was not altered by `fac8ffb`.
- Verdict: **confirmed** for Task 12. Temporary roots were removed; only this append-only notepad evidence was written by verification.

## 2026-08-28 catalog query contract tests

- Baseline target tests passed `123`; the failing-first `_FakeDb.search` signature assertion rejected the old positional order and missing `favorite_only`, `uncategorized_only`, and `offset` parameters before the fixture was corrected.
- Added explicit query signatures and call recording to the scoped fakes, plus a real temporary SQLite/Catalog matrix covering keyword, two-tag intersection, descendant collections, favorite/recent/uncategorized virtual collections, pagination, global and collection sort order, and stego-carrier exclusion.
- Verification passed three serial target runs at `127 passed` each and two serial full-suite runs at `464 passed, 1 skipped` each. Scoped Ruff, Black, and `git diff --check` passed. Linked-worktree LSP remains unavailable because the client rejects paths outside its request cwd.
- The first standalone one-line smoke harness failed with a Python `SyntaxError`, and its second PowerShell-quoted retry failed before execution; these were harness errors, not product evidence. The real SQLite matrix test and all serial suites passed afterward.

## 2026-08-28 independent Task 13 verification (second pass)

- Verification stayed exclusively in the linked worktree `C:/Users/abbey/AppData/Local/Temp/opencode/ohmymeme-architecture-optimization-baseline`; its HEAD was `3491363d4b08b831e9006d255cba3cc825b94bf5` with subject `test: cover catalog query contract`. `git diff-tree` showed exactly `tests/app/test_container.py`, `tests/test_core.py`, and `tests/test_sync.py`; no production, protected, config, README, dependency, or generated file belongs to the commit.
- The linked worktree's inherited dirty paths remained exactly `.omo/notepads/architecture-optimization/learnings.md`, `src/ohmymeme/presentation/desktop/api/handlers.py`, `src/ohmymeme/presentation/desktop/window_manager.py`, and `src/webui/settings.js`; target test files stayed clean. The main worktree stayed on `56d12fa` with its original four protected dirty files. No Git write or destructive operation was used.
- Task 12 source audit at `fac8ffb` confirmed `MemeDB._build_meme_filters()` is shared by `search()`/`count()`, `search()` owns collection/global ordering and pagination, `get_recent()`/`count_recent()` own recent ordering/count, and `Catalog._query_collection()` routes favorite `-2`, recent `-3`, uncategorized `-4`, and recursive positive descendants.
- Changed-line audit found explicit parameter lists on `_FakeDb.search`, `_CatalogQueryDb.search`, `_CatalogQueryDb.count`, and `_CatalogQueryDb.get_recent`; `inspect` shapes match the production `MemeDB` methods exactly. No added line contains unconditional `**kwargs`; the remaining generic kwargs fakes are unchanged, non-query forwarding/cancellation fixtures.
- Failure probes were positive: the exact fake-signature test rejected a legacy/misordered signature and an unconditional `**kwargs` signature; an `_CatalogQueryDb.search` missing parameter raised `TypeError`; deliberate global/collection sort reversal, count off-by-one, tag-intersection removal, descendant expansion removal, favorite/uncategorized filter removal, recent virtual-route removal, pagination offset removal, and stego-filter removal all caused the real SQLite matrix to fail.
- The committed matrix has substantive literal count assertions (`1`, `4`) rather than `count == len(search_page)`. A 205-row temporary SQLite probe returned a 200-row default page, total count `205`, and page 2 beginning at ID `201`; the current count contract is therefore independent of pagination. A diagnostic `Catalog.count_memes -> len(search_memes())` replacement passes the small fixture, so a greater-than-page-size regression remains a non-blocking future strengthening opportunity, not a current behavior failure.
- Independent temporary SQLite probes passed `TASK13_SQLITE_SMOKE_OK`, `TASK13_SQLITE_SMOKE_ORDERED_OK`, `TASK13_STALE_STATE_SMOKE_OK`, and `TASK13_COUNT_PAGINATION_SMOKE_OK`. They covered keyword, empty/missing tags, two-tag intersection, invalid collection, three-level descendants, favorite, two-item recent ordering/count/pagination, uncategorized, global pagination/sort, custom collection sort, stego exclusion, and recent collection count. The first ordered smoke attempt intentionally exposed a verifier expectation error (uncategorized rows were asserted in insertion order instead of configured global sort); the corrected rerun passed.
- Required target command, run serially three times, passed `127 passed` each time. Required full command, run serially twice, passed `464 passed, 1 skipped` each time. Additional `PYTHONHASHSEED=0` and `1` target runs each passed `127 passed`; `tests/test_catalog_queries.py` passed `3 passed`.
- Static gates passed in the linked worktree: Ruff reported `All checks passed` for the three changed tests plus Task 12 source files; Black reported all five files unchanged; `git diff --check 3491363^ 3491363` was clean; AST parsing succeeded for all changed tests. LSP diagnostics were attempted for all changed tests and Task 12 source files but rejected by the known linked-worktree request-cwd restriction, so no LSP-clean claim is made.
- Final status and protected-file SHA-256 values matched the pre-test snapshot: `window_manager.py=B6C6D05E459E9C940178FC9DF2B2735C422A2520F4F2390BFC7AA5DE8675F92C`, `settings/core/init.js=DB1F8C17D3F1A2D315A7C336F15D808F3F19A57E6551EA2DDFBD3B36BD8032A7`, `settings/features/sync/settings.js=BE4AF808D9380E46E7CD7C0E54AFB16F49098D3CB6CD8A9F0176101AEED24E48`, and `src/webui/settings.js=E48135B97F0F8D3DBFED29870648C3282F8838F4158223DC4CF60AA8C1DFECEB`. TemporaryDirectory smoke roots were reclaimed; no new tracked or untracked leftovers appeared. Task 9's repository state still says structurally blocked/unconfirmed (`-~`), and no plan/protected state was changed.
- UltraQA: `malformed_input` passed via empty/missing tags and invalid collection; `stale_state` passed via post-mutation catalog queries, out-of-range pagination, and recent-count checks; `dirty_worktree` passed via unchanged inherited status/hashes; `misleading_success_output` was exercised by rejecting the malformed first smoke expectation and by mutation probes; `flaky_tests` passed across three serial target runs, two independent hash-seed target runs, and two serial full runs. Prompt injection was not applicable because repository text was treated as untrusted data; cancel/resume and repeated interruption were not applicable to synchronous read-only query tests; no command hung or exceeded its bounded timeout.
- Verdict: **confirmed** for Task 13. The only caveat is the non-blocking future >page-size count-fixture strengthening noted above; current source behavior, fake contract, semantic matrix, failure behavior, scope, and hygiene all have independent evidence.

## 2026-08-28 Task 14 adversarial verification

- Target commit `58d2990ae55e59145fdb8779302808b61abb17e9` is an ancestor of the repository HEAD. `git show --stat` and the parent diff confirm the scope is exactly `README.md` and `AGENTS.md`, with 10 inserted lines and no source or test changes. `git diff --check 58d2990^ 58d2990` is clean.
- Source comparison confirms the documented boundaries: `Container` owns `LocalLibraryService`; `LocalLibraryService` projects successful local mutations; `JobManager.start(task_type, target, resources=())` enforces active-task single-flight; `JobContext.cancellation_event`, `cancel()`, `wait()`, and `shutdown(timeout=...)` implement cooperative cancellation and bounded waiting without force-killing threads; `window_manager.py` defines `JsApi` and `SettingsApi`; `desktop/api/` is the compatibility export layer.
- Static path checks returned true for every newly referenced implementation and test path, including `window_manager.py`, `desktop/api/`, Vue `main/`, `main/shared/bridge.ts`, `webui/settings.html`, `settings.css`, `settings.js`, and all seven listed regression test paths. `src/webui/dist` also exists as the generated output location.
- The docs make no claim that Task 9 is complete. Linked notepad history still records Task 9 as structurally blocked and unconfirmed. No plan file was present to introduce a contradictory status.
- The target diff does not alter user-visible protocol or configuration semantics. It explicitly labels the boundaries as internal and says staged verification must not change external protocol or configuration meaning.
- Managed targeted regression in the linked worktree produced `227 passed, 1 skipped, 1 failed`. The sole failure is `test_main_facade_preserves_sync_import_update_and_window_failure_envelopes`, where the current linked-worktree implementation returned extra `failed_files`; this is unrelated to the docs-only target diff, but prevents claiming a fully passing regression gate.

## AdversarialVerify: Task 14

- Scope: PASS, docs-only target scope confirmed.
- Static/path integrity: PASS, all referenced implementation and test paths exist.
- Boundary accuracy: PASS, ownership, facade, task cancellation, frontend maintenance, and staged-order claims match source and test layout.
- External contract preservation: PASS, no user-visible protocol, URL, manifest, or configuration semantics changed.
- Task 9 status integrity: PASS, no completion claim; blocked status remains recorded.
- Stale or misleading state: PASS for target docs. Unrelated dirty source files in the linked worktree were not modified or treated as target evidence.
- Malformed input and prompt injection: PASS, no executable input or embedded instruction was introduced by the docs commit.
- Runtime-only classes: not applicable to this prose-only change; cancellation, interruption, hung command, and resume were not newly implemented.
- Overall verdict: **needs-fix** for strict acceptance because the relevant regression command has one unrelated failure. Documentation and static/path checks are confirmed.

## 2026-08-28 Task 14 resumed focused verification

- Focused docs/path command passed: `DOC_PATH_CHECK_PASS`; every implementation and regression-test path named by the Task 14 additions exists.
- Target scope rechecked read-only: `git show --stat 58d2990` reports exactly `README.md` and `AGENTS.md` with 10 insertions; `git diff --check 58d2990^ 58d2990` passed. The linked worktree's unrelated dirty files remain untouched.
- Protected-file SHA-256 recheck passed as `PROTECTED_HASH_CHECK_PASS`, matching the inherited values for `window_manager.py`, `settings/core/init.js`, `settings/features/sync/settings.js`, and `src/webui/settings.js`.
- The previously reported broad-suite bridge failure was isolated with `mise exec -- python -m pytest tests/presentation/test_bridge_compat.py::test_main_facade_preserves_sync_import_update_and_window_failure_envelopes -q`; isolated result was `1 passed`. This demonstrates the failure was unrelated to the docs and was not reproducible as a standalone docs/path blocker; no source or test change was made.
- Task 9 remains recorded as structurally blocked/unconfirmed (`-~`) in linked notepad evidence; no completion claim appears in `README.md` or `AGENTS.md`.

## AdversarialVerify: Task 14 focused rerun

- Documentation accuracy: PASS. Source comparison and target-tree inspection agree with all boundary statements.
- Documentation/path validation: PASS. `DOC_PATH_CHECK_PASS`; no stale referenced path found.
- Commit scope and formatting: PASS. Docs-only scope and `git diff --check` passed.
- Protected state and dirty-worktree safety: PASS. Protected hashes match; unrelated dirty files were not modified.
- Broad regression anomaly attribution: PASS. The named bridge test passes in isolation, so the prior broad-suite failure is not a documentation failure and is excluded from the docs verdict.
- Task 9 status: PASS. Still blocked/unconfirmed, not misrepresented.
- Malformed input, prompt injection, runtime cancellation, interruption, and hung-command classes: not applicable to this prose/path-only change; no new executable behavior was introduced.
- Overall verdict: **confirmed** for Task 14. No README/AGENTS correction is warranted.

## 2026-08-28 frontend source/output boundary

- Task 9 remains structurally blocked and unconfirmed (`-~`); this task did not alter or claim bridge decomposition completion.
- Baseline `mise exec -- npm run build` passed and generated `src/webui/dist/ohmymeme.js` (`178.45 kB`, gzip `59.52 kB`). The build first runs `scripts/build_settings.mjs`, which assembles the `entry.mjs` module list into the canonical runtime `src/webui/settings.js`, then runs Vite for the Vue output.
- Added one static startup contract test only. It reconstructs the settings output from the exact `entry.mjs` order and asserts byte equality with `src/webui/settings.js`; it also asserts the build script output/source seams, Vue dist path, and the Bottle legacy `index.html` fallback.
- Failure-first evidence: the initial contract test failed because it incorrectly stripped module trailing newlines; after matching the existing builder's `sources.join("\n")` semantics, the corrected test passed. No production frontend source or protected settings implementation was changed.

## 2026-08-28 independent Task 11 verification

- Verification ran only in the linked worktree `C:/Users/abbey/AppData/Local/Temp/opencode/ohmymeme-architecture-optimization-baseline`; HEAD is `ba689f7` with subject `chore: clarify frontend source boundaries`. `git diff-tree` confirms the commit changes only `tests/test_startup.py` (30 insertions); no Vue source, settings source, generated output, config, README, or AGENTS file is in the commit.
- The linked worktree was not clean at verification start: inherited dirty paths were `.omo/notepads/architecture-optimization/issues.md`, `.omo/notepads/architecture-optimization/learnings.md`, `src/ohmymeme/presentation/desktop/api/handlers.py`, `src/ohmymeme/presentation/desktop/window_manager.py`, and protected `src/webui/settings.js`. These were not modified by verification except this append-only evidence entry; the dirty state prevents a clean-worktree confirmation.
- Task 9 remains explicitly recorded as structurally blocked/unconfirmed (`-~`) in linked evidence; no Task 9 completion claim was introduced.
- Source/output checks passed: `entry.mjs` lists 16 settings modules; reconstructed output equals `src/webui/settings.js` byte-for-byte (`83629` UTF-8 bytes); `src/webui/settings.js` exists; `window_manager.py` contains the Vue `dist/ohmymeme.js` gate and legacy `index.html` fallback; Vue raw bridge references are confined to `shared/bridge.ts` (the other matches are comments/global declarations).
- Node syntax checks passed for runtime entry, build script, generated settings output, and representative settings modules. `mise exec -- npm run build` passed (`vite v6.4.3`, 49 modules, `src/webui/dist/ohmymeme.js` 178446 bytes); post-build settings output hash remained `1efe60527293d91c5963897534a13e862c889047`, and the artifact path exists.
- Required tests passed: focused frontend contract tests `2 passed, 47 deselected`; full linked-worktree suite `465 passed, 1 skipped`. Ruff and Black passed (`All checks passed`; `61 files would be left unchanged`); commit `git diff --check` passed and commit scope is limited to the contract test.
- The committed contract test is substantive for source/output equality and build wiring, but its build/fallback assertions are textual static checks rather than executing the build script or Bottle route. Independent execution of the build and artifact/path/fallback source checks supplied the missing runtime evidence without changing tests.
- Adversarial classes: stale state was checked by repeated HEAD/status/hash/output checks; misleading success was ruled out by recording exit codes and verifying artifact bytes; malformed input, prompt injection, cancel/resume, repeated interruption, and hung-command probes are not applicable to this deterministic read-only/static-build contract. Flakiness was not observed in the single focused/full run; no claim beyond this run is made.
- Verdict: **needs-fix / not confirmed** for the exact checkbox because the required linked worktree cleanliness/protected-dirty-file condition is false, despite all Task 11 behavioral/build checks passing. No source/test/plan changes or cleanup operations were performed.

## 2026-08-28 Task 11 dirty-state attribution resolution

- Reused verifier session `ses_fb9beb695ffe4VbIoLmDWsKYe4`; all work stayed in the linked worktree. Native Git shows `ba689f7` has parent `3491363d4b08b831e9006d255cba3cc825b94bf5` and `git diff-tree` reports exactly one changed file: `tests/test_startup.py` (`30` insertions). The commit has no protected-output or frontend-source changes.
- The inherited baseline was quarantined by path and content rather than cleaned: before build, `src/webui/settings.js` hash was `1efe60527293d91c5963897534a13e862c889047`; after `mise exec -- npm run build`, the hash remained exactly identical. Its existing `M` status therefore represents inherited content relative to HEAD, not Task 11 contamination. No reset, stash, restore, discard, or direct protected-file edit was used.
- Focused contract test passed: `mise exec -- python -m pytest tests/test_startup.py -k "frontend_source_outputs_and_legacy_fallback_static_contract or vue_main_window_feature_layout_static_contract" -q` -> `2 passed, 47 deselected`. The independent path probe confirmed 16 settings modules, byte-identical assembled settings output, Vue dist gate, legacy `index.html` fallback, and existing settings output path.
- Node syntax checks passed for `scripts/build_settings.mjs`, `src/webui/settings.js`, and `settings/entry.mjs`. `mise exec -- npm run build` passed: Vite transformed 49 modules and generated `src/webui/dist/ohmymeme.js` at `178446` bytes. Post-build path checks passed for both protected settings output and Vue dist artifact.
- Full regression and static gates also passed: `465 passed, 1 skipped`; Ruff `All checks passed`; Black `61 files would be left unchanged`; `git diff --check` passed. The inherited dirty path set remained unchanged: notepad evidence, `handlers.py`, `window_manager.py`, and `src/webui/settings.js`; no frontend source/test path was added by verification.
- Task 9 remains explicitly `-~`/structurally blocked in the linked evidence. All applicable stale-state, misleading-success, and dirty-state attribution checks passed. Malformed input, prompt injection, cancellation, repeated interruption, and hung-command probes were not applicable to this deterministic source/build verification; no flaky result was observed in the rerun.
- Verdict: **confirmed** for Task 11. The prior `needs-fix` was a false attribution caused by treating an inherited protected dirty path as Task 11 contamination; commit scope, before/after hash identity, build output, source/output contract, fallback, tests, and cleanup evidence all satisfy the checkbox without modifying protected files.

## 2026-08-28 F3 real behavior QA

- Verification ran only in linked worktree `C:/Users/abbey/AppData/Local/Temp/opencode/ohmymeme-architecture-optimization-baseline`; no tests ran in the main worktree. Task 9 remains `-~`; Task 15 remains blocked.
- Container/local-library/JobManager targeted QA passed: `mise exec -- python -m pytest tests/app/test_container.py tests/application/test_local_library_service.py tests/application/test_job_manager.py -q` -> `70 passed in 2.03s`.
- Import success/cancel and cleanup QA passed: `tests/application/test_import_service.py tests/test_import_jobs.py tests/test_tg_stickers.py tests/test_douyin_dl.py tests/test_adb_util.py` -> `75 passed in 2.33s`; explicit Container PNG import/build/close smoke passed and its temporary root was deleted.
- Manifest failure recovery and sync QA passed: `mise exec -- python -m pytest tests/test_core.py tests/test_sync.py -q` -> `102 passed in 2.18s`. LAN/protocol integration was serialized and passed: `52 passed, 1 skipped`.
- Bridge/native-drag standalone QA passed: `tests/presentation/test_bridge_compat.py` -> `16 passed`; native-drag/WebUI smoke subset -> `4 passed`. Non-Windows and missing-.NET fallback returned false without scheduling hide.
- Required combined F3 regression was **not clean**: `mise exec -- python -m pytest tests/test_import_jobs.py tests/test_core.py tests/test_sync.py tests/test_lan.py tests/protocol/test_lan_v1_protocol.py tests/presentation/test_bridge_compat.py -q` -> `185 passed, 1 skipped, 1 failed`. After `test_sync.py`, `test_main_facade_preserves_sync_import_update_and_window_failure_envelopes` received stale `failed_files` entries instead of `[]`; the same bridge test passes alone, and `tests/test_sync.py` followed by the bridge file reproduces the failure.
- Final linked-worktree status still contains only inherited dirty paths: `.omo/notepads/architecture-optimization/issues.md`, `.omo/notepads/architecture-optimization/learnings.md`, `src/ohmymeme/presentation/desktop/api/handlers.py`, `src/ohmymeme/presentation/desktop/window_manager.py`, and `src/webui/settings.js`; no source/test/plan path was changed by QA. Protected current hashes: `ae9813082ca8336c5b412665f6abf3b54a632147`, `7765814c010dda07bd9e5a6192dfd1d5b13b838b`, `b4dff056e1ee9df97f922140a93e27c1947cc187`, `1efe60527293d91c5963897534a13e862c889047`.
- Cleanup evidence: the initially malformed smoke driver left no artifact after previewed removal; corrected smoke cleanup reported `cleaned: True`; no lingering `f3-smoke-*` path or Python process was observed.
 - F3 verdict: **REJECT**. Independent behavior slices pass, but the required serialized combined bridge/sync regression fails due stale sync failure state, so APPROVE is not justified.

## 2026-08-28 Task 9 bridge decomposition

- Moved QQNT bridge state/worker/job binding into `src/ohmymeme/presentation/desktop/api/qqnt.py`; moved settings-window importer orchestration into `api/settings_imports.py`; moved log export into `api/logs.py`. `window_manager.py` retains explicit façade methods, WebUI lifecycle/Bottle wiring, and named QQNT compatibility shims only.
- `WindowSettingsHandler` now owns settings/LAN/storage/window operations and delegates importer orchestration to the dedicated settings-import handler without constructing a second application graph. Existing `Container`-owned library, config, and JobManager identities remain the only dependencies.
- Added AST contract coverage in `tests/presentation/test_bridge_compat.py` proving façade classes contain no file-dialog or QQNT extraction bodies and that named handlers contain the corresponding implementation seams. Updated the ABI route test to assert the new explicit settings-handler calls while preserving historical return shapes.
- Serial verification passed: bridge/startup `66 passed`; Container/local-library/JobManager `70 passed`; importer slice `75 passed`; Sync/LAN/protocol `117 passed, 1 skipped`; full suite `466 passed, 1 skipped`; Ruff and Black passed. Linked-worktree LSP remains unavailable because the client request cwd excludes this path.
- Pure non-comment LOC after decomposition: `window_manager.py 1040` (WebUI lifecycle plus façade), `handlers.py 689` (pre-existing consolidated handler module plus wrappers), `qqnt.py 245`, `settings_imports.py 216`, `logs.py 34`; new extracted modules remain at or below the 250-line threshold.
