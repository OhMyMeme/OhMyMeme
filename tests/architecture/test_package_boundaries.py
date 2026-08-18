"""Enforce the source package layout and dependency direction rules."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PACKAGE = SRC / "ohmymeme"


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return {module for module in modules if module}


def _files_in(package: str) -> list[Path]:
    return _python_files(PACKAGE / package)


def test_business_python_lives_only_in_ohmymeme() -> None:
    """Given the source tree, only the business package contains Python modules."""
    source_python = _python_files(SRC)
    assert all(path.is_relative_to(PACKAGE) for path in source_python)
    assert not [path for path in SRC.glob("*.py")]


def test_src_imports_are_removed() -> None:
    """Given business modules, imports use ohmymeme rather than the old src path."""
    offenders = {
        str(path.relative_to(ROOT)): module
        for path in _python_files(PACKAGE)
        for module in _imported_modules(path)
        if module == "src" or module.startswith("src.")
    }
    assert not offenders


def test_core_does_not_depend_on_outer_layers() -> None:
    """Given core modules, they do not depend on outer layers."""
    forbidden = (
        "ohmymeme.services",
        "ohmymeme.integrations",
        "ohmymeme.presentation",
    )
    offenders = [
        (path, module)
        for path in _files_in("core")
        for module in _imported_modules(path)
        if module.startswith(forbidden)
    ]
    assert not offenders


def test_integrations_do_not_depend_on_presentation() -> None:
    """Given integration adapters, they do not import presentation code."""
    offenders = [
        (path, module)
        for path in _files_in("integrations")
        for module in _imported_modules(path)
        if module.startswith("ohmymeme.presentation")
    ]
    assert not offenders


def test_sync_does_not_depend_on_lan() -> None:
    """Given remote-sync services, they do not import LAN services."""
    offenders = [
        (path, module)
        for path in _files_in("services/sync")
        for module in _imported_modules(path)
        if module.startswith("ohmymeme.services.lan")
    ]
    assert not offenders


def test_lan_protocol_does_not_depend_on_server() -> None:
    """Given the LAN wire protocol, it remains independent of its server."""
    protocol = PACKAGE / "services" / "lan" / "protocol.py"
    imported = _imported_modules(protocol)
    assert "ohmymeme.services.lan.server" not in imported
