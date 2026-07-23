#!/usr/bin/env python3
"""
OhMyMeme 打包脚本
依赖: pip install pyinstaller
用法:
    python scripts/build.py                  # 默认打包
    python scripts/build.py --onefile        # 单文件
    python scripts/build.py --onedir         # 目录模式
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
BUILD_DIR = PROJECT_ROOT / "dist"
APP_NAME = "OhMyMeme"


def clean():
    for d in [BUILD_DIR, PROJECT_ROOT / "build", PROJECT_ROOT / "*.spec"]:
        if isinstance(d, Path):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
            elif d.parent.glob(d.name):
                for f in d.parent.glob(d.name):
                    f.unlink()


def build_pyinstaller(onefile: bool = True):
    """使用 PyInstaller 打包"""
    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        print("错误: 未找到 pyinstaller，请执行 pip install pyinstaller")
        sys.exit(1)

    clean()

    # 平台特定选项
    platform_opts = []
    system = platform.system()

    if system == "Windows":
        platform_opts = [
            "--noconsole",          # 无控制台窗口
            "--uac-admin",          # 请求管理员权限（热键注册需要）
        ]
        # 可添加图标: --icon=src/resources/icon.ico
    elif system == "Darwin":
        platform_opts = [
            "--noconsole",
            "--osx-bundle-identifier", "com.ohmymeme.app",
        ]
    else:  # Linux
        platform_opts = ["--noconsole"]

    # 隐藏导入（确保 PyInstaller 能找到）
    hidden_imports = [
        "--hidden-import", "PIL",
        "--hidden-import", "pystray",
        "--hidden-import", "pyperclip",
        "--hidden-import", "cryptography",
        "--hidden-import", "keyboard",
        "--hidden-import", "bottle",
        "--hidden-import", "webview",
        "--hidden-import", "pythonnet",
        "--hidden-import", "clr_loader",
    ]
    # pywebview 需要额外数据
    data_opts = [
        "--add-data", f"{SRC_DIR}{os.pathsep}src",
        "--add-data", f"{SRC_DIR / 'webui'}{os.pathsep}src/webui",
    ]

    cmd = [
        pyinstaller,
        "--name", APP_NAME,
        "--distpath", str(BUILD_DIR),
    ] + data_opts + platform_opts + hidden_imports

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    cmd.append(str(SRC_DIR / "__main__.py"))

    print(f"运行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))

    # 重命名输出
    if onefile:
        ext = ".exe" if system == "Windows" else ""
        src = BUILD_DIR / f"{APP_NAME}{ext}"
        dst = BUILD_DIR / f"{APP_NAME}-v0.1.0-{system.lower()}{ext}"
        if src.exists():
            src.rename(dst)
            print(f"打包完成: {dst}")

    print("构建完成!")


def build_all():
    """构建所有平台的包"""
    build_pyinstaller(onefile=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OhMyMeme 打包脚本")
    parser.add_argument("--onefile", action="store_true", default=True,
                        help="单文件模式 (默认)")
    parser.add_argument("--onedir", action="store_true",
                        help="目录模式")
    args = parser.parse_args()

    onefile = not args.onedir
    build_pyinstaller(onefile=onefile)
