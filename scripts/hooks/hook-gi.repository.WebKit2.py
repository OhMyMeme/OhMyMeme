# -*- coding: utf-8 -*-
# OhMyMeme 自定义 PyInstaller hook
# 收集 WebKit2 typelib / 共享库 / GIR（pywebview GTK 后端必需，PyInstaller 内置无此 hook）
# 无 gi 或 typelib 时静默跳过，不阻断构建。

from PyInstaller.utils.hooks.gi import GiModuleInfo


def hook(hook_api):
    for version in ("4.1", "4.0"):
        module_info = GiModuleInfo("WebKit2", version, hook_api=hook_api)
        if not module_info.available:
            continue
        binaries, datas, hiddenimports = module_info.collect_typelib_data()
        hook_api.add_datas(datas)
        hook_api.add_binaries(binaries)
        hook_api.add_imports(*hiddenimports)
        return
