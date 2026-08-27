# Problems — architecture-optimization

Unresolved blockers and technical debt discovered during work on this plan.

---

## 2026-08-27 baseline

- No unresolved isolation blocker remains. GitButler-specific status is unavailable in the native worktree, but physical isolation and native Git status are independently verified.

## 2026-08-27 public projection boundary

- No product blocker remains. Linked-worktree LSP path rejection is an environment limitation already recorded; pytest, ruff, black, static private-call scan, and real smoke evidence are available.

## 2026-08-27 explicit pull metadata boundary

- The concrete mixed-resource `library=None` singleton defect is resolved in the linked worktree. LSP diagnostics remain unavailable because the client rejects paths outside its main-worktree request cwd; validation relies on serial tests, static gates, and a real temporary-root smoke.

## 2026-08-28 importer ownership

- No new production blocker was observed after routing QQNT output through the canonical library boundary. Linked-worktree LSP remains unavailable due to the known request-cwd restriction; serial tests and static checks provide the verification evidence.
- Focused and full serial verification passed after the cancellation rollback and Telegram cleanup-error fixes; linked-worktree LSP remains unavailable for the known request-cwd reason.
- The real mid-callback race is closed by event-aware import-batch compensation; no remaining Task 8 ownership blocker was reproduced in the final serial verification.

## 2026-08-28 shared catalog query predicates

- No Task 12 production blocker remains. The only environment limitation is linked-worktree LSP path rejection; serial SQLite tests and static checks are available evidence.
- UltraQA: malformed/empty tags and invalid/virtual collection combinations pass; stale-state checks covered pagination beyond the result set and recent count consistency; dirty-worktree scope remained limited to the three pre-existing protected files plus Task 12 files; no cancel/resume, hung-command, repeated-interruption, or prompt-injection condition was triggered.
