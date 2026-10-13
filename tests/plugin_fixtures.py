# pyright: basic

"""测试用官方插件夹具：通过真实打包与安装事务落盘。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ohmymeme.core.plugins.manifest import CANONICAL_PROVIDERS  # noqa: E402
from ohmymeme.core.plugins.runtime import seeding  # noqa: E402
from scripts.plugin_packaging import build_plugin_zip  # noqa: E402


# 用真实打包与安装事务安装一个官方插件，返回解析结果
def install_official(data_dir, plugin_id, version="0.0.0-test"):
    archive_dir = Path(data_dir).parent / "_plugin_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    out = archive_dir / ("%s-%s.zip" % (plugin_id.replace(".", "-"), version))
    result = build_plugin_zip(plugin_id, version, out)
    return seeding.install_plugin(data_dir, result["path"])


# 安装全部九个官方插件，返回 id 到解析结果的映射
def install_all_official(data_dir):
    return {
        provider_id: install_official(data_dir, provider_id)
        for provider_id, _, _ in CANONICAL_PROVIDERS
    }
