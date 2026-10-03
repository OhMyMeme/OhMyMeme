# 贡献指南

面向开发者的环境搭建、代码规范、测试与构建说明。用户文档见 [README.md](README.md)，AI 编码助手的完整项目上下文见 [AGENTS.md](AGENTS.md)。

## 开发环境

**要求**: Python 3.10+（推荐 3.12）、Node.js（构建 Vue 前端）；Linux 额外需要 GTK/WebKit 依赖（见下）。

```bash
git clone https://github.com/OhMyMeme/OhMyMeme.git
cd ohmymeme
pip install -r requirements.txt
npm install
python -m src
```

- 主窗口前端为 **Vue 3**（`src/vue-src/`，Vite 构建 IIFE 单文件 → `src/webui/dist/ohmymeme.js`，产物被 gitignore）
- 源码运行时若前端产物缺失会自动执行一次 `npx vite build`；**修改前端后手动重新构建**：`npx vite build`
- 设置窗口为 vanilla 前端（`src/webui/settings.*`，独立 webview，无需构建）
- 旧主窗口（`src/webui/index.*`）已备份至 `src/webui-backup/`，不再使用

### Linux GTK 后端

pywebview 在 Linux 使用 GTK 后端（`WebKit2`）：

```bash
# Debian / Ubuntu
sudo apt install python3-gi
sudo apt install gir1.2-webkit2-4.1   # 或 4.0，按系统版本选择

# Arch Linux
sudo pacman -S python-gobject
yay -S webkit2gtk   # 依赖 libsoup，通过 yay 安装
```

让当前 Python 能导入 `gi`，三选一：

- venv 创建时加 `--system-site-packages`：`python -m venv --system-site-packages .venv`
- 运行前设置 `PYTHONPATH=/usr/lib/python3/dist-packages`（Arch 为 `/usr/lib/python3.12/site-packages`）
- conda 中 `conda install -c conda-forge pygobject`

### CLI 参数

| 参数 | 说明 |
|------|------|
| `--debug` | 输出所有 DEBUG 级别日志 |
| `--silent` | 启动时最小化到托盘（源码模式下需显式传入） |
| `--debug-update` | 强制弹出更新对话框（测试用） |
| `--debug-startup` | 输出开机自启检测详情（注册表键、启动文件夹） |
| `--debug-adb` | 输出 ADB 检测详情及运行时日志（路径、版本、adb 命令） |
| `--debug-env` | 输出环境检测详情（WebView2/.NET）并强制打开检测窗口 |

## 代码规范

- 无类型标注（`database.py`/`updater.py` 除外可使用 `typing` 基本类型）
- 无非必要注释；每段函数需有简单功能注释；无文档字符串（仅公开 API 可极简单行）
- 无 emoji（除非用户要求）
- 无冗余前缀/后缀说明（写完代码即结束，不加总结）
- 新增依赖同时更新 `requirements.txt` 和 `environment.yml`
- **仅做最小必要修改**，不改变现有架构、设计模式与代码组织；尽量不创建新文件
- 增改功能后同步更新 `README.md`、`AGENTS.md` 及 `.gitignore`、`Makefile`、`pyproject.toml` 等关联文件

### 格式 & Lint

```bash
black src/        # 格式化（black 26.5.1, line-length 88）
ruff check src/   # lint（select F, E, W, I）
```

**PR 必须确保 `black --check src/` 和 `ruff check src/` 全部通过**，CI 会检查这两项。

## 测试

```bash
python -m pytest tests/ -v
```

- `test_core.py` 等为 unittest 风格，`test_startup.py` 为全生命周期集成测试（mock WebUI）
- 网格拖拽槽位回归探针：`tests/fixtures/grid_slot_probe.cjs`（Node 脚本）
- 热键测试夹具下通过 `PYTEST_CURRENT_TEST` 环境变量禁用真实文件日志，避免污染 `hotkey.log`
- 微信 keyfinder 的 C++ 测试在 CI 独立 job 运行（`cmake -DWKF_BUILD_TESTS=ON` + ctest，Windows only）

## 前端

