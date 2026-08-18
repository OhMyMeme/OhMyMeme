"""Bottle 请求和桌面文件路径安全边界。"""

from pathlib import Path

from ohmymeme.core.assets import is_safe_filename


def safe_serve_filename(name: str) -> bool:
    """验证媒体服务文件名。"""
    return is_safe_filename(name)


def host_allowed(host: str, port: int) -> bool:
    """仅允许本机回环 Host。"""
    host = (host or "").strip()
    if not host:
        return False
    base = host.split(":")[0] if ":" in host else host
    if base not in ("127.0.0.1", "localhost"):
        return False
    if ":" in host and host.rsplit(":", 1)[-1] != str(port):
        return False
    return True


def storage_dir_validation(new_dir, old_dir, protected=()):
    """验证自定义存储目录。"""
    if not new_dir or not isinstance(new_dir, str):
        return False, "目录不能为空"
    if not Path(new_dir).is_absolute():
        return False, "请选择绝对路径"
    try:
        new = Path(new_dir).resolve()
        old = Path(old_dir).resolve()
    except OSError:
        return False, "路径无效"
    if new == old:
        return False, "与当前目录相同"
    if old in new.parents:
        return False, "不能选择当前目录的子目录"
    if new in old.parents:
        return False, "不能选择当前目录的上级目录"
    for protected_path in protected:
        try:
            protected_path = Path(protected_path).resolve()
        except OSError:
            continue
        if (
            new == protected_path
            or new in protected_path.parents
            or protected_path in new.parents
        ):
            return False, "不能选择应用数据/缩略图目录或其上下级目录"
    return True, ""
