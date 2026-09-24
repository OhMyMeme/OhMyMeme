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