- JS 调用后端：`pywebview.api.method(...)` → 自动序列化；辅助函数 `async function api(method, ...args) { return await pywebview.api[method](...args); }`
- 返回类型 `str`/`int`/`bool`/`dict`/`list`，错误返回 `None` 或 `{"ok": false, "error": "..."}`
- 图片不走 JS API JSON：缩略图通过 `/api/thumb/{id}` HTTP 路由渲染
- XSS 防护：拼入 innerHTML 的外部/动态数据必须经 `esc()`/`renderMarkdown()` 转义（主窗口 `utils/api.ts`，设置窗口 `settings.js` 同理）
- 主窗口状态：`useMemes` composable 为唯一真源，拖拽等交互先改模型再挪 DOM

## 目录结构

```
src/
  main.py         # CLI 入口, OhMyMemeApp 编排
  webui.py        # pywebview 窗口 + JsApi/SettingsApi + Bottle 路由（最大文件）
  updater.py      # 版本检查 + 并发镜像下载
  database.py     # MemeDB (SQLite, 7 表)
  config.py       # Config (JSON + Fernet 加密密钥)
  sync.py         # 同步后端 (FTP/S3/R2/WebDAV)
  lan.py          # 局域网互联 (UDP 发现 + TCP 握手 + AES-GCM 会话)
  tray.py         # TrayManager (pystray, 惰性导入)
  hotkey.py       # GlobalHotkey (三级降级: keyboard→pynput→轮询 + 自愈)
  clipboard_util.py # 剪贴板操作 (Win32 ctypes / macOS / Linux)
  gif_stego.py    # GIF 增量隐写（粘贴表情大小 + 无损还原原图）
  native_drag.py  # Windows 原生文件拖拽 (WinForms DoDragDrop, 惰性加载 pythonnet)
  crypto_util.py  # 加密 (Fernet + PBKDF2, 降级 XOR)
  manifest.py     # meme-index.json 构建/加载
  plugin_manager.py # 插件系统（发现/校验/加载/权限门控/超时熔断）
  platform_util.py # 平台工具 (WSL检测, 开机自启, 单实例互斥)
  adb_util.py     # ADB 检测/下载 + QQ 表情包缓存导入
  qqnt_extract.py # QQNT 本地收藏表情提取（GPL-3.0 衍生模块）
  tg_stickers.py  # Telegram Desktop 缓存表情包提取
  douyin.py       # 抖音表情包下载导入（ABogus 签名 + curl_cffi TLS 指纹）
  abogus.py       # ABogus 签名算法（纯 Python，GPL-3.0）
  backup.py       # 本地备份（ZIP 导出/恢复，仅 PC 间整库迁移）
  wechat_probe.py # 微信收藏表情导入（helper 二进制 + AES-CBC 解密 + CDN 下载）
  wechat_keyfinder/ # 微信密钥提取 C++ 辅助二进制源码
  env_check.py    # 首次运行环境检测（WebView2/.NET + tkinter UI 子进程）
  vue-src/        # Vue 3 前端源码（Vite 构建 → webui/dist/ohmymeme.js）
  webui/          # 前端静态文件（vue.html 主窗口入口 + settings.* 设置窗口）
config/
  offsets.json    # wechat_keyfinder 易变参数（微信升级时只改此文件）
scripts/
  build.py        # PyInstaller + InnoSetup 构建脚本 (i18n zh/en)
  launcher.py     # PyInstaller 入口
  hooks/          # 自定义 PyInstaller hooks（Linux GTK typelib 收集）
tests/            # 单元/集成测试（见上）
```

## 构建

依赖 **PyInstaller 6.0+**。`build.py` 打包前会自动完成三件事，失败默认中止：

1. 编译 Vue 前端（产物缺失时 `npm ci` + `npx vite build`）
2. Windows：cmake+MSVC 编译 `wechat_keyfinder` C++ helper 并 SHA-256 注入（本地开发可 `--allow-missing-keyfinder` 放行）
3. Windows：内置裁剪版 ffmpeg（`scripts/ffmpeg/build_win64.sh` 交叉编译，本地可 `--allow-missing-ffmpeg` 放行，运行时回退系统 ffmpeg）

