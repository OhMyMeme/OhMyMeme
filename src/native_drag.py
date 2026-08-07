"""Windows 原生文件拖拽（DoDragDrop + CF_HDROP）

WebView2 的 HTML5 拖拽拖出到外部应用不会生成 CF_HDROP（http 源限制），
QQ/微信只接受真实本地文件。本模块用 WinForms DoDragDrop 构造文件拖放，
让表情卡片能以原生文件形式拖到外部应用。

仅在 Windows + pythonnet 可用时生效，其余平台返回 False。
"""

import os
import platform
import threading

_lock = threading.Lock()


def _import_wf():
    """惰性导入 pythonnet 与 WinForms，失败返回 None"""
    try:
        import clr

        clr.AddReference("System.Windows.Forms")
        import System.Windows.Forms as WinForms

        return WinForms
    except Exception:
        return None


def start_native_drag(path):
    """在宿主窗口 UI 线程执行原生文件拖拽，返回是否成功启动

    :param path: 本地文件绝对路径
    """
    if platform.system() != "Windows":
        return False
    if not path or not os.path.isfile(path):
        return False
    try:
        import webview

        if not webview.windows:
            return False
        form = webview.windows[0].native
        if form is None:
            return False
    except Exception:
        return False

    WinForms = _import_wf()
    if WinForms is None:
        return False

    from System import Action, Array, String

    data = WinForms.DataObject(WinForms.DataFormats.FileDrop, Array[String]([path]))
    result = {}

    def _run():
        try:
            result["val"] = str(form.DoDragDrop(data, WinForms.DragDropEffects.Copy))
        except Exception as e:
            result["err"] = repr(e)

    try:
        with _lock:
            form.Invoke(Action(_run))
    except Exception:
        return False
    return "err" not in result
