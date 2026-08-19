# OhMyMeme

> 本项目基于 [OhMyMeme/OhMyMeme](https://github.com/OhMyMeme/OhMyMeme) 衍生开发。
>
> **安卓版说明：悬浮窗功能仍在开发中，当前属于不完全版。** 如果悬浮窗可以正常使用，可按需使用；如果无法使用，请忽略该功能，安卓版其他功能不受影响。本人并不擅长 Android 等移动端软件开发，欢迎熟悉 Android 的开发者接替或继续维护。遇到 Bug 请联系：<https://luckywszl.top>。

轻量化跨平台表情包管理系统 — 突破表情包上限，快捷键呼出、搜索即复制。

### **QQ交流群：891636253**

![picture](https://raw.githubusercontent.com/OhMyMeme/OhMyMeme/refs/heads/dev/resource/picture.gif)

## 功能

- **系统托盘运行** — 最小化资源占用，后台常驻
- **全局快捷键** — 默认 `Ctrl+Alt+N` 呼出/隐藏主面板；Windows 可选在鼠标所在屏幕显示隐藏的主面板，默认关闭
- **表情管理** — 导入/搜索/标签分类/收藏/单层文件夹
- **一键复制** — 点击表情包自动复制到剪贴板（GIF 保留动画）；Windows 可选在全局快捷键呼出后安全尝试粘贴回原窗口。仅由全局快捷键从隐藏状态呼出的主窗口，会在复制成功后自动隐藏，普通窗口、托盘呼出及复制失败时保持可见
- **原生文件拖拽** — 关闭拖拽排序后可将表情拖到外部应用；拖拽完成后主窗口保持显示，不会因拖拽自动隐藏
- **复制处理** — 设置页四种模式（不处理 / WebP 缩放 / 转 GIF / 转 GIF 隐写原图）：复制超限尺寸（>200px）的静态图时按所选模式处理，WebP 模式缩放到小尺寸，转 GIF 的两种模式保持原分辨率；隐写模式可无损还原原图；导入含隐写的 GIF 会自动解码并只入库还原后的原图（网格显示原图并标记「隐写导入」，载体 GIF 不入库，此行为不受模式影响）
- **拖放导入** — 直接拖拽图片到窗口即可导入
- **文件夹导入** — 一键导入整个文件夹的图片，可选创建同名文件夹，并为成功导入的表情自动添加同名标签
- **文件夹管理** — 主网格以 Wallpaper Engine 风格的文件夹卡片展示；点击卡片进入文件夹。表情可直接拖到文件夹卡片，或从右键、批量操作中选择“复制到文件夹”或“移动到文件夹”。复制保留原文件夹归属，移动移出其他文件夹；两种方式都会自动添加目标文件夹同名标签
- **右键菜单** — 重命名/收藏/打标签/放入文件夹/从当前文件夹移出/删除
- **标签** — 右键表情打开标签编辑器：点选已有标签、搜索过滤、或输入新建，点击标签按多标签交集筛选
- **GIF 动图** — 网格内自动播放，可在设置中关闭
- **文件夹筛选** — 按收藏夹、自定义文件夹或“未归档”过滤，点击标签可叠加搜索
- **未归档** — 自动汇总未放入任何文件夹的表情，可在设置中开关显示
- **悬浮搜索** — 主窗口可打开独立置顶搜索小窗；在小窗内手动输入关键词即可实时检索本地表情并复制，不读取 QQ、微信或其他应用的输入内容
- **本地缓存** — 缩略图+原图双层缓存，离线可用
- **缓存扫描** — 启动时自动扫描缓存目录，已有文件无需重复导入
- **导入限制** — 拒绝接收超过 2K 分辨率（最长边 2560px）或超过 20MB 的表情，跳过并提示
- **自定义存储位置** — 设置页可更换表情包图片存放目录，切换时可选自动迁移现有文件
- **同步进度条** — 上传/下载实时显示进度、速度、当前文件，支持后台运行
- **远程同步** — FTP / S3 / R2 / WebDAV 多端同步
- **局域网互联** — 与同一局域网内的手机版 OhMyMeme 配对，互相同步表情包、文件夹归属、排序、AI 描述/OCR 文本与配置（UDP 发现 + 密钥握手 + AES-GCM 加密会话）
- **手机导入** — ADB 一键从 Android 手机拉取 QQ 表情包缓存并打包 ZIP（自动识别主存储与外置 TF 卡路径）
- **电脑版 QQ 提取** — 从 PC 版 QQ（QQNT）本地缓存批量提取收藏表情（可复用模块，见下）
- **Telegram 表情导入** — 从 Telegram Desktop 本地缓存解密提取表情包（WebP 直取、WebM 无损转 WebP 且保留透明通道，自动跳过动态表情的静态重复版），支持手动指定 tdata 目录并记忆
- **微信表情导入** — 从微信电脑版缓存提取收藏表情（Windows，需微信正在运行）：C++ 辅助二进制提取进程内存密钥 → AES-CBC 解密表情数据库 → CDN 下载并校验 MD5；支持多账号选择，二进制发布时校验 SHA-256 防篡改（发布版内置真实哈希，未配置时默认拒绝执行）
- **危险操作** — 设置页一键清空本地或云端全部数据（需双重确认）
- **网格大小** — 设置页可在 48px 到 120px 之间调整表情和文件夹卡片的大小，重启后保留选择
- **单实例启动** — Windows 重复打开时不会再初始化第二个窗口、托盘或全局快捷键，避免重复弹窗
- **无边框窗口** — 自定义标题栏，鼠标拖拽移动
- **自动更新** — 启动时检测新版本，运行期间每日自动检测，下载安装包后一键升级
- **AI 工作流** — 标题栏「AI」面板支持：① 多模态整理建议（标签、文件夹、描述与图片文字，必须审核后才写入）、② 网上找表情包（Bing 图片搜索下载导入）、③ AI 文生图；右键单张表情可调用 `images/edits` 生成编辑副本，原图始终保留。设置页将整理与生图拆为两套独立 API（各自 base_url/API Key/模型），兼容 OpenAI 格式服务商；`ai_description` 与 `ai_ocr_text` 会写入同步清单，供 Android、云端和局域网同步保持搜索结果一致
- **本地智能检索** — AI 描述与图片文字可纳入搜索
- **QQ / 微信受控粘贴** — 设置页可选择手动、Windows QQ 或 Windows 微信模式；在目标聊天窗口前台按全局快捷键呼出后，右键明确选择「复制并粘贴」才会尝试 Ctrl+V。普通点击始终只复制，功能绝不读取聊天记录、按 Enter 或发送消息；不兼容时保持复制并提示手动粘贴
- **批量与分享包** — 可批量改标签、复制或移动到文件夹、删除或导出；支持全选当前页和取消全选；`.ohmymeme-pack` 仅包含图片和元数据，可安全导入导出，不携带设置、密钥或本地路径

## Ohmymeme-AI 增强版

`Ohmymeme-AI` 分支基于桌面端 `v0.6.2` 维护，重点提供审核式 AI 整理、单层文件夹、剪切式移动、批量选择、拖拽自动滚动和桌面/Android 分享包互通。完整操作说明见：[Ohmymeme-AI 增强版使用指南](docs/ohmymeme-ai-guide.md)。

> 文件夹“移动进去”按剪切处理：会移除旧文件夹归属；根目录只展示未归档表情。便携版运行时请保留 `OhMyMeme.exe` 同级的 `_internal` 目录。

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

> **说明（GTK 后端）**: 本项目 Linux 使用 pywebview 的 GTK 后端（`WebKit2`）。
> - **deb / rpm 安装包**已内置 `gi` 与 WebKit2/Soup typelib，无需额外安装 python3-gi；但依赖系统的
>   `gir1.2-webkit2-4.1`（或 4.0）包提供的 WebKitGTK 运行库，`apt install gir1.2-webkit2-4.1` 或安装
>   `libwebkit2gtk-4.1-0` 即可（deb 安装时自动处理依赖）。
> - **源码 / conda / venv 运行**必须让当前 Python 能导入 `gi`：先按上面命令在系统层安装 `python3-gi`
>   （含 `gir1.2-webkit2-*`），再让 venv/conda 环境能看到系统 dist-packages，两种方式任选其一：
>   - 创建 venv 时加 `--system-site-packages`：`python -m venv --system-site-packages .venv`
>   - 运行前设置 `PYTHONPATH=/usr/lib/python3/dist-packages`（Arch 为 `/usr/lib/python3.12/site-packages`）
>   - conda 中可执行 `conda install -c conda-forge pygobject` 直接在环境内装 PyGObject

```bash
git clone https://github.com/OhMyMeme/OhMyMeme.git
cd ohmymeme
pip install -r requirements.txt
python -m src
```

主窗口前端为 **Vue 3**（`src/vue-src/`，Vite 构建 IIFE 单文件 `src/webui/dist/ohmymeme.js`）。**源码运行**时若产物缺失会自动执行一次 `npx vite build`；手动构建方式：

```bash
npm install        # 首次构建前安装依赖
npx vite build     # 构建 Vue 前端 → src/webui/dist/ohmymeme.js
```

设置窗口仍为 vanilla 前端（`src/webui/settings.*`，独立 webview，无需构建）。旧主窗口（`src/webui/index.*`）已备份至 `src/webui-backup/`，不再使用。

主窗口启动时播放 `src/resources/OhMyMeme.mp4` 启动动画（全屏遮罩，视频结束或 6s 兜底后淡出），仅启动时播放一次，快捷键/托盘呼出不重播。设置页「显示启动动画」开关（配置 `show_startup_animation`，默认开）可关闭动画：关闭时不播放视频，降级为 300ms 延时后加载后续内容；开启时动画播放期间即并行加载（无 300ms 延时，动画天然覆盖桥接稳定时间）。

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
3. **复制** — 点击任意表情包自动复制到剪贴板（GIF 保留动画）；设置页可关闭「复制时记录最近使用」
4. **搜索** — 搜索栏输入关键词实时筛选；点击标签或文件夹名叠加过滤；搜索/标签筛选结果可直接拖到外部应用，不会触发内部排序
5. **右键菜单** — 重命名 / 收藏 / 放入文件夹 / 从当前文件夹移出 / 删除

### 收藏与文件夹

- 右键 →「收藏」将表情加入收藏夹，点击侧栏「收藏夹」筛选内容
- 点击标题栏「新建文件夹」创建文件夹；也可以导入本地目录时创建同名文件夹
- 主网格首页会显示文件夹卡片；点击卡片进入文件夹，拖动表情到文件夹卡片后可选“复制”或“移动”，两种方式均会自动补充文件夹同名标签
- 删除文件夹只解除文件夹归属，不删除表情文件、表情记录或已自动添加的同名标签

### 设置

点击标题栏⚙按钮打开设置窗口：

| 选项 | 说明 |
|------|------|
| **快捷键** | 自定义全局热键，格式如 `Ctrl+Shift+M` |
| **热键在鼠标处显示** | 默认关闭，仅 Windows 生效；全局热键打开隐藏主面板时按鼠标所在显示器的工作区放置，不影响托盘激活 |
| **开机自启** | 系统登录时自动启动，可选静默启动（仅托盘） |
| **GIF 动画** | 关闭后网格中仅显示 GIF 首帧 |
| **网格大小** | 在 48px 到 120px 之间调整主界面的表情和文件夹卡片大小，设置会保留 |
| **复制处理** | 复制超限静态图时的处理模式：不处理 / WebP 缩放（默认，唯一缩放原图）/ 转 GIF（原分辨率）/ 转 GIF 隐写原图（原分辨率，可无损还原）；导入含隐写的 GIF 始终自动解码，只入库还原后的原图 |
| **上传进度条** | 上传时显示实时进度弹窗 |
| **上传完毕提示** | 上传完成后弹窗告知结果 |
| **下载进度条** | 下载时显示实时进度弹窗 |
| **下载完毕提示** | 下载完成后弹窗告知结果 |
| **从手机导入** | 通过 ADB 从 Android 手机拉取 QQ 表情包缓存并打包为 ZIP |
| **从电脑导入** | 从 PC 版 QQ（QQNT）本地缓存提取收藏表情（向导式：环境检查/选账号/输出位置/进度汇总） |
| **Telegram 导入** | 从 Telegram Desktop 本地缓存解密提取表情包（WebP/WebM，WebM 需 ffmpeg 无损转 WebP 且保留透明通道，自动跳过与动态表情重复的静态版；未自动检测到目录时可手动指定 tdata 并记忆） |
| **微信导入** | 从微信电脑版缓存提取收藏表情（Windows，需微信运行）：辅助二进制提取密钥 → 解密数据库 → CDN 下载校验；支持多账号选择；发布版含二进制 SHA-256 防篡改（未配置真实哈希时拒绝执行） |
| **危险操作** | 一键清空本地/云端全部表情包（需输入 confirm 双重确认） |
| **AI 设置** | 分别配置 AI 整理服务与 AI 生图服务（各自 base_url/API Key/模型）；可选择整理风格。AI 整理会优先处理标签、AI 描述或 OCR 文本尚未补全的表情，不会因已放入文件夹而跳过；整理测试仅发送最小 chat 请求，生图测试会真实请求生成 1 张测试图，可能消耗额度；找图来源独立配置，支持通义千问/OpenAI/SiliconFlow 等 OpenAI 兼容服务商 |
| **聊天客户端适配** | 可选手动复制、Windows QQ 或 Windows 微信。只在目标窗口前台按全局快捷键呼出后，用户右键明确选择「复制并粘贴」时发送 Ctrl+V；绝不读取聊天记录、自动发送或模拟 Enter；无法恢复目标窗口时仅保留剪贴板内容 |
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

依赖 PyInstaller 6.0+。构建前请确认前端产物已生成：`src/webui/dist/ohmymeme.js`（Vue 构建产物已随仓库提交，改过前端后需 `npx vite build` 重新生成，见[从源码运行](#从源码运行)）。

> **⚠️ 注意**: PyInstaller **不支持交叉编译**。`--windows` 参数只能在 Windows 系统上使用，`--linux` 参数只能在 Linux 系统上使用，`--macos` 参数只能在 macOS 上使用。
> 如需在本地构建其他平台安装包，请使用 [GitHub Actions](#ci-github-actions)（推送到 `main` 分支自动触发，或手动运行 workflow）。

```bash
pip install pyinstaller

# 自动检测当前系统打包
python scripts/build.py

# Windows 目标（仅在 Windows 上运行）
python scripts/build.py --windows

# Linux 目标（仅在 Linux 上运行）
python scripts/build.py --linux

# macOS 目标（仅在 macOS 上运行，产出 .app + .dmg；架构默认按机器自动检测）
python scripts/build.py --macos

# 指定 macOS 架构（arm64 / x86_64）
python scripts/build.py --macos --arch x86_64

# 仅打包，跳过安装包
python scripts/build.py --build-only

# 仅制作安装包（PyInstaller 已打包完时，仅 Windows）
python scripts/build.py --installer-only

# Linux 目标指定包类型：all | appimage | deb | rpm（默认 all）
python scripts/build.py --linux --installer-only --package deb
```

**Windows 安装包**: 需 [InnoSetup 6/7](https://jrsoftware.org/isdl.php)。

**Linux 包**: 支持 .deb / .rpm / AppImage，`--package` 指定包类型（`all` / `appimage` / `deb` / `rpm`，默认 `all`）。构建前需安装 GTK/WebKit 依赖（同上）。

**macOS 包**: `--macos` 产出 `.app`（PyInstaller `--windowed`，自动用 iconutil 从 `src/resources/icon.png` 生成 icns）与 `.dmg`（hdiutil 打包，含 /Applications 快捷方式）；文件名带架构后缀 `OhMyMeme-v{version}-{arch}.dmg`，`--arch` 指定 arm64/x86_64（默认自动检测）。

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

网格拖拽槽位回归探针位于 `tests/fixtures/grid_slot_probe.cjs`。

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
│  Vue 3      │     │   (localhost)    │
└──────┬──────┘     └──────────────────┘
       │ API 调用
┌──────▼──────┐     ┌──────────────────┐
│   SQLite    │     │   本地缓存目录    │
│  元数据      │     │  缩略图+原图     │
└─────────────┘     └──────────────────┘
```

主窗口前端基于 **Vue 3**（`src/vue-src/`，Vite 构建为 IIFE 单文件 `src/webui/dist/ohmymeme.js`），通过 `pywebview.api.*` 桥接调用后端 `JsApi`；设置窗口仍为 vanilla（`src/webui/settings.*`）。

## 实现要点

### 启动时序
启动分两阶段：首先 `get_init_data()` 秒开渲染数据库数据，随后执行 `rescan_cache()` → `run_auto_sync()` → `check_update()`。**动画开启时动画播放期间即并行加载**（动画天然覆盖桥接稳定时间，无 300ms 延时）；**动画关闭时降级 300ms 延时**（桥接稳定需要）。**先 rescan 再 sync**（文件与 DB 一致后再对比远端）。

### 缓存去重
扫描缓存目录时**双重去重**：按文件名查 DB 防止每次启动重复注册，按 SHA-256 哈希查 DB 防止同图不同名重复。导入（拖入/对话框）同样有哈希去重。

### GIF 剪贴板
Windows 上 GIF 复制同时写入三个剪贴板格式：`CF_DIB`（首帧 BMP）、`CF_HDROP`（文件路径，QQ/微信粘贴动图必需）、自定义 `"GIF"` 格式。**移除 CF_HDROP 会导致 QQ/微信粘贴 GIF 变静态图。**

### 复制处理模式
设置页「复制处理」下拉（配置 `copy_resize_mode`：0不处理；1webp缩放，默认；2转gif；3转gif隐写原图）：复制超过 `copy_resize_max`（默认 200px）的静态图时按模式处理，动图（GIF/动画 WebP）不受影响。仅模式 1 缩放原图（转 WebP 缩放到限制内，QQ/微信原生支持 WebP）；模式 2/3 按原分辨率转 GIF（模式 3 额外隐写原图，失败时原样复制原图）。处理结果写入系统临时目录 `ohmm_resize_<md5>_<max>_q<质量>_v<版本>.webp` / `ohmm_gif_<md5>_v<版本>.gif` / `ohmm_stego_<md5>_v1.gif` 并保留（CF_HDROP 需在粘贴时仍可读取）；缓存键含编码参数与版本号，改编码逻辑后旧缓存自动失效，命中时校验文件完整性，同一表情重复复制直接复用。

### 加密降级
加密优先使用 `cryptography.fernet.Fernet`，不可用时降级为 `hashlib.pbkdf2_hmac` + XOR + base64。**不能移除 XOR 降级**，否则无 `cryptography` 时系统崩溃。

### Sync 文件夹合并
`pull` 时远端文件夹以**并集**方式合并到本地已有文件夹（不清除本地归属）。远端清单仍使用兼容字段 `collections`，按文件名关联而非本地 ID，跨设备稳定；旧版嵌套清单会被扁平合并。

### Manifest 文件夹清单
构建 `meme-index.json` 时，兼容数据表 `collections` 会输出为单层文件夹清单。空文件夹也会保留，以便同步后仍能看到用户创建的文件夹。

### 拖拽排序反馈
`canReorderMemes()` 仅在未搜索、未按标签筛选、当前为 ID 大于 0 的文件夹且已开启拖拽排序时允许排序。此时表情卡最终为 `scale(0.95)`，带 3px `var(--border-light)` 描边和 3px 偏移，并以独立 `rotate` 属性作轻微快速晃动；正在拖拽、FLIP 让位和分页入场不晃动，系统减少动态效果偏好会禁用该动画。正在拖拽的卡独立使用最终 `translate(...) scale(0.90)`，保留现有透明度、阴影和 FLIP 效果，变换不得叠加。开启工具栏排序开关时沿用现有入场反馈；仅明确关闭该开关时保留当前卡片，以动画退场。搜索、标签筛选、切换文件夹或进入虚拟项导致的资格变化均按普通刷新处理，不播放退场动画。

## 技术栈

| 模块 | 技术 | 理由 |
|------|------|------|
| UI | PyWebView (v6) + Bottle + Vue 3 | 原生 WebView 渲染，Vue 3 组件化前端（Vite 构建） |
| 托盘 | pystray | 最轻跨平台托盘库 |
| 热键 | keyboard → pynput → 轮询回退 | 三级降级保障 |
| 图片 | Pillow | 业界标准 |
| 剪贴板 | ctypes (Win32 API) | 零外部依赖，GIF 动画原始字节 |
| 数据库 | SQLite3 (WAL) | 内置，线程安全 |
| 加密 | cryptography (Fernet) | 轻量对称加密 |
| 窗口 | frameless + JS 拖拽 | 自定义无边框体验 |

## 许可证

GPL-3.0
