"""同步 bridge 服务访问。"""

from ohmymeme.services.sync import service


def progress():
    """返回同步轮询状态。"""
    return service.get_sync_progress()
