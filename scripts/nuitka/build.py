#!/usr/bin/env python3
"""
OhMyMeme 打包脚本 (Nuitka)
依赖: pip install nuitka
Windows 额外依赖: InnoSetup 6/7 (ISCC.exe) — 制作安装包
用法:
    python scripts/build.py                        # 自动检测当前系统打包
    python scripts/build.py --windows              # 打包 Windows 目标
    python scripts/build.py --linux                # 打包 Linux 目标
    python scripts/build.py --clang                # 使用 Clang 编译器
    python scripts/build.py --nuitka-only          # 仅 Nuitka 构建，跳过安装包
    python scripts/build.py --installer-only       # 仅制作安装包(Nuitka 已构建)
    python scripts/build.py --onefile              # 单文件模式
"""

import os
import platform
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
PACKAGE_DIR = SRC_DIR / "ohmymeme"
BUILD_DIR = PROJECT_ROOT / "dist"
APP_NAME = "OhMyMeme"
PLUGIN_MANIFEST_TARGET = "ohmymeme/config/plugin-manifest.json"
OPTIONAL_RUNTIME_EXCLUSIONS = ("gmssl",)
EXTERNAL_HELPER_BINARY_SUFFIXES = {".a", ".dll", ".exe", ".lib", ".obj", ".pdb"}

PYTHON = sys.executable
BUILD_TIMEOUT = 1800.0


