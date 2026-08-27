import threading

import pytest

from ohmymeme.app.job_manager import IMPORT_RESOURCES, IMPORT_TASK_TYPES, JobManager


def test_start_is_single_flight_and_retains_terminal_snapshot():
    manager = JobManager()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def job(context):
        calls.append(context.job_id)
        started.set()
        release.wait(1)
        context.complete()

    try:
        first = manager.start("sync", job, resources=("connection-1",))
        assert started.wait(1)
        duplicate = manager.start("sync", job, resources=("connection-2",))

        assert duplicate.id == first.id
        assert duplicate.status == "running"
        assert calls == [first.id]

        release.set()
        assert manager.wait(first.id, 1)
        terminal = manager.get(first.id)
        assert terminal is not None
        assert terminal.status == "completed"
        assert terminal.resources == ("connection-1",)
    finally:
        release.set()
        manager.shutdown(1)


def test_shutdown_is_bounded_and_does_not_force_kill_worker():
    manager = JobManager()
    started = threading.Event()
    release = threading.Event()

    def job(context):
        started.set()
        release.wait(1)

    manager.start("blocked", job)
    assert started.wait(1)

    try:
        assert manager.shutdown(0.01) is False
        assert manager.active("blocked") is not None
    finally:
        release.set()
        assert manager.shutdown(1) is True


def test_progress_cancel_error_and_terminal_snapshots():
    manager = JobManager()
    progress_seen = threading.Event()

    def cancellable(context):
        context.progress(0.5)
        progress_seen.set()
        context.cancellation_event.wait(1)

    cancelled = manager.start("cancel", cancellable)
    assert progress_seen.wait(1)
    assert manager.cancel(cancelled.id) is True
    assert manager.wait(cancelled.id, 1)
    assert manager.get(cancelled.id).status == "cancelled"
    assert manager.get(cancelled.id).progress == 0.5

    def failing(_context):
        raise RuntimeError("controlled failure")

    errored = manager.start("error", failing)
    assert manager.wait(errored.id, 1)
    error_snapshot = manager.get(errored.id)
    assert error_snapshot.status == "error"
    assert error_snapshot.error == "controlled failure"
    manager.shutdown(1)


def test_importer_job_types_are_single_flight_and_cancelable():
    manager = JobManager()
    started = threading.Event()
    release = threading.Event()

    def importer(context):
        started.set()
        release.wait(1)

    first = manager.start("import.telegram", importer)
    assert started.wait(1)
    duplicate = manager.start("import.telegram", importer)

    assert duplicate.id == first.id
    assert manager.cancel(first.id) is True
    release.set()
    assert manager.wait(first.id, 1)
    assert manager.get(first.id).status == "cancelled"
    manager.shutdown(1)


def test_import_task_types_have_stable_resources_and_snapshot_fields():
    manager = JobManager()
    started = threading.Event()
    release = threading.Event()

    def importer(context):
        context.snapshot(phase="scanning", progress=0.25, message="working")
        started.set()
        release.wait(1)

    try:
        for task_type in IMPORT_TASK_TYPES:
            record, created = manager.try_start(
                task_type, importer, resources=IMPORT_RESOURCES[task_type]
            )
            assert created
            assert record.resources == IMPORT_RESOURCES[task_type]
            assert started.wait(1)
            snapshot = manager.get(record.id)
            assert snapshot.phase == "scanning"
            assert snapshot.progress == 0.25
            assert snapshot.message == "working"
            release.set()
            assert manager.wait(record.id, 1)
            started.clear()
            release.clear()
    finally:
        release.set()
        manager.shutdown(1)


def test_cancel_request_wins_over_late_context_complete():
    manager = JobManager()
    entered = threading.Event()
    release = threading.Event()

    def job(context):
        entered.set()
        release.wait(1)
        context.complete()

    try:
        record = manager.start("cancel-wins", job)
        assert entered.wait(1)
        assert manager.cancel(record.id)
        release.set()
        assert manager.wait(record.id, 1)
        snapshot = manager.get(record.id)
        assert snapshot.status == "cancelled"
        assert manager.active("cancel-wins") is None
    finally:
        release.set()
        manager.shutdown(1)


