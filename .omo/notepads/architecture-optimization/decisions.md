# Decisions — architecture-optimization

Architectural choices and rationales discovered during work on this plan.

---

## 2026-08-27 baseline

- Expected-change allowlist is limited to `.omo/notepads/architecture-optimization/*` baseline evidence/state; no product source, tests, README, AGENTS, build/config files, or protected dirty files.
- Keep the native isolated worktree at `C:/Users/abbey/AppData/Local/Temp/opencode/ohmymeme-architecture-optimization-baseline` for later workers; do not remove it during baseline cleanup.
