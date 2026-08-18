import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ohmymeme.core.assets import ResourceLocator


def test_source_locator_resolves_fixed_resources_without_creating_user_data(
    tmp_path,
):
    # Given: a source checkout and an absent user-data path.
    user_data_dir = tmp_path / "user-data"

    # When: the source locator is created while all filesystem I/O is forbidden.
    with (
        patch.object(Path, "exists", side_effect=AssertionError("filesystem read")),
        patch.object(Path, "mkdir", side_effect=AssertionError("filesystem write")),
        patch.object(Path, "open", side_effect=AssertionError("filesystem read")),
        patch.object(Path, "read_bytes", side_effect=AssertionError("filesystem read")),
        patch.object(Path, "read_text", side_effect=AssertionError("filesystem read")),
    ):
        locator = ResourceLocator.for_source(user_data_dir)

    # Then: fixed resources resolve while user data remains untouched.
    source_root = Path(__file__).resolve().parents[2] / "src"
    assert locator.package_root == source_root / "ohmymeme"
    assert locator.webui_dir == source_root / "webui"
    assert locator.resources_dir == source_root / "resources"
    assert locator.adb_help_path == source_root / "adb-help.txt"
    assert locator.offsets_path == source_root.parent / "config" / "offsets.json"
    assert locator.webui_dir.joinpath("vue.html").is_file()
    assert locator.resources_dir.joinpath("OhMyMeme.mp4").is_file()
    assert locator.resources_dir.joinpath("icon.png").is_file()
    assert locator.adb_help_path.is_file()
    assert locator.offsets_path.is_file()
    assert locator.user_data_dir == user_data_dir
    assert not user_data_dir.exists()


def test_frozen_locator_resolves_simulated_package_resources_without_user_data_io(
    tmp_path,
):
    # Given: an isolated frozen bundle layout and absent user data.
    bundle_root = tmp_path / "bundle"
    package_root = bundle_root / "ohmymeme"
    (package_root / "webui").mkdir(parents=True)
    (package_root / "resources").mkdir()
    (package_root / "config").mkdir()
    (package_root / "webui" / "vue.html").touch()
    (package_root / "resources" / "OhMyMeme.mp4").touch()
    (package_root / "resources" / "icon.png").touch()
    (package_root / "adb-help.txt").touch()
    (package_root / "config" / "offsets.json").touch()
    user_data_dir = tmp_path / "user-data"

    # When: the frozen locator is created while all filesystem I/O is forbidden.
    with (
        patch.object(Path, "exists", side_effect=AssertionError("filesystem read")),
        patch.object(Path, "mkdir", side_effect=AssertionError("filesystem write")),
        patch.object(Path, "open", side_effect=AssertionError("filesystem read")),
        patch.object(Path, "read_bytes", side_effect=AssertionError("filesystem read")),
        patch.object(Path, "read_text", side_effect=AssertionError("filesystem read")),
    ):
        locator = ResourceLocator.for_frozen(bundle_root, user_data_dir)

    # Then: package-contained resources resolve and user data remains absent.
    assert locator.package_root == package_root
    assert locator.webui_dir.joinpath("vue.html").is_file()
    assert locator.resources_dir.joinpath("OhMyMeme.mp4").is_file()
    assert locator.resources_dir.joinpath("icon.png").is_file()
    assert locator.adb_help_path.is_file()
    assert locator.offsets_path.is_file()
    assert locator.user_data_dir == user_data_dir
    assert not user_data_dir.exists()
