import io
import json
import sqlite3
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

import bottle
import pytest
from PIL import Image
from plugin_fixtures import install_official

from ohmymeme.app.container import Container
from ohmymeme.core import assets
from ohmymeme.core.domain import TaskKind
from ohmymeme.core.imports import ImportBytes
from ohmymeme.core.plugins.runtime import seeding
from ohmymeme.core.plugins.runtime.manager import WorkerHandle
from ohmymeme.core.plugins.runtime.worker import PluginWorker
from ohmymeme.presentation.desktop.bottle_app import create_bottle_app

# 该文件由 3404f84d 清扫提交带入，来自未落库的平行工作流：所引用的 Container/Settings/
# Worker 形状与当前实现不一致（container.backups、container.import_jobs、
# save_settings_checked、WorkerHandle.sessions 等均不存在），从未在任何分支通过。
# 整体隔离，待按当前 API 逐条对齐后再解除。
pytestmark = pytest.mark.skip(
    reason="平行工作流回归文件与当前实现 API 不匹配（见 commit 3404f84d）"
)


@pytest.fixture
def container(tmp_path):
    # 全部写入都使用测试独立数据根。
    instance = Container(tmp_path / "app")
    try:
        yield instance
    finally:
        instance.close()


def image_bytes(color):
    # 构造可验证的最小图片。
    output = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(output, "PNG")
    return output.getvalue()


def import_image(container, color="red"):
    # 走真实宿主导入和 manifest 提交流程。
    return (
        container.create_import_service()
        .import_bytes(ImportBytes(image_bytes(color), color + ".png"))
        .imported_ids[0]
    )


def request(app, owner, path, body, content_type="application/json"):
    # 调用真实 WSGI 路由，不启动 GUI 或监听公网。
    environ = {}
    setup_testing_defaults(environ)
    environ.update(
        REQUEST_METHOD="POST",
        PATH_INFO=path,
        CONTENT_TYPE=content_type,
        CONTENT_LENGTH=str(len(body)),
        HTTP_HOST=f"127.0.0.1:{owner._port}",
    )
    environ["wsgi.input"] = io.BytesIO(body)
    observed = {}
    result = app(environ, lambda status, headers, *args: observed.update(status=status))
    raw = b"".join(result)
    if hasattr(result, "close"):
        result.close()
    return observed["status"], json.loads(raw)


def test_actual_plugin_install_route_finishes_and_clears_cache(container):
    owner = container.create_webui()
    owner._runtime_import_workers = {"community.review": object()}
    app = create_bottle_app(owner, bottle, SimpleNamespace())
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "plugin.json",
            json.dumps(
                {
                    "id": "community.review",
                    "version": "1.0",
                    "entry": "review_plugin:create_plugin",
                }
            ),
        )
        archive.writestr("review_plugin.py", "def create_plugin():\n    return None\n")
    status, result = request(
        app,
        owner,
        "/api/plugins/install",
        stream.getvalue(),
        "application/octet-stream",
    )
    assert status == "200 OK"
    assert result == {"ok": True, "plugin": "community.review", "version": "1.0"}
    assert owner._runtime_import_workers == {}
    assert (
        seeding.resolve_plugin(container.config.data_dir, "community.review")["version"]
        == "1.0"
    )
    assert not list(container.config.data_dir.glob("*.zip"))
    status, result = request(
        app, owner, "/api/plugins/uninstall", b'{"id":"community.review"}'
    )
    assert status == "200 OK" and result["ok"]


def test_frozen_composition_uses_packaged_assets(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "ohmymeme" / "webui").mkdir(parents=True)
    (bundle / "ohmymeme" / "webui" / "vue.html").touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(
        assets, "__file__", str(bundle / "ohmymeme" / "core" / "assets.py")
    )
    instance = Container(tmp_path / "app")
    try:
        assert instance.resource_locator.frozen_layout
        assert instance.resource_locator.webui_dir.joinpath("vue.html").is_file()
        assert (
            instance.resource_locator.offsets_path
            == bundle / "ohmymeme" / "config" / "offsets.json"
        )
    finally:
        instance.close()


