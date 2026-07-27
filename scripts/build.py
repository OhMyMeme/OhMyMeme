#!/usr/bin/env python3
"""
OhMyMeme build script (PyInstaller)
Deps: pip install pyinstaller
Windows extra: InnoSetup 6/7 (ISCC.exe) — to create installer

Usage:
    python scripts/build.py                  # build + installer (auto-detect)
    python scripts/build.py --windows        # Windows target
    python scripts/build.py --linux          # Linux target
    python scripts/build.py --installer-only # installer only (assumes already built)
    python scripts/build.py --build-only     # build only, skip installer
    python scripts/build.py --lang en        # force English output
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

# --- i18n ---
_MSGS = {
    "pyinstaller_not_found": {
        "zh": "错误: 未找到 PyInstaller，请执行 pip install pyinstaller",
        "en": "ERROR: PyInstaller not found, run: pip install pyinstaller",
    },
    "running": {"zh": "运行:", "en": "Running:"},
    "build_failed": {"zh": "PyInstaller 打包失败 (code=%d)", "en": "PyInstaller build failed (code=%d)"},
    "build_done": {"zh": "打包完成:", "en": "Build done:"},
    "skip_installer": {"zh": "跳过安装包制作（非 Windows 平台）", "en": "Skipping installer (non-Windows target)"},
    "iscc_not_found": {"zh": "警告: 未找到 ISCC.exe（InnoSetup），跳过安装包制作", "en": "WARNING: ISCC.exe (InnoSetup) not found, skipping installer"},
    "outdir_not_found": {"zh": "错误: 未找到输出目录:", "en": "ERROR: output directory not found:"},
    "run_build_first": {"zh": "请先执行 PyInstaller 构建", "en": "Run PyInstaller build first"},
    "iss_not_found": {"zh": "错误: InnoSetup 脚本不存在:", "en": "ERROR: InnoSetup script not found:"},
    "building_installer": {"zh": "制作安装包...", "en": "Building installer..."},
    "installer_done": {"zh": "安装包制作完成:", "en": "Installer created:"},
    "installer_not_found": {"zh": "安装包制作完成，未找到预期文件:", "en": "Installer created but expected file not found:"},
    "linux_sh_not_found": {"zh": "警告: 未找到 %s，跳过 Linux 打包", "en": "WARNING: %s not found, skipping Linux packaging"},
    "building_linux": {"zh": "制作 Linux 包...", "en": "Building Linux packages..."},
    "linux_failed": {"zh": "Linux 打包失败 (code=%d)", "en": "Linux packaging failed (code=%d)"},
    "installer_only_unsupported": {
        "zh": "错误: --installer-only 不支持当前目标 %s",
        "en": "ERROR: --installer-only not supported for target %s",
    },
}

_lang = "zh"


def _set_lang(lang):
    global _lang
    if lang in ("zh", "en"):
        _lang = lang


def L(key, *args):
    msg = _MSGS.get(key, {}).get(_lang, str(key))
    if args:
        return msg % args
    return msg


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
        print(L("pyinstaller_not_found"))
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
        "--add-data", str(SRC_DIR / "adb-help.txt") + sep + "src/adb-help.txt",
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

    print(L("running"), " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(L("build_failed", result.returncode))
        sys.exit(result.returncode)

    print(L("build_done"), BUILD_DIR / APP_NAME)
    return version


_LANG_URL = "https://raw.githubusercontent.com/jrsoftware/issrc/refs/heads/main/Files/Languages/ChineseSimplified.isl"


def _ensure_lang_file(iscc_exe):
    """Download ChineseSimplified.isl if missing (common on CI runners)."""
    iscc_dir = Path(iscc_exe).resolve().parent
    lang_dir = iscc_dir / "Languages"
    lang_file = lang_dir / "ChineseSimplified.isl"
    if lang_file.exists():
        return
    lang_dir.mkdir(parents=True, exist_ok=True)
    try:
        import urllib.request
        print("Downloading ChineseSimplified.isl...")
        urllib.request.urlretrieve(_LANG_URL, lang_file)
    except Exception as e:
        print("WARNING: failed to download language file:", e)


def build_installer(version, target=None):
    if target is None:
        target = platform.system()
    if target != "Windows":
        print(L("skip_installer"))
        return

    iscc = find_iscc()
    if not iscc:
        print(L("iscc_not_found"))
        return

    _ensure_lang_file(iscc)

    dist_dir = BUILD_DIR / APP_NAME
    if not dist_dir.is_dir():
        print(L("outdir_not_found"), dist_dir)
        print(L("run_build_first"))
        return

    iss_template = PROJECT_ROOT / "scripts" / "installer" / "windows.iss"
    if not iss_template.exists():
        print(L("iss_not_found"), iss_template)
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

    print(L("building_installer"))
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
        print(L("installer_done"), installer)
    else:
        print(L("installer_not_found"), installer)


def build_linux_packages(version):
    build_sh = PROJECT_ROOT / "scripts" / "installer" / "linux" / "build.sh"
    if not build_sh.exists():
        print(L("linux_sh_not_found", build_sh))
        return

    env = os.environ.copy()
    env["SKIP_PYINSTALLER"] = "1"
    print(L("building_linux"))
    result = subprocess.run(
        ["bash", str(build_sh), "all"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    if result.returncode != 0:
        print(L("linux_failed", result.returncode))
        sys.exit(result.returncode)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OhMyMeme build script (PyInstaller)")
    parser.add_argument("--lang", choices=["zh", "en"], default=None,
                        help="Output language (auto-detect: zh locally, en on GitHub Actions)")
    parser.add_argument("--installer-only", action="store_true",
                        help="Only build installer (assumes PyInstaller already ran)")
    parser.add_argument("--build-only", action="store_true",
                        help="Only run PyInstaller, skip installer")
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--windows", action="store_true", dest="target_windows",
                              help="Build for Windows")
    target_group.add_argument("--linux", action="store_true", dest="target_linux",
                              help="Build for Linux")
    parser.set_defaults(target_windows=False, target_linux=False)
    args = parser.parse_args()

    # --- language detection ---
    if args.lang:
        _set_lang(args.lang)
    elif os.environ.get("GITHUB_ACTIONS") == "true":
        _set_lang("en")
    else:
        _set_lang("zh")

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
            print(L("installer_only_unsupported", target))
            sys.exit(1)
    else:
        version = build_pyinstaller(target=target)
        if args.build_only:
            pass
        elif target == "Windows":
            build_installer(version, target=target)
        elif target == "Linux":
            build_linux_packages(version)
