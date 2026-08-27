import threading
import time

import pytest

from ohmymeme.app.job_manager import JobManager
from ohmymeme.integrations.imports import adb_qq, douyin, telegram, wechat


def _wait_for_job(manager, task_type):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        job = manager.active(task_type)
        if job is not None:
            return job
        time.sleep(0.001)
    raise AssertionError(f"no active job: {task_type}")


def test_telegram_cancel_maps_to_job_cancelled(monkeypatch):
    entered = threading.Event()

    def valid_tdata(_path):
        entered.set()
        while not telegram._check_cancel():
            time.sleep(0.001)
        return False

    monkeypatch.setattr(telegram, "is_valid_tdata", valid_tdata)
    manager = JobManager()
    assert telegram.start_tg_import(lambda _: {}, "controlled", job_manager=manager)
    assert entered.wait(1)
    job = _wait_for_job(manager, "import.telegram")
    telegram.cancel_tg_import()
    assert manager.wait(job.id, 1)
    assert telegram.get_tg_progress()["status"] == "cancelled"
    assert manager.get(job.id).status == "cancelled"
    manager.shutdown(1)


def test_douyin_cancel_maps_to_job_cancelled(monkeypatch):
    entered = threading.Event()

    def build_session(_cookie):
        entered.set()
        while not douyin._check_cancel():
            time.sleep(0.001)
        return None

    monkeypatch.setattr(douyin, "_build_session", build_session)
    manager = JobManager()
    assert douyin.start_douyin_import(lambda _: {}, "cookie", manager)
    assert entered.wait(1)
    job = _wait_for_job(manager, "import.douyin")
    douyin.cancel_douyin_import()
    assert manager.wait(job.id, 1)
    assert douyin.get_douyin_progress()["status"] == "cancelled"
    assert manager.get(job.id).status == "cancelled"
    manager.shutdown(1)


def test_wechat_cancel_maps_to_job_cancelled(monkeypatch):
    entered = threading.Event()

    def inspect(_root):
        entered.set()
        while not wechat._check_cancel():
            time.sleep(0.001)
        return {"status": "unsupported_platform"}

    monkeypatch.setattr(wechat, "inspect_wechat_environment", inspect)
    manager = JobManager()
    assert wechat.start_wechat_import(lambda _: {}, job_manager=manager)
    assert entered.wait(1)
    job = _wait_for_job(manager, "import.wechat")
    wechat.cancel_wechat_import()
    assert manager.wait(job.id, 1)
    assert wechat.get_wechat_progress()["status"] == "cancelled"
    assert manager.get(job.id).status == "cancelled"
    manager.shutdown(1)


def test_adb_cancel_maps_to_job_cancelled(monkeypatch):
    entered = threading.Event()

    def detect():
        entered.set()
        while not adb_qq._check_cancel():
            time.sleep(0.001)
        return ""

    monkeypatch.setattr(adb_qq, "detect_adb", detect)
    manager = JobManager()
    assert adb_qq.start_qq_import(manager)
    assert entered.wait(1)
    job = _wait_for_job(manager, "import.adb_qq")
    adb_qq.cancel_qq_import()
    assert manager.wait(job.id, 1)
    assert adb_qq.get_qq_progress()["status"] == "cancelled"
    assert manager.get(job.id).status == "cancelled"
    manager.shutdown(1)


def test_source_error_maps_to_job_error_without_losing_source_payload(monkeypatch):
    monkeypatch.setattr(telegram, "is_valid_tdata", lambda _path: False)
    manager = JobManager()
    assert telegram.start_tg_import(lambda _: {}, "invalid", job_manager=manager)
    job = _wait_for_job(manager, "import.telegram")
    assert manager.wait(job.id, 1)
    state = telegram.get_tg_progress()
    snapshot = manager.get(job.id)
    assert state["status"] == "error"
    assert state["error_code"] == "invalid_tdata"
    assert snapshot.status == "error"
    assert "invalid_tdata" in snapshot.error
    assert state["error"] in snapshot.error
    manager.shutdown(1)


