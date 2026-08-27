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
