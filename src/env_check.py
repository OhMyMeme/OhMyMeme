"""首次运行环境检测 - WebView2/.NET 检测 + 非 webview 原生 UI（tkinter/MessageBox）"""

import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import tkinter
except ImportError:
    tkinter = None

try:
    import winreg
except ImportError:
    winreg = None

from .config import _get_config_dir

logger = logging.getLogger(__name__)

# pywebview 6.x winforms._is_chromium 判定的最低 WebView2 版本回退值
# （运行时优先从已安装 pywebview 源码解析该常量，随 pywebview 升级自动跟随）
_MIN_WEBVIEW2_FALLBACK = "86.0.622.0"
# 本项目实际所需最低 WebView2 版本：pywebview 6 在 CoreWebView2 初始化完成回调中
# 无条件执行 settings.IsSwipeNavigationEnabled = False（ICoreWebView2Settings6，
# SDK 1.0.992.28 引入），按 WebView2 forward-compat 规则（API 所在 SDK 的第三段
# build 号 ≤ Runtime 的第三段 build 号）需 Runtime >= 94.0.992.x；更旧 Runtime 上
# 该 setter 抛 NotImplementedException 中断初始化（白屏），故门槛取 94.0.992.0
# 而非 pywebview _is_chromium 的 86.0.622.0 后端可用底线。
_PROJECT_MIN_WEBVIEW2 = "94.0.992.0"
# .NET Framework 4.6.2（pywebview winforms._is_chromium 同阈值）
_MIN_DOTNET_RELEASE = 394802
# EdgeUpdate 各渠道客户端 GUID（与 pywebview winforms._is_chromium 一致）
_WV2_CLIENTS = (
    ("Stable", "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ("Beta", "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}"),
    ("Dev", "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}"),
    ("Canary", "{65C35B14-6C1D-4122-AC46-7148CC9D6497}"),
)
_MARKER_NAME = "env_check.json"
_OK_COLOR = "#16a34a"
_FAIL_COLOR = "#dc2626"


def marker_path() -> Path:
    """检测标记文件路径（%APPDATA%/OhMyMeme/env_check.json）"""
    return _get_config_dir() / _MARKER_NAME


def is_done(path=None) -> bool:
    """检测 UI 是否已被确定过（标记文件存在即不再自动显示）"""
    p = Path(path) if path else marker_path()
    return p.is_file()


def mark_done(checks, path=None) -> None:
    """确定按钮写入标记（附带本次检测结果快照便于排查）"""
    p = Path(path) if path else marker_path()
    payload = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": checks}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("写入环境检测标记失败: %s", e)


def version_tuple(v: str) -> tuple:
    """点分版本转 int 元组（非数字段按 0）"""
    parts = []
    for seg in str(v).split("."):
        parts.append(int(seg) if seg.isdigit() else 0)
    return tuple(parts)


def version_at_least(current: str, minimum: str) -> bool:
    """current >= minimum（按点分段逐段比较，短侧补 0）"""
    a, b = version_tuple(current), version_tuple(minimum)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a >= b


def parse_min_version(source_text: str):
    """从 pywebview winforms 源码解析 _is_new_version 阈值，未命中返回 None"""
    m = re.search(r"_is_new_version\(\s*'([\d.]+)'\s*,\s*build\s*\)", source_text)
    return m.group(1) if m else None


def min_webview2_version() -> str:
    """本项目所需最低 WebView2 版本 = max(pywebview 源码阈值, 项目特性门槛)"""
    found = _MIN_WEBVIEW2_FALLBACK
    try:
        import webview

        src = Path(webview.__file__).resolve().parent / "platforms" / "winforms.py"
        parsed = parse_min_version(src.read_text(encoding="utf-8"))
        if parsed:
            found = parsed
    except Exception as e:
        logger.debug("解析 pywebview 最低 WebView2 版本失败，使用回退值: %s", e)
    if version_at_least(_PROJECT_MIN_WEBVIEW2, found):
        return _PROJECT_MIN_WEBVIEW2
    return found


