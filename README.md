# OhMyMeme

轻量化跨平台表情包管理系统 — 突破表情包上限，快捷键呼出、搜索即复制。

### **QQ交流群：891636253**

![picture](https://raw.githubusercontent.com/OhMyMeme/OhMyMeme/refs/heads/dev/resource/picture.gif)

## 功能

- **系统托盘运行** — 最小化资源占用，后台常驻
- **单实例运行** — 重复启动自动检测已有实例并退出，避免数据冲突
- **全局快捷键** — 默认 `Ctrl+Alt+N` 呼出/隐藏主面板；热键失效自动修复，无需重启软件
- **表情管理** — 导入 / 搜索 / 标签 / 收藏 / 多级分组（最多 3 层）
- **悬停放大预览** — 鼠标悬停 0.5s 浮出完整原图，设置页可关闭
- **一键复制** — 点击表情包自动复制到剪贴板（GIF 保留动画）；快捷键呼出后复制成功自动隐藏
- **批量操作** — 多选模式下批量加组 / 移动 / 打标签 / 删除
- **原生文件拖拽** — 关闭拖拽排序后，表情可直接拖到 QQ/微信等外部应用
- **复制处理** — 超限静态图按四种模式处理（不处理 / WebP 缩放 / 转 GIF / 转 GIF 隐写原图可无损还原）；可避免输出 WebP 以兼容微信等应用
- **多种导入** — 窗口拖放、文件夹导入（可自动建同名分组）
- **右键菜单** — 重命名 / 收藏 / 打标签 / 添加分组 / 删除；卡片悬停快捷收藏
- **标签** — 多标签交集筛选，搜索同时匹配文件名与标签名
- **GIF 动图** — 网格内自动播放，设置中可关闭
- **分组筛选** — 收藏夹/自定义分组，可与标签、搜索叠加；「未分类」分组自动汇总未分组表情
- **侧边栏滑动手势** — 左缘右滑展开、侧栏内左滑折叠
- **本地缓存** — 缩略图+原图双层缓存，离线可用；启动自动扫描去重
- **导入限制** — 超过 2K 分辨率或 20MB 的表情拒绝导入
- **自定义存储位置** — 可更换图片存放目录，切换时自动迁移现有文件
- **本地备份与恢复** — 一键导出全量备份 ZIP，新设备一键恢复
- **远程同步** — FTP / S3 / R2 / WebDAV 多端同步，实时进度与速度
- **云端直接使用** — 本地未下载的云端表情带云角标显示，点击即下载并使用（默认开启）
- **局域网互联** — 与同局域网的手机版配对，互相同步表情包与配置
- **多源导入** — 手机 QQ 表情（ADB 拉取）、电脑版 QQ（QQNT）收藏、Telegram、微信电脑版收藏、抖音自定义表情
- **插件系统** — 第三方插件扩展主窗口与设置页，可单独启用/停用
- **无边框窗口** — 自定义标题栏，可选允许拖边框调整窗口大小
- **自动更新** — 启动时与每日自动检测新版本，一键升级

## 快速开始

### 下载

从 [Releases](https://github.com/OhMyMeme/OhMyMeme/releases/latest) 下载对应系统的安装包或可执行文件，直接运行。

### 从源码运行

**环境要求**: Python 3.10+

```bash
git clone https://github.com/OhMyMeme/OhMyMeme.git
cd ohmymeme
pip install -r requirements.txt
python -m src
```

- 主窗口前端为 Vue 3，源码运行时若构建产物缺失会自动执行一次 `npx vite build`
- Linux 额外需要 GTK/WebKit 依赖（`python3-gi` + `gir1.2-webkit2-*`），详见 [CONTRIBUTING.md](CONTRIBUTING.md)

或使用 conda：

```bash
conda create -n ohmymeme python=3.12
conda activate ohmymeme
pip install -r requirements.txt
python -m src
```

## 使用

### 基本操作

1. **启动** — 运行后系统托盘出现蓝色图标，按 `Ctrl+Alt+N` 呼出主面板
2. **导入** — 点击标题栏「导入」按钮，或直接拖拽图片到窗口（支持 png/jpg/gif/webp）
3. **复制** — 点击任意表情包自动复制到剪贴板（GIF 保留动画）
4. **搜索** — 搜索框输入关键词实时筛选（同时匹配文件名与标签名）；点击标签或分组叠加过滤
5. **右键菜单** — 重命名 / 收藏 / 打标签 / 添加分组 / 删除

### 收藏与分组

- 右键 →「收藏」将表情加入收藏夹，点击左上角⭐按钮筛选收藏内容
- 右键 →「添加到分组」创建或选择已有分组；分组显示在搜索栏下方，点击即筛选
- 右键分组可新建小分组（最多 3 层）、重命名或删除

### 设置

点击标题栏⚙按钮打开设置页，主要选项：

| 选项 | 说明 |
|------|------|
| **快捷键** | 自定义全局热键，格式如 `Ctrl+Shift+M` |
| **热键在鼠标处显示** | 默认关闭，仅 Windows；热键呼出隐藏面板时放在鼠标所在显示器 |
| **开机自启** | 系统登录时自动启动，可选静默启动（仅托盘） |
| **允许调整窗口大小** | 默认关闭；开启后拖动边框调整窗口大小，尺寸自动记忆 |
| **GIF 动画** | 关闭后网格中仅显示 GIF 首帧 |
| **复制处理** | 复制超限静态图的处理模式（不处理 / WebP 缩放 / 转 GIF / 转 GIF 隐写原图） |
| **复制时避免 WebP** | 默认关闭；开启后复制产物不含 WebP，兼容微信等把 WebP 当文件的应用 |
| **同步进度/提示** | 上传/下载进度条与完成提示，可分别开关 |
| **导入** | 从手机（ADB）/ 从电脑（QQNT）/ Telegram / 抖音 / 微信 |
| **局域网互联** | 设置端口与连接密钥，开启后同局域网手机版可发现本机 |
| **远程同步** | 配置 FTP / S3 / R2 / WebDAV 同步 |
| **云端同步** | 云端直接使用、标签/收藏写入清单、缺失缩略图自动补传等开关 |
| **备份与恢复** | 备份目录、创建备份、备份列表管理、从 ZIP 恢复 |
| **插件** | 查看已安装插件、修改插件设置、启用/停用 |
| **危险操作** | 一键清空本地/云端全部表情包（需双重确认） |
| **关于** | 版本号与检查更新、GitHub 地址、QQ 群入口、贡献者名单 |

### 插件

把插件文件夹放入插件目录（设置页「打开插件目录」直达），目录内含 `plugin.json`，重启软件后加载。开发期可把插件路径加入 `config.json` 的 `plugin_dirs` 数组直连，免复制。

- 插件开发：见[插件模板仓库](https://github.com/OhMyMeme/omm-plugin-template)
- 官方[个性化插件](https://github.com/OhMyMeme/omm-personalized-plugin)可自定义启动动画、背景、字体与顶栏按钮布局

### 远程同步

支持 FTP / S3 / R2 / WebDAV 四种后端同步多台设备的表情包库。配置完成后点击「测试连接」验证，然后使用标题栏的⬆上传 / ⬇下载按钮同步。

> ⚠️ 若设置中开启了「同步时删除远程文件」，上传操作会删除远程端已不存在的文件。

**云端直接使用**（默认开启）：本地未下载的云端表情与本地表情穿插显示在网格中（左下角云角标），点击云卡片即下载、校验并自动复制使用。

### 局域网互联

与同一局域网内的手机版 OhMyMeme 配对，无需公网即可互相同步表情包与配置：

1. **配置** — 设置页「局域网互联」设置端口（默认 17852）与连接密钥
2. **开启** — 勾选「开启互联访问」临时启动服务（重启后默认关闭）
3. **连接** — 手机版扫描发现本机并输入密钥配对，电脑端确认设备信息后开始同步

> ⚠️ 服务可被同一局域网内所有设备探测到，仅在你信任的 Wi-Fi 下开启。

### 路径说明

| 用途 | Windows | 其他平台 |
|------|---------|----------|
| 配置文件 | `%APPDATA%/OhMyMeme/config.json` | `~/.config/OhMyMeme/config.json` |
| 数据库 | `%LOCALAPPDATA%/OhMyMeme/memes.db` | `~/.local/share/OhMyMeme/memes.db` |
| 缓存原图 | `%LOCALAPPDATA%/OhMyMeme/cache/` | `~/.local/share/OhMyMeme/cache/` |
| 缩略图 | `%LOCALAPPDATA%/OhMyMeme/thumbnails/` | `~/.local/share/OhMyMeme/thumbnails/` |
| 同步清单 | `%LOCALAPPDATA%/OhMyMeme/meme-index.json` | `~/.local/share/OhMyMeme/meme-index.json` |
| 插件目录 | `%LOCALAPPDATA%/OhMyMeme/plugins/` | `~/.local/share/OhMyMeme/plugins/` |

macOS 对应 `~/Library/Application Support/OhMyMeme/`（配置）与 `~/Library/Caches/OhMyMeme/`（数据）。

## 构建

```bash
pip install pyinstaller
python scripts/build.py   # 自动检测当前系统打包
```

> **⚠️ 注意**: PyInstaller **不支持交叉编译**，Windows/Linux/macOS 各平台需在自己的系统上构建。
> 其他参数（`--windows`/`--linux`/`--macos`/`--package` 等）与打包细节见 [CONTRIBUTING.md](CONTRIBUTING.md)。
> 也可使用 [GitHub Actions](https://github.com/OhMyMeme/OhMyMeme/actions)（推送 `main` 自动触发，或手动运行 workflow）。

## PR 贡献

欢迎提交 Pull Request。提交前请确保通过以下检查：

```bash
ruff check src/       # lint 检查
black --check src/    # 格式检查
python -m pytest tests/ -v   # 测试
```

CI 会自动运行 lint+test，更多贡献指引见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 贡献者

[![Contributors](https://contributor.starsfire.top/OhMyMeme/OhMyMeme/)](https://github.com/OhMyMeme/OhMyMeme/graphs/contributors)

## AI 辅助开发

本项目包含 `AGENTS.md` 文件，供 AI 编码助手读取以了解项目结构、代码规范和关键实现细节。若通过 AI 修改代码，请确保 AI 读取该文件后再进行操作。

## Star History

<a href="https://www.star-history.com/?repos=ohmymeme%2Fohmymeme&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=ohmymeme/ohmymeme&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=ohmymeme/ohmymeme&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=ohmymeme/ohmymeme&type=date&legend=top-left" />
 </picture>
</a>

## 许可证

GPL-3.0
