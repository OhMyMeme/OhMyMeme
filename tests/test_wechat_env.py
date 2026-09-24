import logging
import os
import platform
import subprocess

import pytest

from src import wechat_probe

# 仅平台相关的用例需要跳过；helper 分发 / 完整性 / 下载判定等用例与平台无关，
# 通过 mock 平台与冻结态后可在 Ubuntu CI 上真实执行（此前整模块跳过导致零覆盖）。
windows_only = pytest.mark.skipif(
    platform.system() != "Windows", reason="微信导入仅支持 Windows"
)


def _make_account(root, name, with_db=True, plaintext=True):
    """构造账号目录，db_storage/emoticon/emoticon.db 可选明文/加密"""
    db_dir = os.path.join(str(root), name, "db_storage", "emoticon")
    os.makedirs(db_dir, exist_ok=True)
    if with_db:
        header = b"SQLite format 3\x00" if plaintext else b"\x00" * 16
        with open(os.path.join(db_dir, "emoticon.db"), "wb") as f:
            f.write(header + b"\x00" * 32)


@windows_only
def test_account_without_wxid_prefix_detected(tmp_path):
    _make_account(tmp_path, "custom_nickname")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"
    assert [a["id"] for a in r["accounts"]] == ["custom_nickname"]


@windows_only
def test_wxid_prefix_account_still_detected(tmp_path):
    _make_account(tmp_path, "wxid_abc123")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"
    assert [a["id"] for a in r["accounts"]] == ["wxid_abc123"]


@windows_only
def test_selected_account_dir_without_wxid_prefix(tmp_path):
    _make_account(tmp_path, "my_account")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path) + os.sep + "my_account")
    assert r["status"] == "supported"
    assert r["accounts"][0]["id"] == "my_account"


@windows_only
def test_dir_without_emoticon_db_not_account(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "random_folder"))
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "no_accounts"
    assert r["accounts"] == []


@windows_only
def test_encrypted_index_without_wxid_prefix(tmp_path):
    _make_account(tmp_path, "old_wechat", plaintext=False)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "encrypted_index"


@windows_only
def test_non_wxid_dir_without_db_ignored_alongside_valid_account(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "backup_old"))
    _make_account(tmp_path, "wxid_one")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert [a["id"] for a in r["accounts"]] == ["wxid_one"]


