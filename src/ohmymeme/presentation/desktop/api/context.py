"""Explicit platform callbacks for desktop bridge handlers."""


class BridgeContext:
    """Provides platform operations without importing desktop façades."""

    def __init__(
        self,
        webview,
        copy_mode_1,
        copy_mode_2,
        copy_mode_3,
        copy_image,
        strip_url,
        connectivity,
        qqnt_start,
        qqnt_progress,
        qqnt_cancel,
        log_lock,
        log_buffer,
    ):
        self.webview = webview
        self.copy_mode_1 = copy_mode_1
        self.copy_mode_2 = copy_mode_2
        self.copy_mode_3 = copy_mode_3
        self.copy_image = copy_image
        self.strip_url = strip_url
        self.connectivity = connectivity
        self.qqnt_start = qqnt_start
        self.qqnt_progress = qqnt_progress
        self.qqnt_cancel = qqnt_cancel
        self.log_lock = log_lock
        self.log_buffer = log_buffer
