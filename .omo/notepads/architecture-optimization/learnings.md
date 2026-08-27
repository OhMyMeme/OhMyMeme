# Learnings — architecture-optimization

Conventions and successful approaches discovered during work on this plan.

---

## 2026-08-27 baseline

- Native `git worktree add -b` safely created a separate physical worktree from committed `HEAD` without carrying main-worktree dirty content.
- The isolated worktree must install dependencies into its own `.venv`; the project's `mise run setup` assumes pip exists and failed before installation, so `mise exec -- uv pip install --python .venv\Scripts\python.exe ...` was used without changing repository files.