def test_importer_phase_progress_updates_external_job_snapshot(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def worker(*_args):
        entered.set()
        release.wait(1)

    monkeypatch.setattr(telegram, "_tg_worker", worker)
    manager = JobManager()
    try:
        assert telegram.start_tg_import(lambda _: {}, "controlled", job_manager=manager)
        assert entered.wait(1)
        job = _wait_for_job(manager, "import.telegram")
        telegram._update_tg(progress=37)
        snapshot = manager.get(job.id)
        assert snapshot.progress == 0.37
        assert snapshot.resources == ("telegram",)
    finally:
        release.set()
        manager.shutdown(1)


def test_douyin_source_error_maps_to_job_error(monkeypatch):
    monkeypatch.setattr(douyin, "_build_session", lambda _cookie: None)
    monkeypatch.setattr(douyin, "_check_login", lambda _session: False)
    manager = JobManager()
    assert douyin.start_douyin_import(lambda _: {}, "cookie", manager)
    job = _wait_for_job(manager, "import.douyin")
    assert manager.wait(job.id, 1)
    assert douyin.get_douyin_progress()["error_code"] == "login_failed"
    assert manager.get(job.id).status == "error"
    manager.shutdown(1)


def test_wechat_source_error_maps_to_job_error(monkeypatch):
    monkeypatch.setattr(
        wechat,
        "inspect_wechat_environment",
        lambda _root: {"status": "unsupported_platform", "reason": "controlled"},
    )
    manager = JobManager()
    assert wechat.start_wechat_import(lambda _: {}, job_manager=manager)
    job = _wait_for_job(manager, "import.wechat")
    assert manager.wait(job.id, 1)
    state = wechat.get_wechat_progress()
    assert state["error_code"] == "unsupported_platform"
    assert manager.get(job.id).status == "error"
    manager.shutdown(1)


def test_adb_source_error_maps_to_job_error(monkeypatch):
    monkeypatch.setattr(adb_qq, "detect_adb", lambda: "")
    monkeypatch.setattr(adb_qq, "_download_with_progress", lambda: False)
    manager = JobManager()
    assert adb_qq.start_qq_import(manager)
    job = _wait_for_job(manager, "import.adb_qq")
    assert manager.wait(job.id, 1)
    assert adb_qq.get_qq_progress()["status"] == "error"
    assert manager.get(job.id).status == "error"
    manager.shutdown(1)


def test_adb_cancel_does_not_overwrite_terminal_done_state():
    adb_qq.reset_qq_import()
    adb_qq._update_qq(status="done", progress=100, zip_path="result.zip")
    try:
        adb_qq.cancel_qq_import()
        state = adb_qq.get_qq_progress()
        assert state["status"] == "done"
        assert state["zip_path"] == "result.zip"
    finally:
        adb_qq.reset_qq_import()


def test_adb_legacy_start_is_single_flight(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def worker():
        calls.append(True)
        entered.set()
        release.wait(1)

    monkeypatch.setattr(adb_qq, "_qq_worker", worker)
    adb_qq.reset_qq_import()
    try:
        assert adb_qq.start_qq_import() is True
        assert entered.wait(1)
        assert adb_qq.start_qq_import() is False
        assert calls == [True]
    finally:
        adb_qq.cancel_qq_import()
        release.set()
        assert adb_qq.get_qq_progress()["status"] == "cancelled"
        adb_qq.reset_qq_import()


def test_adb_worker_exception_maps_to_terminal_error(monkeypatch):
    def fail_detect():
        raise ValueError("unexpected detect failure")

    monkeypatch.setattr(
        adb_qq,
        "detect_adb",
        fail_detect,
    )
    manager = JobManager()
    adb_qq.reset_qq_import()
    try:
        assert adb_qq.start_qq_import(manager)
        job = _wait_for_job(manager, "import.adb_qq")
        assert manager.wait(job.id, 1)
        state = adb_qq.get_qq_progress()
        assert state["status"] == "error"
        assert "unexpected detect failure" in state["error"]
        assert manager.get(job.id).status == "error"
        assert manager.active("import.adb_qq") is None
    finally:
        manager.shutdown(1)
        adb_qq.reset_qq_import()


def test_adb_worker_exception_cleans_owned_temp_dir(monkeypatch, tmp_path):
    temp_dir = tmp_path / "qq-worker"

    def fail_worker():
        temp_dir.mkdir()
        (temp_dir / "partial.bin").write_bytes(b"partial")
        adb_qq._QQ_TMP_DIR = temp_dir
        raise ValueError("unexpected processing failure")

    monkeypatch.setattr(adb_qq, "_qq_worker", fail_worker)
    manager = JobManager()
    adb_qq.reset_qq_import()
    try:
        assert adb_qq.start_qq_import(manager)
        job = _wait_for_job(manager, "import.adb_qq")
        assert manager.wait(job.id, 1)
        assert adb_qq.get_qq_progress()["status"] == "error"
        assert not temp_dir.exists()
        assert adb_qq._QQ_TMP_DIR is None
        assert manager.active("import.adb_qq") is None
    finally:
        manager.shutdown(1)
        adb_qq.reset_qq_import()


def test_adb_managed_keyboard_interrupt_reconciles_ui_job_and_temp_cleanup(
    monkeypatch, tmp_path
):
    entered = threading.Event()
    release = threading.Event()
    temp_dir = tmp_path / "qq-interrupt"
    error = "KeyboardInterrupt: controlled adb interrupt"

    def fail_worker():
        temp_dir.mkdir()
        (temp_dir / "partial.bin").write_bytes(b"partial")
        adb_qq._QQ_TMP_DIR = temp_dir
        entered.set()
        release.wait(1)
        raise KeyboardInterrupt("controlled adb interrupt")

    monkeypatch.setattr(adb_qq, "_qq_worker", fail_worker)
    manager = JobManager()
    adb_qq.reset_qq_import()
    try:
        assert adb_qq.start_qq_import(manager)
        assert entered.wait(1)
        job = _wait_for_job(manager, "import.adb_qq")
        release.set()
        assert manager.wait(job.id, 1)

        snapshot = manager.get(job.id)
        state = adb_qq.get_qq_progress()
        assert snapshot.status == "error"
        assert snapshot.error == error
        assert state["status"] == "error"
        assert state["error"] == error
        assert manager.active("import.adb_qq") is None
        assert not temp_dir.exists()
        assert adb_qq._QQ_TMP_DIR is None
        assert adb_qq._QQ_JOB_CANCEL is None
        assert adb_qq._QQ_JOB_SNAPSHOT is None
    finally:
        release.set()
        manager.shutdown(1)
        adb_qq.reset_qq_import()


def test_douyin_cancel_reclaims_worker_temp_dir(monkeypatch, tmp_path):
    entered = threading.Event()
    temp_dir = tmp_path / "douyin-worker"

    def build_session(_cookie):
        temp_dir.mkdir()
        (temp_dir / "partial.webp").write_bytes(b"partial")
        entered.set()
        douyin.cancel_douyin_import()
        return "cancelled-session"

    monkeypatch.setattr(
        douyin,
        "tempfile",
        type("Temp", (), {"mkdtemp": lambda **_kwargs: str(temp_dir)}),
    )
    monkeypatch.setattr(douyin, "_build_session", build_session)
    manager = JobManager()
    try:
        assert douyin.start_douyin_import(lambda _paths: {}, "cookie", manager)
        assert entered.wait(1)
        job = _wait_for_job(manager, "import.douyin")
        douyin.cancel_douyin_import()
        assert manager.wait(job.id, 1)
        assert douyin.get_douyin_progress()["status"] == "cancelled"
        assert not temp_dir.exists()
    finally:
        manager.shutdown(1)
        douyin._reset_state()


def test_douyin_cancel_then_restart_does_not_reuse_old_worker(monkeypatch):
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    calls = []

    def build_session(_cookie):
        index = len(calls)
        calls.append(index)
        entered[index].set()
        release[index].wait(1)
        return None

    monkeypatch.setattr(douyin, "_build_session", build_session)
    manager = JobManager()
    try:
        assert douyin.start_douyin_import(lambda _paths: {}, "cookie", manager)
        assert entered[0].wait(1)
        first = _wait_for_job(manager, "import.douyin")
        assert manager.cancel(first.id)
        release[0].set()
        assert manager.wait(first.id, 1)
        assert manager.get(first.id).status == "cancelled"

        monkeypatch.setattr(douyin, "_check_login", lambda _session: False)
        assert douyin.start_douyin_import(lambda _paths: {}, "cookie", manager)
        assert entered[1].wait(1)
        second = _wait_for_job(manager, "import.douyin")
        release[1].set()
        assert manager.wait(second.id, 1)
        assert second.id != first.id
        assert manager.get(second.id).status == "error"
        assert calls == [0, 1]
    finally:
        for event in release:
            event.set()
        manager.shutdown(1)
        douyin._reset_state()


def test_wechat_cancel_reclaims_worker_temp_dir(monkeypatch, tmp_path):
    entered = threading.Event()
    temp_dir = tmp_path / "wechat-worker"

    monkeypatch.setattr(
        wechat,
        "inspect_wechat_environment",
        lambda _root: {
            "status": "supported",
            "accounts": [
                {
                    "id": "wxid",
                    "path": "root",
                    "db_path": "db",
                    "status": "supported",
                }
            ],
            "account_directory_count": 1,
        },
    )
    monkeypatch.setattr(
        wechat,
        "_read_plaintext_metadata",
        lambda _path: [{"url": "url", "md5": "md5"}],
    )
    monkeypatch.setattr(wechat.tempfile, "mkdtemp", lambda **_kwargs: str(temp_dir))

    def download(_url, _key):
        temp_dir.mkdir()
        (temp_dir / "partial.png").write_bytes(b"partial")
        entered.set()
        wechat.cancel_wechat_import()
        return None

    monkeypatch.setattr(wechat, "_download_sticker", download)
    manager = JobManager()
    try:
        assert wechat.start_wechat_import(lambda _paths: {}, job_manager=manager)
        assert entered.wait(1)
        job = _wait_for_job(manager, "import.wechat")
        wechat.cancel_wechat_import()
        assert manager.wait(job.id, 1)
        assert wechat.get_wechat_progress()["status"] == "cancelled"
        assert not temp_dir.exists()
    finally:
        manager.shutdown(1)
        wechat._reset_state()


def test_closed_manager_rolls_back_telegram_admission_state():
    manager = JobManager()
    manager.shutdown(1)
    telegram._reset_state()
    telegram._TG_JOB_CANCEL = None
    telegram._TG_JOB_SNAPSHOT = None

    try:
        with pytest.raises(RuntimeError, match="job manager is shut down"):
            telegram.start_tg_import(lambda _paths: {}, "closed", job_manager=manager)
        state = telegram.get_tg_progress()
        assert state["status"] == "idle"
        assert manager.active("import.telegram") is None
        assert telegram._TG_JOB_CANCEL is None
        assert telegram._TG_JOB_SNAPSHOT is None
    finally:
        manager.shutdown(1)
        telegram._reset_state()


def test_closed_manager_rolls_back_douyin_admission_state():
    manager = JobManager()
    manager.shutdown(1)
    douyin._reset_state()
    douyin._DOUYIN_JOB_CANCEL = None
    douyin._DOUYIN_JOB_SNAPSHOT = None

    try:
        with pytest.raises(RuntimeError, match="job manager is shut down"):
            douyin.start_douyin_import(lambda _paths: {}, "closed", manager)
        state = douyin.get_douyin_progress()
        assert state["status"] == "idle"
        assert manager.active("import.douyin") is None
        assert douyin._DOUYIN_JOB_CANCEL is None
        assert douyin._DOUYIN_JOB_SNAPSHOT is None
    finally:
        manager.shutdown(1)
        douyin._reset_state()


def test_closed_manager_rolls_back_wechat_admission_state():
    manager = JobManager()
    manager.shutdown(1)
    wechat._reset_state()
    wechat._WECHAT_JOB_CANCEL = None
    wechat._WECHAT_JOB_SNAPSHOT = None

    try:
        with pytest.raises(RuntimeError, match="job manager is shut down"):
            wechat.start_wechat_import(lambda _paths: {}, job_manager=manager)
        state = wechat.get_wechat_progress()
        assert state["status"] == "idle"
        assert manager.active("import.wechat") is None
        assert wechat._WECHAT_JOB_CANCEL is None
        assert wechat._WECHAT_JOB_SNAPSHOT is None
    finally:
        manager.shutdown(1)
        wechat._reset_state()