@windows_only
def test_wide_fallback_db_in_other_subdir(tmp_path):
    _make_account(tmp_path, "acc", with_db=False)
    db_dir = os.path.join(str(tmp_path), "acc", "db_storage", "emoticon_backup")
    os.makedirs(db_dir)
    with open(os.path.join(db_dir, "emoticon.db"), "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 32)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"


@windows_only
def test_wide_fallback_db_directly_under_db_storage(tmp_path):
    _make_account(tmp_path, "acc", with_db=False)
    storage = os.path.join(str(tmp_path), "acc", "db_storage")
    with open(os.path.join(storage, "emoticon.db"), "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 32)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"


@windows_only
def test_no_database_reports_existing_db_files(tmp_path):
    _make_account(tmp_path, "wxid_x", with_db=False)
    fav_dir = os.path.join(str(tmp_path), "wxid_x", "db_storage", "favorite")
    os.makedirs(fav_dir)
    with open(os.path.join(fav_dir, "favorite.db"), "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 32)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "no_database"
    assert r["accounts"][0]["db_files"] == ["favorite/favorite.db"]


@windows_only
def test_wechat_3x_layout_reports_unsupported(tmp_path):
    acc = os.path.join(str(tmp_path), "wxid_old")
    os.makedirs(os.path.join(acc, "Msg", "Multi"))
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "unsupported_version"
    assert r["reason"] == "wechat_3x_unsupported"


@windows_only
def test_wechat_3x_micromsg_marker_also_unsupported(tmp_path):
    acc = os.path.join(str(tmp_path), "wxid_old2")
    os.makedirs(os.path.join(acc, "Msg"))
    with open(os.path.join(acc, "Msg", "MicroMsg.db"), "wb") as f:
        f.write(b"\x00" * 16)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "unsupported_version"


@windows_only
def test_msg_emoticon_db_still_supported(tmp_path):
    _make_account(tmp_path, "wxid_m", with_db=False)
    msg_dir = os.path.join(str(tmp_path), "wxid_m", "Msg")
    os.makedirs(msg_dir)
    with open(os.path.join(msg_dir, "emoticon.db"), "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 32)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"


def _mock_windows(monkeypatch, frozen=True):
    """把平台与冻结态固定为「Windows + 发布产物」，使用例可在任意 CI 平台执行"""
    monkeypatch.setattr(wechat_probe.platform, "system", lambda: "Windows")
    monkeypatch.setattr(wechat_probe.sys, "frozen", frozen, raising=False)


def test_bundled_binary_resolved_from_meipass(tmp_path, monkeypatch):
    """冻结环境下 helper 应从 _MEIPASS 解析（随包分发）"""
    _mock_windows(monkeypatch)
    fake_meipass = tmp_path / "_internal"
    target_dir = fake_meipass / "src" / "wechat_keyfinder"
    target_dir.mkdir(parents=True)
    exe = target_dir / "wechat_keyfinder.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(wechat_probe.sys, "_MEIPASS", str(fake_meipass), raising=False)
    assert wechat_probe.detect_wechat_keyfinder() == str(exe)
    assert wechat_probe._bundled_binary_path() == str(exe)


def test_bundled_binary_missing_returns_empty(tmp_path, monkeypatch):
    """helper 缺失时返回空串（而非抛错），供上层提示安装包不完整"""
    _mock_windows(monkeypatch)
    monkeypatch.setattr(wechat_probe.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(wechat_probe, "_bundled_binary_path", lambda: "")
    assert wechat_probe.detect_wechat_keyfinder() == ""
    assert wechat_probe.ensure_wechat_keyfinder() == ""


def test_offsets_resolved_from_meipass(tmp_path, monkeypatch):
    """冻结环境下 offsets.json 从 _MEIPASS/config 解析"""
    fake_meipass = tmp_path / "_internal"
    (fake_meipass / "config").mkdir(parents=True)
    cfg = fake_meipass / "config" / "offsets.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(wechat_probe.sys, "_MEIPASS", str(fake_meipass), raising=False)
    assert wechat_probe._offsets_path() == cfg


def test_integrity_rejects_tampered_binary(tmp_path, monkeypatch):
    """发布态下完整性校验必须拒绝与固定哈希不符的文件"""
    _mock_windows(monkeypatch)
    exe = tmp_path / "wechat_keyfinder.exe"
    exe.write_bytes(b"not the real binary")
    monkeypatch.setattr(
        wechat_probe,
        "_WECHAT_KEYFINDER_SHA256",
        {"Windows": "0" * 64},
    )
    assert wechat_probe.verify_binary_integrity(str(exe)) is False


def test_ensure_returns_empty_on_integrity_failure(tmp_path, monkeypatch):
    """发布态下哈希不匹配时 ensure 不得返回路径（防篡改后执行）"""
    _mock_windows(monkeypatch)
    exe = tmp_path / "wechat_keyfinder.exe"
    exe.write_bytes(b"tampered")
    monkeypatch.setattr(wechat_probe, "_bundled_binary_path", lambda: str(exe))
    monkeypatch.setattr(wechat_probe, "_WECHAT_KEYFINDER_SHA256", {"Windows": "0" * 64})
    assert wechat_probe.ensure_wechat_keyfinder() == ""


def test_pinned_hash_accepts_matching_binary(tmp_path, monkeypatch):
    """发布态下固定哈希与文件一致时应放行（正常发布路径）"""
    import hashlib

    _mock_windows(monkeypatch)
    exe = tmp_path / "wechat_keyfinder.exe"
    payload = b"MZ fake but stable"
    exe.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(wechat_probe, "_WECHAT_KEYFINDER_SHA256", {"Windows": digest})
    assert wechat_probe.verify_binary_integrity(str(exe)) is True


def test_source_run_skips_pinned_hash(tmp_path, monkeypatch):
    """源码运行使用本地构建产物，其哈希与随包固定值必然不同，应跳过比对

    否则开发者自行编译 helper 后仍会因哈希不匹配而无法使用微信导入。
    """
    _mock_windows(monkeypatch, frozen=False)
    exe = tmp_path / "wechat_keyfinder.exe"
    exe.write_bytes(b"locally built helper")
    monkeypatch.setattr(wechat_probe, "_WECHAT_KEYFINDER_SHA256", {"Windows": "0" * 64})
    assert wechat_probe.verify_binary_integrity(str(exe)) is True


def _arm_dev_build(tmp_path, monkeypatch):
    """让 _ensure_dev_helper 走到 cmake 构建分支（无 helper + 假 cmake）"""
    _mock_windows(monkeypatch, frozen=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(wechat_probe, "_DEV_BUILD_DONE", False)
    stub = tmp_path / "wechat_probe_stub.py"
    stub.write_text("", encoding="utf-8")
    (tmp_path / "wechat_keyfinder").mkdir(exist_ok=True)
    monkeypatch.setattr(wechat_probe, "__file__", str(stub))
    monkeypatch.setattr(
        wechat_probe.shutil, "which", lambda name, *a, **k: "/fake/cmake"
    )


def test_dev_build_timeout_is_handled(tmp_path, monkeypatch, caplog):
    """cmake 超时必须降级为告警

    TimeoutExpired 不是 OSError 子类，若漏捕获会穿透到调用方
    （ensure_wechat_keyfinder -> 导入流程），变成异常中断而非「不可用」提示。
    """

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout"))

    _arm_dev_build(tmp_path, monkeypatch)
    monkeypatch.setattr(wechat_probe.subprocess, "run", boom)
    with caplog.at_level(logging.WARNING):
        wechat_probe._ensure_dev_helper()  # 不得抛出
    assert "超时" in caplog.text


def test_dev_build_passes_timeouts_to_cmake(tmp_path, monkeypatch):
    """两次 cmake 调用都必须带 timeout，否则可能无限期挂起"""
    seen = []

    def record(cmd, **kw):
        seen.append(kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="stop here")

    _arm_dev_build(tmp_path, monkeypatch)
    monkeypatch.setattr(wechat_probe.subprocess, "run", record)
    wechat_probe._ensure_dev_helper()
    assert seen and all(t is not None for t in seen), f"缺少 timeout: {seen}"


def test_dev_build_failure_reports_cmake_output(tmp_path, monkeypatch, caplog):
    """构建失败时告警须带 cmake 输出，否则失败原因不可见"""
    detail = "CMake Error: could not find any instance of Visual Studio"

    def fail(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=detail)

    _arm_dev_build(tmp_path, monkeypatch)
    monkeypatch.setattr(wechat_probe.subprocess, "run", fail)
    with caplog.at_level(logging.WARNING):
        wechat_probe._ensure_dev_helper()
    assert "无 Visual Studio" in caplog.text or detail in caplog.text
    assert "配置失败" in caplog.text


def test_locate_uses_source_tree_in_dev_mode(tmp_path, monkeypatch):
    """开发态 helper 从源码目录解析（不依赖 _MEIPASS）"""
    _mock_windows(monkeypatch, frozen=False)
    src_dir = tmp_path / "wechat_keyfinder"
    src_dir.mkdir()
    fake_module = tmp_path / "wechat_probe_stub.py"
    fake_module.write_text("", encoding="utf-8")
    exe = src_dir / "wechat_keyfinder.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(wechat_probe, "__file__", str(fake_module))
    assert wechat_probe._bundled_binary_path() == str(exe)


# --- _download_sticker：明文优先判定（回归：长度恰为 16 倍数时被无谓解密毁坏）---


class _FakeResponse:
    """最小响应对象，模拟 urllib 的 context manager + read(n)"""

    def __init__(self, payload):
        self._payload = payload

    def read(self, n=-1):
        return self._payload if n < 0 else self._payload[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    def __init__(self, payload, record=None):
        self._payload = payload
        self._record = record

    def open(self, req, timeout=None):
        if self._record is not None:
            self._record.append(req.full_url)
        return _FakeResponse(self._payload)


def _stub_download(monkeypatch, payload):
    """让 _download_sticker 的取数步骤返回 payload（跳过真实网络与 DNS）"""
    seen = []
    monkeypatch.setattr(
        wechat_probe.urllib.request,
        "build_opener",
        lambda *a, **k: _FakeOpener(payload, seen),
    )
    monkeypatch.setattr(wechat_probe, "_resolve_safe", lambda host: True)
    return seen


def _png_of_length(n):
    """构造魔数为 PNG 的载荷，总长度精确为 n（长度是本次回归的关键变量）"""
    assert n >= 8
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * (n - 8)


URL = "http://vweixinf.tc.qq.com/110/20401/stodownload?m=x"


def test_plaintext_16_multiple_survives_with_aes_key(monkeypatch):
    """核心回归：明文图片长度恰为 16 倍数且带 aes_key 时，必须原样返回

    旧实现对该长度无条件做 AES-CBC 解密，把明文解坏后判定非法而丢弃，
    导致约 1/16 的表情被静默跳过。
    """
    payload = _png_of_length(64)
    assert len(payload) % 16 == 0
    _stub_download(monkeypatch, payload)
    got = wechat_probe._download_sticker(URL, "0b250c45917240a49914826c8bf9ed94")
    assert got == payload


def test_plaintext_non_multiple_16_survives(monkeypatch):
    """长度非 16 倍数（旧实现因跳过解密而侥幸成功）仍须正常返回"""
    payload = _png_of_length(67)
    assert len(payload) % 16 != 0
    _stub_download(monkeypatch, payload)
    got = wechat_probe._download_sticker(URL, "0b250c45917240a49914826c8bf9ed94")
    assert got == payload


def test_plaintext_without_aes_key(monkeypatch):
    """无 aes_key 时明文直接返回"""
    payload = _png_of_length(64)
    _stub_download(monkeypatch, payload)
    assert wechat_probe._download_sticker(URL) == payload


def test_encrypted_payload_is_decrypted(monkeypatch):
    """密文（非明文）路径仍须能解密——AES-CBC 输出恒为 16 倍数"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    real_png = _png_of_length(64)
    key = bytes.fromhex("0b250c45917240a49914826c8bf9ed94")
    enc = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor().update(real_png)
    assert len(enc) % 16 == 0
    _stub_download(monkeypatch, enc)
    got = wechat_probe._download_sticker(URL, key.hex())
    assert got == real_png


def test_non_image_payload_rejected(monkeypatch):
    """既非明文图片、解密后也非图片时返回 None"""
    _stub_download(monkeypatch, b"not an image at all........")
    assert (
        wechat_probe._download_sticker(URL, "0b250c45917240a49914826c8bf9ed94") is None
    )


def test_oversize_payload_rejected(monkeypatch):
    """超过 _MAX_DOWNLOAD 上限的响应被拒绝"""
    payload = _png_of_length(wechat_probe._MAX_DOWNLOAD + 64)
    _stub_download(monkeypatch, payload)
    assert (
        wechat_probe._download_sticker(URL, "0b250c45917240a49914826c8bf9ed94") is None
    )


def test_disallowed_host_rejected(monkeypatch):
    """非白名单主机即便有 aes_key 也拒绝（防 SSRF）"""
    _stub_download(monkeypatch, _png_of_length(64))
    assert wechat_probe._download_sticker("http://evil.example.com/x") is None
