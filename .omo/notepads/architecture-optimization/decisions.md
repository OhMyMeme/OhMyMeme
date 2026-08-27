# Decisions — architecture-optimization

Architectural choices and rationales discovered during work on this plan.

---

## 2026-08-27 baseline

- Expected-change allowlist is limited to `.omo/notepads/architecture-optimization/*` baseline evidence/state; no product source, tests, README, AGENTS, build/config files, or protected dirty files.
- Keep the native isolated worktree at `C:/Users/abbey/AppData/Local/Temp/opencode/ohmymeme-architecture-optimization-baseline` for later workers; do not remove it during baseline cleanup.

## 2026-08-27 public projection boundary

- Use `project_manifest()` as the public projection operation and `apply_remote_manifest_operation()` as the explicit remote planning/apply operation. Keep `_project_after_mutation()` private and retain the old `apply_remote_operation()` name as a compatibility alias rather than changing existing callers' observable result shape.
- Do not move importer-owned projection or alter the manifest format in this task; the requested boundary is limited to sync/LAN cross-module direct private-call removal.
