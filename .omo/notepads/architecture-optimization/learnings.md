# Learnings — architecture-optimization

Conventions and successful approaches discovered during work on this plan.

---

## 2026-08-27 baseline

- Native `git worktree add -b` safely created a separate physical worktree from committed `HEAD` without carrying main-worktree dirty content.
- The isolated worktree must install dependencies into its own `.venv`; the project's `mise run setup` assumes pip exists and failed before installation, so `mise exec -- uv pip install --python .venv\Scripts\python.exe ...` was used without changing repository files.

## 2026-08-27 local projection invariants

- `LocalLibraryService` deliberately keeps a successful SQLite mutation when manifest projection fails; a recoverable projection failure returns `False` after restoring the prior manifest, while restore failure re-raises the projection error with the restore error as its cause.
- `ManifestBuilder.build()` writes version 3 before deleting empty collections, and nested collection membership is serialized by filename rather than database ID; direct tests now assert both database rows and manifest JSON.
