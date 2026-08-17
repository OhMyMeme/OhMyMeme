"""离线发布产物契约 smoke 测试。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.package_smoke import ArtifactContract, ContractViolation, validate_contract

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
