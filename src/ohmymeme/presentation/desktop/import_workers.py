"""桌面导入回调和 QQNT 表现层 worker。"""

import os
from pathlib import Path

from ohmymeme.core.imports import ImportPath


def import_paths(webui, file_paths, names=None):
    """通过当前 Container 的导入服务导入路径。"""

    requests = []
    for index, source in enumerate(file_paths):
        name = (
            names[index]
            if names and index < len(names)
            else os.path.splitext(os.path.basename(source))[0]
        )
        requests.append(ImportPath(Path(source), name))
    webui._container.library.configure_stego_decoder(webui._decode_stego)
    result = webui._container.library.import_batch(requests)
    return {"ids": list(result.imported_ids), "rejected": result.rejected}
