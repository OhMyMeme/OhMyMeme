import ctypes
import os
import time
from ctypes import wintypes

_TARGET_EXECUTABLES = {
    "qq": {"qq.exe", "qqnt.exe"},
    "wechat": {"wechat.exe", "weixin.exe"},
}


def _window_text(user32, hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _process_path(kernel32, pid):
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
    finally:
        kernel32.CloseHandle(handle)
    return ""


def capture_foreground_target(mode):
    # 记录用户主动呼出前的 QQ 或微信顶层窗口，不读取聊天内容
    if os.name != "nt" or mode not in _TARGET_EXECUTABLES:
        return {"ok": False, "status": "manual_paste_required"}
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd = user32.GetForegroundWindow()
    if not hwnd or not user32.IsWindow(hwnd):
        return {"ok": False, "status": "target_missing"}
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    path = _process_path(kernel32, pid.value)
    executable = os.path.basename(path).lower()
    if executable not in _TARGET_EXECUTABLES[mode]:
        return {"ok": False, "status": "target_mismatch"}
    return {
        "ok": True,
        "status": "target_bound",
        "hwnd": int(hwnd),
        "pid": int(pid.value),
        "title": _window_text(user32, hwnd),
        "executable": executable,
    }


def _send_ctrl_v(user32):
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

    key_input = 1
    key_up = 0x0002
    control = 0x11
    v_key = 0x56
    events = (INPUT * 4)(
        INPUT(key_input, INPUT_UNION(ki=KEYBDINPUT(control, 0, 0, 0, None))),
        INPUT(key_input, INPUT_UNION(ki=KEYBDINPUT(v_key, 0, 0, 0, None))),
        INPUT(key_input, INPUT_UNION(ki=KEYBDINPUT(v_key, 0, key_up, 0, None))),
        INPUT(key_input, INPUT_UNION(ki=KEYBDINPUT(control, 0, key_up, 0, None))),
    )
    return user32.SendInput(len(events), events, ctypes.sizeof(INPUT)) == len(events)


def paste_to_target(mode, target):
    # 仅向已绑定且仍为目标客户端的窗口发送 Ctrl+V，绝不发送消息
    if os.name != "nt" or mode not in _TARGET_EXECUTABLES or not target:
        return {"ok": False, "status": "manual_paste_required"}
    hwnd = int(target.get("hwnd", 0) or 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not hwnd or not user32.IsWindow(hwnd):
        return {"ok": False, "status": "target_closed"}
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    executable = os.path.basename(_process_path(kernel32, pid.value)).lower()
    if executable not in _TARGET_EXECUTABLES[mode]:
        return {"ok": False, "status": "target_mismatch"}
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.12)
    if user32.GetForegroundWindow() != hwnd:
        return {"ok": False, "status": "foreground_denied"}
    if not _send_ctrl_v(user32):
        return {"ok": False, "status": "paste_failed"}
    return {"ok": True, "status": "paste_attempted"}
