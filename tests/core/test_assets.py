import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ohmymeme.core.assets import AssetPaths, ResourceLocator
from ohmymeme.core.database import MemeDB
from ohmymeme.core.manifest import ManifestBuilder, _load


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


def test_missing_manifest_loads_as_empty_version_3_structure(tmp_path):
    # Given: an isolated data directory without a manifest
    assets = AssetPaths(tmp_path, tmp_path / "cache")

    # When: the manifest loader reads the absent file
    result = _load(assets)

    # Then: the absence is represented by the canonical empty v3 structure
    assert result == {"version": 3, "memes": [], "collections": []}


def test_manifest_build_removes_empty_collection_from_database_and_projection(
    tmp_path,
):
    # Given: a real database containing a meme and an empty collection
    assets = AssetPaths(tmp_path, tmp_path / "cache")
    assets.cache_dir.mkdir()
    db = MemeDB(tmp_path / "memes.db")
    meme_id = db.add_meme("example.png", original_name="Example")
    populated_id = db.create_collection("Populated")
    db.add_to_collection(meme_id, populated_id)
    empty_id = db.create_collection("Empty")

    # When: the manifest is built from the database
    manifest = ManifestBuilder(None, db, assets).build()

    # Then: the meme projection succeeds, while the empty DB collection is cleaned
    data = json.loads(assets.manifest_path.read_text(encoding="utf-8"))
    assert manifest == [
        {
            "filename": "example.png",
            "name": "Example",
            "sha256": "",
            "file_size": 0,
            "mtime": "",
        }
    ]
    assert [item["name"] for item in data["collections"]] == ["Populated"]
    assert db.get_collections() == [(populated_id, "Populated", None, 0)]
    assert all(item["name"] != "Empty" for item in data["collections"])
    assert db.get_by_id(meme_id)["filename"] == "example.png"
    assert db.get_by_id(empty_id) is None
    db.close()


def test_manifest_build_preserves_nested_v3_collection_names_and_filenames(tmp_path):
    # Given: nested collections with members associated by database filenames
    assets = AssetPaths(tmp_path, tmp_path / "cache")
    assets.cache_dir.mkdir()
    db = MemeDB(tmp_path / "memes.db")
    first_id = db.add_meme("first.png", original_name="First")
    second_id = db.add_meme("second.png", original_name="Second")
    root_id = db.create_collection("Root")
    child_id = db.create_collection("Child", parent_id=root_id)
    db.add_to_collection(first_id, root_id)
    db.add_to_collection(second_id, child_id)

    # When: the nested manifest is projected
    ManifestBuilder(None, db, assets).build()

    # Then: v3 stores nested names and stable filename associations
    data = json.loads(assets.manifest_path.read_text(encoding="utf-8"))
    assert data["version"] == 3
    assert data["collections"] == [
        {
            "name": "Root",
            "filenames": ["first.png"],
            "children": [{"name": "Child", "filenames": ["second.png"]}],
        }
    ]
    assert db.get_by_id(first_id)["filename"] == "first.png"
    assert db.get_by_id(second_id)["filename"] == "second.png"
    assert sorted(db.get_collections()) == sorted(
        [
            (root_id, "Root", None, 0),
            (child_id, "Child", root_id, 0),
        ]
    )
    db.close()
