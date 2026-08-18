"""OhMyMeme - PyInstaller 启动入口"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(1, str(ROOT))

from ohmymeme.app.bootstrap import main  # noqa: E402

main()
