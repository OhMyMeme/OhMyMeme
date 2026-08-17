"""离线验证六类发布产物的命名与元数据契约。"""

import argparse
import json
import plistlib
import re
from dataclasses import dataclass, replace
from pathlib import Path

from scripts.package_lifecycle import (
    LifecycleProbe,
    LifecycleViolation,
    probes_for,
    validate_probes,
)

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "src" / "__init__.py"
WINDOWS_ISS = ROOT / "scripts" / "installer" / "windows.iss"
LINUX_BUILD = ROOT / "scripts" / "installer" / "linux" / "build.sh"
BUILD_SCRIPT = ROOT / "scripts" / "build.py"
MACOS_INFO_PLIST = ROOT / "scripts" / "installer" / "macos" / "Info.plist"


class ContractViolation(ValueError):
    """发布产物不符合冻结契约。"""


@dataclass(frozen=True)
class ArtifactContract:
    target: str
    filename: str
    architecture: str
    channel: str
    package_version: str
    updater_selectable: bool
    app_id: str = ""
    bundle_id: str = ""
    package_name: str = ""
    license: str = ""
    resources: tuple[str, ...] = ()
    lifecycle_probes: tuple[LifecycleProbe, ...] = ()

    @classmethod
    def default(cls, target, version, channel="stable"):
        contracts = _contracts(version, channel)
        try:
            return contracts[target]
        except KeyError as exc:
            raise ContractViolation("unknown target: %s" % target) from exc

    def with_metadata(self, **metadata):
        return replace(self, **metadata)


def _contracts(version, channel="stable"):
    nightly = channel == "nightly"
    artifact_version = "nightly" if nightly else version
    updater_selectable = not nightly
    resources = ("src/resources/icon.png",)
    contracts = {
        "windows-x64": ArtifactContract(
            "windows-x64",
            "OhMyMeme-%s-setup.exe" % artifact_version,
            "x64",
            channel,
            version,
            updater_selectable,
            app_id="{B8F4A3D2-1C5E-4A7B-9D6F-8E2C3A1B5D7F}",
            resources=resources,
        ),
        "linux-appimage-x64": ArtifactContract(
            "linux-appimage-x64",
            "OhMyMeme-v%s-x86_64.AppImage" % artifact_version,
            "x86_64",
            channel,
            version,
            updater_selectable,
            package_name="ohmymeme",
            resources=resources,
        ),
        "linux-deb-amd64": ArtifactContract(
            "linux-deb-amd64",
            "OhMyMeme-v%s-amd64.deb" % artifact_version,
            "amd64",
            channel,
            version,
            False,
            package_name="ohmymeme",
            resources=resources,
        ),
        "linux-rpm-x64": ArtifactContract(
            "linux-rpm-x64",
            "OhMyMeme-v%s-x86_64.rpm" % artifact_version,
            "x86_64",
            channel,
            version,
            False,
            package_name="ohmymeme",
            license="GPL-3.0",
            resources=resources,
        ),
        "macos-arm64": ArtifactContract(
            "macos-arm64",
            "OhMyMeme-v%s-arm64.dmg" % artifact_version,
            "arm64",
            channel,
            version,
            updater_selectable,
            bundle_id="com.ohmymeme.app",
            resources=(
                "src/resources/icon.png",
                "scripts/installer/macos/Info.plist",
                "OhMyMeme.app",
            ),
        ),
        "macos-x86_64": ArtifactContract(
            "macos-x86_64",
            "OhMyMeme-v%s-x86_64.dmg" % artifact_version,
            "x86_64",
            channel,
            version,
            updater_selectable,
            bundle_id="com.ohmymeme.app",
            resources=(
                "src/resources/icon.png",
                "scripts/installer/macos/Info.plist",
                "OhMyMeme.app",
            ),
        ),
    }
    return {
        target: replace(contract, lifecycle_probes=probes_for(target))
        for target, contract in contracts.items()
    }


def _version():
    match = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_FILE.read_text("utf-8"))
    if not match:
        raise ContractViolation("package version is missing")
    return match.group(1)


def _fail(field, expected, actual):
    raise ContractViolation("%s drift: expected %s, got %s" % (field, expected, actual))


def _macos_bundle_id():
    with MACOS_INFO_PLIST.open("rb") as handle:
        data = plistlib.load(handle)
    bundle_id = data.get("CFBundleIdentifier")
    if not isinstance(bundle_id, str):
        raise ContractViolation("macOS bundle id is missing")
    return bundle_id


def validate_contract(contract):
    expected = ArtifactContract.default(
        contract.target, contract.package_version, contract.channel
    )
    for field in (
        "filename",
        "architecture",
        "channel",
        "package_version",
        "updater_selectable",
        "app_id",
        "bundle_id",
        "package_name",
        "license",
        "resources",
        "lifecycle_probes",
    ):
        actual = getattr(contract, field)
        wanted = getattr(expected, field)
        if actual != wanted:
            _fail(field.replace("_", " "), wanted, actual)
    for resource in contract.resources:
        if "/" in resource and not (ROOT / resource).is_file():
            raise ContractViolation("resource missing: %s" % resource)
    try:
        validate_probes(contract.lifecycle_probes)
    except LifecycleViolation as exc:
        raise ContractViolation(str(exc)) from exc


def _validate_source_contracts():
    windows = WINDOWS_ISS.read_text("utf-8")
    linux = LINUX_BUILD.read_text("utf-8")
    build_script = BUILD_SCRIPT.read_text("utf-8")
    bundle_id = _macos_bundle_id()
    required = (
        ("AppId={{B8F4A3D2-1C5E-4A7B-9D6F-8E2C3A1B5D7F}", windows),
        ("ArchitecturesInstallIn64BitMode=x64compatible", windows),
        ("ARCH=x86_64 ./appimagetool", linux),
        ("Architecture: amd64", linux),
        ("License: GPL-3.0", linux),
        ("OhMyMeme-v${APP_VERSION}-x86_64.AppImage", linux),
        ("OhMyMeme-v${APP_VERSION}-amd64.deb", linux),
        ("OhMyMeme-v${APP_VERSION}-x86_64.rpm", linux),
    )
    for value, source in required:
        if value not in source:
            raise ContractViolation("source metadata missing: %s" % value)
    if bundle_id != "com.ohmymeme.app":
        _fail("bundle id", "com.ohmymeme.app", bundle_id)
    if 'shutil.copy2(info_plist, contents_dir / "Info.plist")' not in build_script:
        raise ContractViolation("macOS bundle id input is not wired to packaging")


def contract_report(target=None, channel="stable"):
    version = _version()
    contracts = _contracts(version, channel)
    selected = [contracts[target]] if target else list(contracts.values())
    _validate_source_contracts()
    rows = []
    for contract in selected:
        validate_contract(contract)
        rows.append(
            {
                "target": contract.target,
                "filename": contract.filename,
                "architecture": contract.architecture,
                "channel": contract.channel,
                "package_version": contract.package_version,
                "updater_selectable": contract.updater_selectable,
                "lifecycle_probes": [
                    probe.phase for probe in contract.lifecycle_probes
                ],
                "valid": True,
            }
        )
    return {"contract_only": True, "targets": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate package contracts offline")
    parser.add_argument("--contract-only", action="store_true")
    parser.add_argument("--target", choices=tuple(_contracts(_version())))
    parser.add_argument("--channel", choices=("stable", "nightly"), default="stable")
    args = parser.parse_args(argv)
    if not args.contract_only:
        parser.error("--contract-only is required; this command never builds artifacts")
    print(
        json.dumps(
            contract_report(args.target, args.channel),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
