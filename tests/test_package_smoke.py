"""离线发布产物契约 smoke 测试。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.package_smoke import (
    ArtifactContract,
    ContractViolation,
    contract_report,
    validate_contract,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_contract_only_reports_six_release_targets():
    """Given repository contracts, when smoke runs, then six targets pass."""
    result = subprocess.run(
        ["mise", "run", "package-smoke", "--", "--contract-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["contract_only"] is True
    assert [row["target"] for row in report["targets"]] == [
        "windows-x64",
        "linux-appimage-x64",
        "linux-deb-amd64",
        "linux-rpm-x64",
        "macos-arm64",
        "macos-x86_64",
    ]
    assert all(row["valid"] for row in report["targets"])


def test_every_target_defines_required_non_skippable_lifecycle_probes():
    """Given all release targets, when loaded, then each owns six required probes."""
    for target in (
        "windows-x64",
        "linux-appimage-x64",
        "linux-deb-amd64",
        "linux-rpm-x64",
        "macos-arm64",
        "macos-x86_64",
    ):
        contract = ArtifactContract.default(target, "0.6.2")

        assert tuple(probe.phase for probe in contract.lifecycle_probes) == (
            "build",
            "install",
            "launch",
            "upgrade",
            "rollback",
            "uninstall",
        )
        assert all(probe.required for probe in contract.lifecycle_probes)
        assert all(
            probe.runner and probe.tool and probe.input
            for probe in contract.lifecycle_probes
        )
        assert all(
            probe.command and probe.observable and probe.cleanup
            for probe in contract.lifecycle_probes
        )
        assert contract.lifecycle_probes[0].input == "source tree"
        assert contract.lifecycle_probes[0].command.startswith(
            "python scripts/build.py"
        )
        assert contract.lifecycle_probes[3].input == "previous and candidate artifacts"


def test_contract_rejects_missing_lifecycle_probe():
    """Given a target contract, when a lifecycle probe is omitted, then it fails."""
    contract = ArtifactContract.default("windows-x64", "0.6.2")
    invalid = contract.with_metadata(lifecycle_probes=contract.lifecycle_probes[:-1])

    with pytest.raises(ContractViolation, match="lifecycle probes"):
        validate_contract(invalid)


def test_contract_rejects_skippable_lifecycle_probe():
    """Given a target contract, when a required probe is skippable, then it fails."""
    contract = ArtifactContract.default("linux-rpm-x64", "0.6.2")
    invalid = contract.with_metadata(
        lifecycle_probes=(
            contract.lifecycle_probes[0].with_field("required", False),
            *contract.lifecycle_probes[1:],
        )
    )

    with pytest.raises(ContractViolation, match="required"):
        validate_contract(invalid)


@pytest.mark.parametrize("field", ("command", "observable", "cleanup"))
def test_contract_rejects_incomplete_executable_lifecycle_probe(field):
    """Given a lifecycle probe, when its Todo 30 spec is absent, then it fails."""
    contract = ArtifactContract.default("linux-appimage-x64", "0.6.2")
    incomplete = contract.lifecycle_probes[0].with_field(field, "")
    invalid = contract.with_metadata(
        lifecycle_probes=(incomplete, *contract.lifecycle_probes[1:])
    )

    with pytest.raises(ContractViolation, match=field):
        validate_contract(invalid)


def test_macos_bundle_id_is_derived_from_info_plist(monkeypatch, tmp_path):
    """Given a plist bundle ID, when loading macOS contracts, then it is derived."""
    from scripts import package_smoke

    plist = tmp_path / "Info.plist"
    plist.write_text(
        "<?xml version='1.0'?><plist><dict><key>CFBundleIdentifier</key>"
        "<string>com.example.derived</string></dict></plist>",
        encoding="utf-8",
    )
    monkeypatch.setattr(package_smoke, "MACOS_INFO_PLIST", plist)

    assert ArtifactContract.default("macos-arm64", "0.6.2").bundle_id == (
        "com.example.derived"
    )


def test_macos_bundle_id_is_read_from_build_input(monkeypatch, tmp_path):
    """Given a drifted Info.plist, when reporting, then it rejects the build input."""
    from scripts import package_smoke

    plist = tmp_path / "Info.plist"
    plist.write_text(
        "<?xml version='1.0'?><plist><dict><key>CFBundleIdentifier</key>"
        "<string>com.example.drift</string></dict></plist>",
        encoding="utf-8",
    )
    monkeypatch.setattr(package_smoke, "MACOS_INFO_PLIST", plist)

    with pytest.raises(ContractViolation, match="bundle id"):
        contract_report(target="macos-arm64")


def test_macos_packaging_copies_bundle_id_build_input(monkeypatch, tmp_path):
    """Given a macOS app, when DMG staging runs, then it copies Info.plist."""
    from scripts import build

    project = tmp_path / "project"
    template = project / "scripts" / "installer" / "macos" / "Info.plist"
    template.parent.mkdir(parents=True)
    template.write_text("bundle input", encoding="utf-8")
    contents = tmp_path / "dist" / "OhMyMeme.app" / "Contents"
    contents.mkdir(parents=True)

    class Result:
        returncode = 0

    monkeypatch.setattr(build, "PROJECT_ROOT", project)
    monkeypatch.setattr(build, "BUILD_DIR", tmp_path / "dist")
    monkeypatch.setattr(build.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(build.os, "symlink", lambda *args: None)

    build.build_macos_packages("0.6.2", arch="arm64")

    assert (contents / "Info.plist").read_text(encoding="utf-8") == "bundle input"


def test_contract_rejects_wrong_architecture():
    """Given an AppImage artifact, when architecture drifts, then validation fails."""

    contract = ArtifactContract.default("linux-appimage-x64", "0.6.2")
    invalid = contract.with_metadata(architecture="arm64")

    with pytest.raises(ContractViolation, match="architecture"):
        validate_contract(invalid)


def test_contract_rejects_missing_required_resource():
    """Given a DMG contract, when its resource is missing, then validation fails."""

    contract = ArtifactContract.default("macos-arm64", "0.6.2")
    invalid = contract.with_metadata(resources=())

    with pytest.raises(ContractViolation, match="resource"):
        validate_contract(invalid)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("windows-x64", "app_id", "wrong-app-id"),
        ("linux-rpm-x64", "license", "MIT"),
        ("macos-x86_64", "bundle_id", "com.example.drift"),
    ],
)
def test_contract_rejects_identity_and_metadata_drift(target, field, value):
    """Given an artifact, when identity metadata drifts, then validation fails."""

    contract = ArtifactContract.default(target, "0.6.2")
    invalid = contract.with_metadata(**{field: value})

    with pytest.raises(ContractViolation, match=field.replace("_", " ")):
        validate_contract(invalid)


def test_nightly_release_is_never_selected_as_stable(monkeypatch):
    """Given a nightly release, when stable parsing runs, then it is rejected."""
    from src import updater

    monkeypatch.setattr(updater.platform, "system", lambda: "Windows")
    release = {
        "tag_name": "nightly",
        "prerelease": False,
        "assets": [{"name": "OhMyMeme-nightly-setup.exe", "browser_download_url": "x"}],
    }

    assert updater._parse_release(release) is None


def test_linux_updater_selects_only_appimage(monkeypatch):
    """Given Linux release assets, when selection runs, then deb and rpm are ignored."""
    from src import updater

    monkeypatch.setattr(updater.platform, "system", lambda: "Linux")
    assets = [
        {"name": "OhMyMeme-v0.6.2-amd64.deb", "browser_download_url": "deb"},
        {"name": "OhMyMeme-v0.6.2-x86_64.rpm", "browser_download_url": "rpm"},
        {
            "name": "OhMyMeme-v0.6.2-x86_64.AppImage",
            "browser_download_url": "appimage",
        },
    ]

    assert updater._pick_asset_url(assets) == "appimage"


def test_nightly_contracts_are_not_updater_selectable():
    """Given nightly contracts, when reported, then none joins the stable updater."""
    from scripts.package_smoke import contract_report

    report = contract_report(channel="nightly")

    assert all(row["channel"] == "nightly" for row in report["targets"])
    assert not any(row["updater_selectable"] for row in report["targets"])


@pytest.mark.parametrize(
    "workflow",
    [".github/workflows/build.yml", ".github/workflows/nightly.yml"],
)
def test_release_workflows_run_contract_smoke_before_upload(workflow):
    """Given a release workflow, when built, then smoke runs before upload."""
    content = (ROOT / workflow).read_text(encoding="utf-8")

    assert content.count("Package contract smoke") == 3
    assert content.count("--contract-only") == 3
    assert content.index("Package contract smoke") < content.index("Upload artifact")