def _configured_build_timeout():
    # Keep every external build process bounded by one environment setting.
    raw = os.environ.get("OHMYMEME_BUILD_TIMEOUT", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return BUILD_TIMEOUT
    return value if value > 0 else BUILD_TIMEOUT


BUILD_TIMEOUT = _configured_build_timeout()


def _run_bounded(command, **kwargs):
    # subprocess.run terminates and waits for the child when its timeout expires.
    try:
        return subprocess.run(command, timeout=BUILD_TIMEOUT, **kwargs)
    except subprocess.TimeoutExpired as error:
        print(
            "ERROR: build command timed out after %.3gs: %s"
            % (BUILD_TIMEOUT, command),
            file=sys.stderr,
        )
        raise SystemExit(124) from error


def _snapshot_path(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return set()
    if path.is_dir() and not path.is_symlink():
        return {path, *path.rglob("*")}
    return {path}


def _remove_path(path):
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError:
        pass


def _cleanup_created_paths(snapshots):
    for root, before in snapshots:
        current = _snapshot_path(root)
        for path in sorted(
            current - before, key=lambda item: len(item.parts), reverse=True
        ):
            _remove_path(path)


@contextmanager
def _cleanup_owned_on_failure(paths):
    snapshots = tuple((Path(path), _snapshot_path(path)) for path in paths)
    completed = False
    try:
        yield
        completed = True
    finally:
        if not completed:
            _cleanup_created_paths(snapshots)


def _compiler_cleanup_paths():
    return (
        BUILD_DIR,
        PROJECT_ROOT / "build",
        PROJECT_ROOT / (APP_NAME + ".build"),
        PROJECT_ROOT / (APP_NAME + ".dist"),
    )


def _assert_external_helper_not_packaged():
    # The runtime-fetched helper and static OpenSSL inputs are never frozen data.
    helper_root = SRC_DIR / "wechat_keyfinder"
    payloads = sorted(
        path
        for path in helper_root.rglob("*")
        if path.is_file() and path.suffix.lower() in EXTERNAL_HELPER_BINARY_SUFFIXES
    )
    if payloads:
        names = ", ".join(
            str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            for path in payloads
        )
        raise SystemExit(f"external wechat helper payload is not a frozen input: {names}")


def get_version():
    init_py = PACKAGE_DIR / "__init__.py"
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


def check_nuitka():
    try:
        import nuitka
    except ImportError:
        print("错误: 未找到 Nuitka，请执行 pip install nuitka")
        sys.exit(1)


def clean():
    for d in [BUILD_DIR, PROJECT_ROOT / "build", PROJECT_ROOT / "*.spec"]:
        if isinstance(d, Path):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
            elif d.parent.glob(d.name):
                for f in d.parent.glob(d.name):
                    f.unlink()
    build_dir = PROJECT_ROOT / ("%s.build" % APP_NAME)
    if build_dir.is_dir():
        shutil.rmtree(build_dir, ignore_errors=True)
    dist_src = PROJECT_ROOT / ("%s.dist" % APP_NAME)
    if dist_src.is_dir():
        shutil.rmtree(dist_src, ignore_errors=True)


def build_nuitka(onefile=False, use_clang=False, target=None):
    _assert_external_helper_not_packaged()
    check_nuitka()
    clean()
    with _cleanup_owned_on_failure(_compiler_cleanup_paths()):
        if target is None:
            target = platform.system()

        version = get_version()
        platform_opts = []

        if target == "Windows":
            icon_file = str(SRC_DIR / "resources" / "icon.ico")
            platform_opts = [
                "--windows-console-mode=disable",
                "--windows-icon-from-ico=" + icon_file,
                "--msvc=latest",
            ]
            if use_clang:
                platform_opts.append("--clang")
        elif target == "Linux":
            icon_path = SRC_DIR / "resources" / "icon.png"
            if icon_path.exists():
                platform_opts.append("--linux-icon=" + str(icon_path))
            if use_clang:
                platform_opts.append("--clang")
        elif target == "Darwin":
            platform_opts = [
                "--macos-create-app-bundle",
                "--macos-app-name=" + APP_NAME,
            ]

        data_opts = [
            "--include-data-dir=" + str(SRC_DIR / "webui") + "=ohmymeme/webui",
            "--include-data-dir=" + str(SRC_DIR / "resources") + "=ohmymeme/resources",
            "--include-data-files="
            + str(SRC_DIR / "adb-help.txt")
            + "=ohmymeme/adb-help.txt",
            "--include-data-files="
            + str(PROJECT_ROOT / "LICENSE")
            + "=ohmymeme/LICENSE",
            "--include-data-files="
            + str(PROJECT_ROOT / "NOTICE")
            + "=ohmymeme/NOTICE",
            "--include-data-dir="
            + str(PROJECT_ROOT / "LICENSES")
            + "=ohmymeme/LICENSES",
            "--include-data-dir="
            + str(PROJECT_ROOT / "THIRD-PARTY-NOTICES")
            + "=ohmymeme/THIRD-PARTY-NOTICES",
            "--include-data-files="
            + str(PROJECT_ROOT / "config" / "offsets.json")
            + "=ohmymeme/config/offsets.json",
            "--include-data-files="
            + str(PROJECT_ROOT / "config" / "plugin-manifest.json")
            + "="
            + PLUGIN_MANIFEST_TARGET,
        ]

        nofollow_opts = [
            "--nofollow-import-to=pygments",
            "--nofollow-import-to=PyQt5",
            "--nofollow-import-to=PyQt6",
            "--nofollow-import-to=PySide2",
            "--nofollow-import-to=PySide6",
            "--nofollow-import-to=boto3.docs",
        ]
        nofollow_opts.extend(
            "--nofollow-import-to=" + module
            for module in OPTIONAL_RUNTIME_EXCLUSIONS
        )

        pkg_opts = [
            "--include-package=PIL",
            "--include-package=pystray",
            "--include-package=pyperclip",
            "--include-package=cryptography",
            "--include-package=curl_cffi",
            "--include-package=keyboard",
            "--include-package=bottle",
            "--disable-plugin=pywebview",
        ]

        if target == "Windows":
            pkg_opts += [
                "--include-module=webview.platforms.win32",
                "--include-module=webview.platforms.winforms",
                "--include-module=webview.platforms.edgechromium",
                "--include-module=webview.platforms.mshtml",
                "--include-module=webview.platforms.cef",
            ]

        cmd = [
            PYTHON, "-m", "nuitka",
            "--standalone",
            "--output-dir=" + str(BUILD_DIR),
            "--output-filename=" + APP_NAME,
            "--python-flag=nosite",
            "--python-flag=-m",
            "--noinclude-pytest-mode=nofollow",
            "--low-memory",
        ] + nofollow_opts + data_opts + pkg_opts + platform_opts

        if onefile:
            cmd.append("--onefile")

        cmd.append(str(PACKAGE_DIR / "__main__.py"))

        print("运行: %s" % " ".join(cmd))
        result = _run_bounded(cmd, cwd=str(PROJECT_ROOT))
        if result.returncode != 0:
            print("Nuitka 打包失败 (code=%d)" % result.returncode)
            sys.exit(result.returncode)

        ext_map = {"Windows": ".exe", "Darwin": "", "Linux": ".bin"}
        ext = ext_map.get(target, "")
        if onefile:
            src = BUILD_DIR / ("%s%s" % (APP_NAME, ext))
            dst = BUILD_DIR / ("%s-v%s-%s%s" % (APP_NAME, version, target.lower(), ext))
            if src.exists():
                src.rename(dst)
                print("打包完成: %s" % dst)
        else:
            # 查找实际生成的 .dist 目录
            dist_dirs = sorted(BUILD_DIR.glob("*.dist"))
            if dist_dirs:
                print("打包完成: %s" % dist_dirs[-1])

        print("Nuitka 构建完成!")
        return version


def build_installer(version):
    """使用 InnoSetup 制作 Windows 安装包"""
    system = platform.system()
    if system != "Windows":
        print("跳过安装包制作（非 Windows 平台）")
        return

    iscc = find_iscc()
    if not iscc:
        print("警告: 未找到 ISCC.exe（InnoSetup），跳过安装包制作")
        print("请安装 InnoSetup 6/7 或设置 ISCC_DIR 环境变量指向 ISCC.exe")
        return

    dist_dirs = sorted(BUILD_DIR.glob("*.dist"))
    if not dist_dirs:
        print("错误: 未找到 Nuitka 输出目录 (dist/*.dist)")
        print("请先执行 Nuitka 构建")
        return
    dist_dir = dist_dirs[-1]

    iss_template = PROJECT_ROOT / "scripts" / "installer" / "windows.iss"
    if not iss_template.exists():
        print("错误: InnoSetup 脚本不存在: %s" % iss_template)
        return

    iss_content = iss_template.read_text(encoding="utf-8")
    iss_content = iss_content.replace(
        '#define MyAppVersion "0.1.0"',
        '#define MyAppVersion "%s"' % version,
    )
    # 替换路径为绝对路径（ISS 临时文件位置改变，相对路径会算错）
    source_dir_abs = str(dist_dir.resolve())
    iss_content = iss_content.replace(
        '#define SourceDir "..\\..\\dist\\OhMyMeme"',
        '#define SourceDir "%s"' % source_dir_abs,
    )
    iss_content = iss_content.replace(
        'OutputDir=..\\..\\dist',
        'OutputDir=%s' % str(BUILD_DIR.resolve()),
    )
    iss_temp = BUILD_DIR / "ohmy meme.iss"
    iss_temp.write_text(iss_content, encoding="utf-8")

    print("制作安装包...")
    try:
        result = _run_bounded(
            [iscc, str(iss_temp)],
            cwd=str(PROJECT_ROOT),
        )
    finally:
        if iss_temp.exists():
            iss_temp.unlink()
    if result.returncode != 0:
        sys.exit(result.returncode)

    output_name = "%s-%s-setup.exe" % (APP_NAME, version)
    installer = BUILD_DIR / output_name
    if installer.exists():
        print("安装包制作完成: %s" % installer)
    else:
        print("安装包制作完成，未找到预期文件: %s" % installer)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OhMyMeme 打包脚本 (Nuitka)")
    parser.add_argument("--onefile", action="store_true", dest="onefile",
                        help="单文件模式 (可能因 zstd OOM 失败)")
    parser.add_argument("--onedir", action="store_false", dest="onefile",
                        help="目录模式 (默认)")
    parser.add_argument("--nuitka-only", action="store_true",
                        help="仅 Nuitka 构建，跳过安装包制作")
    parser.add_argument("--installer-only", action="store_true",
                        help="仅制作安装包（假设 Nuitka 已构建）")
    parser.add_argument("--clang", action="store_true", dest="use_clang",
                        help="使用 Clang 编译器")
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--windows", action="store_true", dest="target_windows",
                              help="构建 Windows 目标")
    target_group.add_argument("--linux", action="store_true", dest="target_linux",
                              help="构建 Linux 目标")
    parser.set_defaults(onefile=False, use_clang=False, target_windows=False, target_linux=False)
    args = parser.parse_args()

    if args.target_windows:
        target = "Windows"
    elif args.target_linux:
        target = "Linux"
    else:
        target = None  # auto-detect

    if args.installer_only:
        if target is not None and target != "Windows":
            print("错误: --installer-only 仅支持 Windows 目标")
            sys.exit(1)
        build_installer(get_version())
    else:
        version = build_nuitka(onefile=args.onefile, use_clang=args.use_clang, target=target)
        make_installer = not args.nuitka_only and (target is None or target == "Windows")
        if make_installer:
            build_installer(version)
