"""质量门禁配置契约。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(relative_path: str) -> str:
    """读取仓库内的质量配置文件。"""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_mise_exposes_each_quality_gate() -> None:
    """Given quality tooling, when mise loads tasks, then every gate is addressable."""
    mise_config = _source("mise.toml")

    missing = [
        task_name
        for task_name in (
            "lint",
            "typecheck-python",
            "test-python",
            "typecheck-frontend",
            "test-frontend",
            "build-frontend",
            "test-contracts",
            "e2e",
        )
        if f"[tasks.{task_name}]" not in mise_config
    ]
    assert not missing


def test_python_gate_uses_strict_scoped_configuration() -> None:
    """Given strict config, when loaded, then its scope is explicit."""
    pyproject = _source("pyproject.toml")

    assert 'typeCheckingMode = "all"' in pyproject
    for scope in (
        "src/ohmymeme/__init__.py",
        "src/ohmymeme/__main__.py",
        "src/ohmymeme/presentation/desktop/api/__init__.py",
        "src/ohmymeme/presentation/desktop/routes/contributors.py",
        "src/ohmymeme/presentation/desktop/routes/media.py",
        "src/ohmymeme/presentation/desktop/routes/pages.py",
        "src/ohmymeme/app/ports.py",
        "src/ohmymeme/services/ports.py",
        "src/ohmymeme/services/lifecycle.py",
        "tests/architecture/test_package_boundaries.py",
        "tests/architecture/test_import_boundaries.py",
        "tests/architecture/test_quality_gates.py",
    ):
        assert f'"{scope}"' in pyproject
    exclusions = pyproject.split("exclude = [", maxsplit=1)[1]
    assert "Existing untyped core modules" not in exclusions
    for platform_exception in (
        "src/ohmymeme/integrations/platform/clipboard.py",
        "src/ohmymeme/integrations/platform/hotkey.py",
        "src/ohmymeme/integrations/platform/native_drag.py",
        "src/ohmymeme/integrations/platform/system.py",
        "src/ohmymeme/integrations/platform/tray.py",
        "src/ohmymeme/presentation/desktop/window_manager.py",
    ):
        assert f'"{platform_exception}"' in pyproject


def test_python_tasks_do_not_reenter_mise() -> None:
    """Given Python gates, when invoked, then their interpreter is active."""
    mise_config = _source("mise.toml")

    assert "task.run_auto_install = false" in mise_config
    assert "run = 'python -m pytest'" in mise_config
    assert "run = 'python -m scripts.package_smoke'" in mise_config


def test_python_quality_dependencies_are_pinned() -> None:
    """Given setup, when it runs, then quality tools are reproducible."""
    requirements_path = ROOT / "requirements-dev.txt"

    assert requirements_path.is_file()
    requirements = requirements_path.read_text(encoding="utf-8")
    for dependency in (
        "basedpyright==1.39.10",
        "black==26.5.1",
        "pytest==9.1.1",
        "ruff==0.16.3",
    ):
        assert dependency in requirements
    assert "requirements-dev.txt" in _source("environment.yml")


def test_frontend_gate_has_typed_test_dependencies_and_commands() -> None:
    """Given package scripts, when loaded, then typecheck and test tools exist."""
    package = _source("package.json")

    for script in ("typecheck", "test", "test:e2e"):
        assert f'"{script}":' in package
    for dependency in (
        "@playwright/test",
        "@vue/test-utils",
        "typescript",
        "vitest",
        "vue-tsc",
    ):
        assert f'"{dependency}":' in package
    playwright_config = _source("playwright.config.ts")
    assert "outputDir: join(" in playwright_config
    assert "tmpdir()" in playwright_config
    assert "--pass-with-no-tests" not in package
    assert (ROOT / "tests/e2e/main-window.spec.js").is_file()
    assert "Pager.vue" in _source("tests/frontend/quality_gate.test.js")
    assert "npm exec playwright install chromium" in _source("mise.toml")
    tsconfig = _source("tsconfig.json")
    assert '"src/ohmymeme/presentation/frontend/main/app/**/*.vue"' in tsconfig
    assert '"src/ohmymeme/presentation/frontend/main/features/**/*.vue"' in tsconfig
    assert '"src/ohmymeme/presentation/frontend/main/shared/**/*.ts"' in tsconfig


def test_check_runs_package_smoke_and_browser_tests() -> None:
    """Given the aggregate gate, when it runs, then no required gate is omitted."""
    mise_config = _source("mise.toml")

    assert "mise run package-smoke" in mise_config
    assert "mise run e2e" in mise_config


def test_ci_uses_immutable_quality_gate_actions() -> None:
    """Given the CI gate, when Actions runs it, then actions are commit pinned."""
    workflow = _source(".github/workflows/check.yml")

    for action in ("actions/checkout", "jdx/mise-action"):
        assert re.search(rf"uses: {re.escape(action)}@[0-9a-f]{{40}}", workflow)
    assert "mise run check" in workflow
    assert "npm exec playwright install --with-deps chromium" in workflow
