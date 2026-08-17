# Learnings — full-project-modular-refactor

Conventions, patterns, and successful approaches discovered during work on this plan.

_Auto-scaffolded by /start-work. Append new entries below - never overwrite._

---

- 2026-08-18T00:00:00Z: Created task-owned worktree `D:\UserFiles\Development\Worktrees\OhMyMeme-modular-refactor` on branch `refactor/full-project-modular` at HEAD `891f95c6d136bff41625dcd7fbb23d73474a6dce`; primary worktree was clean and no product files were changed.
- 2026-08-18: Todo 6 freezes six offline package contracts. Linux application updates remain AppImage-only; deb and rpm are release artifacts but are not updater-selectable.
- 2026-08-18: Todo 4 recovery seams use same-directory temporary files plus `os.replace`; callers must receive write failures rather than treating stale manifests as success. Storage migration must reverse completed moves when persisting `cache_dir` fails.