```bash
pip install pyinstaller

python scripts/build.py                  # 自动检测当前系统打包
python scripts/build.py --windows        # Windows（仅 Windows 上运行）
python scripts/build.py --linux          # Linux（仅 Linux 上运行）
python scripts/build.py --macos          # macOS（仅 macOS 上运行，.app + .dmg）
python scripts/build.py --macos --arch x86_64   # 指定 macOS 架构（默认自动检测）
python scripts/build.py --build-only     # 仅打包，跳过安装包
python scripts/build.py --installer-only # 仅制作安装包（Windows）
python scripts/build.py --linux --installer-only --package deb  # Linux 包类型 all|appimage|deb|rpm
```

- **PyInstaller 不支持交叉编译**，各平台需在对应系统上构建；跨平台构建用 GitHub Actions
- Windows 安装包需 [InnoSetup 6/7](https://jrsoftware.org/isdl.php)
- Linux 包支持 .deb / .rpm / .AppImage，构建机需装 GTK/WebKit 依赖（见 AGENTS.md「Linux 打包（GTK）」）
- 输出目录: `dist/`

## CI（GitHub Actions）

| Workflow | 触发 | 内容 |
|----------|------|------|
| `check.yml` | push/PR 到任意分支 | Ubuntu lint + test（含 `keyfinder-tests` C++ 测试 job，Windows） |
| `ffmpeg-win64.yml` | 被 build/nightly 以 `needs` 拉起 | 交叉编译裁剪版 ffmpeg，artifact 上传（按脚本内容哈希缓存） |
| `build.yml` | `check` 通过 main 后自动，或手动 | Windows 安装包（含 ffmpeg/helper 校验）+ Linux 三格式 + macOS 双架构 `.dmg` |
| `nightly.yml` | 每日 UTC 20:00 + 手动 | 从 `dev` 分支构建非正式版，发布为 `nightly` prerelease（软件更新不会指向 nightly） |

## 数据与配置路径

| 用途 | Windows | macOS | Linux |
|------|---------|-------|-------|
| 配置文件 | `%APPDATA%/OhMyMeme/config.json` | `~/Library/Application Support/OhMyMeme/config.json` | `~/.config/OhMyMeme/config.json` |
| 环境检测标记 | `%APPDATA%/OhMyMeme/env_check.json` | 同左 | 同左 |
| 插件设置 | `%APPDATA%/OhMyMeme/plugins/<id>/settings.json` | 同左 | 同左 |
| 数据库 | `%LOCALAPPDATA%/OhMyMeme/memes.db` | `~/Library/Caches/OhMyMeme/memes.db` | `~/.local/share/OhMyMeme/memes.db` |
| 缓存原图 | `%LOCALAPPDATA%/OhMyMeme/cache/` | 同左 | 同左 |
| 缩略图 | `%LOCALAPPDATA%/OhMyMeme/thumbnails/` | 同左 | 同左 |
| 同步清单 | `%LOCALAPPDATA%/OhMyMeme/meme-index.json` | 同左 | 同左 |
| 云端清单缓存 | `%LOCALAPPDATA%/OhMyMeme/cloud-index.json` | 同左 | 同左 |
| 热键事件日志 | `%LOCALAPPDATA%/OhMyMeme/hotkey.log` | 同左 | 同左 |
| 插件目录 | `%LOCALAPPDATA%/OhMyMeme/plugins/`（私有数据 `plugins_data/`，启停状态 `plugins_state.json`） | 同左 | 同左 |
| 备份目录 | `%LOCALAPPDATA%/OhMyMeme/backups/`（可配置） | 同左 | 同左 |

Linux 遵循 XDG：配置 `$XDG_CONFIG_HOME`、数据 `$XDG_DATA_HOME`（缺省 `~/.config` / `~/.local/share`）。

## PR 检查清单

```bash
ruff check src/       # lint
black --check src/    # 格式
python -m pytest tests/ -v   # 测试
```

- 新增依赖已同步 `requirements.txt` + `environment.yml`
- 新增功能/文件已同步 `README.md` 与 `AGENTS.md`
- 涉及前端改动已重新 `npx vite build`
