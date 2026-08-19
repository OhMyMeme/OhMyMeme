# OhMyMeme-AI

[![Release](https://img.shields.io/github/v/release/luckymolong/OhMyMeme-AI?display_name=tag&sort=semver&style=flat-square)](https://github.com/luckymolong/OhMyMeme-AI/releases)
[![License](https://img.shields.io/github/license/luckymolong/OhMyMeme-AI?style=flat-square)](LICENSE)
[![Windows](https://img.shields.io/badge/Windows-supported-0078D4?logo=windows&logoColor=white&style=flat-square)](#直接使用发布包)
[![Android](https://img.shields.io/badge/Android-Debug_build-3DDC84?logo=android&logoColor=white&style=flat-square)](#直接使用发布包)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white&style=flat-square)](#从源码运行)
[![Vue](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white&style=flat-square)](https://vuejs.org/)

轻量化跨平台表情包管理器。支持本地导入、搜索、标签、文件夹、同步、分享包和 AI 辅助整理；桌面端通过快捷键快速呼出，点击表情即可复制。

## 项目声明

> **本项目是 [OhMyMeme/OhMyMeme](https://github.com/OhMyMeme/OhMyMeme) 的衍生增强项目，不在原作者仓库内进行修改。**

本仓库在上游项目基础上维护 AI 工作流、文件夹管理、拖拽交互和 Android 端互通等增强功能。上游项目的版权、许可证和原有署名均应保留；本项目的修改内容同样受仓库根目录 [GPL-3.0](LICENSE) 约束。

## 界面预览

![OhMyMeme preview](https://raw.githubusercontent.com/OhMyMeme/OhMyMeme/dev/resource/picture.gif)

## 主要更新

- **独立 AI 设置**：AI 整理与 AI 生图分别配置服务地址、API Key 和模型，兼容 OpenAI 格式接口。
- **审核式 AI 整理**：AI 只生成标签、文件夹、描述和 OCR 建议；用户审核、修改并确认后才写入数据库。
- **单层文件夹管理**：使用 Wallpaper Engine 风格的文件夹卡片替代旧分组。支持复制与移动，其中移动按剪切语义移除旧归属；根目录仅显示未归档表情。
- **批量与多选拖拽**：表情、文件夹和标签均可批量选择；多个表情可一次拖入收藏夹或文件夹。
- **拖拽与排序优化**：修复预览从左上角跳入和拖动抽帧；拖到网格边缘自动滚动，并支持排序模式下拖入任意两个表情之间。
- **分享包互通**：恢复 `.ohmymeme-pack` 导入和导出。分享包保存图片、名称、标签、收藏、文件夹归属和排序，不携带 API Key、同步密码或本机路径。
- **桌面端与 Android 端互通**：同步 AI 描述、OCR、文件夹归属和分享包数据。
- **AI 绘图入口**：主界面可打开 AI 绘图面板，生成任务结束后自动刷新图库。

> Android 悬浮窗目前仍是开发中的不完全版。无法使用时可忽略，不影响导入、搜索、AI、文件夹、分享包和同步等其他功能。问题反馈请访问 <https://luckywszl.top>。

## 直接使用发布包

前往 [OhMyMeme-AI Releases](https://github.com/luckymolong/OhMyMeme-AI/releases) 下载对应平台的文件。

### Windows 便携版

1. 下载 Windows ZIP 压缩包并完整解压。
2. 保留 `OhMyMeme.exe` 与同级 `_internal` 目录。
3. 运行 `OhMyMeme.exe`。

`_internal` 中包含运行依赖，不能只单独复制 exe 文件。

### Android Debug APK

从同一 Release 页面下载 Android Debug APK，在 Android 系统中允许安装未知来源应用后安装。Android 源码的详细构建说明见 [android/README.md](android/README.md)。

## 从源码运行

### 环境要求

- Python 3.10+
- Node.js 20+ 与 npm（修改或构建 Vue 前端时需要）
- Git
- Windows、Linux 或 macOS
- Linux 还需要 GTK/WebKit 运行库

### 桌面端

```bash
git clone https://github.com/luckymolong/OhMyMeme-AI.git
cd OhMyMeme-AI
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
python -m src
```

修改 `src/vue-src/` 后，需要重新构建前端产物：

```bash
npm install
npx vite build
python -m src
```

Linux 的 Debian/Ubuntu 环境可安装：

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1
```

不同发行版的 WebKitGTK 包名可能不同，请按发行版仓库提供的版本调整。

## 常用操作

- **导入**：使用标题栏导入按钮，或直接把图片拖入窗口。
- **复制**：点击表情复制到剪贴板；GIF 会保留动画数据。
- **文件夹**：新建文件夹后，可从右键菜单、批量操作或拖拽把表情复制/移动进去。
- **AI 整理**：从“更多”菜单打开 AI 整理，检查建议后再应用。
- **AI 绘图**：从“更多”菜单打开 AI 绘图，填写提示词并等待任务完成。
- **分享包**：通过导入/导出菜单在设备或用户之间迁移表情包数据。

完整的增强功能操作说明见 [OhMyMeme-AI 增强版使用指南](docs/ohmymeme-ai-guide.md)。

## 构建 Windows 便携版

先完成 Vue 构建，并在 Windows 环境安装 PyInstaller：

```bash
npm install
npx vite build
pip install pyinstaller
python scripts/build.py --windows
```

PyInstaller 不支持跨平台构建。Windows 包应在 Windows 中构建；Linux 与 macOS 包也应在各自平台构建。

## 验证与贡献

提交前建议运行：

```bash
python -m unittest tests.test_core
```

欢迎通过 GitHub Issue 或 Pull Request 提交问题和改进建议。提交派生修改时，请保留上游版权、许可证与来源说明。

## 致谢与许可证

- 上游项目：[OhMyMeme/OhMyMeme](https://github.com/OhMyMeme/OhMyMeme)
- 本项目基于上游项目继续开发，感谢原作者及贡献者提供的基础。
- 许可证：[GNU GPL v3.0](LICENSE)
