"""verify_keyfinder_bundle 测试：CI 打包后校验 helper 的三项检查

该函数是 build.yml / nightly.yml 共用的唯一校验入口（此前两处内联脚本重复），
它一旦退化会让 CI 静默放过不完整的产物，故需要回归保护。
"""

import importlib.util
from pathlib import Path

import pytest

_BUILD_PY = Path(__file__).resolve().parent.parent / "scripts" / "build.py"


@pytest.fixture(scope="module")
def build_mod():
    """导入 scripts/build.py（顶层无副作用，仅有 __main__ 守卫）"""
    spec = importlib.util.spec_from_file_location("om_build_script", _BUILD_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stage(
    tmp_path, monkeypatch, build_mod, name="wechat_keyfinder.exe", payload=b"MZ"
):
    """把产物树与模块常量指向 tmp_path，返回 (root, helper_path)"""
    root = tmp_path / "OhMyMeme"
    helper = root / "_internal" / "src" / "wechat_keyfinder" / name
    helper.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        helper.write_bytes(payload)
    monkeypatch.setattr(build_mod, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(build_mod, "APP_NAME", "OhMyMeme")
    return root, helper


def test_passes_on_wellformed_bundle(tmp_path, monkeypatch, build_mod):
    """正常产物应通过（非 Windows 仅走存在性检查，故用无后缀二进制名）"""
    monkeypatch.setattr(build_mod, "IS_WINDOWS", False)
    _stage(tmp_path, monkeypatch, build_mod, name="wechat_keyfinder")
    assert build_mod.verify_keyfinder_bundle() is True


def test_fails_when_helper_missing(tmp_path, monkeypatch, build_mod):
    """helper 未随包分发时必须失败（否则用户侧微信导入全废）"""
    monkeypatch.setattr(build_mod, "IS_WINDOWS", False)
    _stage(tmp_path, monkeypatch, build_mod, name="wechat_keyfinder", payload=None)
    assert build_mod.verify_keyfinder_bundle() is False


def test_fails_when_dist_dir_absent(tmp_path, monkeypatch, build_mod):
    """未打包（无产物目录）时必须失败并提示先构建"""
    monkeypatch.setattr(build_mod, "BUILD_DIR", tmp_path / "nonexistent")
    monkeypatch.setattr(build_mod, "APP_NAME", "OhMyMeme")
    assert build_mod.verify_keyfinder_bundle() is False


def test_finds_helper_at_nested_path(tmp_path, monkeypatch, build_mod):
    """按文件名在产物树内查找，不硬编码 _internal 布局

    这样 PyInstaller 调整目录结构时校验仍有效（硬编码路径会静默失效）。
    """
    monkeypatch.setattr(build_mod, "IS_WINDOWS", False)
    root = tmp_path / "OhMyMeme"
    nested = root / "some" / "other" / "layout"
    nested.mkdir(parents=True)
    (nested / "wechat_keyfinder").write_bytes(b"MZ")
    monkeypatch.setattr(build_mod, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(build_mod, "APP_NAME", "OhMyMeme")
    assert build_mod.verify_keyfinder_bundle() is True


def test_rejects_truncated_helper(tmp_path, monkeypatch, build_mod):
    """损坏/截断的 helper 必须失败

    旧实现用 `size < 20000` 判断；功能检查（`--help` 退出码）覆盖同一场景
    且不受合法体积变化影响。
    """
    monkeypatch.setattr(build_mod, "IS_WINDOWS", True)
    _stage(tmp_path, monkeypatch, build_mod, payload=b"MZ" + b"\x00" * 100)
    monkeypatch.setattr(
        build_mod,
        "read_pe_version_strings",
        lambda p: {"CompanyName": "OhMyMeme"},
    )
    assert build_mod.verify_keyfinder_bundle() is False


def test_rejects_missing_version_resource(tmp_path, monkeypatch, build_mod):
    """缺 CompanyName 必须失败（无元数据会退回 Defender 误报特征）"""
    monkeypatch.setattr(build_mod, "IS_WINDOWS", True)
    _stage(tmp_path, monkeypatch, build_mod)
    monkeypatch.setattr(build_mod, "read_pe_version_strings", lambda p: {})
    # 让可执行性检查通过，单独暴露版本资源这一项
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *a, **k: build_mod.subprocess.CompletedProcess(a[0], 0, b"", b""),
    )
    assert build_mod.verify_keyfinder_bundle() is False


def test_read_pe_version_strings_on_real_helper(build_mod):
    """真实 helper 上读取版本资源（非 Windows 跳过）"""
    if not build_mod.IS_WINDOWS:
        pytest.skip("PE 版本资源读取仅 Windows")
    helper = (
        _BUILD_PY.parent.parent / "src" / "wechat_keyfinder" / "wechat_keyfinder.exe"
    )
    if not helper.is_file():
        pytest.skip("helper 未构建")
    info = build_mod.read_pe_version_strings(helper)
    assert info.get("CompanyName") == "OhMyMeme"
    assert info.get("OriginalFilename") == "wechat_keyfinder.exe"


def test_read_pe_version_strings_on_garbage_returns_empty(tmp_path, build_mod):
    """非 PE 文件不得抛异常，返回空 dict"""
    if not build_mod.IS_WINDOWS:
        pytest.skip("仅 Windows 有 version.dll")
    junk = tmp_path / "junk.exe"
    junk.write_bytes(b"not a PE file at all")
    assert build_mod.read_pe_version_strings(junk) == {}


# --- verify_ffmpeg_bundle：裁剪版 ffmpeg 随包校验 ---


def _stage_ffmpeg(tmp_path, monkeypatch, build_mod, payload=b"MZ"):
    """产物树中放入 ffmpeg.exe，返回 exe 路径"""
    exe = tmp_path / "OhMyMeme" / "_internal" / "tools" / "ffmpeg" / "ffmpeg.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        exe.write_bytes(payload)
    monkeypatch.setattr(build_mod, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(build_mod, "APP_NAME", "OhMyMeme")
    return exe


def test_ffmpeg_missing_from_bundle(tmp_path, monkeypatch, build_mod):
    """ffmpeg.exe 未随包分发必须失败（否则用户侧 TG 导入 WebM 转换全废）"""
    (tmp_path / "OhMyMeme" / "_internal").mkdir(parents=True)
    monkeypatch.setattr(build_mod, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(build_mod, "APP_NAME", "OhMyMeme")
    assert build_mod.verify_ffmpeg_bundle() is False


def test_ffmpeg_dist_absent(tmp_path, monkeypatch, build_mod):
    """未打包时必须失败并提示先构建"""
    monkeypatch.setattr(build_mod, "BUILD_DIR", tmp_path / "nonexistent")
    monkeypatch.setattr(build_mod, "APP_NAME", "OhMyMeme")
    assert build_mod.verify_ffmpeg_bundle() is False


def test_ffmpeg_components_ok_and_convert_ok(tmp_path, monkeypatch, build_mod):
    """组件列表齐全 + 端到端转换通过 → 校验通过"""
    _stage_ffmpeg(tmp_path, monkeypatch, build_mod)
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *a, **k: build_mod.subprocess.CompletedProcess(
            a[0], 0, b"libvpx-vp9\nlibwebp_anim\n", b""
        ),
    )
    monkeypatch.setattr(build_mod, "_verify_ffmpeg_convert", lambda exe, fix: [])
    assert build_mod.verify_ffmpeg_bundle() is True


def test_ffmpeg_missing_component(tmp_path, monkeypatch, build_mod):
    """configure 漏编组件（如 libvpx-vp9 解码器）必须失败"""
    _stage_ffmpeg(tmp_path, monkeypatch, build_mod)
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *a, **k: build_mod.subprocess.CompletedProcess(
            a[0], 0, b"vp9 native decoder\n", b""
        ),
    )
    assert build_mod.verify_ffmpeg_bundle() is False


def test_ffmpeg_convert_failure_fails_verify(tmp_path, monkeypatch, build_mod):
    """组件检查通过但端到端转换失败 → 整体校验必须失败"""
    _stage_ffmpeg(tmp_path, monkeypatch, build_mod)
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *a, **k: build_mod.subprocess.CompletedProcess(
            a[0], 0, b"libvpx-vp9\nlibwebp_anim\n", b""
        ),
    )
    monkeypatch.setattr(
        build_mod, "_verify_ffmpeg_convert", lambda exe, fix: ["convert failed"]
    )
    assert build_mod.verify_ffmpeg_bundle() is False


def test_ffmpeg_missing_fixture(tmp_path, monkeypatch, build_mod):
    """缺少端到端转换夹具必须失败（否则只做了组件名字符串检查）"""
    _stage_ffmpeg(tmp_path, monkeypatch, build_mod)
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *a, **k: build_mod.subprocess.CompletedProcess(
            a[0], 0, b"libvpx-vp9\nlibwebp_anim\n", b""
        ),
    )
    monkeypatch.setattr(build_mod, "PROJECT_ROOT", tmp_path)
    assert build_mod.verify_ffmpeg_bundle() is False


