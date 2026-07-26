"""OhMyMeme - PyInstaller 启动入口"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main import main

main()
