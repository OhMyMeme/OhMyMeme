#!/usr/bin/env python3
"""
OhMyMeme build script (PyInstaller)
Deps: pip install pyinstaller
Windows extra: InnoSetup 6/7 (ISCC.exe) — to create installer

Usage:
    python scripts/build.py                  # build + installer (auto-detect)
    python scripts/build.py --windows        # Windows target
    python scripts/build.py --linux          # Linux target
    python scripts/build.py --macos          # macOS target (.app + .dmg, arch auto-detect)
    python scripts/build.py --macos --arch x86_64  # macOS Intel build
    python scripts/build.py --installer-only # installer only (assumes already built)
    python scripts/build.py --build-only     # build only, skip installer
    python scripts/build.py --package deb    # Linux package type: all|appimage|deb|rpm
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

# 裁剪版 ffmpeg（TG 导入 webm->webp 用，仅 Windows 打包内置）
FFMPEG_DEST = (
    "tools/ffmpeg"  # --add-binary 目标（相对 _internal/，运行时经 _MEIPASS 解析）
)
FFMPEG_CI_DIR = PROJECT_ROOT / "ffmpeg-win64"  # CI download-artifact 落点
FFMPEG_LOCAL_OUT = (
    PROJECT_ROOT / "build" / "ffmpeg-win64" / "out"
)  # build_win64.sh 产物

PYTHON = sys.executable
IS_WINDOWS = platform.system() == "Windows"

# --- i18n ---
_MSGS = {
    "pyinstaller_not_found": {
        "zh": "错误: 未找到 PyInstaller，请执行 pip install pyinstaller",
        "en": "ERROR: PyInstaller not found, run: pip install pyinstaller",
    },
    "running": {"zh": "运行:", "en": "Running:"},
    "build_failed": {
        "zh": "PyInstaller 打包失败 (code=%d)",
        "en": "PyInstaller build failed (code=%d)",
    },
    "build_done": {"zh": "打包完成:", "en": "Build done:"},
    "vue_build_failed": {
        "zh": "Vue 前端构建失败，请检查 node/npm 环境",
        "en": "Vue frontend build failed, check node/npm environment",
    },
    "skip_installer": {
        "zh": "跳过安装包制作（非 Windows 平台）",
        "en": "Skipping installer (non-Windows target)",
    },
    "iscc_not_found": {
        "zh": "警告: 未找到 ISCC.exe（InnoSetup），跳过安装包制作",
        "en": "WARNING: ISCC.exe (InnoSetup) not found, skipping installer",
    },
    "outdir_not_found": {
        "zh": "错误: 未找到输出目录:",
        "en": "ERROR: output directory not found:",
    },
    "run_build_first": {
        "zh": "请先执行 PyInstaller 构建",
        "en": "Run PyInstaller build first",
    },
    "iss_not_found": {
        "zh": "错误: InnoSetup 脚本不存在:",
        "en": "ERROR: InnoSetup script not found:",
    },
    "building_installer": {"zh": "制作安装包...", "en": "Building installer..."},
    "installer_done": {"zh": "安装包制作完成:", "en": "Installer created:"},
    "installer_not_found": {
        "zh": "安装包制作完成，未找到预期文件:",
        "en": "Installer created but expected file not found:",
    },
    "linux_sh_not_found": {
        "zh": "警告: 未找到 %s，跳过 Linux 打包",
        "en": "WARNING: %s not found, skipping Linux packaging",
    },
    "building_linux": {"zh": "制作 Linux 包...", "en": "Building Linux packages..."},
    "linux_failed": {
        "zh": "Linux 打包失败 (code=%d)",
        "en": "Linux packaging failed (code=%d)",
    },
    "building_macos": {
        "zh": "制作 macOS 包（.app/.dmg）...",
        "en": "Building macOS packages (.app/.dmg)...",
    },
    "macos_failed": {
        "zh": "macOS 打包失败 (code=%d)",
        "en": "macOS packaging failed (code=%d)",
    },
    "installer_only_unsupported": {
        "zh": "错误: --installer-only 不支持当前目标 %s",
        "en": "ERROR: --installer-only not supported for target %s",
    },
    "cross_compile_not_supported": {
        "zh": "错误: PyInstaller 不支持交叉编译，在 Linux 上无法生成 Windows 可执行文件。\n      请使用 GitHub Actions（推送到 main 或手动触发 workflow）或在 Windows 机器上运行此脚本。",
        "en": "ERROR: PyInstaller does not support cross-compilation. Cannot produce a Windows executable from Linux.\n       Use GitHub Actions (push to main or trigger workflow_dispatch) or run this script on a Windows machine.",
    },
    "keyfinder_missing": {
        "zh": "警告: 未找到 %s，微信导入功能在产物中将不可用（先编译 src/wechat_keyfinder）",
        "en": "WARNING: %s not found; WeChat import will be unavailable in the build (compile src/wechat_keyfinder first)",
    },
    "keyfinder_required": {
        "zh": "错误: 构建 wechat_keyfinder 失败。helper 随包内置，缺失会导致微信导入不可用，"
        "故中止打包。请安装 cmake + MSVC（VS BuildTools 即可）后重试；"
        "仅本地开发可加 --allow-missing-keyfinder 跳过此检查。",
        "en": "ERROR: building wechat_keyfinder failed. The helper ships inside the installer, "
        "so packaging aborts to avoid producing a build without WeChat import support. "
        "Install cmake + MSVC (VS BuildTools is enough) and retry; "
        "local development only may pass --allow-missing-keyfinder to skip this check.",
    },
    "keyfinder_no_cmake": {
        "zh": "错误: 未找到 cmake，无法构建 wechat_keyfinder",
        "en": "ERROR: cmake not found, cannot build wechat_keyfinder",
    },
    "keyfinder_building": {
        "zh": "编译 wechat_keyfinder...",
        "en": "Building wechat_keyfinder...",
    },
    "keyfinder_build_failed": {
        "zh": "错误: wechat_keyfinder 编译失败",
        "en": "ERROR: wechat_keyfinder build failed",
    },
    "keyfinder_pinned": {
        "zh": "已固定 wechat_keyfinder SHA-256: %s",
        "en": "Pinned wechat_keyfinder SHA-256: %s",
    },
    "verify_no_dist": {
        "zh": "错误: 未找到产物目录 %s，请先执行打包",
        "en": "ERROR: build output directory not found: %s (run the build first)",
    },
    "verify_missing": {
        "zh": "错误: 产物中未找到 wechat_keyfinder.exe（微信导入功能将不可用），已搜索 %s",
        "en": "ERROR: wechat_keyfinder.exe missing from build output "
        "(WeChat import would be unavailable); searched %s",
    },
    "verify_found": {
        "zh": "已找到 helper: %s（%d 字节）",
        "en": "helper found: %s (%d bytes)",
    },
    "verify_runs": {
        "zh": "helper 可正常执行（--help 退出码 0）",
        "en": "helper executes correctly (--help exited 0)",
    },
    "verify_run_failed": {
        "zh": "错误: helper 执行失败（退出码 %s）",
        "en": "ERROR: helper failed to run (exit code %s)",
    },
    "verify_run_error": {
        "zh": "错误: 无法执行 helper: %s",
        "en": "ERROR: cannot execute helper: %s",
    },
    "verify_no_version": {
        "zh": "错误: helper 缺失版本资源 CompanyName（当前: %s）——"
        "无元数据会让产物退回被 Defender 误报的特征",
        "en": "ERROR: helper has no version resource CompanyName (got: %s) — "
        "missing metadata reintroduces the Defender false-positive signal",
    },
    "verify_version_ok": {
        "zh": "版本资源正常: CompanyName=%s",
        "en": "version resource OK: CompanyName=%s",
    },
    "verify_ok": {
        "zh": "helper 校验通过",
        "en": "helper verification passed",
    },
    "verify_failed": {
        "zh": "helper 校验未通过",
        "en": "helper verification failed",
    },
    "ffmpeg_bundled": {
        "zh": "已定位 ffmpeg: %s（%d 字节）",
        "en": "ffmpeg found: %s (%d bytes)",
    },
    "ffmpeg_not_found": {
        "zh": "错误: 未找到裁剪版 ffmpeg。CI 由 ffmpeg-win64 job 提供"
        "（artifact 下载到 ffmpeg-win64/），本地可运行 "
        "bash scripts/ffmpeg/build_win64.sh 或设置 OHMYMEME_FFMPEG 指向 "
        "ffmpeg.exe；仅本地开发可加 --allow-missing-ffmpeg 跳过"
        "（运行时回退 PATH 中的系统 ffmpeg）",
        "en": "ERROR: trimmed ffmpeg not found. On CI it comes from the "
        "ffmpeg-win64 job (artifact downloaded to ffmpeg-win64/); locally "
        "run bash scripts/ffmpeg/build_win64.sh or set OHMYMEME_FFMPEG to "
        "an ffmpeg.exe. Local development may pass --allow-missing-ffmpeg "
        "(runtime falls back to ffmpeg on PATH)",
    },
    "ffmpeg_missing_allow": {
        "zh": "警告: 跳过内置 ffmpeg（--allow-missing-ffmpeg），"
        "TG 导入将依赖 PATH 中的 ffmpeg",
        "en": "WARNING: bundling ffmpeg skipped (--allow-missing-ffmpeg); "
        "TG import will rely on ffmpeg from PATH",
    },
    "verify_ffmpeg_missing": {
        "zh": "错误: 产物中未找到 ffmpeg.exe（TG 导入的 WebM 转换将不可用），已搜索 %s",
        "en": "ERROR: ffmpeg.exe missing from build output (WebM conversion in TG "
        "import would be unavailable); searched %s",
    },
    "verify_ffmpeg_found": {
        "zh": "已找到 ffmpeg: %s（%d 字节）",
        "en": "ffmpeg found: %s (%d bytes)",
    },
    "verify_ffmpeg_no_component": {
        "zh": "错误: 内置 ffmpeg 缺少组件 %s（裁剪 configure 漏编）",
        "en": "ERROR: bundled ffmpeg lacks component %s (trimmed configure missed it)",
    },
    "verify_ffmpeg_components_ok": {
        "zh": "ffmpeg 组件齐全（libvpx-vp9 解码 / libwebp_anim 编码）",
        "en": "ffmpeg components OK (libvpx-vp9 decoder / libwebp_anim encoder)",
    },
    "verify_ffmpeg_no_fixture": {
        "zh": "错误: 缺少转换夹具 %s",
        "en": "ERROR: conversion fixture missing: %s",
    },
    "verify_ffmpeg_convert_failed": {
        "zh": "错误: ffmpeg 转换夹具失败（退出码 %s）",
        "en": "ERROR: ffmpeg failed to convert the fixture (exit code %s)",
    },
    "verify_ffmpeg_bad_output": {
        "zh": "错误: 转换输出不是有效 WebP（RIFF/WEBP 魔数不符）",
        "en": "ERROR: conversion output is not valid WebP (RIFF/WEBP magic mismatch)",
    },
    "verify_ffmpeg_convert_ok": {
        "zh": "ffmpeg 端到端转换通过（webm -> webp）",
        "en": "ffmpeg end-to-end conversion passed (webm -> webp)",
    },
    "verify_ffmpeg_ok": {
        "zh": "ffmpeg 校验通过",
        "en": "ffmpeg verification passed",
    },
    "verify_ffmpeg_failed": {
        "zh": "ffmpeg 校验未通过",
        "en": "ffmpeg verification failed",
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


def set_version(v: str):
    """临时改写 src/__init__.py 的 __version__（nightly 构建用，构建后恢复）"""
    init_py = SRC_DIR / "__init__.py"
    content = init_py.read_text(encoding="utf-8")
    new_content = re.sub(
        r'__version__\s*=\s*"[^"]*"',
        '__version__ = "%s"' % v,
        content,
        count=1,
    )
    init_py.write_text(new_content, encoding="utf-8")


def build_keyfinder_helper(allow_missing=False):
    """编译 wechat_keyfinder helper（Windows 专用，cmake + MSVC）

    helper 不再随 Release 单独分发，改为随安装包内置，故必须在打包前构建。
    每次都重新配置并构建 Release 产物：不复用已存在的 exe，也不按修改时间挑选
    输出——否则可能把 Debug 或带 WKF_ENABLE_TEST_KEY 的开发产物打进发布包。
    cmake 缺失或构建失败时默认中止（静默产出一个微信导入不可用的安装包比构建
    失败更糟）；仅本地开发可用 allow_missing 显式放行。返回可执行文件路径，
    allow_missing 且无法构建时返回 None。
    """
    if not IS_WINDOWS:
        return None
    src_dir = SRC_DIR / "wechat_keyfinder"
    exe = src_dir / "wechat_keyfinder.exe"

    def give_up(reason):
        print(reason)
        if allow_missing:
            return None
        print(L("keyfinder_required"))
        sys.exit(1)

    if not shutil.which("cmake"):
        return give_up(L("keyfinder_no_cmake"))

    build_dir = PROJECT_ROOT / "build" / "wechat_keyfinder"
    print(L("keyfinder_building"))
    # 不指定 -G：由 cmake 选用本机最新 Visual Studio 生成器（CI/local 均可）
    configure = [
        "cmake",
        "-S",
        str(src_dir),
        "-B",
        str(build_dir),
        "-A",
        "x64",
        "-DWKF_ENABLE_TEST_KEY=OFF",
    ]
    result = subprocess.run(configure, cwd=str(PROJECT_ROOT))
    if result.returncode == 0:
        result = subprocess.run(
            ["cmake", "--build", str(build_dir), "--config", "Release"],
            cwd=str(PROJECT_ROOT),
        )
    if result.returncode != 0:
        return give_up(L("keyfinder_build_failed"))

    # 只认本次构建的确定路径（VS 生成器为 <build>/Release/，单配置生成器为 <build>/）
    produced = build_dir / "Release" / "wechat_keyfinder.exe"
    if not produced.is_file():
        produced = build_dir / "wechat_keyfinder.exe"
    if not produced.is_file():
        return give_up(L("keyfinder_build_failed"))
    shutil.copy2(produced, exe)
    return exe


def pin_keyfinder_hash(exe_path):
    """把 helper 实际 SHA-256 写入 wechat_probe.py，返回原文本用于还原

    MSVC 构建非确定性（嵌入时间戳），CI 每次重编译的产物哈希都不同，
    因此哈希必须在打包时按实际产物注入 —— 校验的意义在于检测安装后被篡改，
    而非绑定某一个特定构建。传入 exe 为 None 时返回 None（无需还原）。
    """
    import hashlib

    if exe_path is None:
        return None
    probe = SRC_DIR / "wechat_probe.py"
    original = probe.read_text(encoding="utf-8")
    digest = hashlib.sha256(exe_path.read_bytes()).hexdigest()
    pattern = r'(_WECHAT_KEYFINDER_SHA256 = \{)(\s*"Windows": ")[0-9a-fA-F]{64}(")'
    patched = re.sub(
        pattern,
        lambda m: m.group(1) + m.group(2) + digest + m.group(3),
        original,
        count=1,
    )
    # 注入失败必须显式报错：否则产物会带着过期哈希，运行期校验必然失败
    if not re.search(pattern, patched) or digest not in patched:
        raise RuntimeError(
            "无法写入 wechat_keyfinder SHA-256（_WECHAT_KEYFINDER_SHA256 格式已变更）"
        )
    if patched == original:
        return None
    probe.write_text(patched, encoding="utf-8")
    print(L("keyfinder_pinned", digest))
    return original


def unpin_keyfinder_hash(original):
    """还原 wechat_probe.py 中被打包时注入的 helper 哈希"""
    (SRC_DIR / "wechat_probe.py").write_text(original, encoding="utf-8")


def read_pe_version_strings(path):
    """读取 PE 版本资源中的字符串字段（仅 Windows；不可用时返回空 dict）"""
    if not IS_WINDOWS:
        return {}
    import ctypes
    from ctypes import wintypes

    ver = ctypes.WinDLL("version", use_last_error=True)
    ver.GetFileVersionInfoSizeW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    ver.VerQueryValueW.restype = wintypes.BOOL

    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return {}
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return {}

    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if (
        not ver.VerQueryValueW(
            buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)
        )
        or length.value < 4
    ):
        return {}
    words = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD))
    lang, codepage = words[0], words[1]

    out = {}
    for name in ("CompanyName", "FileDescription", "OriginalFilename"):
        sub = "\\StringFileInfo\\%04x%04x\\%s" % (lang, codepage, name)
        val = ctypes.c_void_p()
        vlen = wintypes.UINT()
        if ver.VerQueryValueW(buf, sub, ctypes.byref(val), ctypes.byref(vlen)):
            if val.value:
                out[name] = ctypes.wstring_at(val, vlen.value).rstrip("\x00")
    return out


def verify_keyfinder_bundle():
    """校验打包产物中的 helper（build.yml / nightly.yml 共用）

    三个检查，覆盖已知的失败模式：
      1. 存在 —— helper 是否随 --add-binary 进入产物（否则用户侧微信导入全废）
      2. 可执行 —— `--help` 退出码为 0。替代原先的体积阈值：既能发现截断/
         架构不符/缺失依赖，也不会因合法体积变化而误报
      3. 版本资源 —— CompanyName 必须在，缺失即退回被 Defender 重点标记的
         「无元数据」特征（本次改动的起因）
    按文件名在产物树内查找而非硬编码 `_internal/...`，以免 PyInstaller
    调整布局后此处静默失效。
    """
    bin_name = "wechat_keyfinder.exe" if IS_WINDOWS else "wechat_keyfinder"
    root = BUILD_DIR / APP_NAME
    if not root.is_dir():
        print(L("verify_no_dist", root))
        return False
    matches = [p for p in root.rglob(bin_name) if p.is_file()]
    if not matches:
        print(L("verify_missing", root))
        return False
    helper = matches[0]
    print(L("verify_found", helper, helper.stat().st_size))

    errors = []
    if IS_WINDOWS:
        try:
            proc = subprocess.run(
                [str(helper), "--help"], capture_output=True, timeout=30
            )
            if proc.returncode != 0:
                errors.append(L("verify_run_failed", proc.returncode))
            else:
                print(L("verify_runs"))
        except subprocess.TimeoutExpired:
            errors.append(L("verify_run_error", "超时（30s）"))
        except OSError as e:
            errors.append(L("verify_run_error", e))

        company = read_pe_version_strings(helper).get("CompanyName", "")
        if company != APP_NAME:
            errors.append(L("verify_no_version", company or "(空)"))
        else:
            print(L("verify_version_ok", company))

    for e in errors:
        print(e)
    return not errors


def ensure_ffmpeg(allow_missing=False):
    """定位随包分发的裁剪版 ffmpeg（仅 Windows 打包）

    顺序：OHMYMEME_FFMPEG（文件或含 ffmpeg.exe 的目录）→ 工作区 ffmpeg-win64/
    （CI artifact）→ build/ffmpeg-win64/out/（本地跑 build_win64.sh）。
    缺失时中止打包——与 wechat_keyfinder 同理，静默产出 WebM 转换不可用的
    安装包比构建失败更糟；allow_missing 仅供本地开发放行。返回路径或 None。
    """
    if not IS_WINDOWS:
        return None
    cands = []
    env = os.environ.get("OHMYMEME_FFMPEG", "")
    if env:
        p = Path(env)
        if p.is_dir():
            cands.append(p / "ffmpeg.exe")
        cands.append(p)
    cands.append(FFMPEG_CI_DIR / "ffmpeg.exe")
    cands.append(FFMPEG_LOCAL_OUT / "ffmpeg.exe")
    for p in cands:
        if p.is_file():
            if p.name != "ffmpeg.exe":
                # --add-binary 保留源文件名，运行时/校验只认 ffmpeg.exe，先标准化
                stage = PROJECT_ROOT / "build" / "ffmpeg-stage"
                stage.mkdir(parents=True, exist_ok=True)
                staged = stage / "ffmpeg.exe"
                shutil.copy2(p, staged)
                p = staged
            print(L("ffmpeg_bundled", p, p.stat().st_size))
            return p
    if allow_missing:
        print(L("ffmpeg_missing_allow"))
        return None
    print(L("ffmpeg_not_found"))
    sys.exit(1)


def _verify_ffmpeg_convert(exe, fixture):
    """用产物 ffmpeg 实跑 TG 转换命令（与运行时共用 _webm_cmd），校验 WebP 魔数

    configure 的组件名配错时组件列表检查可能漏判（enable 拼写错误不会报错），
    端到端转换是硬验收。
    """
    added = str(PROJECT_ROOT) not in sys.path
    if added:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from src.tg_stickers import _webm_cmd
    except Exception as e:
        return [L("verify_run_error", e)]
    finally:
        if added:
            try:
                sys.path.remove(str(PROJECT_ROOT))
            except ValueError:
                pass
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out.webp"
        cmd = _webm_cmd(str(exe), str(fixture), str(out))
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return [L("verify_run_error", "超时（60s）")]
        except OSError as e:
            return [L("verify_run_error", e)]
        if proc.returncode != 0:
            return [L("verify_ffmpeg_convert_failed", proc.returncode)]
        if not out.is_file():
            return [L("verify_ffmpeg_bad_output")]
        magic = out.read_bytes()[:12]
        if not (magic[:4] == b"RIFF" and magic[8:12] == b"WEBP"):
            return [L("verify_ffmpeg_bad_output")]
    print(L("verify_ffmpeg_convert_ok"))
    return []


def verify_ffmpeg_bundle():
    """校验打包产物中的裁剪版 ffmpeg（build.yml / nightly.yml 共用）

    三个检查：
      1. 存在 —— ffmpeg.exe 是否随 --add-binary 进入产物
      2. 可执行且组件齐全 —— `-decoders` 含 libvpx-vp9、`-encoders` 含
         libwebp_anim（透明动画两要素，缺一 TG 转换即废）
      3. 端到端 —— 对 tests/fixtures/tiny_vp9.webm 实跑转换命令并校验
         RIFF/WEBP 魔数
    按文件名在产物树内查找，不硬编码 _internal 布局（同 verify_keyfinder_bundle）。
    """
    root = BUILD_DIR / APP_NAME
    if not root.is_dir():
        print(L("verify_no_dist", root))
        return False
    matches = [p for p in root.rglob("ffmpeg.exe") if p.is_file()]
    if not matches:
        print(L("verify_ffmpeg_missing", root))
        return False
    exe = matches[0]
    print(L("verify_ffmpeg_found", exe, exe.stat().st_size))

    errors = []
    try:
        for flag, needle in (
            ("-decoders", b"libvpx-vp9"),
            ("-encoders", b"libwebp_anim"),
        ):
            proc = subprocess.run(
                [str(exe), "-hide_banner", flag], capture_output=True, timeout=30
            )
            if proc.returncode != 0:
                errors.append(L("verify_run_failed", proc.returncode))
                break
            if needle not in proc.stdout:
                errors.append(L("verify_ffmpeg_no_component", needle.decode()))
                break
        else:
            print(L("verify_ffmpeg_components_ok"))
    except subprocess.TimeoutExpired:
        errors.append(L("verify_run_error", "超时（30s）"))
    except OSError as e:
        errors.append(L("verify_run_error", e))

    if not errors:
        fixture = PROJECT_ROOT / "tests" / "fixtures" / "tiny_vp9.webm"
        if not fixture.is_file():
            errors.append(L("verify_ffmpeg_no_fixture", fixture))
        else:
            errors.extend(_verify_ffmpeg_convert(exe, fixture))

    for e in errors:
        print(e)
    return not errors


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


def ensure_vue_frontend():
    """确保 Vue 前端产物存在（dist/ 被 gitignore），缺失则 npm ci + vite build"""
    dist_js = SRC_DIR / "webui" / "dist" / "ohmymeme.js"
    if dist_js.exists():
        return
    if not (PROJECT_ROOT / "package.json").exists():
        print("WARNING: package.json not found, cannot build Vue frontend")
        return
    npx = "npx.cmd" if IS_WINDOWS else "npx"
    cmds = []
    if not (PROJECT_ROOT / "node_modules").exists():
        ci = "npm.cmd" if IS_WINDOWS else "npm"
        lock = PROJECT_ROOT / "package-lock.json"
        cmd = [ci, "ci"] if lock.exists() else [ci, "install"]
        cmds.append(cmd)
    cmds.append([npx, "vite", "build"])
    for c in cmds:
        print("Running:", " ".join(c))
        result = subprocess.run(c, cwd=str(PROJECT_ROOT))
        if result.returncode != 0:
            print(L("vue_build_failed"))
            sys.exit(result.returncode)
    if not dist_js.exists():
        print(L("vue_build_failed"))
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


def build_pyinstaller(target=None, ffmpeg=None):
    check_pyinstaller()
    ensure_vue_frontend()
    clean()

    version = get_version()
    sep = ";" if IS_WINDOWS else ":"

    cmd = [
        PYTHON,
        "-m",
        "PyInstaller",
        "--onedir",
        "--name",
        APP_NAME,
        "--distpath",
        str(BUILD_DIR),
        "--specpath",
        str(PROJECT_ROOT / "build"),
        "--noconfirm",
        "--clean",
        "--add-data",
        str(SRC_DIR / "webui") + sep + "src/webui",
        "--add-data",
        str(SRC_DIR / "resources") + sep + "src/resources",
        "--add-data",
        str(SRC_DIR / "adb-help.txt") + sep + "src/adb-help.txt",
        "--add-data",
        str(PROJECT_ROOT / "config" / "offsets.json") + sep + "config",
    ]
    keyfinder = SRC_DIR / "wechat_keyfinder" / "wechat_keyfinder.exe"
    if IS_WINDOWS and target in (None, "Windows"):
        if keyfinder.is_file():
            cmd += [
                "--add-binary",
                str(keyfinder) + sep + "src/wechat_keyfinder",
            ]
        else:
            print(L("keyfinder_missing", keyfinder))
        if ffmpeg is not None:
            cmd += ["--add-binary", str(ffmpeg) + sep + FFMPEG_DEST]
    cmd += [
        "--hidden-import",
        "src.main",
        str(PROJECT_ROOT / "scripts" / "launcher.py"),
    ]

    exclude = [
        "numpy",
        "PyQt5",
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "PyQt5.QtWidgets",
        "PyQt5.QtNetwork",
        "PyQt5.QtSvg",
        "psutil",
        "setuptools",
        "pkg_resources",
        "pyreadline3",
        "yaml",
        "tornado",
        "jaraco",
        "jaraco.text",
        "jaraco.functools",
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
        _add_linux_gi_flags(cmd, sep)
    elif target == "Darwin":
        icon_icns = _ensure_icns()
        cmd += ["--windowed"]
        if icon_icns:
            cmd += ["--icon=" + str(icon_icns)]

    print(L("running"), " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(L("build_failed", result.returncode))
        sys.exit(result.returncode)

    print(L("build_done"), BUILD_DIR / APP_NAME)
    return version


_LANG_URL = "https://raw.githubusercontent.com/jrsoftware/issrc/refs/heads/main/Files/Languages/ChineseSimplified.isl"


def _add_linux_gi_flags(cmd, sep):
    """Linux 目标追加 PyGObject/GTK 收集参数（issue #58：打包 gi + WebKit2/Soup typelib）"""
    hooks_dir = PROJECT_ROOT / "scripts" / "hooks"
    if hooks_dir.is_dir():
        cmd += ["--additional-hooks-dir", str(hooks_dir)]
    cmd += ["--collect-all", "gi"]
    cmd += ["--hidden-import", "gi.repository.WebKit2"]
    cmd += ["--hidden-import", "gi.repository.Soup"]
    # 系统 typelib 目录（构建环境装有 python3-gi / gir1.2-webkit2 时整体收集，作为 hooks 之外的安全网）
    for typelib_dir in (
        "/usr/lib/x86_64-linux-gnu/girepository-1.0",
        "/usr/lib/girepository-1.0",
        "/usr/lib64/girepository-1.0",
        "/usr/local/lib/girepository-1.0",
        "/usr/lib/aarch64-linux-gnu/girepository-1.0",
    ):
        if os.path.isdir(typelib_dir):
            cmd += ["--add-data", typelib_dir + sep + "gi_typelibs"]


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


