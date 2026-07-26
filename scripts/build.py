#!/usr/bin/env python3
"""
OhMyMeme 打包脚本 (PyInstaller)
依赖: pip install pyinstaller
Windows 额外依赖: InnoSetup 6/7 (ISCC.exe) — 制作安装包
用法:
    python scripts/build.py                  # 打包 + 制作安装包 (自动检测)
    python scripts/build.py --windows        # Windows 目标
    python scripts/build.py --linux          # Linux 目标
    python scripts/build.py --installer-only # 仅制作安装包(假设已打包)
    python scripts/build.py --build-only     # 仅打包，跳过安装包
"""

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
BUILD_DIR = PROJECT_ROOT / "dist"
APP_NAME = "OhMyMeme"

PYTHON = sys.executable
IS_WINDOWS = platform.system() == "Windows"


def get_version():
    init_py = SRC_DIR / "__init__.py"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init_py.read_text(encoding="utf-8"))
    return m.group(1) if m else "0.1.0"


def find_iscc():
    paths = [
        os.environ.get("ISCC_DIR", ""),
        r"C:\Program Files\Inno Setup 7\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe",
    ]
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def check_pyinstaller():
    try:
        import PyInstaller
    except ImportError:
        print("错误: 未找到 PyInstaller，请执行 pip install pyinstaller")
        sys.exit(1)


def clean():
    out_dir = BUILD_DIR / APP_NAME
    if out_dir.is_dir():
        shutil.rmtree(out_dir, ignore_errors=True)
    build_dir = PROJECT_ROOT / "build" / APP_NAME
    if build_dir.is_dir():
        shutil.rmtree(build_dir, ignore_errors=True)
    spec_file = PROJECT_ROOT / ("%s.spec" % APP_NAME)
    if spec_file.exists():
        spec_file.unlink()


def build_pyinstaller(target=None):
    check_pyinstaller()
    clean()

    version = get_version()
    sep = ";" if IS_WINDOWS else ":"

    cmd = [
        PYTHON, "-m", "PyInstaller",
        "--onedir",
        "--name", APP_NAME,
        "--distpath", str(BUILD_DIR),
        "--specpath", str(PROJECT_ROOT / "build"),
        "--noconfirm",
        "--clean",
        "--add-data", str(SRC_DIR / "webui") + sep + "src/webui",
        "--hidden-import", "src.main",
        str(PROJECT_ROOT / "scripts" / "launcher.py"),
    ]

    exclude = [
        "numpy", "PyQt5", "PyQt5.QtCore", "PyQt5.QtGui",
        "PyQt5.QtWidgets", "PyQt5.QtNetwork", "PyQt5.QtSvg",
        "psutil", "setuptools", "pkg_resources", "pyreadline3",
        "yaml", "tornado", "jaraco", "jaraco.text", "jaraco.functools",
    ]
    for m in exclude:
        cmd += ["--exclude-module", m]

    if target == "Windows" or (target is None and IS_WINDOWS):
        icon = str(SRC_DIR / "resources" / "icon.ico")
        cmd += ["--windowed", "--icon=" + icon]
    elif target == "Linux":
        icon_png = SRC_DIR / "resources" / "icon.png"
        if icon_png.exists():
            cmd += ["--icon=" + str(icon_png)]

    print("运行: %s" % " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("PyInstaller 打包失败 (code=%d)" % result.returncode)
        sys.exit(result.returncode)

    print("打包完成: %s" % (BUILD_DIR / APP_NAME))
    return version


def build_installer(version, target=None):
    if target is None:
        target = platform.system()
    if target != "Windows":
        print("跳过安装包制作（非 Windows 平台）")
        return

    iscc = find_iscc()
    if not iscc:
        print("警告: 未找到 ISCC.exe（InnoSetup），跳过安装包制作")
        return

    # 查找 PyInstaller 输出目录
    dist_dir = BUILD_DIR / APP_NAME
    if not dist_dir.is_dir():
        print("错误: 未找到输出目录: %s" % dist_dir)
        print("请先执行 PyInstaller 构建")
        return

    iss_template = PROJECT_ROOT / "scripts" / "installer" / "windows.iss"
    if not iss_template.exists():
        print("错误: InnoSetup 脚本不存在: %s" % iss_template)
        return

    iss_content = iss_template.read_text(encoding="utf-8")
    iss_content = iss_content.replace(
        '#define MyAppVersion "0.1.0"',
        '#define MyAppVersion "%s"' % version,
    )
    source_dir_abs = str(dist_dir.resolve())
    iss_content = iss_content.replace(
        '#define SourceDir "..\\..\\dist\\src.dist"',
        '#define SourceDir "%s"' % source_dir_abs,
    )
    iss_content = iss_content.replace(
        'OutputDir=..\\..\\dist',
        'OutputDir=%s' % str(BUILD_DIR.resolve()),
    )

    iss_temp = BUILD_DIR / "ohmy meme.iss"
    iss_temp.write_text(iss_content, encoding="utf-8")

    print("制作安装包...")
    result = subprocess.run(
        [iscc, str(iss_temp)],
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    if iss_temp.exists():
        iss_temp.unlink()

    output_name = "%s-%s-setup.exe" % (APP_NAME, version)
    installer = BUILD_DIR / output_name
    if installer.exists():
        print("安装包制作完成: %s" % installer)
    else:
        print("安装包制作完成，未找到预期文件: %s" % installer)


def build_linux_packages(version):
    """使用 build.sh 构建 Linux 包 (.deb / AppImage)"""
    build_sh = PROJECT_ROOT / "scripts" / "installer" / "linux" / "build.sh"
    if not build_sh.exists():
        print("警告: 未找到 %s，跳过 Linux 打包" % build_sh)
        return

    # build.sh 内部会调用 PyInstaller，传 no_build 避免重复构建
    env = os.environ.copy()
    env["SKIP_PYINSTALLER"] = "1"
    print("制作 Linux 包...")
    result = subprocess.run(
        ["bash", str(build_sh), "all"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    if result.returncode != 0:
        print("Linux 打包失败 (code=%d)" % result.returncode)
        sys.exit(result.returncode)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OhMyMeme 打包脚本 (PyInstaller)")
    parser.add_argument("--installer-only", action="store_true",
                        help="仅制作安装包（假设 PyInstaller 已构建）")
    parser.add_argument("--build-only", action="store_true",
                        help="仅打包，跳过安装包制作")
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--windows", action="store_true", dest="target_windows",
                              help="构建 Windows 目标")
    target_group.add_argument("--linux", action="store_true", dest="target_linux",
                              help="构建 Linux 目标")
    parser.set_defaults(target_windows=False, target_linux=False)
    args = parser.parse_args()

    if args.target_windows:
        target = "Windows"
    elif args.target_linux:
        target = "Linux"
    else:
        target = platform.system()

    if args.installer_only:
        if target == "Windows":
            build_installer(get_version(), target=target)
        elif target == "Linux":
            build_linux_packages(get_version())
        else:
            print("错误: --installer-only 不支持当前目标 %s" % target)
            sys.exit(1)
    else:
        version = build_pyinstaller(target=target)
        if args.build_only:
            pass
        elif target == "Windows":
            build_installer(version, target=target)
        elif target == "Linux":
            build_linux_packages(version)
