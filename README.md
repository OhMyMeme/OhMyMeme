# OhMyMeme

轻量化跨平台表情包管理系统 — 突破表情包上限，快捷键呼出、搜索即复制。

## 功能

- **系统托盘运行** — 最小化资源占用，后台常驻
- **全局快捷键** — 默认 `Ctrl+Alt+M` 呼出/隐藏主面板
- **表情管理** — 导入/搜索/标签分类/收藏/自定义分组
- **一键复制** — 点击表情包自动复制到剪贴板（GIF 保留动画）
- **拖放导入** — 直接拖拽图片到窗口即可导入
- **右键菜单** — 重命名/收藏/添加分组/从分组移除/删除
- **GIF 动图** — 网格内自动播放，可在设置中关闭
- **分组筛选** — 按收藏夹或自定义分组过滤，点击标签+分组叠加搜索
- **本地缓存** — 缩略图+原图双层缓存，离线可用
- **缓存扫描** — 启动时自动扫描缓存目录，已有文件无需重复导入
- **远程同步** — FTP / S3 / R2 多端同步
- **无边框窗口** — 自定义标题栏，鼠标拖拽移动

## 快速开始

### 下载

从 [Releases](https://github.com/TNTXZ/ohmymeme/releases) 下载对应系统的安装包或可执行文件，直接运行。

### 从源码运行

**环境要求**: Python 3.10+

**Linux 额外依赖**:
```bash
# Debian / Ubuntu
sudo apt install python3-gi
# apt install gir1.2-webkit2-4.0  # 按系统版本选择 webkit2gtk 包

# Arch Linux
sudo pacman -S python-gobject
yay -S webkit2gtk  # 依赖 libsoup，通过 yay 安装
```

```bash
git clone https://github.com/TNTXZ/ohmymeme.git
cd ohmymeme
pip install -r requirements.txt
python -m src
```

或使用 conda：

```bash
conda create -n ohmymeme python=3.12
conda activate ohmymeme
pip install -r requirements.txt
python -m src
```

## 使用

### 基本操作

1. **启动** — 运行后系统托盘出现蓝色图标，按 `Ctrl+Alt+M` 呼出主面板
2. **导入** — 点击标题栏「导入」按钮或直接拖拽图片到窗口，支持 png/jpg/gif/webp
3. **复制** — 点击任意表情包自动复制到剪贴板（GIF 保留动画）
4. **搜索** — 搜索栏输入关键词实时筛选；点击标签或分组名叠加过滤
5. **右键菜单** — 重命名 / 收藏 / 添加到分组 / 从分组移除 / 删除

### 收藏与分组

- 右键 →「收藏」将表情加入收藏夹，点击左上角⭐按钮筛选收藏内容
- 右键 →「添加到分组」创建或选择已有分组
- 分组显示在搜索栏下方，点击即可筛选该分组内的表情

### 设置

点击标题栏⚙按钮打开设置窗口：

| 选项 | 说明 |
|------|------|
| **快捷键** | 自定义全局热键，格式如 `Ctrl+Shift+M` |
| **开机自启** | 系统登录时自动启动 |
| **GIF 动画** | 关闭后网格中仅显示 GIF 首帧 |
| **缓存目录** | 修改表情包缓存位置 |
| **远程同步** | 配置 FTP / S3 / R2 同步（见下） |

### 远程同步

支持三种后端同步多台设备的表情包库：

- **FTP** — 服务器地址、端口、用户名/密码（留空为匿名登录）
- **S3** — Endpoint、Region、Bucket、Access Key、Secret Key、路径前缀
- **R2** — Account ID、Access Key ID、Secret Access Key、Bucket、路径前缀（Endpoint 自动拼接）

配置完成后点击「测试连接」验证，然后使用标题栏的⬆上传 / ⬇下载按钮同步。

> ⚠️ 若设置中开启了「同步时删除远程文件」，上传操作会删除远程端已不存在的文件。

### 路径说明

| 用途 | 路径 |
|------|------|
| 配置文件 | `%APPDATA%/OhMyMeme/config.json` |
| 数据库 | `%LOCALAPPDATA%/OhMyMeme/memes.db` |
| 缓存原图 | `%LOCALAPPDATA%/OhMyMeme/cache/` |
| 缩略图 | `%LOCALAPPDATA%/OhMyMeme/thumbnails/` |
| 索引文件 | `%LOCALAPPDATA%/OhMyMeme/meme-index.json` |

## 构建

依赖 PyInstaller 6.0+。

```bash
pip install pyinstaller

# 自动检测当前系统打包
python scripts/build.py

# 指定目标系统
python scripts/build.py --windows          # Windows 目标
python scripts/build.py --linux            # Linux 目标

# 仅打包，跳过安装包
python scripts/build.py --build-only

# 仅制作安装包（PyInstaller 已打包完时，仅 Windows）
python scripts/build.py --installer-only
```

**Windows 安装包**: 需 [InnoSetup 6/7](https://jrsoftware.org/isdl.php)。

**Linux 包**: 支持 .deb / .rpm / AppImage，详见 `scripts/installer/linux/build.sh`。构建前需安装 GTK/WebKit 依赖（同上）。

```bash
bash scripts/installer/linux/build.sh all      # AppImage + .deb
bash scripts/installer/linux/build.sh deb      # 仅 .deb
bash scripts/installer/linux/build.sh rpm      # 仅 .rpm
bash scripts/installer/linux/build.sh appimage # 仅 AppImage
```

> 原 Nuitka 构建脚本已移至 `scripts/nuitka/build.py`，待申诉完成后重新启用。

输出目录: `dist/`。

## 架构

```
┌─────────────┐     ┌──────────────────┐
│  系统托盘    │◄────│   全局快捷键      │
│  (pystray)   │     │  (Ctrl+Alt+M)    │
└──────┬──────┘     └──────────────────┘
       │ 呼出
┌──────▼──────┐     ┌──────────────────┐
│  WebView    │────►│   Bottle API     │
│  HTML/CSS   │     │   (localhost)    │
└──────┬──────┘     └──────────────────┘
       │ API 调用
┌──────▼──────┐     ┌──────────────────┐
│   SQLite    │     │   本地缓存目录    │
│  元数据      │     │  缩略图+原图     │
└─────────────┘     └──────────────────┘
```

## 技术栈

| 模块 | 技术 | 理由 |
|------|------|------|
| UI | PyWebView (v6) + Bottle | 原生 WebView 渲染，HTML/CSS/JS 前端 |
| 托盘 | pystray | 最轻跨平台托盘库 |
| 热键 | keyboard → pynput → 轮询回退 | 三级降级保障 |
| 图片 | Pillow | 业界标准 |
| 剪贴板 | ctypes (Win32 API) | 零外部依赖，GIF 动画原始字节 |
| 数据库 | SQLite3 (WAL) | 内置，线程安全 |
| 加密 | cryptography (Fernet) | 轻量对称加密 |
| 窗口 | frameless + JS 拖拽 | 自定义无边框体验 |

## 许可证

MIT