def test_ffmpeg_convert_detects_failed_process(monkeypatch, build_mod):
    """转换命令非零退出必须报错"""
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *a, **k: build_mod.subprocess.CompletedProcess(a[0], 1, b"", b""),
    )
    errors = build_mod._verify_ffmpeg_convert(Path("x/ffmpeg.exe"), Path("f.webm"))
    assert errors


def test_ffmpeg_convert_rejects_bad_magic(monkeypatch, build_mod):
    """输出非 RIFF/WEBP 必须报错"""

    def run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"NOT-A-WEBP!!")
        return build_mod.subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(build_mod.subprocess, "run", run)
    errors = build_mod._verify_ffmpeg_convert(Path("x/ffmpeg.exe"), Path("f.webm"))
    assert errors


def test_ffmpeg_convert_passes_on_valid_webp(monkeypatch, build_mod):
    """输出带 RIFF/WEBP 魔数且退出码 0 → 通过"""

    def run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"RIFF\x10\x00\x00\x00WEBPVP8 ")
        return build_mod.subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(build_mod.subprocess, "run", run)
    errors = build_mod._verify_ffmpeg_convert(Path("x/ffmpeg.exe"), Path("f.webm"))
    assert errors == []


# --- ensure_ffmpeg：打包前定位裁剪版 ffmpeg ---


