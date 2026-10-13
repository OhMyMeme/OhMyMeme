#!/usr/bin/env python3
"""Validate and stage the nine official plugin distributions."""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from email.parser import Parser
from importlib import import_module
from importlib import metadata as importlib_metadata
from importlib import util as importlib_util
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MANIFEST_TARGET = Path("ohmymeme") / "config" / "plugin-manifest.json"
ENTRY_POINT_GROUP = "ohmymeme.plugins.v1"
SCHEMA_VERSION = 1
_PLUGIN_ROW_FIELDS = {
    "dependencies",
    "distribution",
    "factory",
    "id",
    "license",
    "license_files",
    "license_files_disabled",
    "metadata_files",
    "module",
    "module_files",
    "optional_dependencies",
    "optional_dependencies_disabled",
    "resource_files",
    "resources_disabled",
}


class PackagingError(ValueError):
    """A packaging contract failed."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


def _manifest_module():
    # Load the host validator only for its frozen descriptor contract.
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    return import_module("ohmymeme.core.plugins.manifest")


def _seeding_module():
    # Load the host install transaction without importing the application layer.
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    return import_module("ohmymeme.core.plugins.runtime.seeding")


def _distribution_name(provider_id):
    # Distribution names preserve the published official identity.
    suffix = (
        provider_id.replace(".", "-")
        if provider_id.startswith("sync.")
        else provider_id.rsplit(".", 1)[-1]
    )
    return "ohmymeme-plugin-" + suffix


def _module_name(provider_id):
    # Sync modules retain the published sync namespace in their package root.
    prefix = (
        "ohmymeme_plugin_sync_"
        if provider_id.startswith("sync.")
        else "ohmymeme_plugin_"
    )
    return prefix + provider_id.rsplit(".", 1)[-1]


def _package_dir(provider_id):
    # Each official provider owns a sibling package directory.
    return ROOT / "plugins" / provider_id


def _posix_path(path):
    # Staging manifests use portable relative paths.
    return Path(path).as_posix()


def _safe_relative_path(value, field):
    # Reject absolute paths and traversal before touching staging files.
    if not isinstance(value, str) or not value:
        raise PackagingError([f"{field}: expected non-empty relative path"])
    candidate = Path(value.replace("/", os.sep))
    if candidate.is_absolute() or value.startswith(("/", "\\")):
        raise PackagingError([f"{field}: absolute path is not allowed"])
    if any(part in ("", ".", "..") for part in candidate.parts):
        raise PackagingError([f"{field}: unsafe relative path {value!r}"])
    return candidate


def _sha256_bytes(data):
    # Hash the bytes actually consumed by the parity check.
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    # Hash a file without relying on metadata or self-reported values.
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path, field):
    # Decode JSON while retaining the original bytes for manifest parity.
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise PackagingError([f"{field}: cannot read {path}: {error}"])
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagingError([f"{field}: invalid UTF-8 JSON: {error}"])


def _load_source_manifest(path):
    # Validate the authored manifest and its canonical bytes before staging.
    manifest_module = _manifest_module()
    raw, value = _read_json(path, "source manifest")
    errors = []
    try:
        descriptors = manifest_module.validate_manifest(value, ENTRY_POINT_GROUP)
    except ValueError as error:
        errors.extend(getattr(error, "errors", (str(error),)))
        descriptors = ()
    try:
        canonical_raw = manifest_module.canonical_document(value)
    except (TypeError, ValueError) as error:
        errors.append(f"source manifest: cannot serialize canonical bytes: {error}")
    else:
        if raw != canonical_raw:
            errors.append(
                "source manifest: bytes are not canonical_document(value) "
                f"(actual={_sha256_bytes(raw)}, "
                f"canonical={_sha256_bytes(canonical_raw)})"
            )
    if errors:
        raise PackagingError(errors)
    return raw, value, descriptors


def _project_data(package_dir, provider_id):
    # Read official distribution metadata directly from pyproject.toml.
    path = package_dir / "pyproject.toml"
    errors = []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise PackagingError([f"{provider_id}.pyproject: {error}"])
    project = data.get("project")
    if not isinstance(project, dict):
        raise PackagingError([f"{provider_id}.project: missing required table"])
    required = ("name", "version", "description", "requires-python", "license")
    for field in required:
        value = project.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{provider_id}.project.{field}: missing official metadata")
    expected_distribution = _distribution_name(provider_id)
    if project.get("name") != expected_distribution:
        errors.append(
            f"{provider_id}.project.name: expected {expected_distribution}, "
            f"got {project.get('name')!r}"
        )
    if project.get("license-files") != ["LICENSE"]:
        errors.append(f"{provider_id}.project.license-files: expected ['LICENSE']")
    build_system = data.get("build-system")
    if not isinstance(build_system, dict):
        errors.append(f"{provider_id}.build-system: missing official metadata")
    elif build_system.get("build-backend") != "setuptools.build_meta":
        errors.append(
            f"{provider_id}.build-system.build-backend: expected setuptools.build_meta"
        )
    entry_points = project.get("entry-points")
    group = (
        entry_points.get(ENTRY_POINT_GROUP) if isinstance(entry_points, dict) else None
    )
    if not isinstance(group, dict):
        errors.append(
            f"{provider_id}.project.entry-points.{ENTRY_POINT_GROUP}: "
            "missing official metadata"
        )
        group = {}
    expected_name = provider_id
    package_root = _module_name(provider_id)
    expected_value = f"{package_root}:create_plugin"
    if group.get(expected_name) != expected_value:
        errors.append(
            f"{provider_id}.project.entry-points.{ENTRY_POINT_GROUP}.{provider_id}: "
            f"expected {expected_value}, got {group.get(provider_id)!r}"
        )
    if set(group) != {expected_name}:
        errors.append(
            f"{provider_id}.project.entry-points.{ENTRY_POINT_GROUP}: "
            f"expected only {expected_name!r}"
        )
    package_find = (
        data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
    )
    where = package_find.get("where") if isinstance(package_find, dict) else None
    if not isinstance(where, list) or "src" not in where:
        errors.append(
            f"{provider_id}.tool.setuptools.packages.find.where: expected src"
        )
    if errors:
        raise PackagingError(errors)
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(value, str) and value.strip() for value in dependencies
    ):
        raise PackagingError(
            [f"{provider_id}.project.dependencies: expected string array"]
        )
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict) or any(
        not isinstance(name, str)
        or not isinstance(values, list)
        or not all(isinstance(value, str) and value.strip() for value in values)
        for name, values in optional.items()
    ):
        raise PackagingError(
            [f"{provider_id}.project.optional-dependencies: expected string arrays"]
        )
    optional_values = [
        f"{name}:{value}" for name, values in optional.items() for value in values
    ]
    return {
        "provider_id": provider_id,
        "package_dir": package_dir,
        "project": project,
        "distribution": expected_distribution,
        "module": package_root,
        "factory": expected_value,
        "dependencies": tuple(dependencies),
        "optional_dependencies": tuple(optional_values),
    }


def _source_files(info):
    # Enumerate only owned package modules and package data.
    package_root = info["package_dir"] / "src" / info["module"]
    if not package_root.is_dir():
        raise PackagingError(
            [f"{info['provider_id']}.module: missing package root {package_root}"]
        )
    module_files = sorted(
        path for path in package_root.rglob("*.py") if "__pycache__" not in path.parts
    )
    init_path = package_root / "__init__.py"
    if not init_path.is_file():
        raise PackagingError(
            [
                f"{info['provider_id']}.module: missing factory module "
                f"{_posix_path(Path(info['module']) / '__init__.py')}"
            ]
        )
    resource_files = sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    )
    license_files = sorted(
        path
        for path in info["package_dir"].iterdir()
        if path.is_file()
        and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))
    )
    info["module_files"] = tuple(
        _posix_path(Path(info["module"]) / path.relative_to(package_root))
        for path in module_files
    )
    info["resource_files"] = tuple(
        _posix_path(Path(info["module"]) / path.relative_to(package_root))
        for path in resource_files
    )
    info["license_files"] = tuple(
        _posix_path(path.relative_to(info["package_dir"])) for path in license_files
    )
    info["module_hashes"] = {
        name: _sha256_file(info["package_dir"] / "src" / name)
        for name in info["module_files"]
    }
    info["resource_hashes"] = {
        name: _sha256_file(info["package_dir"] / "src" / name)
        for name in info["resource_files"]
    }
    info["license_hashes"] = {
        name: _sha256_file(info["package_dir"] / name) for name in info["license_files"]
    }


def _validate_plugin_imports(info):
    # Official packages may depend on narrow core ports, never host implementations.
    forbidden = (
        "ohmymeme.app",
        "ohmymeme.integrations",
        "ohmymeme.presentation",
        "ohmymeme.services",
    )
    errors = []
    for name in info["module_files"]:
        path = info["package_dir"] / "src" / name
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            errors.append(f"{info['provider_id']}.module.{name}: {error}")
            continue
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        for module in imports:
            if module.startswith(forbidden):
                errors.append(
                    f"{info['provider_id']}.module.{name}: reverse host import {module}"
                )
    return errors


def _purge_plugin_modules(module_names):
    # Remove source imports before loading same-named modules from frozen staging.
    for name in tuple(sys.modules):
        if any(name == root or name.startswith(root + ".") for root in module_names):
            del sys.modules[name]


def _probe_factories(infos, roots, location):
    # Import real factories and verify the provider identity exposed by each instance.
    for root in reversed(tuple(roots)):
        root = str(root)
        if root not in sys.path:
            sys.path.insert(0, root)
    _purge_plugin_modules([info["module"] for info in infos])
    rows = []
    errors = []
    for info in infos:
        provider_id = info["provider_id"]
        try:
            module = import_module(info["module"])
            origin = Path(module.__file__).resolve() if module.__file__ else None
            expected_root = (
                info["package_dir"] / "src" / info["module"]
                if location == "source"
                else Path(roots[0]) / info["module"]
            ).resolve()
            if origin is None or not origin.is_relative_to(expected_root):
                errors.append(
                    f"{provider_id}.module: {location} import resolved to {origin}, "
                    f"expected under {expected_root}"
                )
            factory = getattr(module, "create_plugin", None)
            if not callable(factory):
                errors.append(f"{provider_id}.factory: create_plugin is not callable")
                continue
            instance = factory()
            actual_provider = getattr(instance, "provider_id", None)
            actual_api = getattr(instance, "api_version", None)
            if actual_provider != provider_id:
                errors.append(
                    f"{provider_id}.factory.provider_id: expected {provider_id}, "
                    f"got {actual_provider!r}"
                )
            if type(actual_api) is not int or actual_api != SCHEMA_VERSION:
                errors.append(
                    f"{provider_id}.factory.api_version: expected {SCHEMA_VERSION}, "
                    f"got {actual_api!r}"
                )
            rows.append(
                {
                    "id": provider_id,
                    "module": info["module"],
                    "factory": info["factory"],
                    "origin": str(origin) if origin else "",
                    "provider_id": actual_provider,
                    "api_version": actual_api,
                    "factory_callable": True,
                }
            )
        except Exception as error:
            errors.append(
                f"{provider_id}.factory: import or construction failed: {error}"
            )
    return rows, errors


def _validate_repo_plugin_json(provider_id, descriptor):
    # Repository plugin.json must mirror the canonical identity exactly.
    path = _package_dir(provider_id) / "plugin.json"
    if not path.is_file():
        return [f"{provider_id}.plugin.json: missing repository plugin.json"]
    try:
        _, value = _read_json(path, f"{provider_id}.plugin.json")
    except PackagingError as error:
        return list(error.errors)
    if not isinstance(value, dict):
        return [f"{provider_id}.plugin.json: expected object"]
    expected = {
        "id": descriptor.id,
        "entry": descriptor.value,
        "api_version": descriptor.api_version,
        "package_root": descriptor.package_root,
        "capabilities": list(descriptor.capabilities.names),
    }
    errors = []
    for field, want in expected.items():
        if value.get(field) != want:
            errors.append(
                f"{provider_id}.plugin.json.{field}: expected {want!r}, "
                f"got {value.get(field)!r}"
            )
    allowed = set(expected) | {"name", "version"}
    for field in sorted(set(value) - allowed):
        errors.append(f"{provider_id}.plugin.json.{field}: unexpected property")
    return errors


def _source_analysis(descriptors):
    # Inspect source metadata, owned files and import direction without execution.
    infos = []
    errors = []
    for descriptor in descriptors:
        info = None
        try:
            info = _project_data(_package_dir(descriptor.id), descriptor.id)
            if info["module"] != descriptor.package_root:
                errors.append(
                    f"{descriptor.id}.module: expected {descriptor.package_root}, "
                    f"got {info['module']}"
                )
            if info["factory"] != descriptor.value:
                errors.append(
                    f"{descriptor.id}.factory: expected {descriptor.value}, "
                    f"got {info['factory']}"
                )
            errors.extend(_validate_repo_plugin_json(descriptor.id, descriptor))
            _source_files(info)
            errors.extend(_validate_plugin_imports(info))
            infos.append(info)
        except PackagingError as error:
            errors.extend(error.errors)
        except OSError as error:
            errors.append(f"{descriptor.id}.package: {error}")
    return infos, errors


def _metadata_values(path):
    # Parse distribution metadata fields from the actual staged METADATA file.
    try:
        message = Parser().parsestr(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return None, [f"metadata {path}: cannot read: {error}"]
    required = ("Name", "Version", "Summary", "Requires-Python", "License-Expression")
    errors = []
    values = {}
    for field in required:
        value = message.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"metadata {path}: missing field {field}")
        else:
            values[field] = value
    values["Requires-Dist"] = tuple(message.get_all("Requires-Dist", []))
    values["License-File"] = tuple(message.get_all("License-File", []))
    return values, errors


def _entry_points_from_file(path):
    # Parse the standard entry_points.txt file without trusting a report.
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        return (), [f"metadata {path}: cannot read entry points: {error}"]
    group = None
    entries = []
    errors = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        if "=" not in line or group is None:
            errors.append(f"metadata {path}: malformed entry point line {line!r}")
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        entries.append((group, name, value))
    return tuple(entries), errors


def _expected_dist_info_names(infos):
    # PEP 427 normalizes distribution name separators in dist-info directories.
    return {
        "{}-{}.dist-info".format(
            info["distribution"].replace("-", "_").replace(".", "_"),
            info["project"]["version"],
        )
        for info in infos
    }


def _validate_staged_dist_info_names(staging, infos):
    # Reject every staged dist-info outside the exact nine official names.
    expected = _expected_dist_info_names(infos)
    errors = []
    for path in sorted(item for item in staging.rglob("*.dist-info") if item.is_dir()):
        relative = _posix_path(path.relative_to(staging))
        if path.parent != staging or path.name not in expected:
            errors.append(
                "staging distribution: unknown or misplaced dist-info "
                f"{relative}; expected only {sorted(expected)!r}"
            )
    return errors


def _validate_staging_manifest(staging_manifest_path, infos, staging):
    # Validate the generated staging inventory using actual files and source hashes.
    errors = []
    try:
        _, value = _read_json(staging_manifest_path, "staging manifest")
    except PackagingError as error:
        return {}, list(error.errors)
    errors.extend(_validate_staged_dist_info_names(staging, infos))
    if not isinstance(value, dict):
        return {}, ["staging manifest: expected object"]
    expected_top = {"schema_version", "manifest_target", "packages"}
    extra = sorted(set(value) - expected_top)
    missing = sorted(expected_top - set(value))
    errors.extend(f"staging manifest.{field}: unexpected property" for field in extra)
    errors.extend(
        f"staging manifest.{field}: missing required field" for field in missing
    )
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != SCHEMA_VERSION
    ):
        errors.append(f"staging manifest.schema_version: expected {SCHEMA_VERSION}")
    if value.get("manifest_target") != _posix_path(MANIFEST_TARGET):
        errors.append(
            "staging manifest.manifest_target: expected "
            f"{_posix_path(MANIFEST_TARGET)}"
        )
    packages = value.get("packages")
    if not isinstance(packages, list):
        errors.append("staging manifest.packages: expected array")
        return value, errors
    info_by_id = {info["provider_id"]: info for info in infos}
    rows = {}
    for index, row in enumerate(packages):
        prefix = f"staging manifest.packages[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix}: expected object")
            continue
        errors.extend(
            f"{prefix}.{field}: unexpected property"
            for field in sorted(set(row) - _PLUGIN_ROW_FIELDS)
        )
        errors.extend(
            f"{prefix}.{field}: missing required field"
            for field in sorted(_PLUGIN_ROW_FIELDS - set(row))
        )
        provider_id = row.get("id")
        if not isinstance(provider_id, str) or provider_id not in info_by_id:
            errors.append(f"{prefix}.id: unknown official provider {provider_id!r}")
            continue
        if provider_id in rows:
            errors.append(
                f"staging manifest.packages: duplicate provider {provider_id}"
            )
            continue
        rows[provider_id] = row
    for info in infos:
        provider_id = info["provider_id"]
        if provider_id not in rows:
            errors.append(f"staging manifest.packages: missing provider {provider_id}")
    if tuple(row.get("id") for row in packages if isinstance(row, dict)) != tuple(
        info["provider_id"] for info in infos
    ):
        errors.append("staging manifest.packages: expected canonical provider order")

    for provider_id, row in rows.items():
        info = info_by_id[provider_id]
        prefix = f"staging manifest.packages[{provider_id}]"
        expected_values = {
            "distribution": info["distribution"],
            "module": info["module"],
            "factory": info["factory"],
            "license": info["project"]["license"],
            "dependencies": list(info["dependencies"]),
            "optional_dependencies": list(info["optional_dependencies"]),
            "module_files": list(info["module_files"]),
            "resource_files": list(info["resource_files"]),
            "license_files": list(info["license_files"]),
        }
        for field, expected in expected_values.items():
            if row.get(field) != expected:
                errors.append(
                    f"{prefix}.{field}: expected {expected!r}, got {row.get(field)!r}"
                )
        for field in ("module_files", "resource_files", "license_files"):
            values = row.get(field)
            if not isinstance(values, list) or any(
                not isinstance(item, str) for item in values
            ):
                errors.append(f"{prefix}.{field}: expected string array")
                continue
            if len(values) != len(set(values)):
                errors.append(f"{prefix}.{field}: duplicate staged path")
            for item_index, item in enumerate(values):
                try:
                    relative = _safe_relative_path(
                        item, f"{prefix}.{field}[{item_index}]"
                    )
                except PackagingError as error:
                    errors.extend(error.errors)
                    continue
                actual = staging / relative
                if not actual.is_file():
                    kind = {
                        "module_files": "module",
                        "resource_files": "resource",
                        "license_files": "license",
                    }[field]
                    errors.append(
                        f"{prefix}.{field}[{item_index}]: missing staged {kind} {item}"
                    )
        for field in (
            "resources_disabled",
            "optional_dependencies_disabled",
            "license_files_disabled",
        ):
            if type(row.get(field)) is not bool:
                errors.append(f"{prefix}.{field}: expected bool")
        disabled_pairs = (
            ("resources_disabled", "resource_files"),
            ("optional_dependencies_disabled", "optional_dependencies"),
            ("license_files_disabled", "license_files"),
        )
        for disabled_field, values_field in disabled_pairs:
            if row.get(disabled_field) is True and row.get(values_field) not in (
                [],
                None,
            ):
                errors.append(
                    f"{prefix}.{disabled_field}: true requires empty {values_field}"
                )
            if row.get(disabled_field) is False and not row.get(values_field):
                errors.append(
                    f"{prefix}.{disabled_field}: false requires {values_field}"
                )

        metadata_files = row.get("metadata_files")
        if not isinstance(metadata_files, list) or not metadata_files:
            errors.append(f"{prefix}.metadata_files: expected non-empty string array")
            metadata_files = []
        for item_index, item in enumerate(metadata_files):
            if not isinstance(item, str):
                errors.append(f"{prefix}.metadata_files[{item_index}]: expected string")
                continue
            try:
                relative = _safe_relative_path(
                    item, f"{prefix}.metadata_files[{item_index}]"
                )
            except PackagingError as error:
                errors.extend(error.errors)
                continue
            if not (staging / relative).is_file():
                errors.append(
                    f"{prefix}.metadata_files[{item_index}]: missing staged "
                    f"metadata {item}"
                )
        metadata_path = next(
            (
                staging / item
                for item in metadata_files
                if isinstance(item, str) and item.endswith("/METADATA")
            ),
            None,
        )
        entry_points_path = next(
            (
                staging / item
                for item in metadata_files
                if isinstance(item, str) and item.endswith("/entry_points.txt")
            ),
            None,
        )
        if metadata_path is None or not metadata_path.is_file():
            errors.append(f"{prefix}.metadata_files: missing staged metadata METADATA")
        if entry_points_path is None or not entry_points_path.is_file():
            errors.append(
                f"{prefix}.metadata_files: missing staged metadata entry_points.txt"
            )
        if metadata_path is not None and metadata_path.is_file():
            metadata_values, metadata_errors = _metadata_values(metadata_path)
            errors.extend(f"{prefix}: {error}" for error in metadata_errors)
            if metadata_values:
                checks = {
                    "Name": info["distribution"],
                    "Version": info["project"]["version"],
                    "Summary": info["project"]["description"],
                    "Requires-Python": info["project"]["requires-python"],
                    "License-Expression": info["project"]["license"],
                    "License-File": tuple(info["project"]["license-files"]),
                }
                for field, expected in checks.items():
                    if metadata_values.get(field) != expected:
                        errors.append(
                            f"{prefix}.metadata.{field}: expected {expected!r}, "
                            f"got {metadata_values.get(field)!r}"
                        )
                if (
                    tuple(metadata_values.get("Requires-Dist", ()))
                    != info["dependencies"]
                ):
                    errors.append(
                        f"{prefix}.metadata.Requires-Dist: expected "
                        f"{list(info['dependencies'])!r}, "
                        f"got {list(metadata_values.get('Requires-Dist', ()))!r}"
                    )
                declared_license_paths = set()
                for item_index, item in enumerate(
                    metadata_values.get("License-File", ())
                ):
                    try:
                        relative = _safe_relative_path(
                            item,
                            f"{prefix}.metadata.License-File[{item_index}]",
                        )
                    except PackagingError as error:
                        errors.extend(error.errors)
                        continue
                    declared_license_paths.add(
                        metadata_path.parent / "licenses" / relative
                    )
                actual_license_paths = {
                    path
                    for path in (metadata_path.parent / "licenses").rglob("*")
                    if path.is_file()
                }
                for path in sorted(declared_license_paths - actual_license_paths):
                    errors.append(
                        f"{prefix}.metadata.License-File: missing staged license "
                        f"{_posix_path(path.relative_to(staging))}"
                    )
                for path in sorted(actual_license_paths - declared_license_paths):
                    errors.append(
                        f"{prefix}.metadata.License-File: unclaimed staged license "
                        f"{_posix_path(path.relative_to(staging))}"
                    )
        if entry_points_path is not None and entry_points_path.is_file():
            entries, entry_errors = _entry_points_from_file(entry_points_path)
            errors.extend(f"{prefix}: {error}" for error in entry_errors)
            expected_entry = (ENTRY_POINT_GROUP, provider_id, info["factory"])
            if entries != (expected_entry,):
                errors.append(
                    f"{prefix}.metadata.entry_points: expected {expected_entry!r}, "
                    f"got {entries!r}"
                )
        actual_metadata_files = set()
        for metadata_dir in staging.glob("*.dist-info"):
            metadata_file = metadata_dir / "METADATA"
            if not metadata_file.is_file():
                continue
            metadata_values, _ = _metadata_values(metadata_file)
            if metadata_values and metadata_values.get("Name") == info["distribution"]:
                actual_metadata_files = {
                    _posix_path(path.relative_to(staging))
                    for path in metadata_dir.rglob("*")
                    if path.is_file()
                }
                break
        for item in sorted(actual_metadata_files - set(metadata_files)):
            errors.append(f"{prefix}.metadata_files: omitted staged metadata {item}")

        for field, hashes in (
            ("module_files", info["module_hashes"]),
            ("resource_files", info["resource_hashes"]),
            ("license_files", info["license_hashes"]),
        ):
            for item in row.get(field, []) if isinstance(row.get(field), list) else []:
                path = staging / item
                if (
                    path.is_file()
                    and item in hashes
                    and _sha256_file(path) != hashes[item]
                ):
                    errors.append(f"{prefix}.{field}: hash mismatch for staged {item}")
    return value, errors


def _frozen_distributions(staging, infos):
    # Check importlib.metadata against the staged dist-info directories.
    errors = []
    rows = []
    try:
        distributions = tuple(importlib_metadata.distributions(path=[str(staging)]))
    except Exception as error:
        return [], [f"frozen metadata discovery: {error}"]
    for info in infos:
        matches = tuple(
            distribution
            for distribution in distributions
            if distribution.metadata.get("Name") == info["distribution"]
        )
        if len(matches) != 1:
            errors.append(
                f"{info['provider_id']}.metadata: expected one staged distribution "
                f"{info['distribution']}, found {len(matches)}"
            )
            continue
        entries = tuple(
            (entry.group, entry.name, entry.value)
            for entry in matches[0].entry_points
            if entry.group == ENTRY_POINT_GROUP
        )
        expected = ((ENTRY_POINT_GROUP, info["provider_id"], info["factory"]),)
        if entries != expected:
            errors.append(
                f"{info['provider_id']}.metadata.entry_points: expected {expected!r}, "
                f"got {entries!r}"
            )
        if matches[0].version != info["project"]["version"]:
            errors.append(
                f"{info['provider_id']}.metadata.Version: expected "
                f"{info['project']['version']}, got {matches[0].version}"
            )
        rows.append(
            {
                "id": info["provider_id"],
                "distribution": matches[0].metadata.get("Name", ""),
                "version": matches[0].version,
                "entry_points": [list(entry) for entry in entries],
                "metadata_path": str(matches[0].locate_file("")),
            }
        )
    return rows, errors


def _frozen_analysis(
    staging, staging_manifest_path, frozen_manifest_path, source_raw, infos
):
    # Validate the frozen manifest, staged inventory and metadata without execution.
    errors = []
    staging_value, staging_errors = _validate_staging_manifest(
        staging_manifest_path, infos, staging
    )
    errors.extend(staging_errors)
    staged_plugin_manifest = staging / MANIFEST_TARGET
    try:
        staged_raw, _ = _read_json(staged_plugin_manifest, "staging plugin manifest")
    except PackagingError as error:
        errors.extend(error.errors)
    else:
        if staged_raw != source_raw:
            errors.append(
                "staging plugin manifest: bytes differ from canonical source manifest "
                f"(source={_sha256_bytes(source_raw)}, "
                f"staging={_sha256_bytes(staged_raw)})"
            )
    try:
        frozen_raw, frozen_value = _read_json(frozen_manifest_path, "frozen manifest")
    except PackagingError as error:
        return {}, errors + list(error.errors)
    if frozen_raw != source_raw:
        errors.append(
            "frozen manifest: bytes differ from canonical source manifest "
            f"(source={_sha256_bytes(source_raw)}, frozen={_sha256_bytes(frozen_raw)})"
        )
    manifest_module = _manifest_module()
    try:
        canonical_raw = manifest_module.canonical_document(frozen_value)
    except (TypeError, ValueError) as error:
        errors.append(f"frozen manifest: cannot serialize canonical bytes: {error}")
    else:
        if frozen_raw != canonical_raw:
            errors.append(
                "frozen manifest: bytes are not canonical_document(value) "
                f"(actual={_sha256_bytes(frozen_raw)}, "
                f"canonical={_sha256_bytes(canonical_raw)})"
            )
    try:
        descriptors = manifest_module.validate_manifest(frozen_value, ENTRY_POINT_GROUP)
    except ValueError as error:
        errors.extend(getattr(error, "errors", (str(error),)))
        descriptors = ()
    if tuple(descriptor.id for descriptor in descriptors) != tuple(
        info["provider_id"] for info in infos
    ):
        errors.append(
            "frozen manifest: descriptor order or identity differs from source"
        )
    distribution_rows, distribution_errors = _frozen_distributions(staging, infos)
    errors.extend(distribution_errors)
    return {
        "staging_manifest_sha256": (
            _sha256_file(staging_manifest_path)
            if staging_manifest_path.is_file()
            else ""
        ),
        "manifest_sha256": _sha256_bytes(frozen_raw),
        "descriptors": [descriptor.id for descriptor in descriptors],
        "distributions": distribution_rows,
        "discovery": [],
        "staging_manifest": staging_value,
    }, errors


def _metadata_for_stage(package_dir):
    # Ask setuptools for actual PEP 517 metadata without network or isolation.
    try:
        import setuptools.build_meta as build_meta
    except ImportError as error:
        raise PackagingError(
            [f"{package_dir}: setuptools metadata unavailable: {error}"]
        )
    with tempfile.TemporaryDirectory(prefix="ohmymeme-plugin-metadata-") as temp_dir:
        old_cwd = Path.cwd()
        try:
            os.chdir(package_dir)
            build_meta.prepare_metadata_for_build_wheel(temp_dir)
        except Exception as error:
            raise PackagingError([f"{package_dir}: metadata build failed: {error}"])
        finally:
            os.chdir(old_cwd)
        candidates = sorted(Path(temp_dir).glob("*.dist-info"))
        if len(candidates) != 1:
            raise PackagingError(
                [
                    f"{package_dir}: expected one generated dist-info, "
                    f"found {len(candidates)}"
                ]
            )
        source = candidates[0]
        return source.name, [
            (path.relative_to(source), path.read_bytes())
            for path in source.rglob("*")
            if path.is_file()
        ]


def _stage_official(staging, staging_manifest_path, source_manifest_path):
    # Copy real modules and generated distribution metadata into build-only staging.
    if staging.exists() and any(staging.iterdir()):
        raise PackagingError([f"staging directory is not empty: {staging}"])
    staging.mkdir(parents=True, exist_ok=True)
    source_raw, _, descriptors = _load_source_manifest(source_manifest_path)
    infos, errors = _source_analysis(descriptors)
    if errors:
        raise PackagingError(errors)
    rows = []
    for info in infos:
        for field in ("module_files", "resource_files", "license_files"):
            for relative_name in info[field]:
                source = info["package_dir"] / "src" / relative_name
                if field == "license_files":
                    source = info["package_dir"] / relative_name
                destination = staging / relative_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        metadata_root, metadata_files_data = _metadata_for_stage(info["package_dir"])
        for relative, data in metadata_files_data:
            destination = staging / metadata_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        metadata_files = sorted(
            _posix_path(path.relative_to(staging))
            for path in (staging / metadata_root).rglob("*")
            if path.is_file()
        )
        rows.append(
            {
                "id": info["provider_id"],
                "distribution": info["distribution"],
                "module": info["module"],
                "factory": info["factory"],
                "module_files": list(info["module_files"]),
                "metadata_files": metadata_files,
                "resource_files": list(info["resource_files"]),
                "optional_dependencies": list(info["optional_dependencies"]),
                "optional_dependencies_disabled": not bool(
                    info["optional_dependencies"]
                ),
                "dependencies": list(info["dependencies"]),
                "license": info["project"]["license"],
                "license_files": list(info["license_files"]),
                "license_files_disabled": not bool(info["license_files"]),
                "resources_disabled": not bool(info["resource_files"]),
            }
        )
    manifest_destination = staging / MANIFEST_TARGET
    manifest_destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_destination.write_bytes(source_raw)
    staging_manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_target": _posix_path(MANIFEST_TARGET),
        "packages": rows,
    }
    staging_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    staging_manifest_path.write_text(
        json.dumps(
            staging_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n",
        encoding="utf-8",
    )
    _, staging_errors = _validate_staging_manifest(
        staging_manifest_path, infos, staging
    )
    if staging_errors:
        raise PackagingError(staging_errors)
    source_discovery, import_errors = _probe_factories(
        infos, [info["package_dir"] / "src" for info in infos], "source"
    )
    if import_errors:
        raise PackagingError(import_errors)
    return {
        "source_manifest_sha256": _sha256_bytes(source_raw),
        "staging_manifest_sha256": _sha256_file(staging_manifest_path),
        "discovery": source_discovery,
        "staging": str(staging),
    }


def _run_source(args):
    # Run the full source/frozen parity check and return actual observations.
    source_manifest = _resolve_root_path(args.source_manifest)
    staging = _resolve_root_path(args.frozen_staging)
    staging_manifest = _resolve_root_path(args.staging_manifest)
    frozen_manifest = _resolve_frozen_manifest(staging, args.frozen_manifest)
    source_raw, _, descriptors = _load_source_manifest(source_manifest)
    infos, source_errors = _source_analysis(descriptors)
    frozen_observation, frozen_errors = _frozen_analysis(
        staging, staging_manifest, frozen_manifest, source_raw, infos
    )
    errors = source_errors + frozen_errors
    source_discovery = []
    frozen_discovery = []
    if not errors:
        source_discovery, source_import_errors = _probe_factories(
            infos, [info["package_dir"] / "src" for info in infos], "source"
        )
        errors.extend(source_import_errors)
        if not source_import_errors:
            frozen_discovery, frozen_import_errors = _probe_factories(
                infos, [staging], "frozen"
            )
            errors.extend(frozen_import_errors)
    frozen_observation["discovery"] = frozen_discovery
    discovery_match = bool(source_discovery and frozen_discovery) and (
        _discovery_identity(source_discovery) == _discovery_identity(frozen_discovery)
    )
    if not discovery_match:
        errors.append("discovery: source and frozen factory identities differ")
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "source",
        "status": "PASS" if not errors else "REJECTED",
        "source": {
            "manifest": str(source_manifest),
            "manifest_sha256": _sha256_bytes(source_raw),
            "manifest_bytes": len(source_raw),
            "descriptors": [descriptor.id for descriptor in descriptors],
            "packages": _package_observations(infos),
            "discovery": source_discovery,
        },
        "frozen": {
            "staging": str(staging),
            "staging_manifest": str(staging_manifest),
            "manifest": str(frozen_manifest),
            **frozen_observation,
        },
        "discovery_match": discovery_match,
        "errors": errors,
    }


def _discovery_identity(rows):
    # Compare actual provider identities while ignoring source-specific file paths.
    return tuple(
        (
            row.get("id"),
            row.get("module"),
            row.get("factory"),
            row.get("provider_id"),
            row.get("api_version"),
        )
        for row in rows
    )


def _package_observations(infos):
    # Expose hashes and metadata observed from source files for the evidence report.
    rows = []
    for info in infos:
        rows.append(
            {
                "id": info["provider_id"],
                "distribution": info["distribution"],
                "version": info["project"]["version"],
                "module": info["module"],
                "factory": info["factory"],
                "module_files": [
                    {"path": name, "sha256": info["module_hashes"][name]}
                    for name in info["module_files"]
                ],
                "resource_files": [
                    {"path": name, "sha256": info["resource_hashes"][name]}
                    for name in info["resource_files"]
                ],
                "license_files": [
                    {"path": name, "sha256": info["license_hashes"][name]}
                    for name in info["license_files"]
                ],
                "optional_dependencies": list(info["optional_dependencies"]),
                "optional_dependencies_disabled": not bool(
                    info["optional_dependencies"]
                ),
                "license_files_disabled": not bool(info["license_files"]),
                "resources_disabled": not bool(info["resource_files"]),
            }
        )
    return rows


def _resolve_root_path(value):
    # Resolve command paths relative to this worktree, never the caller's shell.
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _resolve_frozen_manifest(staging, value):
    # Frozen manifest arguments name a path inside the supplied staging tree.
    path = Path(value)
    if path.is_absolute():
        return path
    return staging / path


def _direct_url_source_path(value):
    # Convert a PEP 610 local file URL into its resolved source-tree path.
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(url2pathname(unquote(parsed.path))).resolve()


def _installed_module_origin(module_name):
    # Locate the installed module without importing or executing its factory.
    try:
        spec = importlib_util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if spec is None or not spec.origin or spec.origin in ("built-in", "frozen"):
        return None
    return Path(spec.origin).resolve()


def _package_ids_from_paths(paths):
    # Map editable-install arguments to canonical provider IDs without guessing.
    expected = {
        _package_dir(provider_id).resolve(): provider_id
        for provider_id in _canonical_ids()
    }
    ids = []
    errors = []
    for value in paths:
        path = Path(value)
        resolved = (ROOT / path if not path.is_absolute() else path).resolve()
        provider_id = expected.get(resolved)
        if provider_id is None:
            errors.append(f"editable package: not an official package root: {value}")
        elif provider_id in ids:
            errors.append(f"editable package: duplicate official package {provider_id}")
        else:
            ids.append(provider_id)
    canonical = _canonical_ids()
    if tuple(ids) != canonical:
        errors.append(
            "editable package: expected canonical nine package order "
            f"{canonical!r}, got {tuple(ids)!r}"
        )
    if errors:
        raise PackagingError(errors)
    return ids


def _canonical_ids():
    # Keep the editable command tied to the canonical manifest order.
    manifest_module = _manifest_module()
    return tuple(item[0] for item in manifest_module.CANONICAL_PROVIDERS)


def _run_process(command, timeout=180):
    # Bound editable packaging so a hung build cannot report success.
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise PackagingError([f"editable install timed out after {timeout}s"])
    if process.returncode != 0:
        raise PackagingError(
            [
                f"editable install failed with exit {process.returncode}:\n"
                f"{output.rstrip()}"
            ]
        )
    return output


def _validate_installed_metadata(ids):
    # Confirm metadata, direct_url source trees and module origins in this venv.
    errors = []
    rows = []
    venv_root = (ROOT / ".venv").resolve()
    for provider_id in ids:
        distribution_name = _distribution_name(provider_id)
        try:
            distribution = importlib_metadata.distribution(distribution_name)
        except importlib_metadata.PackageNotFoundError:
            errors.append(f"{provider_id}.metadata: distribution not installed")
            continue
        expected_root = _module_name(provider_id)
        expected_value = f"{expected_root}:create_plugin"
        actual_distribution = distribution.metadata.get("Name")
        if actual_distribution != distribution_name:
            errors.append(
                f"{provider_id}.metadata.Name: expected {distribution_name!r}, "
                f"got {actual_distribution!r}"
            )
        try:
            expected_version = _project_data(_package_dir(provider_id), provider_id)[
                "project"
            ]["version"]
        except PackagingError as error:
            expected_version = None
            errors.extend(error.errors)
        if expected_version is not None and distribution.version != expected_version:
            errors.append(
                f"{provider_id}.metadata.Version: expected {expected_version}, "
                f"got {distribution.version}"
            )
        entries = tuple(
            (entry.group, entry.name, entry.value)
            for entry in distribution.entry_points
            if entry.group == ENTRY_POINT_GROUP
        )
        expected = ((ENTRY_POINT_GROUP, provider_id, expected_value),)
        if entries != expected:
            errors.append(
                f"{provider_id}.metadata.entry_points: expected {expected!r}, "
                f"got {entries!r}"
            )
        try:
            direct_url_raw = distribution.read_text("direct_url.json")
        except (AttributeError, OSError) as error:
            direct_url_raw = None
            errors.append(f"{provider_id}.direct_url: cannot read: {error}")
        direct_url = {}
        if not direct_url_raw:
            errors.append(f"{provider_id}.direct_url: missing direct_url.json")
        else:
            try:
                parsed_direct_url = json.loads(direct_url_raw)
            except (TypeError, json.JSONDecodeError) as error:
                errors.append(f"{provider_id}.direct_url: invalid JSON: {error}")
            else:
                if isinstance(parsed_direct_url, dict):
                    direct_url = parsed_direct_url
                else:
                    errors.append(f"{provider_id}.direct_url: expected object")
        source_tree = _direct_url_source_path(direct_url.get("url"))
        expected_source_tree = _package_dir(provider_id).resolve()
        if source_tree is None:
            errors.append(
                f"{provider_id}.direct_url.url: expected local file URL for "
                f"{expected_source_tree}"
            )
        elif source_tree != expected_source_tree or not source_tree.is_dir():
            errors.append(
                f"{provider_id}.direct_url.url: expected real source tree "
                f"{expected_source_tree}, got {source_tree}"
            )
        dir_info = direct_url.get("dir_info")
        if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
            errors.append(f"{provider_id}.direct_url.dir_info.editable: expected true")
        installed_root = Path(distribution.locate_file("")).resolve()
        if not installed_root.is_relative_to(venv_root):
            errors.append(
                f"{provider_id}.metadata: installed outside current worktree venv "
                f"{venv_root}: {installed_root}"
            )
        origin = _installed_module_origin(expected_root)
        expected_module_dir = expected_source_tree / "src" / expected_root
        if origin is None or not origin.is_relative_to(expected_module_dir):
            errors.append(
                f"{provider_id}.module: installed origin expected under "
                f"{expected_module_dir}, got {origin}"
            )
        rows.append(
            {
                "id": provider_id,
                "distribution": distribution.metadata.get("Name", ""),
                "version": distribution.version,
                "entry_points": [list(entry) for entry in entries],
                "metadata_path": str(distribution.locate_file("")),
                "direct_url": direct_url.get("url", ""),
                "source_tree": str(source_tree) if source_tree else "",
                "editable": (
                    dir_info.get("editable") is True
                    if isinstance(dir_info, dict)
                    else False
                ),
                "module_origin": str(origin) if origin else "",
            }
        )
    return rows, errors


def _run_editable(paths):
    # Install only official editable packages, with dependency resolution disabled.
    ids = _package_ids_from_paths(paths)
    package_paths = [str(Path(value)) for value in paths]
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-build-isolation",
        "--no-index",
    ]
    for path in package_paths:
        command.extend(("-e", path))
    output = _run_process(command)
    metadata_rows, errors = _validate_installed_metadata(ids)
    source_infos = []
    for provider_id in ids:
        try:
            info = _project_data(_package_dir(provider_id), provider_id)
            _source_files(info)
            source_infos.append(info)
        except PackagingError as error:
            errors.extend(error.errors)
    discovery = []
    if not errors:
        discovery, import_errors = _probe_factories(
            source_infos,
            [info["package_dir"] / "src" for info in source_infos],
            "source",
        )
        errors.extend(import_errors)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "install-editable-official",
        "status": "PASS" if not errors else "REJECTED",
        "command": command,
        "packages": metadata_rows,
        "discovery": discovery,
        "pip_output_tail": output[-4000:],
        "errors": errors,
    }


def _zip_filename(provider_id, version):
    # Release attachment name keeps the published plugin identity and version.
    return "OhMyMeme-plugin-%s-v%s.zip" % (provider_id, version)


def _app_version():
    # Read the single version source without importing the application package.
    path = SRC / "ohmymeme" / "__init__.py"
    try:
        match = re.search(r'__version__\s*=\s*"([^"]+)"', path.read_text("utf-8"))
    except OSError as error:
        raise PackagingError([f"app version: cannot read {path}: {error}"])
    if match is None:
        raise PackagingError([f"app version: __version__ missing in {path}"])
    return match.group(1)


def build_plugin_zip(provider_id, version, out_path):
    # Build a deterministic official distribution ZIP from committed source.
    manifest_module = _manifest_module()
    canonical = manifest_module.CANONICAL_BY_ID.get(provider_id)
    if canonical is None:
        raise PackagingError([f"plugin zip: unknown official provider {provider_id!r}"])
    _, package_root, capabilities = canonical
    meta = {
        "api_version": manifest_module.PLUGIN_API_VERSION,
        "capabilities": list(capabilities),
        "entry": f"{package_root}:create_plugin",
        "id": provider_id,
        "name": _distribution_name(provider_id),
        "package_root": package_root,
        "version": version,
    }
    source_root = _package_dir(provider_id) / "src" / package_root
    if not source_root.is_dir():
        raise PackagingError(
            [f"{provider_id}.module: missing package root {source_root}"]
        )
    entries = [
        (
            "plugin.json",
            json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            )
            + b"\n",
        )
    ]
    for path in sorted(source_root.rglob("*")):
        relative = path.relative_to(source_root)
        if not path.is_file():
            continue
        if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo"):
            continue
        entries.append((f"{package_root}/{relative.as_posix()}", path.read_bytes()))
    plugin_root = _package_dir(provider_id)
    for path in sorted(plugin_root.iterdir()):
        if path.is_file() and path.name.upper().startswith(
            ("LICENSE", "COPYING", "NOTICE")
        ):
            entries.append((path.name, path.read_bytes()))
    entries.sort(key=lambda item: item[0])
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, data)
    return {"path": str(out), "sha256": _sha256_file(out), "bytes": out.stat().st_size}


def _run_pack_zips(out_dir, version):
    # Generate the nine official ZIP attachments and report their content hashes.
    out = Path(out_dir)
    packed = []
    errors = []
    for provider_id in _canonical_ids():
        try:
            result = build_plugin_zip(
                provider_id, version, out / _zip_filename(provider_id, version)
            )
        except PackagingError as error:
            errors.extend(error.errors)
            continue
        except OSError as error:
            errors.append(f"{provider_id}.zip: {error}")
            continue
        packed.append({"id": provider_id, **result})
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "pack-zips",
        "status": "PASS" if not errors else "REJECTED",
        "version": version,
        "out": str(out),
        "packages": packed,
        "errors": errors,
    }


def _run_install_dev(data_dir, version):
    # Install the nine official ZIPs into a data dir through the real host transaction.
    try:
        seeding = _seeding_module()
    except ImportError as error:
        raise PackagingError([f"install-dev: cannot import host seeding: {error}"])
    target = Path(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    packages = []
    errors = []
    with tempfile.TemporaryDirectory(prefix="ohmymeme-plugin-install-dev-") as temp_dir:
        for provider_id in _canonical_ids():
            archive = Path(temp_dir) / _zip_filename(provider_id, version)
            try:
                build_plugin_zip(provider_id, version, archive)
                resolved = seeding.install_plugin(str(target), archive)
            except PackagingError as error:
                errors.extend(error.errors)
                continue
            except (OSError, seeding.PluginSeedError) as error:
                errors.append(f"{provider_id}.install: {error}")
                continue
            packages.append(
                {"id": provider_id, "version": resolved.get("version", version)}
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "install-dev",
        "status": "PASS" if not errors else "REJECTED",
        "version": version,
        "data_dir": str(target),
        "packages": packages,
        "errors": errors,
    }


def _write_report(path, report):
    # Write deterministic evidence only after actual validation has completed.
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _parse_args(argv):
    # Keep source, staging, editable, pack-zips and install-dev modes exclusive.
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--source", action="store_true")
    modes.add_argument("--stage", action="store_true")
    modes.add_argument("--install-editable-official", nargs="+")
    modes.add_argument("--pack-zips", action="store_true")
    modes.add_argument("--install-dev", action="store_true")
    parser.add_argument("--frozen-staging")
    parser.add_argument("--staging-dir")
    parser.add_argument("--staging-manifest")
    parser.add_argument("--source-manifest", default="config/plugin-manifest.json")
    parser.add_argument("--frozen-manifest", default=_posix_path(MANIFEST_TARGET))
    parser.add_argument("--report")
    parser.add_argument("--out")
    parser.add_argument("--data-dir")
    parser.add_argument("--version")
    args = parser.parse_args(argv)
    if args.source and not all(
        (
            args.frozen_staging,
            args.staging_manifest,
            args.source_manifest,
            args.frozen_manifest,
        )
    ):
        parser.error(
            "--source requires frozen staging, staging manifest and both manifests"
        )
    if args.stage and not all(
        (args.staging_dir, args.staging_manifest, args.source_manifest)
    ):
        parser.error(
            "--stage requires --staging-dir, --staging-manifest and --source-manifest"
        )
    if args.install_editable_official and any(
        value is not None
        for value in (args.frozen_staging, args.staging_dir, args.staging_manifest)
    ):
        parser.error("editable installation does not accept staging arguments")
    if args.pack_zips and not args.out:
        parser.error("--pack-zips requires --out")
    if args.install_dev and not args.data_dir:
        parser.error("--install-dev requires --data-dir")
    return args


def main(argv=None):
    # Execute one mode and use a nonzero exit for every failed contract.
    args = _parse_args(argv)
    report_path = _resolve_root_path(args.report) if args.report else None
    try:
        if args.source:
            report = _run_source(args)
        elif args.stage:
            report = _stage_official(
                _resolve_root_path(args.staging_dir),
                _resolve_root_path(args.staging_manifest),
                _resolve_root_path(args.source_manifest),
            )
            report = {
                "schema_version": SCHEMA_VERSION,
                "mode": "stage",
                "status": "PASS",
                **report,
                "errors": [],
            }
        elif args.pack_zips:
            version = args.version or _app_version()
            report = _run_pack_zips(args.out, version)
        elif args.install_dev:
            version = args.version or _app_version()
            report = _run_install_dev(args.data_dir, version)
        else:
            report = _run_editable(args.install_editable_official)
    except PackagingError as error:
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": (
                "source"
                if args.source
                else (
                    "stage"
                    if args.stage
                    else (
                        "pack-zips"
                        if args.pack_zips
                        else (
                            "install-dev"
                            if args.install_dev
                            else "install-editable-official"
                        )
                    )
                )
            ),
            "status": "REJECTED",
            "errors": list(error.errors),
        }
    _write_report(report_path, report)
    if report.get("errors"):
        for error in report["errors"]:
            print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
