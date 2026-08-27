# Issues — architecture-optimization

Problems and gotchas encountered during work on this plan.

---

## 2026-08-27 baseline

- `but status -fv --no-hint` cannot run in the native isolated worktree because GitButler is not configured there; it returned `No GitButler project found at .`. Main-worktree GitButler status was captured separately and remained unchanged.
- `mise run setup` failed at `python -m pip install --upgrade pip` because the auto-created uv venv has no pip. This was resolved with managed `uv pip` installation in the isolated venv only.
