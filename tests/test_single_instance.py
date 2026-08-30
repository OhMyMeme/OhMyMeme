import errno
import sys
import types

import pytest

from src import platform_util


@pytest.fixture
def fake_fcntl(monkeypatch, tmp_path):
    """注入假 fcntl 模块并把锁文件定向到 tmp_path，覆盖 POSIX 分支"""
    monkeypatch.setattr(platform_util.platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform_util.tempfile, "gettempdir", lambda: str(tmp_path))
    fake = types.ModuleType("fcntl")
    fake.LOCK_EX = 2
    fake.LOCK_NB = 4
    monkeypatch.setitem(sys.modules, "fcntl", fake)
    return fake


def test_posix_lock_file_created_and_held(fake_fcntl, tmp_path):
    assert platform_util.acquire_single_instance() is True
    lock = tmp_path / "ohmymeme-0.lock"
    assert lock.exists()


def test_flock_eagain_returns_false(fake_fcntl):
    fake_fcntl.flock = lambda *a: (_ for _ in ()).throw(
        OSError(errno.EAGAIN, "resource busy")
    )
    assert platform_util.acquire_single_instance() is False


def test_flock_eacces_returns_false(fake_fcntl):
    fake_fcntl.flock = lambda *a: (_ for _ in ()).throw(
        OSError(errno.EACCES, "permission denied")
    )
    assert platform_util.acquire_single_instance() is False


def test_flock_eopnotsupp_fails_open(fake_fcntl):
    fake_fcntl.flock = lambda *a: (_ for _ in ()).throw(
        OSError(errno.EOPNOTSUPP, "not supported")
    )
    assert platform_util.acquire_single_instance() is True