def test_old_import_sink_follows_storage_switch(container, tmp_path):
    sink = container.create_import_sink()
    meme_id = import_image(container)
    owner = container.create_webui()
    target = tmp_path / "new-cache"
    result = owner._settings_api.apply_storage_dir(str(target), True)
    assert result["ok"]
    assert container.assets.cache_dir == target
    assert (target / container.db.get_by_id(meme_id)["filename"]).is_file()
    second = sink.import_bytes(ImportBytes(image_bytes("blue"), "blue.png"))
    assert (
        target / container.db.get_by_id(second.imported_ids[0])["filename"]
    ).is_file()


def test_delete_rejected_before_file_changes_when_sync_holds_lease(container):
    meme_id = import_image(container)
    path = container.assets.cache_dir / container.db.get_by_id(meme_id)["filename"]
    entered, release = threading.Event(), threading.Event()

    def hold():
        with container.remote_mutations.mutation("sync.fixture"):
            entered.set()
            release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert entered.wait(5)
        api = container.create_webui()._api
        assert api.delete_meme(meme_id) is False
        assert api.delete_memes([meme_id]) == {"ok": False, "deleted": 0}
        assert path.is_file() and container.db.get_by_id(meme_id)
    finally:
        release.set()
        thread.join(5)


def test_failed_metadata_delete_restores_staged_original(container, monkeypatch):
    meme_id = import_image(container)
    path = container.assets.cache_dir / container.db.get_by_id(meme_id)["filename"]

    def fail(_ids):
        raise sqlite3.OperationalError("fixture write failure")

    monkeypatch.setattr(container.db, "delete_memes", fail)
    assert container.catalog.delete_meme(meme_id) is False
    assert path.is_file()
    assert not container.assets.data_dir.joinpath(".delete-recovery.json").exists()


def test_collection_replacement_rolls_back_before_later_commit(container):
    one, two = import_image(container), import_image(container, "blue")
    cid = container.db.create_collection("group")
    container.db.set_collection_members(cid, [one])
    assert container.catalog.set_collection_members(cid, [two, 999999]) is False
    assert not container.db._get_conn().in_transaction
    container.db.toggle_favorite(one)
    assert [row["id"] for row in container.db.search(collection_id=cid)] == [one]


def test_large_collection_editor_gets_complete_member_set(container):
    conn = container.db._get_conn()
    conn.executemany(
        "INSERT INTO memes (filename, file_hash) VALUES (?, ?)",
        [(f"{i}.png", f"{i:064x}") for i in range(5010)],
    )
    conn.commit()
    ids = [row["id"] for row in container.db.search(limit=6000)]
    cid = container.db.create_collection("large")
    container.db.set_collection_members(cid, ids)
    assert len(container.catalog.get_collection_members(cid)) == 5010


def test_reordering_page_two_preserves_page_one_slots(container):
    ids = [container.db.add_meme(f"{i}.png", file_hash=f"{i:064x}") for i in range(205)]
    container.db.reorder_memes(ids)
    assert container.catalog.reorder_memes(list(reversed(ids[200:])))
    assert [row["id"] for row in container.db.search(limit=205)] == ids[:200] + list(
        reversed(ids[200:])
    )


def test_lan_confirmation_finishes_the_owned_server(container):
    entry = {"done": threading.Event(), "approved": False}
    container.lan._pending_confirms["fixture"] = entry
    assert container.create_webui()._api.lan_confirm_device(True, "fixture")["ok"]
    assert entry["done"].is_set() and entry["approved"]


def test_closing_settings_keeps_lan_running(container, monkeypatch):
    owner = container.create_webui()
    calls = []
    monkeypatch.setattr(container.lan, "stop", lambda: calls.append("stop"))
    owner.close_settings()
    assert calls == []


