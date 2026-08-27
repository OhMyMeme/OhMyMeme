import threading
import time

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
