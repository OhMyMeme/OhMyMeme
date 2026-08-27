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
