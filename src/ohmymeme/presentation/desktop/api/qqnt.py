"""QQNT extraction bridge state and worker lifecycle."""

import logging
import threading
from pathlib import Path

from ohmymeme.integrations.imports import qqnt

logger = logging.getLogger(__name__)

_STATE = {
    "status": "idle",
    "progress": 0,
    "message": "",
    "error": "",
    "log": [],
    "result": None,
}
_LOCK = threading.Lock()
_CANCEL = False
_JOB_MANAGER = None
_JOB_ID = None
_JOB_SNAPSHOT = None
_LEGACY_STATE_HOOK = None


def _notify_legacy_state():
    if _LEGACY_STATE_HOOK is not None:
        _LEGACY_STATE_HOOK()


def _bind_job(manager, record, context):
    global _CANCEL, _JOB_MANAGER, _JOB_ID, _JOB_SNAPSHOT
    with _LOCK:
        _CANCEL = False
        _STATE.update(
            status="running",
            progress=0,
            message="准备中",
            error="",
            log=[],
            result=None,
        )
        _JOB_MANAGER = manager
        _JOB_ID = record.id
        _JOB_SNAPSHOT = context.snapshot
    _notify_legacy_state()


def _set_state(**values):
    global _JOB_SNAPSHOT
    with _LOCK:
        _STATE.update(values)
        snapshot = _JOB_SNAPSHOT
        state = dict(_STATE)
    if snapshot is not None:
        snapshot(
            phase=state["status"],
            progress=state["progress"] / 100,
            message=state["message"],
            error_code="error" if state["status"] == "error" else "",
            error=state["error"],
        )


def _append_log(message):
    with _LOCK:
        _STATE["log"] = (_STATE["log"] + [message])[-100:]


def progress():
    with _LOCK:
        return dict(_STATE)


def cancel():
    global _CANCEL
    _CANCEL = True
    if _JOB_MANAGER is not None and _JOB_ID is not None:
        _JOB_MANAGER.cancel(_JOB_ID)


def _run_legacy_worker(target_worker, args, import_callback):
    try:
        target_worker(*args, import_callback=import_callback)
    finally:
        with _LOCK:
            active = _STATE["status"] == "running"
            if active:
                _STATE.update(status="idle", message="")
        _notify_legacy_state()


def start(
    qq_number,
    output_dir,
    image_only=False,
    overwrite=False,
    ini_path=None,
    userdata_save_path=None,
    job_manager=None,
    import_callback=None,
    worker=None,
    legacy_state_hook=None,
):
    global _CANCEL, _JOB_MANAGER, _JOB_ID, _LEGACY_STATE_HOOK
    _LEGACY_STATE_HOOK = legacy_state_hook
    if job_manager is not None and job_manager.active("import.qqnt") is not None:
        return False
    with _LOCK:
        if job_manager is None and _STATE["status"] == "running":
            return False
        if job_manager is None:
            _CANCEL = False
            _STATE.update(
                status="running",
                progress=0,
                message="准备中",
                error="",
                log=[],
                result=None,
            )
    args = (
        qq_number,
        output_dir,
        image_only,
        overwrite,
        ini_path,
        userdata_save_path,
    )
    target_worker = worker or _worker
    if job_manager is None:
        threading.Thread(
            target=_run_legacy_worker,
            args=(target_worker, args, import_callback),
            daemon=True,
        ).start()
    else:

        def target(context):
            global _JOB_MANAGER, _JOB_ID, _JOB_SNAPSHOT
            try:
                target_worker(
                    *args,
                    cancellation_event=context.cancellation_event,
                    import_callback=import_callback,
                )
                if _STATE["status"] == "error":
                    raise RuntimeError(_STATE["error"])
            finally:
                with _LOCK:
                    active = job_manager.active("import.qqnt")
                    if _JOB_ID == context.job_id and (
                        active is None or active.id == context.job_id
                    ):
                        _JOB_MANAGER = None
                        _JOB_ID = None
                        _JOB_SNAPSHOT = None
                    if _STATE["status"] == "running":
                        _STATE.update(status="idle", message="")
                _notify_legacy_state()

        try:
            _, created = job_manager.try_start(
                "import.qqnt",
                target,
                resources=("qqnt",),
                on_admit=lambda record, context: _bind_job(
                    job_manager, record, context
                ),
            )
        except BaseException:
            with _LOCK:
                _JOB_MANAGER = None
                _JOB_ID = None
                _JOB_SNAPSHOT = None
                _STATE.update(
                    status="idle",
                    progress=0,
                    message="",
                    error="",
                    log=[],
                    result=None,
                )
            _notify_legacy_state()
            raise
        if not created:
            return False
    return True


def _worker(
    qq_number,
    output_dir,
    image_only,
    overwrite,
    ini_path,
    userdata_save_path,
    cancellation_event=None,
    import_callback=None,
):
    def on_progress(done, total, _src, _dst):
        pct = int(done * 100 / total) if total else 0
        _set_state(progress=pct, message="复制中 %d/%d" % (done, total))

    def on_error(src, message):
        _append_log("失败: %s (%s)" % (src, message))

    def on_log(message):
        _append_log(message)

    try:
        result = qqnt.extract_qq_emojis(
            qq_number,
            output_dir,
            userdata_save_path=userdata_save_path,
            ini_path=ini_path or qqnt.DEFAULT_INI_PATH,
            image_only=image_only,
            overwrite=overwrite,
            should_stop=lambda: _CANCEL
            or (cancellation_event is not None and cancellation_event.is_set()),
            on_progress=on_progress,
            on_error=on_error,
            on_log=on_log,
        )
        if import_callback and not (
            _CANCEL or (cancellation_event is not None and cancellation_event.is_set())
        ):
            output = Path(output_dir)
            paths = [
                str(path)
                for path in output.rglob("*")
                if path.is_file()
                and path.suffix.lower()
                in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
            ]
            if paths:
                result = import_callback(paths, cancellation_event)
                if _CANCEL or (
                    cancellation_event is not None and cancellation_event.is_set()
                ):
                    imported_ids = getattr(result, "imported_ids", ())
                    if isinstance(result, dict):
                        imported_ids = result.get("ids", [])
                    if imported_ids:
                        owner = getattr(import_callback, "__self__", None)
                        if owner is not None and hasattr(owner, "delete_memes"):
                            owner.delete_memes(imported_ids)
        if _CANCEL or (cancellation_event is not None and cancellation_event.is_set()):
            _set_state(status="cancelled", message="已取消", result=result)
        else:
            _set_state(status="done", progress=100, message="提取完成", result=result)
    except Exception as error:
        logger.error("qqnt extract error: %s", error)
        _set_state(status="error", message="提取失败", error=str(error))
    except BaseException as error:
        logger.error("qqnt extract worker terminated: %s", error)
        cancelled = _CANCEL or (
            cancellation_event is not None and cancellation_event.is_set()
        )
        if cancelled:
            _set_state(status="cancelled", message="已取消")
        else:
            _set_state(
                status="error",
                message="提取失败",
                error=f"{type(error).__name__}: {error}",
            )
        raise


worker = _worker


def set_state(**values):
    _set_state(**values)
