"""LAN bridge 服务访问。"""

from ohmymeme.services import lan


def status():
    """返回 LAN 状态。"""
    return lan.get_status()
