import json
import os
import shutil
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path
from types import SimpleNamespace

import pytest
from setuptools import build_meta

import scripts.plugin_packaging as packaging
from ohmymeme.core.plugins.runtime import seeding

ROOT = Path(__file__).resolve().parents[1]
PACKAGING_SCRIPT = ROOT / "scripts" / "plugin_packaging.py"
PLUGIN_PATHS = [
    "plugins/source.qqnt",
    "plugins/source.telegram",
    "plugins/source.douyin",
    "plugins/source.wechat",
    "plugins/sync.ftp",
    "plugins/sync.s3",
    "plugins/sync.r2",
    "plugins/sync.webdav",
    "plugins/transport.lan",
]


def _run_source_cli(staging, source_manifest, report):
    # Execute the packaging CLI against the copied fixture, not expected data.
    result = subprocess.run(
        [
            sys.executable,
            str(PACKAGING_SCRIPT),
            "--source",
            "--frozen-staging",
            str(staging),
            "--staging-manifest",
            str(staging / "staging-manifest.json"),
            "--source-manifest",
            str(source_manifest),
            "--frozen-manifest",
            "ohmymeme/config/plugin-manifest.json",
            "--report",
            str(report),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return result, json.loads(report.read_text(encoding="utf-8"))


def test_stage_metadata_carries_pep639_license_files(tmp_path):
    # Real setuptools metadata must retain every plugin's declared GPL file.
    staging = tmp_path / "staging"
    staging_manifest = staging / "staging-manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            str(PACKAGING_SCRIPT),
            "--stage",
            "--staging-dir",
            str(staging),
            "--staging-manifest",
            str(staging_manifest),
            "--source-manifest",
            str(ROOT / "config/plugin-manifest.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout
    manifest = json.loads(staging_manifest.read_text(encoding="utf-8"))
    for row in manifest["packages"]:
        metadata_name = next(
            name for name in row["metadata_files"] if name.endswith("/METADATA")
        )
        metadata = Parser().parsestr((staging / metadata_name).read_text("utf-8"))
        assert metadata.get("License-Expression") == "GPL-3.0-only"
        assert metadata.get_all("License-File") == ["LICENSE"]
        license_name = metadata_name.rsplit("/", 1)[0] + "/licenses/LICENSE"
        assert (staging / license_name).read_bytes() == (
            ROOT / "plugins" / row["id"] / "LICENSE"
        ).read_bytes()


def test_root_metadata_carries_only_owned_pep639_license_file(tmp_path):
    # Host metadata lists only the actual root GPL file, not third-party notices.
    project = tmp_path / "host"
    project.mkdir()
    for name in ("LICENSE", "README.md", "setup.py"):
        shutil.copy2(ROOT / name, project / name)
    shutil.copytree(ROOT / "src/ohmymeme", project / "src/ohmymeme")
    metadata_root = project / "metadata"
    metadata_root.mkdir()
    previous = Path.cwd()
    try:
        os.chdir(project)
        dist_info_name = build_meta.prepare_metadata_for_build_wheel(str(metadata_root))
    finally:
        os.chdir(previous)
    dist_info = metadata_root / dist_info_name
    metadata = Parser().parsestr((dist_info / "METADATA").read_text("utf-8"))

    assert metadata.get("License-Expression") == "GPL-3.0-only"
    assert metadata.get_all("License-File") == ["LICENSE"]
    assert (dist_info / "licenses/LICENSE").read_bytes() == (
        ROOT / "LICENSE"
    ).read_bytes()
    assert sorted(path.name for path in (dist_info / "licenses").iterdir()) == [
        "LICENSE"
    ]


def test_staging_rejects_unclaimed_pep639_license_file(tmp_path):
    # A frozen licenses directory cannot carry a file absent from License-File.
    staging = tmp_path / "unclaimed-license-staging"
    shutil.copytree(ROOT / "fixtures/plugin-parity/frozen-staging", staging)
    extra = staging / "ohmymeme_plugin_qqnt-0.1.0.dist-info/licenses/UNDECLARED-NOTICE"
    extra.write_text("not declared by metadata", encoding="utf-8")
    manifest_path = staging / "staging-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = next(item for item in manifest["packages"] if item["id"] == "source.qqnt")
    row["metadata_files"].append(
        "ohmymeme_plugin_qqnt-0.1.0.dist-info/licenses/UNDECLARED-NOTICE"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result, report = _run_source_cli(
        staging, ROOT / "config/plugin-manifest.json", tmp_path / "report.json"
    )

    assert result.returncode == 1
    assert report["status"] == "REJECTED"
    assert any("unclaimed staged license" in error for error in report["errors"])


def test_rogue_dist_info_is_rejected(tmp_path):
    # A real staged copy with an extra dist-info must fail closed.
    staging = tmp_path / "rogue-staging"
    shutil.copytree(ROOT / "fixtures/plugin-parity/frozen-staging", staging)
    rogue = staging / "rogue_plugin-9.9.9.dist-info"
    rogue.mkdir()
    (rogue / "METADATA").write_text(
        "Name: rogue-plugin\nVersion: 9.9.9\n", encoding="utf-8"
    )
    result, report = _run_source_cli(
        staging, ROOT / "config/plugin-manifest.json", tmp_path / "report.json"
    )
    assert result.returncode == 1
    assert report["status"] == "REJECTED"
    assert any("unknown or misplaced dist-info" in error for error in report["errors"])


@pytest.mark.parametrize("newline", [b" ", b"\r\n"])
def test_noncanonical_source_manifest_is_rejected(tmp_path, newline):
    # Semantically valid but noncanonical source bytes cannot pass.
    staging = tmp_path / "noncanonical-staging"
    shutil.copytree(ROOT / "fixtures/plugin-parity/frozen-staging", staging)
    source = tmp_path / "source-manifest.json"
    raw = (ROOT / "config/plugin-manifest.json").read_bytes()
    if newline == b" ":
        source.write_bytes(raw + newline)
    else:
        source.write_bytes(raw.replace(b"\n", newline))
    result, report = _run_source_cli(staging, source, tmp_path / "report.json")
    assert result.returncode == 1
    assert report["status"] == "REJECTED"
    assert any(
        "source manifest" in error and "canonical" in error
        for error in report["errors"]
    )


def test_equal_noncanonical_source_and_frozen_are_rejected(tmp_path):
    # Equal malformed projections must not turn byte equality into PASS.
    staging = tmp_path / "equal-noncanonical-staging"
    shutil.copytree(ROOT / "fixtures/plugin-parity/frozen-staging", staging)
    source = tmp_path / "source-manifest.json"
    source.write_bytes((ROOT / "config/plugin-manifest.json").read_bytes() + b" ")
    frozen = staging / "ohmymeme/config/plugin-manifest.json"
    frozen.write_bytes(frozen.read_bytes() + b" ")
    result, report = _run_source_cli(staging, source, tmp_path / "report.json")
    assert result.returncode == 1
    assert report["status"] == "REJECTED"
    assert any("source manifest" in error for error in report["errors"])


def test_bad_staging_is_rejected_before_provider_probe(monkeypatch):
    # The invalid committed fixture must stop before any factory probe call.
    called = []

    def probe(*args):
        called.append(args)
        return [], []

    monkeypatch.setattr(packaging, "_probe_factories", probe)
    args = SimpleNamespace(
        source_manifest="config/plugin-manifest.json",
        frozen_staging="fixtures/plugin-parity/frozen-staging-invalid",
        staging_manifest=(
            "fixtures/plugin-parity/frozen-staging-invalid/staging-manifest.json"
        ),
        frozen_manifest="ohmymeme/config/plugin-manifest.json",
    )
    report = packaging._run_source(args)
    assert report["status"] == "REJECTED"
    assert called == []


def test_stale_staged_module_is_rejected_before_provider_probe(monkeypatch, tmp_path):
    # A stale staged module must fail hash verification before any factory import.
    staging = tmp_path / "stale-staging"
    shutil.copytree(ROOT / "fixtures/plugin-parity/frozen-staging", staging)
    staged_module = staging / "ohmymeme_plugin_sync_webdav/__init__.py"
    staged_module.write_bytes(staged_module.read_bytes() + b"\n# stale staging probe\n")
    called = []

    def probe(*args):
        called.append(args)
        return [], []

    monkeypatch.setattr(packaging, "_probe_factories", probe)
    args = SimpleNamespace(
        source_manifest="config/plugin-manifest.json",
        frozen_staging=str(staging),
        staging_manifest=str(staging / "staging-manifest.json"),
        frozen_manifest="ohmymeme/config/plugin-manifest.json",
    )
    report = packaging._run_source(args)

    assert report["status"] == "REJECTED"
    assert any("hash mismatch for staged" in error for error in report["errors"])
    assert called == []


def test_outside_direct_url_is_rejected_before_provider_probe(monkeypatch):
    # Valid metadata cannot override a direct_url source tree outside this worktree.
    class FakeDistribution:
        def __init__(self, provider_id):
            self.metadata = {"Name": packaging._distribution_name(provider_id)}
            self.version = "0.1.0"
            self.entry_points = (
                SimpleNamespace(
                    group=packaging.ENTRY_POINT_GROUP,
                    name=provider_id,
                    value=f"{packaging._module_name(provider_id)}:create_plugin",
                ),
            )

        def read_text(self, name):
            assert name == "direct_url.json"
            return json.dumps(
                {
                    "url": "file:///C:/outside/todo13-plugin",
                    "dir_info": {"editable": True},
                }
            )

        def locate_file(self, value):
            return ROOT / ".venv/Lib/site-packages"

    def distribution(name):
        provider_id = next(
            provider_id
            for provider_id in packaging._canonical_ids()
            if packaging._distribution_name(provider_id) == name
        )
        return FakeDistribution(provider_id)

    called = []
    monkeypatch.setattr(packaging.importlib_metadata, "distribution", distribution)
    monkeypatch.setattr(packaging, "_run_process", lambda command: "")
    monkeypatch.setattr(
        packaging, "_probe_factories", lambda *args: (called.append(args) or ([], []))
    )
    report = packaging._run_editable(PLUGIN_PATHS)
    assert report["status"] == "REJECTED"
    assert called == []
    assert any("direct_url.url" in error for error in report["errors"])


@pytest.mark.parametrize("module_name", ["scripts.build", "scripts.nuitka.build"])
def test_build_timeout_is_captured_and_rejected(monkeypatch, module_name):
    # The build runner passes a timeout to subprocess.run and rejects a hung child.
    module = __import__(module_name, fromlist=["_"])
    captured = []

    def timeout_stub(command, **kwargs):
        captured.append({"command": command, "timeout": kwargs.get("timeout")})
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", timeout_stub)
    monkeypatch.setattr(module, "BUILD_TIMEOUT", 0.2)
    with pytest.raises(SystemExit) as error:
        module._run_bounded(["hung-build"])
    assert error.value.code == 124
    assert captured == [{"command": ["hung-build"], "timeout": 0.2}]

    monkeypatch.undo()
    monkeypatch.setattr(module, "BUILD_TIMEOUT", 0.2)
    with pytest.raises(SystemExit) as error:
        module._run_bounded([sys.executable, "-c", "import time; time.sleep(30)"])
    assert error.value.code == 124


def _write_hung_child(path, body):
    path.write_text(
        "import time\n" "from pathlib import Path\n" + body + "time.sleep(30)\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("module_name", ["scripts.build", "scripts.nuitka.build"])
@pytest.mark.parametrize("preexisting", [False, True])
def test_staging_timeout_reclaims_only_owned_paths(
    monkeypatch, tmp_path, module_name, preexisting
):
    # A real child creates a partial marker before the bounded timeout.
    module = __import__(module_name, fromlist=["_"])
    staging = tmp_path / "plugin-staging"
    if preexisting:
        staging.mkdir()
        (staging / "keep.txt").write_text("keep", encoding="utf-8")
    child = tmp_path / "hung-staging.py"
    _write_hung_child(
        child,
        "args = __import__('sys').argv\n"
        "staging = Path(args[args.index('--staging-dir') + 1])\n"
        "staging.mkdir(parents=True, exist_ok=True)\n"
        "(staging / 'partial.marker').write_text('partial', encoding='utf-8')\n",
    )

    monkeypatch.setattr(module, "PYTHON", sys.executable)
    monkeypatch.setattr(module, "PLUGIN_PACKAGING", child)
    monkeypatch.setattr(module, "PLUGIN_STAGING_DIR", staging)
    monkeypatch.setattr(module, "PLUGIN_STAGING_MANIFEST", staging / "staging.json")
    monkeypatch.setattr(module, "BUILD_TIMEOUT", 0.2)

    with pytest.raises(SystemExit) as error:
        module.stage_official_plugins()

    assert error.value.code == 124
    assert (staging / "partial.marker").exists() is False
    if preexisting:
        assert staging.is_dir()
        assert (staging / "keep.txt").read_text(encoding="utf-8") == "keep"
    else:
        assert staging.exists() is False


@pytest.mark.parametrize(
    ("module_name", "build_name", "check_name"),
    [
        ("scripts.build", "build_pyinstaller", "check_pyinstaller"),
        ("scripts.nuitka.build", "build_nuitka", "check_nuitka"),
    ],
)
def test_compiler_timeout_reclaims_owned_outputs_and_preserves_existing(
    monkeypatch, tmp_path, module_name, build_name, check_name
):
    # The compiler stub writes partial output and then hangs; the build wrapper
    # must preserve the original timeout exit while reclaiming only new paths.
    module = __import__(module_name, fromlist=["_"])
    project_root = tmp_path
    build_root = project_root / "build"
    dist_root = project_root / "dist"
    build_root.mkdir()
    dist_root.mkdir()
    (build_root / "existing-output").write_text("keep", encoding="utf-8")
    (dist_root / "existing-output").write_text("keep", encoding="utf-8")
    staging = build_root / "plugin-staging"
    partial_dist = dist_root / "partial-output"
    partial_build = build_root / "partial-output"
    child = tmp_path / "hung-compiler.py"
    _write_hung_child(
        child,
        "import sys\n"
        "for value in sys.argv[1:]:\n"
        "    output = Path(value)\n"
        "    output.mkdir(parents=True, exist_ok=True)\n"
        "    (output / 'partial.marker').write_text('partial', encoding='utf-8')\n",
    )

    monkeypatch.setattr(module, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(module, "BUILD_DIR", dist_root)
    monkeypatch.setattr(module, "PLUGIN_STAGING_DIR", staging)
    monkeypatch.setattr(module, "PLUGIN_STAGING_MANIFEST", staging / "staging.json")
    monkeypatch.setattr(module, "PACKAGE_DIR", tmp_path)
    monkeypatch.setattr(module, "SRC_DIR", tmp_path / "src")
    monkeypatch.setattr(module, "PYTHON", sys.executable)
    monkeypatch.setattr(module, "BUILD_TIMEOUT", 0.2)
    monkeypatch.setattr(module, check_name, lambda: None)
    monkeypatch.setattr(module, "clean", lambda: None)
    monkeypatch.setattr(module, "get_version", lambda: "0.1.0")
    if module_name == "scripts.build":
        monkeypatch.setattr(module, "ensure_vue_frontend", lambda: None)

    def stage_stub():
        staging.mkdir(parents=True)
        (staging / "partial.marker").write_text("partial", encoding="utf-8")
        return staging

    monkeypatch.setattr(module, "stage_official_plugins", stage_stub)
    original_runner = module._run_bounded

    def compiler_stub(_command, **kwargs):
        return original_runner(
            [sys.executable, str(child), str(partial_dist), str(partial_build)],
            **kwargs,
        )

    monkeypatch.setattr(module, "_run_bounded", compiler_stub)

    with pytest.raises(SystemExit) as error:
        if module_name == "scripts.build":
            getattr(module, build_name)(target="Linux")
        else:
            getattr(module, build_name)(target="Linux")

    assert error.value.code == 124
    assert staging.exists() is False
    assert partial_dist.exists() is False
    assert partial_build.exists() is False
    assert (dist_root / "existing-output").read_text(encoding="utf-8") == "keep"
    assert (build_root / "existing-output").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("module_name", ["scripts.build", "scripts.nuitka.build"])
def test_installer_iss_is_reclaimed_on_timeout(monkeypatch, tmp_path, module_name):
    # The existing installer finally path must remain intact for both scripts.
    module = __import__(module_name, fromlist=["_"])
    project_root = tmp_path
    dist_root = project_root / "dist"
    dist_root.mkdir()
    if module_name == "scripts.build":
        (dist_root / "OhMyMeme").mkdir()
    else:
        (dist_root / "OhMyMeme.dist").mkdir()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    installer_script = project_root / "scripts" / "installer" / "windows.iss"
    installer_script.parent.mkdir(parents=True)
    installer_script.write_text(
        '#define MyAppVersion "0.1.0"\n'
        '#define SourceDir "..\\\\..\\\\dist\\\\OhMyMeme"\n'
        "OutputDir=..\\\\..\\\\dist\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(module, "BUILD_DIR", dist_root)
    monkeypatch.setattr(module, "find_iscc", lambda: "fake-iscc")
    if hasattr(module, "_ensure_lang_file"):
        monkeypatch.setattr(module, "_ensure_lang_file", lambda _iscc: None)

    def timeout_stub(_command, **_kwargs):
        raise SystemExit(124)

    monkeypatch.setattr(module, "_run_bounded", timeout_stub)
    with pytest.raises(SystemExit) as error:
        if module_name == "scripts.build":
            module.build_installer("0.1.0", target="Windows")
        else:
            module.build_installer("0.1.0")

    assert error.value.code == 124
    assert (dist_root / "ohmy meme.iss").exists() is False


def test_build_plugin_zip_round_trips_through_install(tmp_path):
    # Generated ZIP must install through the real transaction and resolve.
    package_root = packaging._module_name("source.qqnt")
    out = tmp_path / "qqnt.zip"
    result = packaging.build_plugin_zip("source.qqnt", "1.0.0", out)
    assert result["path"] == str(out)
    assert result["bytes"] == out.stat().st_size
    assert result["sha256"] == packaging._sha256_file(out)

    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
    assert "plugin.json" in names
    assert any(name.startswith(package_root + "/") for name in names)
    for name in names:
        assert (
            name == "plugin.json"
            or name.startswith(package_root + "/")
            or name == "LICENSE"
        )
    assert "pyproject.toml" not in names

    data = tmp_path / "data"
    entry = seeding.install_plugin(data, out)
    assert entry["id"] == "source.qqnt"
    assert entry["kind"] == "source"
    assert entry["package_root"] == package_root
    assert entry["capabilities"] == ("filesystem.read", "import.submit")
    assert seeding.resolve_plugin(data, "source.qqnt")["version"] == "1.0.0"