def _read_pv(guid: str) -> str:
    """读某渠道 EdgeUpdate 客户端 pv（HKCU/HKLM 与 pywebview 同路径策略，取最高版本）"""
    if winreg is None:
        return ""
    best = ""
    machine = platform.machine()
    for hive_name in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        if machine == "x86" or hive_name == "HKEY_CURRENT_USER":
            sub = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"
        else:
            sub = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"
        try:
            with winreg.OpenKey(getattr(winreg, hive_name), sub) as key:
                pv, _ = winreg.QueryValueEx(key, "pv")
            pv = str(pv)
        except OSError:
            continue
        if (
            pv
            and pv != "0.0.0.0"
            and (not best or version_tuple(pv) > version_tuple(best))
        ):
            best = pv
    return best


def _read_dotnet_release() -> int:
    """读 .NET Framework v4 Full 的 Release 号（未安装/读取失败返回 0）"""
    if winreg is None:
        return 0
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
        ) as key:
            release, _ = winreg.QueryValueEx(key, "Release")
        return int(release)
    except OSError:
        return 0


def detect_webview2(minimum=None) -> dict:
    """检测 WebView2 Runtime：返回 installed/version/channel/minimum/ok"""
    minimum = minimum or min_webview2_version()
    found = {}
    for channel, guid in _WV2_CLIENTS:
        pv = _read_pv(guid)
        if pv:
            found[channel] = pv
    version = found.get("Stable", "")
    channel = "Stable" if version else ""
    if not version and found:
        channel = max(found, key=lambda c: version_tuple(found[c]))
        version = found[channel]
    ok = any(version_at_least(pv, minimum) for pv in found.values())
    return {
        "installed": bool(found),
        "version": version,
        "channel": channel,
        "minimum": minimum,
        "ok": ok,
    }


def detect_checks(is_windows=None) -> list:
    """环境检测项列表（Windows：WebView2 + .NET；其他平台：占位通过项）"""
    win = os.name == "nt" if is_windows is None else is_windows
    if not win:
        return [
            {
                "name": "环境检测",
                "ok": True,
                "detail": "当前平台暂无检测项（仅 Windows 提供 WebView2 检测）",
            }
        ]
    minimum = min_webview2_version()
    wv = detect_webview2(minimum)
    dotnet = _read_dotnet_release()
    checks = []
    if wv["installed"]:
        detail = "已安装 " + wv["version"]
        if wv["channel"] != "Stable":
            detail += f'（{wv["channel"]} 渠道）'
        checks.append(
            {"name": "Microsoft Edge WebView2 Runtime", "ok": True, "detail": detail}
        )
    else:
        checks.append(
            {"name": "Microsoft Edge WebView2 Runtime", "ok": False, "detail": "未安装"}
        )
    if not wv["installed"]:
        checks.append(
            {
                "name": f"WebView2 版本 ≥ {minimum}",
                "ok": False,
                "detail": "未安装，无法比对版本",
            }
        )
    elif wv["ok"]:
        checks.append(
            {
                "name": f"WebView2 版本 ≥ {minimum}",
                "ok": True,
                "detail": f'{wv["version"]} 满足要求',
            }
        )
    else:
        checks.append(
            {
                "name": f"WebView2 版本 ≥ {minimum}",
                "ok": False,
                "detail": f'{wv["version"]} 低于 pywebview 支持的最低版本',
            }
        )
    if dotnet >= _MIN_DOTNET_RELEASE:
        checks.append(
            {
                "name": ".NET Framework ≥ 4.6.2",
                "ok": True,
                "detail": f"已安装（Release {dotnet}）",
            }
        )
    else:
        detail = (
            f"未满足（Release {dotnet}）" if dotnet else "未检测到 .NET Framework v4"
        )
        checks.append({"name": ".NET Framework ≥ 4.6.2", "ok": False, "detail": detail})
    return checks


