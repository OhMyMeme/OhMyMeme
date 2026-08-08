# OhMyMeme

轻量化跨平台表情包管理系统 — 突破表情包上限，快捷键呼出、搜索即复制。

### **QQ交流群：891636253**

![picture](https://raw.githubusercontent.com/OhMyMeme/OhMyMeme/refs/heads/dev/resource/picture.gif)

## 功能

- **系统托盘运行** — 最小化资源占用，后台常驻
- **全局快捷键** — 默认 `Ctrl+Alt+N` 呼出/隐藏主面板
- **表情管理** — 导入/搜索/标签分类/收藏/自定义分组
- **一键复制** — 点击表情包自动复制到剪贴板（GIF 保留动画）
- **复制处理** — 设置页四种模式（不处理 / WebP 缩放 / 转 GIF / 转 GIF 隐写原图）：复制超限尺寸（>200px）的静态图时按所选模式处理，WebP 模式缩放到小尺寸，转 GIF 的两种模式保持原分辨率；隐写模式可无损还原原图；导入含隐写的 GIF 会自动解码并只入库还原后的原图（网格显示原图并标记「隐写导入」，载体 GIF 不入库，此行为不受模式影响）
- **拖放导入** — 直接拖拽图片到窗口即可导入
- **文件夹导入** — 一键导入整个文件夹的图片，可选自动创建同名分组
- **右键菜单** — 重命名/收藏/打标签/添加分组/从分组移除/删除
- **标签** — 右键表情打标签（逗号分隔多标签），点击标签按多标签交集筛选
- **GIF 动图** — 网格内自动播放，可在设置中关闭
- **分组筛选** — 按收藏夹或自定义分组过滤，点击标签+分组叠加搜索
- **分组/标签栏横向滚动** — 栏内溢出时显示细滚动条，鼠标滚轮横向翻页
- **本地缓存** — 缩略图+原图双层缓存，离线可用
- **缓存扫描** — 启动时自动扫描缓存目录，已有文件无需重复导入
- **自定义存储位置** — 设置页可更换表情包图片存放目录，切换时可选自动迁移现有文件
- **同步进度条** — 上传/下载实时显示进度、速度、当前文件，支持后台运行
- **远程同步** — FTP / S3 / R2 / WebDAV 多端同步
- **局域网互联** — 与同一局域网内的手机版 OhMyMeme 配对，互相同步表情包与配置（UDP 发现 + 密钥握手 + AES-GCM 加密会话）
- **手机导入** — ADB 一键从 Android 手机拉取 QQ 表情包缓存并打包 ZIP
- **电脑版 QQ 提取** — 从 PC 版 QQ（QQNT）本地缓存批量提取收藏表情（可复用模块，见下）
- **危险操作** — 设置页一键清空本地或云端全部数据（需双重确认）
- **无边框窗口** — 自定义标题栏，鼠标拖拽移动
- **自动更新** — 启动时检测新版本，运行期间每日自动检测，下载安装包后一键升级

## 快速开始

### 下载

从 [Releases](https://github.com/OhMyMeme/OhMyMeme/releases/latest) 下载对应系统的安装包或可执行文件，直接运行。

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
git clone https://github.com/OhMyMeme/OhMyMeme.git
cd ohmymeme
pip install -r requirements.txt
python -m src
```

可用调试参数：

| 参数 | 说明 |
|------|------|
| `--debug-update` | 强制弹出更新对话框（测试用） |
| `--debug-startup` | 输出开机自启检测详情（注册表键、启动文件夹） |
| `--debug-adb` | 输出 ADB 检测详情及运行时日志（路径、版本、adb 命令） |
| `--debug` | 输出所有 DEBUG 级别日志 |
| `--silent` | 启动时最小化到托盘（源码模式下需显式传入） |

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
| **开机自启** | 系统登录时自动启动，可选静默启动（仅托盘） |
| **GIF 动画** | 关闭后网格中仅显示 GIF 首帧 |
| **复制处理** | 复制超限静态图时的处理模式：不处理 / WebP 缩放（默认，唯一缩放原图）/ 转 GIF（原分辨率）/ 转 GIF 隐写原图（原分辨率，可无损还原）；导入含隐写的 GIF 始终自动解码，只入库还原后的原图 |
| **上传进度条** | 上传时显示实时进度弹窗 |
| **上传完毕提示** | 上传完成后弹窗告知结果 |
| **下载进度条** | 下载时显示实时进度弹窗 |
| **下载完毕提示** | 下载完成后弹窗告知结果 |
| **从手机导入** | 通过 ADB 从 Android 手机拉取 QQ 表情包缓存并打包为 ZIP |
| **从电脑导入** | 从 PC 版 QQ（QQNT）本地缓存提取收藏表情（向导式：环境检查/选账号/输出位置/进度汇总） |
| **危险操作** | 一键清空本地/云端全部表情包（需输入 confirm 双重确认） |
| **局域网互联** | 设置端口与连接密钥，开启后同一局域网内手机版可发现并同步表情包/配置（见下） |
| **远程同步** | 配置 FTP / S3 / R2 / WebDAV 同步（见下） |

### 远程同步

支持四种后端同步多台设备的表情包库：

- **FTP** — 服务器地址、端口、用户名/密码（留空为匿名登录）
- **S3** — Endpoint、Region、Bucket、Access Key、Secret Key、路径前缀
- **R2** — Account ID、Access Key ID、Secret Access Key、Bucket、路径前缀（Endpoint 自动拼接）
- **WebDAV** — 配置项：`webdav_url`（服务地址）、`webdav_user`（用户名）、`webdav_password`（密码）、`webdav_path`（远程路径前缀，可选）。使用用户名/密码 Basic Auth 认证，密码自动加密保存；基于 Python 标准库 `urllib.request` 实现，无需新增依赖

配置完成后点击「测试连接」验证，然后使用标题栏的⬆上传 / ⬇下载按钮同步。

> ⚠️ 若设置中开启了「同步时删除远程文件」，上传操作会删除远程端已不存在的文件。

### 局域网互联

与同一局域网内的手机版 OhMyMeme 配对，无需公网即可互相同步表情包与配置：

1. **配置** — 设置页「局域网互联」设置端口（默认 17852）与连接密钥（留空表示同局域网内无需密钥，不推荐）
2. **开启** — 勾选「开启互联访问」临时启动服务（重启后默认关闭，不写入配置）
3. **连接** — 手机版扫描局域网发现本机，输入密钥配对；配对成功后电脑弹窗确认设备信息，允许后才开始同步
4. **安全** — 数据帧使用 AES-GCM 会话加密；设备连接需电脑端确认；配置同步默认剔除 FTP/S3/R2/WebDAV 等密码字段，开启「允许密钥传输」（仅本次会话，弹窗警示）后才会包含密钥；`push_file` 四重校验（文件名、≤64MB、sha256、合法图片），不合法字节绝不落盘

> ⚠️ 服务绑定 `0.0.0.0`，同一局域网内所有设备均可探测到本机（发现响应不含任何密钥信息）。仅在你信任的 Wi-Fi 下开启。

### 电脑版 QQ（QQNT）收藏表情提取

`src/qqnt_extract.py` 提供从 PC 版 QQ（QQNT）本地缓存批量提取收藏表情的可复用模块：

- 自动读取 `C:\Users\Public\Documents\Tencent\QQ\UserDataInfo.ini` 获取用户数据目录（自适应 GBK/UTF-8 编码，支持 BOM）
- 多账号（纯数字子目录）识别，可通过 `uapis.cn` 查询昵称（本地 JSON 缓存 1 小时，可选、依赖网络）
- 表情目录：`<UserDataSavePath>/<QQ号>/nt_qq/nt_data/Emoji/personal_emoji/Ori`
- `os.walk` + `shutil.copy2` 复制，**逐文件容错**（失败跳过继续并通过 `on_error` 上报、清理半成品），进度/日志通过 `on_progress`/`on_log` 回调输出，不依赖任何 UI 框架；支持 `image_only` 仅提取图片、`overwrite` 覆盖已有目录（默认拒绝写入非空目录）
- 环境探测 `get_extract_status()` 可区分「配置缺失」「路径失效」「无可用账号」三种情况
- 已集成到设置页「从电脑导入」向导：环境检查 → 选账号 → 输出位置 → 进度与结果汇总；手动选择的配置文件/用户数据目录会持久化，提取过程支持取消；「选择配置文件/选择用户数据目录」按钮在探测成功后仍显示，指定用户数据目录后完全覆盖 INI 推导路径（应对多用户 Windows 下 `UserDataInfo.ini` 仅记录第一个用户路径的场景）
- 复制后按文件头魔数修正扩展名（QQ 缓存文件常无扩展名或扩展名错误）
- 无弹窗、无 `sys.exit`，失败以返回值/异常表达

> ⚠️ **许可证**：`src/qqnt_extract.py` 改编自 GPL-3.0 项目 [QQFavoriteExtract](https://github.com/VanillaNahida/QQFavoriteExtract)（作者：香草味的纳西妲），按 **GPL-3.0** 协议分发，与项目其余部分的 MIT 许可不同。引入该模块后，整体作品在再分发时需以 GPL-3.0 兼容方式处理，请在使用前确认合规性。

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

> **⚠️ 注意**: PyInstaller **不支持交叉编译**。`--windows` 参数只能在 Windows 系统上使用，`--linux` 参数只能在 Linux 系统上使用。
> 如需在 Linux 上构建 Windows 安装包，请使用 [GitHub Actions](#ci-github-actions)（推送到 `main` 分支自动触发，或手动运行 workflow）。

```bash
pip install pyinstaller

# 自动检测当前系统打包
python scripts/build.py

# Windows 目标（仅在 Windows 上运行）
python scripts/build.py --windows

# Linux 目标（仅在 Linux 上运行）
python scripts/build.py --linux

# 仅打包，跳过安装包
python scripts/build.py --build-only

# 仅制作安装包（PyInstaller 已打包完时，仅 Windows）
python scripts/build.py --installer-only

# Linux 目标指定包类型：all | appimage | deb | rpm（默认 all）
python scripts/build.py --linux --installer-only --package deb
```

**Windows 安装包**: 需 [InnoSetup 6/7](https://jrsoftware.org/isdl.php)。

**Linux 包**: 支持 .deb / .rpm / AppImage，`--package` 指定包类型（`all` / `appimage` / `deb` / `rpm`，默认 `all`）。构建前需安装 GTK/WebKit 依赖（同上）。

```bash
# 等价于 bash scripts/installer/linux/build.sh all / deb / rpm / appimage
python scripts/build.py --linux --installer-only --package all
python scripts/build.py --linux --installer-only --package deb
python scripts/build.py --linux --installer-only --package rpm
python scripts/build.py --linux --installer-only --package appimage
```

> 原 Nuitka 构建脚本已移至 `scripts/nuitka/build.py`，待申诉完成后重新启用。

输出目录: `dist/`。

## PR 贡献

欢迎提交 Pull Request。提交前请确保通过以下检查：

```bash
ruff check src/   # lint 检查
black --check src/  # 格式检查（black 26.5.1, line-length 88）
python -m pytest tests/ -v  # 测试
```

CI 会自动运行 lint+test。

## 贡献者

[![Contributors](https://contributor.starsfire.top/OhMyMeme/OhMyMeme/)](https://github.com/OhMyMeme/OhMyMeme/graphs/contributors)

## AI 辅助开发

本项目包含 `AGENTS.md` 文件，供 AI 编码助手读取以了解项目结构、代码规范和关键实现细节。若通过 AI 修改代码，请确保 AI 读取该文件后再进行操作。

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

## 实现要点

### 启动时序
启动分两阶段：首先 `get_init_data()` 秒开渲染数据库数据，300ms 后依次执行 `rescan_cache()` → `run_auto_sync()` → `check_update()`。**300ms 延迟不可移除**（桥接稳定需要），**先 rescan 再 sync**（文件与 DB 一致后再对比远端）。

### 缓存去重
扫描缓存目录时**双重去重**：按文件名查 DB 防止每次启动重复注册，按 SHA-256 哈希查 DB 防止同图不同名重复。导入（拖入/对话框）同样有哈希去重。

### GIF 剪贴板
Windows 上 GIF 复制同时写入三个剪贴板格式：`CF_DIB`（首帧 BMP）、`CF_HDROP`（文件路径，QQ/微信粘贴动图必需）、自定义 `"GIF"` 格式。**移除 CF_HDROP 会导致 QQ/微信粘贴 GIF 变静态图。**

### 复制处理模式
设置页「复制处理」下拉（配置 `copy_resize_mode`：0不处理；1webp缩放，默认；2转gif；3转gif隐写原图）：复制超过 `copy_resize_max`（默认 200px）的静态图时按模式处理，动图（GIF/动画 WebP）不受影响。仅模式 1 缩放原图（转 WebP 缩放到限制内，QQ/微信原生支持 WebP）；模式 2/3 按原分辨率转 GIF（模式 3 额外隐写原图，失败时原样复制原图）。处理结果写入系统临时目录 `ohmm_resize_<md5>_<max>_q<质量>_v<版本>.webp` / `ohmm_gif_<md5>_v<版本>.gif` / `ohmm_stego_<md5>_v1.gif` 并保留（CF_HDROP 需在粘贴时仍可读取）；缓存键含编码参数与版本号，改编码逻辑后旧缓存自动失效，命中时校验文件完整性，同一表情重复复制直接复用。

### 加密降级
加密优先使用 `cryptography.fernet.Fernet`，不可用时降级为 `hashlib.pbkdf2_hmac` + XOR + base64。**不能移除 XOR 降级**，否则无 `cryptography` 时系统崩溃。

### Sync 集合合并
`pull` 时远端分组以**并集**方式合并到本地已有分组（不清除本地成员）。远端 manifest 中的 `collections` 用文件名关联（非 ID），跨设备稳定。

### Manifest 自动清理
构建 `meme-index.json` 时，若某分组无成员则自动删除该分组并跳过写入，防止空分组累积到远端。

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
