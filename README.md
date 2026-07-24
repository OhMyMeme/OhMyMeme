# OhMyMeme

轻量化跨平台表情包管理系统 — 突破表情包上限，快捷键呼出、搜索即复制。

## 功能

- **系统托盘运行** — 最小化资源占用，后台常驻
- **全局快捷键** — 默认 `Ctrl+Alt+M` 呼出/隐藏主面板
- **表情管理** — 导入/搜索/标签分类/收藏/自定义分组
- **一键复制** — 点击表情包自动复制到剪贴板
- **右键菜单** — 重命名/收藏/添加分组/从分组移除/删除
- **GIF 动图** — 网格内自动播放，可在设置中关闭
- **分组筛选** — 按收藏夹或自定义分组过滤，点击标签+分组叠加搜索
- **本地缓存** — 缩略图+原图双层缓存，离线可用
- **缓存扫描** — 启动时自动扫描缓存目录，已有文件无需重复导入
- **窗口拖拽** — 无边框窗口，鼠标拖拽标题栏移动

## 安装

### 从源码运行

**环境要求**: Python 3.10+

```bash
git clone https://github.com/TNTXZ/ohmymeme.git
cd ohmymeme
pip install -r requirements.txt
python -m src
```

### 使用 conda

```bash
conda create -n ohmymeme python=3.12
conda activate ohmymeme
pip install -r requirements.txt
python -m src
```

### 构建安装包

```bash
pip install pyinstaller
python scripts/build.py --onefile
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

## 使用

1. 启动后托盘出现图标，按 `Ctrl+Alt+M` 呼出主面板
2. 点击「导入」选择表情包文件（支持 png/jpg/gif/webp）
3. 点击任意表情包自动复制到剪贴板
4. 右键表情包：重命名/收藏/添加分组/从分组移除/删除
5. 搜索栏输入关键词，点击标签或分组名进行筛选

## 许可证

MIT