def build_installer(version, target=None, filename_version=None):
    """生成 InnoSetup 安装包；filename_version 仅用于输出文件名（nightly 版本）"""
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

    filename_version = filename_version or version
    # InnoSetup 要求 AppVersion 为纯数字版本；nightly 时文件名可含 -nightly 后缀
    numeric_version = re.match(r"^\d+(\.\d+)*", filename_version)
    app_version = numeric_version.group(0) if numeric_version else version
    iss_content = iss_template.read_text(encoding="utf-8")
    iss_content = iss_content.replace(
        '#define MyAppVersion "0.1.0"',
        '#define MyAppVersion "%s"' % app_version,
    )
    iss_content = iss_content.replace(
        "OutputBaseFilename=OhMyMeme-{#MyAppVersion}-setup",
        "OutputBaseFilename=OhMyMeme-%s-setup" % filename_version,
    )
    source_dir_abs = str(dist_dir.resolve())
    iss_content = iss_content.replace(
        '#define SourceDir "..\\..\\dist\\src.dist"',
        '#define SourceDir "%s"' % source_dir_abs,
    )
    iss_content = iss_content.replace(
        "OutputDir=..\\..\\dist",
        "OutputDir=%s" % str(BUILD_DIR.resolve()),
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

    output_name = "%s-%s-setup.exe" % (APP_NAME, filename_version)
    installer = BUILD_DIR / output_name
    if installer.exists():
        print(L("installer_done"), installer)
    else:
        print(L("installer_not_found"), installer)


def build_linux_packages(version, package="all", pkg_version=None, arch=None):
    build_sh = PROJECT_ROOT / "scripts" / "installer" / "linux" / "build.sh"
    if not build_sh.exists():
        print(L("linux_sh_not_found", build_sh))
        return

    env = os.environ.copy()
    env["SKIP_PYINSTALLER"] = "1"
    # deb/rpm 的 Version 字段必须是数字开头；nightly 时回退到基础版本号
    if pkg_version:
        env["OHMYMEME_PKG_VERSION"] = pkg_version
    # 传递架构参数给 build.sh
    if arch:
        # 统一架构名称：aarch64 -> aarch64, arm64 -> aarch64
        env["OHMYMEME_ARCH"] = "aarch64" if arch in ("arm64", "aarch64") else arch
    print(L("building_linux"))
    result = subprocess.run(
        ["bash", str(build_sh), package],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    if result.returncode != 0:
        print(L("linux_failed", result.returncode))
        sys.exit(result.returncode)


def _ensure_icns():
    """将 icon.png 转为 macOS .icns（PyInstaller 需要）；成功返回路径，失败返回 None"""
    png = SRC_DIR / "resources" / "icon.png"
    icns = BUILD_DIR / "OhMyMeme.icns"
    if not png.exists():
        return None
    # icon.png 存在但 icns 未生成或已过期时重新生成
    if icns.exists() and icns.stat().st_mtime >= png.stat().st_mtime:
        return icns
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        import tempfile

        tmp = tempfile.mkdtemp()
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir(parents=True, exist_ok=True)
        img = Image.open(png).convert("RGBA")
        # iconset 各尺寸（标准 macOS 图标集），按规范名导出
        for px, name in [
            (16, "icon_16x16.png"),
            (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"),
            (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"),
            (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"),
            (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"),
            (1024, "icon_512x512@2x.png"),
        ]:
            resized = img.resize((px, px), Image.LANCZOS)
            resized.save(iconset / name)
        # 用 iconutil 生成 .icns（macOS 自带）
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("WARNING: iconutil failed:", result.stderr or result.stdout)
            return None
        shutil.rmtree(tmp, ignore_errors=True)
        return icns
    except Exception as e:
        print("WARNING: failed to generate .icns:", e)
        return None


def get_macos_arch(arch=None):
    """返回 macOS 架构名（arm64 / x86_64）；未指定时按当前机器检测"""
    if arch:
        return arch
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "x86_64"


def build_macos_packages(version, filename_version=None, arch=None):
    """制作 macOS .dmg（内含 .app）；version 用于 dmg 文件名版本段，arch 追加架构后缀"""
    filename_version = filename_version or version
    arch = get_macos_arch(arch)
    app_dir = BUILD_DIR / (APP_NAME + ".app")
    if not app_dir.is_dir():
        print(L("outdir_not_found"), app_dir)
        print(L("run_build_first"))
        return

    print(L("building_macos"))
    dmg_name = "%s-v%s-%s.dmg" % (APP_NAME, filename_version, arch)
    dmg_path = BUILD_DIR / dmg_name
    if dmg_path.exists():
        dmg_path.unlink()

    staging = BUILD_DIR / "dmg-staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    # 复制 .app 到暂存目录，并添加 /Applications 软链
    shutil.copytree(app_dir, staging / (APP_NAME + ".app"))
    try:
        os.symlink("/Applications", staging / "Applications")
    except OSError:
        pass

    result = subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(dmg_path),
        ],
        cwd=str(PROJECT_ROOT),
    )
    shutil.rmtree(staging, ignore_errors=True)
    if result.returncode != 0:
        print(L("macos_failed", result.returncode))
        sys.exit(result.returncode)
    if dmg_path.exists():
        print(L("installer_done"), dmg_path)
    else:
        print(L("installer_not_found"), dmg_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OhMyMeme build script (PyInstaller)")
    parser.add_argument(
        "--lang",
        choices=["zh", "en"],
        default=None,
        help="Output language (auto-detect: zh locally, en on GitHub Actions)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override version string " "(default: read from src/__init__.py)",
    )
    parser.add_argument(
        "--nightly",
        action="store_true",
        help="Build a nightly (non-stable) release: version is 'nightly'",
    )
    parser.add_argument(
        "--installer-only",
        action="store_true",
        help="Only build installer (assumes PyInstaller already ran)",
    )
    parser.add_argument(
        "--build-only", action="store_true", help="Only run PyInstaller, skip installer"
    )
    parser.add_argument(
        "--allow-missing-keyfinder",
        action="store_true",
        help="Continue even if the wechat_keyfinder helper cannot be built "
        "(local development only; the packaged app loses WeChat import)",
    )
    parser.add_argument(
        "--verify-helper",
        action="store_true",
        help="Verify the bundled wechat_keyfinder helper in dist/ "
        "(used by CI after packaging; exits non-zero on failure)",
    )
    parser.add_argument(
        "--allow-missing-ffmpeg",
        action="store_true",
        help="Continue even if the trimmed ffmpeg cannot be located "
        "(local development only; TG WebM conversion then falls "
        "back to ffmpeg on PATH)",
    )
    parser.add_argument(
        "--verify-ffmpeg",
        action="store_true",
        help="Verify the bundled ffmpeg in dist/ (component list + "
        "end-to-end fixture conversion; used by CI; exits "
        "non-zero on failure)",
    )
    parser.add_argument(
        "--package",
        choices=["all", "appimage", "deb", "rpm"],
        default="all",
        help="Linux package type to build (default: all)",
    )
    parser.add_argument(
        "--arch",
        choices=["arm64", "x86_64", "aarch64"],
        default=None,
        help="Architecture (macOS: arm64/x86_64, Linux: aarch64/x86_64, default: auto-detect)",
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--windows",
        action="store_true",
        dest="target_windows",
        help="Build for Windows",
    )
    target_group.add_argument(
        "--linux", action="store_true", dest="target_linux", help="Build for Linux"
    )
    target_group.add_argument(
        "--macos",
        action="store_true",
        dest="target_macos",
        help="Build for macOS (.app + .dmg)",
    )
    parser.set_defaults(target_windows=False, target_linux=False, target_macos=False)
    args = parser.parse_args()

    # --- language detection ---
    if args.lang:
        _set_lang(args.lang)
    elif os.environ.get("GITHUB_ACTIONS") == "true":
        _set_lang("en")
    else:
        _set_lang("zh")

    if args.target_windows:
        if not IS_WINDOWS:
            print(L("cross_compile_not_supported"))
            sys.exit(1)
        target = "Windows"
    elif args.target_linux:
        target = "Linux"
    elif args.target_macos:
        target = "Darwin"
    else:
        target = platform.system()

    # --- helper 校验模式（CI 打包后调用；不触发版本改写等构建副作用）---
    if args.verify_helper:
        ok = verify_keyfinder_bundle()
        print(L("verify_ok") if ok else L("verify_failed"))
        sys.exit(0 if ok else 1)

    # --- ffmpeg 校验模式（CI 打包后调用，同上无构建副作用）---
    if args.verify_ffmpeg:
        ok = verify_ffmpeg_bundle()
        print(L("verify_ffmpeg_ok") if ok else L("verify_ffmpeg_failed"))
        sys.exit(0 if ok else 1)

    # --- version override / nightly ---
    base_version = get_version()
    build_version = base_version
    if args.nightly:
        build_version = "nightly"
    if args.version:
        build_version = args.version

    # InnoSetup 要求 AppVersion 为纯数字；nightly 时回退到基础版本号
    m = re.match(r"^\d+(\.\d+)*", build_version)
    app_version = m.group(0) if m else base_version

    # nightly / 指定版本时临时改写 __init__.py，构建后恢复
    patched = build_version != base_version
    keyfinder_original = None
    if patched:
        set_version(build_version)

    try:
        if args.installer_only:
            if target == "Windows":
                build_installer(
                    app_version, target=target, filename_version=build_version
                )
            elif target == "Linux":
                build_linux_packages(
                    build_version, args.package, pkg_version=app_version, arch=args.arch
                )
            elif target == "Darwin":
                build_macos_packages(
                    build_version, filename_version=build_version, arch=args.arch
                )
            else:
                print(L("installer_only_unsupported", target))
                sys.exit(1)
        else:
            # helper/ffmpeg 随包分发：先编译/定位，再打包（helper 按实际产物注入哈希）
            ffmpeg = None
            if target == "Windows":
                keyfinder = build_keyfinder_helper(
                    allow_missing=args.allow_missing_keyfinder
                )
                if keyfinder:
                    keyfinder_original = pin_keyfinder_hash(keyfinder)
                ffmpeg = ensure_ffmpeg(allow_missing=args.allow_missing_ffmpeg)
            version = build_pyinstaller(target=target, ffmpeg=ffmpeg)
            if args.build_only:
                pass
            elif target == "Windows":
                build_installer(
                    app_version, target=target, filename_version=build_version
                )
            elif target == "Linux":
                build_linux_packages(
                    version, args.package, pkg_version=app_version, arch=args.arch
                )
            elif target == "Darwin":
                build_macos_packages(
                    version, filename_version=build_version, arch=args.arch
                )
    finally:
        if keyfinder_original is not None:
            unpin_keyfinder_hash(keyfinder_original)
        if patched:
            set_version(base_version)