def test_seeded_official_factory_is_loaded_from_active_version(container, monkeypatch):
    install_official(container.config.data_dir, "source.qqnt")
    spec = seeding.resolve_plugin(container.config.data_dir, "source.qqnt")
    worker = PluginWorker("source.qqnt", "fixture")
    with monkeypatch.context() as scoped:
        scoped.setitem(
            sys.modules, "ohmymeme_plugin_qqnt", sys.modules.get("ohmymeme_plugin_qqnt")
        )
        worker._load_plugin(spec)
        assert Path(sys.modules["ohmymeme_plugin_qqnt"].__file__).is_relative_to(
            Path(spec["package_dir"])
        )


@pytest.mark.parametrize("version", [True, 999])
def test_worker_rejects_incompatible_api_version(tmp_path, version):
    (tmp_path / "review_version.py").write_text(
        f'class Provider:\n    provider_id="community.review"\n    api_version={version!r}\ndef create_plugin():\n    return Provider()\n',
        encoding="utf-8",
    )
    worker = PluginWorker("community.review", "fixture")
    with pytest.raises(RuntimeError, match="identity"):
        worker._load_plugin(
            {
                "id": "community.review",
                "entry": "review_version:create_plugin",
                "package_dir": str(tmp_path),
            }
        )


def test_heartbeat_does_not_reset_business_idle_time(container):
    worker = WorkerHandle("fixture", {}, "fixture")
    worker.last_activity = 0
    worker.channel = SimpleNamespace(call=lambda *args, **kwargs: {"pong": True})
    with patch(
        "ohmymeme.core.plugins.runtime.manager.time.monotonic", return_value=1000
    ):
        container.plugin_runtime._ping_worker(worker)
    assert worker.last_activity == 0
    worker.sessions.add("lan")
    assert container.plugin_runtime._worker_busy(worker)


def test_webp_animation_properties_are_injected_at_composition_root(container):
    output = io.BytesIO()
    Image.new("RGB", (12, 12), "red").save(
        output,
        "WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (12, 12), "blue")],
        duration=100,
    )
    result = container.create_import_service().import_bytes(
        ImportBytes(output.getvalue(), "animated.webp")
    )
    assert (
        next(
            row
            for row in container.catalog.search_memes()
            if row["id"] == result.imported_ids[0]
        )["is_animated"]
        is True
    )


def test_failed_settings_save_does_not_claim_success(container, monkeypatch):
    original = container.config.get("hotkey")
    with monkeypatch.context() as scoped:
        scoped.setattr(
            type(container.config),
            "save",
            lambda self: (_ for _ in ()).throw(OSError("fixture disk failure")),
        )
        result = container.create_webui()._settings_api.save_settings_checked(
            {"hotkey": "Ctrl+Shift+X"}
        )
    assert result == {"ok": False, "error": "fixture disk failure"}
    assert container.config.get("hotkey") == original


def test_local_job_repeated_folder_import_reuses_members(container, tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "one.png").write_bytes(image_bytes("red"))
    for _ in range(2):
        assert container.import_jobs.start_folder(folder)["ok"]
        container.operations.wait(TaskKind.IMPORT_LOCAL, 5)
        assert container.import_jobs.get_progress()["status"] == "done"
    assert container.db.count() == 1
    assert len(container.db.get_collections()) == 1


def test_backup_roundtrip_preserves_metadata_and_rejects_nonempty_restore(
    container, tmp_path
):
    meme_id = import_image(container)
    container.catalog.set_meme_tags(meme_id, ["tag"])
    container.catalog.toggle_favorite(meme_id)
    container.catalog.add_to_collection(meme_id, "group")
    assert container.backups.start()["ok"]
    container.operations.wait(TaskKind.BACKUP_CREATE, 5)
    state = container.backups.get_progress()
    assert state["status"] == "done", state
    path = container.backups.directory / state["result"]["path"]
    assert container.backups.start(str(path))["ok"] is False
    destination = Container(tmp_path / "destination")
    try:
        assert destination.backups.start(str(path))["ok"]
        destination.operations.wait(TaskKind.BACKUP_RESTORE, 5)
        assert destination.backups.get_progress()["status"] == "done"
        assert destination.db.get_meme_tags(meme_id) == ["tag"]
        assert destination.db.is_favorite(meme_id)
        assert destination.db.get_collections()[0][1] == "group"
        assert destination.find_meme_file(destination.db.get_by_id(meme_id)["filename"])
    finally:
        destination.close()