@pytest.mark.parametrize("base_error", (KeyboardInterrupt, SystemExit))
def test_base_exception_worker_is_finalized_and_releases_active_slot(base_error):
    manager = JobManager()

    def interrupted(_context):
        raise base_error("controlled interrupt")

    try:
        record = manager.start("interrupt", interrupted)
        assert manager.wait(record.id, 1)
        snapshot = manager.get(record.id)
        assert snapshot.status == "error"
        assert snapshot.error == f"{base_error.__name__}: controlled interrupt"
        assert manager.active("interrupt") is None
    finally:
        manager.shutdown(1)


def test_arbitrary_base_exception_worker_is_finalized_and_releases_active_slot():
    class ControlledBaseException(BaseException):
        pass

    manager = JobManager()

    def interrupted(_context):
        raise ControlledBaseException("controlled base exception")

    try:
        record = manager.start("custom-interrupt", interrupted)
        assert manager.wait(record.id, 1)
        snapshot = manager.get(record.id)
        assert snapshot.status == "error"
        assert snapshot.error == ("ControlledBaseException: controlled base exception")
        assert manager.active("custom-interrupt") is None
    finally:
        manager.shutdown(1)


def test_try_start_rolls_back_when_admission_callback_fails():
    manager = JobManager()

    def fail_admission(_record, _context):
        raise RuntimeError("admit boom")

    try:
        with pytest.raises(RuntimeError, match="admit boom"):
            manager.try_start(
                "admission-failure", lambda _context: None, on_admit=fail_admission
            )
        record = manager.get(next(iter(manager._records)))
        assert record.status == "error"
        assert record.error == "RuntimeError: admit boom"
        assert manager.wait(record.id, 1)
        assert manager.active("admission-failure") is None
    finally:
        manager.shutdown(1)


def test_try_start_rolls_back_when_thread_start_fails(monkeypatch):
    manager = JobManager()

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start boom")

        def join(self, _timeout=None):
            return None

        def is_alive(self):
            return False

    monkeypatch.setattr("ohmymeme.app.job_manager.Thread", FailingThread)
    try:
        with pytest.raises(RuntimeError, match="thread start boom"):
            manager.try_start("thread-failure", lambda _context: None)
        record = manager.get(next(iter(manager._records)))
        assert record.status == "error"
        assert record.error == "RuntimeError: thread start boom"
        assert manager.wait(record.id, 1)
        assert manager.active("thread-failure") is None
    finally:
        manager.shutdown(1)


@pytest.mark.parametrize("failure_stage", ("admit", "thread"))
def test_try_start_finalizes_arbitrary_base_exception(failure_stage, monkeypatch):
    class ControlledBaseException(BaseException):
        pass

    manager = JobManager()

    def fail_admission(_record, _context):
        raise ControlledBaseException("admission base failure")

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise ControlledBaseException("thread base failure")

        def join(self, _timeout=None):
            return None

        def is_alive(self):
            return False

    if failure_stage == "thread":
        monkeypatch.setattr("ohmymeme.app.job_manager.Thread", FailingThread)
    callback = fail_admission if failure_stage == "admit" else None
    failure_message = (
        "ControlledBaseException: admission base failure"
        if failure_stage == "admit"
        else "ControlledBaseException: thread base failure"
    )
    try:
        with pytest.raises(ControlledBaseException):
            manager.try_start(
                "base-admission", lambda _context: None, on_admit=callback
            )
        record = manager.get(next(iter(manager._records)))
        assert record.status == "error"
        assert record.error == failure_message
        assert manager.wait(record.id, 1)
        assert manager.active("base-admission") is None
    finally:
        manager.shutdown(1)
