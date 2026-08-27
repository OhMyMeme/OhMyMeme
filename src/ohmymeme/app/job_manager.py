"""进程内后台任务生命周期管理。"""

import time
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from uuid import uuid4

IMPORT_TASK_TYPES = (
    "import.telegram",
    "import.douyin",
    "import.wechat",
    "import.adb_qq",
    "import.qqnt",
)
IMPORT_RESOURCES = {
    "import.telegram": ("telegram",),
    "import.douyin": ("douyin",),
    "import.wechat": ("wechat",),
    "import.adb_qq": ("adb",),
    "import.qqnt": ("qqnt",),
}


@dataclass(frozen=True, slots=True)
class JobRecord:
    """对外可观察的任务快照。"""

    type: str
    id: str
    status: str
    progress: float
    error: str | None
    cancellation_event: Event = field(repr=False, compare=False)
    resources: tuple[str, ...]
    phase: str = ""
    message: str = ""
    error_code: str = ""


class JobContext:
    """后台任务更新自身状态的受控上下文。"""

    def __init__(self, manager, record_id, cancellation_event):
        self._manager = manager
        self.job_id = record_id
        self.cancellation_event = cancellation_event

    def progress(self, value):
        """更新任务进度。"""
        self._manager._update(self.job_id, progress=value)

    def complete(self):
        """将任务标记为成功完成。"""
        self._manager._finish(self.job_id, "completed")

    def snapshot(self, phase="", progress=None, message="", error_code="", error=None):
        """更新任务的外部阶段快照。"""
        self._manager._update(
            self.job_id,
            progress=progress,
            phase=phase,
            message=message,
            error_code=error_code,
            error=error,
        )


class JobManager:
    """拥有进程内任务线程与其终态快照。"""

    def __init__(self):
        self._lock = Lock()
        self._records = {}
        self._threads = {}
        self._active = {}
        self._closed = False

    def start(self, task_type, target, resources=()):
        """启动任务；同类型活动任务只返回其当前快照。"""
        with self._lock:
            active_id = self._active.get(task_type)
            if active_id is not None:
                return self._snapshot_locked(active_id)
            if self._closed:
                raise RuntimeError("job manager is shut down")
            record_id = uuid4().hex
            cancellation_event = Event()
            record = JobRecord(
                task_type,
                record_id,
                "running",
                0.0,
                None,
                cancellation_event,
                tuple(resources),
            )
            self._records[record_id] = record
            self._active[task_type] = record_id
            thread = Thread(
                target=self._run,
                args=(record, target),
                name=f"ohmymeme-job-{task_type}",
                daemon=True,
            )
            self._threads[record_id] = thread
            thread.start()
            return record

    def try_start(self, task_type, target, resources=()):
        """原子启动任务，返回 (快照, 是否由本次调用创建)。"""
        with self._lock:
            active_id = self._active.get(task_type)
            if active_id is not None:
                return self._snapshot_locked(active_id), False
            if self._closed:
                raise RuntimeError("job manager is shut down")
            record_id = uuid4().hex
            cancellation_event = Event()
            record = JobRecord(
                task_type,
                record_id,
                "running",
                0.0,
                None,
                cancellation_event,
                tuple(resources),
            )
            self._records[record_id] = record
            self._active[task_type] = record_id
            thread = Thread(
                target=self._run,
                args=(record, target),
                name=f"ohmymeme-job-{task_type}",
                daemon=True,
            )
            self._threads[record_id] = thread
            thread.start()
            return record, True

    def get(self, job_id):
        """返回任务最新快照，终态快照持续保留。"""
        with self._lock:
            return self._snapshot_locked(job_id) if job_id in self._records else None

    def active(self, task_type):
        """返回指定类型的活动任务快照。"""
        with self._lock:
            job_id = self._active.get(task_type)
            return self._snapshot_locked(job_id) if job_id else None

    def cancel(self, job_id):
        """发出协作取消信号。"""
        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.status != "running":
                return False
            record.cancellation_event.set()
            return True

    def wait(self, job_id, timeout=None):
        """在给定预算内等待任务线程退出。"""
        with self._lock:
            thread = self._threads.get(job_id)
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def shutdown(self, timeout=2.0):
        """请求所有任务取消并在预算内等待，不强杀线程。"""
        with self._lock:
            self._closed = True
            threads = tuple(self._threads.values())
            for job_id in self._active.values():
                self._records[job_id].cancellation_event.set()
        deadline = time.monotonic() + timeout
        for thread in threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        return all(not thread.is_alive() for thread in threads)

    def _run(self, record, target):
        context = JobContext(self, record.id, record.cancellation_event)
        try:
            target(context)
            with self._lock:
                current = self._records[record.id]
                if current.status == "running":
                    status = (
                        "cancelled"
                        if context.cancellation_event.is_set()
                        else "completed"
                    )
                    self._finish_locked(record.id, status)
        except Exception as error:  # noqa: BLE001
            self._finish(record.id, "error", str(error))
        except BaseException as error:  # noqa: BLE001, BROAD_EXCEPT_OK
            status = "cancelled" if context.cancellation_event.is_set() else "error"
            message = f"{type(error).__name__}: {error}"
            self._finish(record.id, status, message)

    def _update(
        self, job_id, progress=None, phase="", message="", error_code="", error=None
    ):
        with self._lock:
            record = self._records[job_id]
            if record.status == "running":
                self._records[job_id] = JobRecord(
                    record.type,
                    record.id,
                    record.status,
                    record.progress if progress is None else progress,
                    record.error if error is None else error,
                    record.cancellation_event,
                    record.resources,
                    phase or record.phase,
                    message or record.message,
                    error_code or record.error_code,
                )

    def _finish(self, job_id, status, error=None):
        with self._lock:
            self._finish_locked(job_id, status, error)

    def _finish_locked(self, job_id, status, error=None):
        record = self._records[job_id]
        if record.status != "running":
            return
        if status == "completed" and record.cancellation_event.is_set():
            status = "cancelled"
        self._records[job_id] = JobRecord(
            record.type,
            record.id,
            status,
            record.progress,
            error,
            record.cancellation_event,
            record.resources,
            record.phase,
            record.message,
            record.error_code,
        )
        self._active.pop(record.type, None)

    def _snapshot_locked(self, job_id):
        record = self._records[job_id]
        return JobRecord(
            record.type,
            record.id,
            record.status,
            record.progress,
            record.error,
            record.cancellation_event,
            record.resources,
            record.phase,
            record.message,
            record.error_code,
        )
