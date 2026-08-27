# Problems — architecture-optimization

Unresolved blockers and technical debt discovered during work on this plan.

---

## 2026-08-27 baseline

- No unresolved isolation blocker remains. GitButler-specific status is unavailable in the native worktree, but physical isolation and native Git status are independently verified.

## 2026-08-27 public projection boundary

- No product blocker remains. Linked-worktree LSP path rejection is an environment limitation already recorded; pytest, ruff, black, static private-call scan, and real smoke evidence are available.