def _prep_ensure(tmp_path, monkeypatch, build_mod):
    """把路径常量指向 tmp 并清掉外部环境变量干扰"""
    monkeypatch.setattr(build_mod, "IS_WINDOWS", True)
    monkeypatch.setattr(build_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build_mod, "FFMPEG_CI_DIR", tmp_path / "ci")
    monkeypatch.setattr(build_mod, "FFMPEG_LOCAL_OUT", tmp_path / "out")
    monkeypatch.delenv("OHMYMEME_FFMPEG", raising=False)


def test_ensure_ffmpeg_stages_nonstandard_name(tmp_path, monkeypatch, build_mod):
    """env 指到非 ffmpeg.exe 命名的文件须复制标准化

    --add-binary 保留源文件名，而运行时/校验只认 ffmpeg.exe。
    """
    _prep_ensure(tmp_path, monkeypatch, build_mod)
    src = tmp_path / "media-ffmpeg-v7.1.exe"
    src.write_bytes(b"MZ")
    monkeypatch.setenv("OHMYMEME_FFMPEG", str(src))
    got = build_mod.ensure_ffmpeg()
    assert got is not None
    assert got.name == "ffmpeg.exe"
    assert got != src
    assert got.read_bytes() == b"MZ"


def test_ensure_ffmpeg_env_dir_uses_standard_directly(tmp_path, monkeypatch, build_mod):
    """env 指向含 ffmpeg.exe 的目录时直接采用，不复制"""
    _prep_ensure(tmp_path, monkeypatch, build_mod)
    env_dir = tmp_path / "envbin"
    env_dir.mkdir()
    exe = env_dir / "ffmpeg.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("OHMYMEME_FFMPEG", str(env_dir))
    assert build_mod.ensure_ffmpeg() == exe


def test_ensure_ffmpeg_finds_ci_artifact(tmp_path, monkeypatch, build_mod):
    """CI download-artifact 落点 ffmpeg-win64/ffmpeg.exe 被拾取"""
    _prep_ensure(tmp_path, monkeypatch, build_mod)
    ci = tmp_path / "ci" / "ffmpeg.exe"
    ci.parent.mkdir(parents=True)
    ci.write_bytes(b"MZ")
    assert build_mod.ensure_ffmpeg() == ci


def test_ensure_ffmpeg_missing_exits(tmp_path, monkeypatch, build_mod):
    """三处候选全缺时默认中止打包（静默产出无 TG 转换的安装包更糟）"""
    _prep_ensure(tmp_path, monkeypatch, build_mod)
    with pytest.raises(SystemExit):
        build_mod.ensure_ffmpeg()


def test_ensure_ffmpeg_allow_missing_returns_none(tmp_path, monkeypatch, build_mod):
    """--allow-missing-ffmpeg 仅供本地开发放行"""
    _prep_ensure(tmp_path, monkeypatch, build_mod)
    assert build_mod.ensure_ffmpeg(allow_missing=True) is None


def test_ensure_ffmpeg_skipped_on_non_windows(tmp_path, monkeypatch, build_mod):
    """仅 Windows 打包内置，其余平台返回 None 交给运行时 PATH 检测"""
    monkeypatch.setattr(build_mod, "IS_WINDOWS", False)
    assert build_mod.ensure_ffmpeg() is None
