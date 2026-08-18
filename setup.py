"""OhMyMeme 安装配置"""

from pathlib import Path

from setuptools import find_packages, setup

HERE = Path(__file__).parent

# 读取版本号
about = {}
with open(HERE / "src" / "ohmymeme" / "__init__.py", encoding="utf-8") as f:
    exec(f.read(), about)

# 读取 README
long_description = ""
readme_path = HERE / "README.md"
if readme_path.exists():
    long_description = readme_path.read_text(encoding="utf-8")

setup(
    name="ohmymeme",
    version=about["__version__"],
    description="轻量化跨平台表情包管理系统",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="OhMyMeme Team",
    url="https://github.com/OhMyMeme/OhMyMeme",
    packages=find_packages(where="src", include=["ohmymeme", "ohmymeme.*"]),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "Pillow>=10.0.0",
        "pywebview>=6.0.0",
        "pystray>=0.19.0",
        "pyperclip>=1.8.2",
        "bottle>=0.13.0",
    ],
    extras_require={
        "hotkey": ["keyboard>=0.13.5"],
        "crypto": ["cryptography>=41.0.0"],
        "full": [
            "keyboard>=0.13.5",
            "cryptography>=41.0.0",
        ],
        "dev": [
            "pytest>=7.0.0",
            "black>=23.0.0",
            "ruff>=0.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ohmymeme=ohmymeme.app.bootstrap:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Desktop Environment",
    ],
)
