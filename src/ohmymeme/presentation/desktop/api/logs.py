"""Settings-window log export operation."""

import logging


def export_logs(webui, context, log_lock, log_buffer):
    window = webui._settings_window or (
        context.webview().windows[0] if context.webview().windows else None
    )
    if not window:
        return {"ok": False, "error": "no window"}
    try:
        result = window.create_file_dialog(
            context.webview().FileDialog.SAVE,
            allow_multiple=False,
            save_filename="OhMyMeme-logs.txt",
            file_types=("文本文件 (*.txt)",),
        )
    except Exception as error:
        logging.getLogger(__name__).warning("export_logs dialog error: %r", error)
        return {"ok": False, "error": "dialog failed"}
    if not result:
        return {"ok": False, "error": "cancelled"}
    destination = result[0] if isinstance(result, (tuple, list)) else result
    if not destination.lower().endswith(".txt"):
        destination += ".txt"
    with log_lock:
        lines = list(log_buffer)
    if not lines:
        return {"ok": False, "error": "no logs"}
    try:
        with open(destination, "w", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
    except OSError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "path": destination, "count": len(lines)}