def ui_command() -> tuple:
    """检测 UI 子进程命令（frozen 用内部旗标，源码用 -m src.env_check）+ cwd"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--env-check-ui"], None
    root = Path(__file__).resolve().parent.parent
    return [sys.executable, "-m", "src.env_check"], str(root)


def _popen_kwargs(cwd) -> dict:
    kwargs = {}
    if cwd:
        kwargs["cwd"] = cwd
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    kwargs["stdout"] = subprocess.DEVNULL
    kwargs["stderr"] = subprocess.DEVNULL
    return kwargs


def spawn_ui() -> bool:
    """独立子进程打开检测 UI（设置页入口，非阻塞）"""
    cmd, cwd = ui_command()
    subprocess.Popen(cmd, **_popen_kwargs(cwd))
    return True


def show_blocking() -> None:
    """启动前阻塞显示检测 UI（关闭后继续启动软件），失败不阻断启动"""
    try:
        cmd, cwd = ui_command()
        subprocess.run(cmd, **_popen_kwargs(cwd))
    except Exception as e:
        logger.warning("打开环境检测 UI 失败: %s", e)


def _run_tk(checks) -> None:
    """tkinter 窗口展示检测结果，确定按钮写标记（×/ESC 不写标记）"""
    if tkinter is None:
        raise RuntimeError("tkinter 不可用")
    failed = any(not c["ok"] for c in checks)
    root = tkinter.Tk()
    root.title("OhMyMeme 环境检测")
    root.resizable(False, False)

    body = tkinter.Frame(root, padx=18, pady=14)
    body.pack(fill="both", expand=True)
    tkinter.Label(
        body,
        text="首次运行环境检测",
        font=("Microsoft YaHei UI", 11, "bold"),
        anchor="w",
    ).pack(fill="x")
    tkinter.Label(
        body,
        text="不使用网页控件，检测本机 WebView2 运行环境",
        anchor="w",
        fg="#666666",
    ).pack(fill="x", pady=(2, 10))
    for c in checks:
        row = tkinter.Frame(body)
        row.pack(fill="x", pady=3)
        color = _OK_COLOR if c["ok"] else _FAIL_COLOR
        status = "通过" if c["ok"] else "未通过"
        tkinter.Label(
            row, text=status, width=5, fg=color, font=("Microsoft YaHei UI", 9, "bold")
        ).pack(side="left")
        content = tkinter.Frame(row)
        content.pack(side="left", fill="x", expand=True)
        tkinter.Label(
            content, text=c["name"], anchor="w", font=("Microsoft YaHei UI", 9, "bold")
        ).pack(fill="x")
        tkinter.Label(content, text=c["detail"], anchor="w", fg="#666666").pack(
            fill="x"
        )
    if failed:
        tkinter.Label(
            body,
            text="提示：后续版本将支持通过 winget 自动安装/升级 WebView2（当前仅检测）",
            anchor="w",
            fg="#666666",
            wraplength=430,
            justify="left",
        ).pack(fill="x", pady=(10, 0))

    def on_ok(_event=None):
        mark_done(checks)
        root.destroy()

    def on_close():
        root.destroy()

    footer = tkinter.Frame(body, pady=10)
    footer.pack(fill="x")
    tkinter.Button(footer, text="确 定", width=12, command=on_ok).pack(side="right")
    root.bind("<Return>", on_ok)
    root.bind("<Escape>", lambda _e: on_close())
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2)
    y = max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 3)
    root.geometry(f"+{x}+{y}")
    root.mainloop()


def _run_messagebox(checks) -> None:
    """tkinter 不可用时的 ctypes MessageBox 兜底（确定同样写标记）"""
    import ctypes

    lines = ["OhMyMeme 环境检测", ""]
    for c in checks:
        status = "通过" if c["ok"] else "未通过"
        lines.append(f"[{status}] {c['name']}：{c['detail']}")
    lines.append("")
    lines.append("点「确定」继续启动并记住本次检测；点「取消」本次不记住。")
    ret = ctypes.windll.user32.MessageBoxW(
        None, "\n".join(lines), "OhMyMeme 环境检测", 0x01
    )
    if ret == 1:
        mark_done(checks)


def run_ui() -> None:
    """检测 UI 入口（子进程调用）：确定写标记后关闭"""
    try:
        checks = detect_checks()
    except Exception as e:
        checks = [{"name": "环境检测", "ok": False, "detail": f"检测执行失败: {e}"}]
    try:
        _run_tk(checks)
    except Exception as e:
        logger.warning("tkinter 环境检测 UI 失败，回退 MessageBox: %s", e)
        try:
            _run_messagebox(checks)
        except Exception as e2:
            logger.warning("环境检测 UI 打开失败: %s", e2)


if __name__ == "__main__":
    run_ui()