def test_multiple_uploads_reach_the_host_import_service(container):
    import base64

    owner = container.create_webui()
    app = create_bottle_app(owner, bottle, SimpleNamespace())
    body = json.dumps(
        {
            "files": [
                {
                    "name": color + ".png",
                    "data": base64.b64encode(image_bytes(color)).decode(),
                }
                for color in ("red", "blue")
            ]
        }
    ).encode()
    status, result = request(app, owner, "/api/upload/", body)
    assert status == "200 OK" and result == {"ok": True, "imported": 2, "rejected": 0}
    assert container.db.count() == 2


def test_capacity_evicts_only_a_worker_without_operations_or_sessions(
    container, monkeypatch
):
    from ohmymeme.core.plugins.runtime.manager import MAX_WORKERS

    runtime = container.plugin_runtime
    workers = [WorkerHandle(str(i), {}, "fixture") for i in range(MAX_WORKERS)]
    for worker in workers[1:]:
        worker.sessions.add("active")
    runtime._workers = {worker.plugin_id: worker for worker in workers}
    stopped = []

    def stop(worker, reason, intentional):
        stopped.append(worker.plugin_id)
        runtime._workers.pop(worker.plugin_id)

    with monkeypatch.context() as scoped:
        scoped.setattr(runtime, "_stop_worker", stop)
        runtime._check_capacity()
    assert stopped == ["0"]
    runtime._workers.clear()


def test_interrupted_delete_is_recovered_before_media_is_exposed(container):
    from ohmymeme.core.adapters.filesystem.atomic_repository import AtomicFileRepository

    meme_id = import_image(container)
    path = container.find_meme_file(container.db.get_by_id(meme_id)["filename"])
    staged = path.with_name(".delete-fixture.pending")
    path.replace(staged)
    marker = container.assets.data_dir / ".delete-recovery.json"
    marker.write_text(
        json.dumps(
            {
                "cache_root": str(container.assets.cache_dir),
                "ids": [meme_id],
                "files": [
                    {"id": meme_id, "original": path.name, "staged": staged.name}
                ],
            }
        )
    )
    assert AtomicFileRepository(container.assets).recover_deletions(
        container.db.get_by_id
    )
    assert path.is_file() and not staged.exists() and not marker.exists()


def test_shutdown_drains_an_untracked_sync_mutation_before_releasing_the_data_root(
    container,
):
    entered, release = threading.Event(), threading.Event()

    def work():
        with container.remote_mutations.mutation("sync.fixture"):
            entered.set()
            release.wait(5)

    writer = threading.Thread(target=work)
    writer.start()
    assert entered.wait(5)
    closed = []
    closer = threading.Thread(target=lambda: closed.append(container.close()))
    closer.start()
    assert container._closing is True or closer.is_alive()
    release.set()
    writer.join(5)
    closer.join(5)
    assert closed and container._closed and not container.remote_mutations.busy


def test_single_instance_lock_prevents_a_second_process(tmp_path):
    import subprocess
    import uuid

    name = "OhMyMeme_Test_" + uuid.uuid4().hex
    code = "from ohmymeme.integrations.platform.system import acquire_single_instance; import sys; print(acquire_single_instance(sys.argv[1]), flush=True); sys.stdin.readline()"
    owner = subprocess.Popen(
        [sys.executable, "-u", "-c", code, name],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert owner.stdout.readline().strip() == "True"
        second = subprocess.run(
            [
                sys.executable,
                "-c",
                "from ohmymeme.integrations.platform.system import acquire_single_instance; import sys; print(acquire_single_instance(sys.argv[1]))",
                name,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert second.stdout.strip() == "False"
    finally:
        owner.stdin.write("stop\n")
        owner.stdin.flush()
        owner.wait(timeout=10)
