# OhMyMeme — AI Agent Guide

## 项目概述
轻量化跨平台表情包管理系统，突破表情包数量限制，支持全局快捷键呼出、搜索复制、FTP/S3/R2 同步、局域网互联。

## 架构
```
系统托盘 (pystray) ↔ 全局快捷键 (keyboard/pynput/轮询)
        ↓ show/hide
WebView 窗口 (pywebview) → Bottle HTTP 服务器 (localhost)
        ↓ JS API 桥 (pywebview.api.method)
JsApi / SettingsApi → SQLite (WAL) + 本地缓存 + 远端同步
```

## 技术栈
- **Python 3.12** + **pywebview** (frameless 窗口) + **Bottle** (静态文件/缩略图路由)
- **SQLite** (WAL, `threading.local()` 连接, `threading.Lock()` 写锁)
- **PIL/Pillow** (缩略图, 剪贴板图像)
- **pystray** (托盘, 惰性导入避免 headless CI 崩溃)
- **InnoSetup** (Windows 安装包) / **PyInstaller** (打包)
- **GitHub Actions** (lint+test on Ubuntu, build+installer on Windows)

## 核心原则
- **不得重构该项目** — 仅做最小必要修改，不改变现有架构、设计模式、代码组织
- **尽量不创建新文件** — 优先修改现有文件
- **增改同步** — 增加新功能或创建新文件后，同步修改 `README.md` 和 `AGENTS.md` 中对应描述
- **关联文件同步** — 修改后检查是否需要同步更新 `.gitignore`、`Makefile`、`pyproject.toml`、`requirements.txt`、`environment.yml` 等关联文件

## 代码规范
- 无类型标注（`database.py`/`updater.py` 除外可使用 `typing` 基本类型）
- 无非必要注释（除非用户明确要求）
- 每段函数需要有简单功能注释
- 无 emoji（除非用户要求）
- 无文档字符串（只对公开 API 使用极简单行 docstring）
- 无冗余前缀/后缀说明（写完代码即结束，不加总结）

## 格式 & Lint
- `black src/` (line-length 88,  black 26.5.1)
- `ruff check src/` (select F, E, W, I)
- 新增依赖同时更新 `requirements.txt` 和 `environment.yml`
- **PR 贡献必须确保 `black --check src/` 和 `ruff check src/` 全部通过**，CI 会检查这两项

## 关键目录
```
src/              # 主代码
  main.py         # CLI 入口, OhMyMemeApp 编排
  webui.py        # pywebview 窗口 + JsApi/SettingsApi + Bottle 路由
  updater.py      # 版本检查 + 并发镜像下载
  database.py     # MemeDB (SQLite, 6 表)
  config.py       # Config (JSON + Fernet 加密密钥)
  sync.py         # 同步后端 (FTP/S3/R2/WebDAV)
  lan.py          # 局域网互联 (UDP 发现 + TCP 握手 + AES-GCM 会话)
  tray.py         # TrayManager (pystray, 惰性导入)
  hotkey.py       # GlobalHotkey (三级降级: keyboard→pynput→轮询)
  clipboard_util.py # 剪贴板操作 (Win32 ctypes / macOS osascript / Linux xclip)
  gif_stego.py     # GIF 增量隐写（实验性：粘贴表情大小 + 无损还原原图）
  native_drag.py   # Windows 原生文件拖拽 (WinForms DoDragDrop + CF_HDROP, 惰性加载 pythonnet)
  crypto_util.py  # 加密 (Fernet + PBKDF2, 降级 XOR)
  manifest.py     # meme-index.json 构建/加载
  platform_util.py # 平台工具 (WSL检测, 开机自启)
  adb_util.py      # ADB 自动检测/下载 + QQ 表情包缓存导入（ADB 拉取 + 魔数识别扩展名 + ZIP 打包）
  qqnt_extract.py  # QQNT 本地收藏表情提取（GPL-3.0 衍生模块，纯函数 + 回调接口，无 UI 依赖）
  tg_stickers.py   # Telegram Desktop 缓存表情包提取（tdata 解密 + webm 转 webp + 入库）
  wechat_probe.py  # 微信收藏表情导入（helper 二进制提取密钥 + AES-CBC 解密 DB + CDN 下载，仅 Windows）
  wechat_keyfinder/ # 微信密钥提取 C++ 辅助二进制源码（CMake 构建）
  config/
    offsets.json  # wechat_keyfinder 易变参数（RVA 偏移/版本号等，微信更新时只改此文件）
  webui/          # 前端静态文件（HTML 与 CSS/JS 分离，经典脚本供内联 onclick 调用全局函数）
    index.html    # 主窗口 HTML 骨架，引用 index.css + index.js
    index.css     # 主窗口样式
    index.js      # 主窗口逻辑（渲染/搜索/拖拽排序/同步/导入/更新）
    settings.html # 设置窗口 HTML 骨架，引用 settings.css + settings.js
    settings.css  # 设置窗口样式
    settings.js   # 设置窗口逻辑（设置项/同步/QQ 导入向导）
scripts/
  build.py        # PyInstaller + InnoSetup 构建脚本 (i18n zh/en)
  launcher.py     # PyInstaller 入口
tests/
  test_core.py    # unittest 风格: Version/Config/Crypto/Database
  test_startup.py # pytest 风格: 全生命周期集成测试
```

## js_api 桥接规范
- `JsApi` 暴露给主窗口，`SettingsApi` 暴露给设置窗口
- JS 调用: `pywebview.api.methodName(...args)` → 自动序列化
- JS 辅助函数: `async function api(method, ...args) { return await pywebview.api[method](...args); }`
- 返回类型: `str` / `int` / `bool` / `dict` / `list`，错误返回 `None` 或 `{"ok": false, "error": "..."}`
- 图片传输: 缩略图通过 `/api/thumb/{id}` HTTP 路径渲染，不通过 JS API JSON

## 关键实现细节

### 系统托盘
- `TrayManager` 在 daemon 线程运行
- 惰性导入: `_pystray_ok()` 避免 headless CI (X11 `DisplayNameError`)
- WSL 自动跳过托盘

### 全局快捷键
- 三级降级: `keyboard` → `pynput` → 200ms 轮询 (`keyboard.is_pressed`)
- WSL 无法捕获全局快捷键

### 窗口
- 主窗口 ~700×500 frameless, 设置窗口 460×560 frameless
- 自定义 JS 拖拽: 鼠标事件 → `pywebview.api.move_window(dx, dy)`
- 增量回退（Windows/macOS）用 `screenX/screenY`（**勿改 `clientX/clientY`** — clientX 是相对窗口坐标，窗口自身滞后位移会被下一次 mousemove 当作反向增量回传，形成反馈振荡导致高频抖动）；Linux 走合成器原生拖动不经过此路径
- **Linux 拖拽必须走合成器**：`w.move()` 在 Wayland 下无效（合成器不允许客户端自定位），mousedown 时 JS 调 `start_window_drag()` → 后端 `GLib.idle_add(native.begin_move_drag, ...)` 交给合成器交互式拖动；时间戳用 `Gdk.CURRENT_TIME`（GDK 文档允许未知时间时用它，X11 回填最近输入事件时间、Wayland 不参与）
- `#titlebar` 上可拖拽 (排除 `.title-btn` 按钮区域)

### 数据库
- 7 表: `memes`, `tags`, `meme_tags`, `collections`, `meme_collections`, `favorites`, `recent_uses`
  - `tags`/`meme_tags`：DB 层方法（`get_all_tags`/`set_meme_tags`/`get_meme_tags`/`search` 标签筛选），已启用；右键表情「打标签」（`JsApi.get_meme_tags`/`set_meme_tags`）逗号分隔多标签，`_set_tags` 覆盖式写入；`_prune_orphan_tags` 在 `_set_tags` 与 `delete_meme` 中清理无任何表情使用的孤儿标签（tagbar 不残留幽灵标签）
- `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`
- `MemeDB.search()`: 动态 WHERE, 多标签交集用 `HAVING COUNT = len(tags)`
- `memes.sort_order`: 自定义排序（拖拽更新），默认 0，查询 `ORDER BY sort_order ASC, updated_at DESC`
- `collections.parent_id`: 多级分组支持（最多 3 层），`NULL` 为顶层分组
- `meme_collections.sort_order`: 分组内成员自定义排序
- `recent_uses`: `meme_id` + `used_at`，复制时 `INSERT OR REPLACE`，按 `used_at DESC` 取最近使用

### 配置
- `%APPDATA%/OhMyMeme/config.json` (Win), JSON 格式
- 密钥字段 (ftp_password, s3_secret_key 等) 用 Fernet 加密存储
- 全局单例: `get_config()`, `get_db()`
- `cache_dir`（表情包图片目录）可自定义：配置键 `cache_dir` 非空时 `Config.cache_dir` 返回该路径，否则默认 `data_dir/cache`；设置页「存储位置」通过 `SettingsApi.pick_storage_dir`/`apply_storage_dir` 切换，`apply_storage_dir` 可选把旧目录文件递归迁移（`os.walk`+`shutil.move`，两阶段：先预检目标同名冲突整体中止、移动中出错回滚，跳过 `thumbnails`）；**切换后旧文件不再可见**，故未迁移时必须确保文件已存在于新目录；`_storage_dir_validation` 拒绝相对/相同/上下级目录以及 `data_dir`/`thumbnail_dir` 及其上下级（受保护路径）；DB/缩略图/manifest 仍留在 `data_dir`，数据库只存文件名，文件在新目录时按 basename 自动解析；`reset_settings` 恢复默认时保留 `cache_dir`

### 同步
- manifest 文件: `meme-index.json`
- SHA-256 差异对比, `push(delete_remote)`/`pull(remove_local)`
- 远端路径: `{root}/memes/`, `{root}/meme-index.json`
- 同步进度: `_sync_state` 全局变量追踪进度，`get_sync_progress()` 供 JS 轮询
- `push()`/`pull()` 内循环中更新 files_done/bytes_done/current_file 等字段
- 前端 300ms 轮询 `get_sync_progress()` 显示进度条 + 实时速度
- 设置页 4 个开关控制进度/完成弹窗是否显示
- **多线程传输**: `push()`/`pull()` 使用 `ThreadPoolExecutor`，每个线程创建独立后端连接
- 并发数: 配置项 `sync_threads`（默认 3，范围 1-8），通过 `config.json` 或 `SettingsApi` 修改
- `_push_worker`/`_pull_worker`: 接收文件子列表，操作独立后端连接，原子递增 `_sync_state`
- `_sync_lock` (`threading.Lock`) 保护 `_sync_state` 写操作；`_increment_sync_progress()` 提供原子递增
- `_chunk_list(lst, n)` 将文件列表均匀切分给各线程
- **push 动态 manifest 维护**: `push()` 上传过程中每 `_HEARTBEAT_INTERVAL`（5s）用「远端已有 + 本次已确认上传」快照增量更新远端 manifest（`_build_push_manifest` + `_upload_manifest_data`，失败仅告警不中断）；部分失败中断前也上传该快照（避免远端有文件却无有效 manifest）；成功路径在合并远端独有项后补入已上传但不在本地清单的项（去重 guard），保本地被清空等边角。manifest 只列确认上传成功的文件，不产生幻影条目
- **孤儿清理互斥与进度**: `cleanup_remote_orphans(delete=True)` 删除前非阻塞获取 `_sync_run_lock`（被 push/pull 占用时返回「同步正在进行中」，绝不并发删除）；删除循环复用 `_sync_state`（`direction="delete"`，更新 current_file/files_done/files_total/progress，状态 deleting→done），前端复用 `#sync-progress-overlay` 轮询展示；扫描（delete=False）不互斥
- **远端文件名校验**: `_safe_remote_fname()` 拒绝路径穿越/绝对路径/隐藏名；`_fetch_remote_memes` 解析远端 manifest 时过滤不安全文件名（含非 dict 条目），`_pull_worker` 下载前二次校验

### 更新
- GitHub API 查询: `/releases/latest` → `/releases?per_page=5` 回退
- 镜像并发: `_urlopen_mirror` / `_urlretrieve_mirror` 用 `ThreadPoolExecutor` + `as_completed`
- 镜像列表: `github.dpik.top` → `gh.dpik.top` → `gh-proxy.org` → 自建镜像（仅用于版本查询）→ 直连 GitHub
- 下载进度: `start_download()` → 后台线程 → JS 每 500ms 轮询 `get_download_progress()`
- Linux 更新: `_pick_asset_url` 选取 `.AppImage` 资产；`run_installer` Linux 分支 chmod +x 后直接 `Popen`（AppImage 是 ELF 非 shell 脚本），无 `/dev/fuse` 时追加 `--appimage-extract-and-run` 回退（`_needs_appimage_fallback`）；下载默认文件名走 `_default_asset_name()`（Linux 为 `OhMyMeme-v{version}-x86_64.AppImage`）

### 局域网互联 (lan.py)
- **入口**: `lan.start(port, secret)` / `lan.stop()`，`get_status()` 供设置页轮询；`set_allow_secret_config()` 控制是否允许密钥传输（仅内存生效），`set_confirm_callback()` 注入设备确认回调（WebUI 提供）
- **UDP 发现**: 绑定 `0.0.0.0:port`，收到 `{"t":"discover"}` → 单播回 `{"t":"hello","name","os","ver","need_secret"}`（**不含任何密钥信息**）
- **TCP 握手（明文帧）**: `[4B 长度][JSON]`；服务端发 `challenge{nonce}` → 客户端回 `proof{HMAC-SHA256(secret, nonce)}` → 验 `ok`/`no`（3 次错误断开）；无密钥时直接放行
- **数据帧（加密）**: `[4B 长度][12B IV][AES-GCM 密文+16B tag]`；密钥由 PBKDF2(secret, 100000) 派生；JSON 载荷，命令由手机（客户端）发起
- **设备确认（连接前置）**: 客户端握手后发 `device_info` 帧（`{name,model,os,ver}`，手机 Build.MODEL/MANUFACTURER/versionName）；桌面端 `_cmd_device_info` 弹窗展示设备信息，用户允许/拒绝后回 `{ok, approved, allow_secret_config}`；**未确认期间其他命令挂起**（`confirmed` Event，等待超时 60s 后拒），无确认回调（测试/无 UI）默认放行；`confirm_device()` 由 JS 回传批准结果（`pending_confirm` 记录 + `threading.Event`）；WebUI 主窗口 `showLanDeviceConfirm()` 弹窗 → `JsApi.lan_confirm_device` 回传
- **命令**: `pull_manifest` / `push_manifest`（复用 sync 的 `_apply_remote_order`/`_apply_remote_collections`）/ `pull_file` / `push_file`（base64 传输）/ `get_config` / `send_config` / `device_info` / `ping`
- **配置同步（双向，电脑为权威源）**: `get_config` 由手机拉取、`send_config` 由手机推送；两端均剔除 `_SECRET_KEYS`（FTP/S3/R2/WebDAV 密码等）；设置页「允许密钥传输」开关（`lan_set_allow_secret_config`，仅内存生效）开启后配置同步才包含密钥字段，开启前弹窗警示「请勿在公共网络或不信任的网络进行此操作！」；`device_info` 确认响应携带 `allow_secret_config` bool，手机端据此动态显示密钥拉取/推送按钮
- **文件安全（与手机端对称）**: `_safe_fname` 拒绝路径穿越/绝对路径；`push_file` 四重校验：文件名安全 → 字节 ≤`MAX_FILE_SIZE`（64MB）→ 可选 `sha256` 与本地计算一致 → `_import_bytes` 先解码校验宽高>0 合法才写盘；**不合法字节绝不落盘**（杜绝孤儿缓存文件）；合法图片按 SHA-256 去重后存 `cache_dir/{hash[:16]}{ext}` 并入库
- **生命周期**: 设置页开关临时启动（重启默认关，不写入 config）；`lan_port`/`lan_secret` 持久化（`lan_secret` 加密存储）；`main.py` `shutdown()` 兜底 `lan.stop()`

### 本地 HTTP 安全加固
- Bottle 只绑 `127.0.0.1` 随机端口；`before_request` 校验 `Host` 必须为本机回环（`_host_allowed`），POST 额外校验 `Origin` 同源且 `Sec-Fetch-Site` 非 `cross-site`，拒绝则 403（阻断 DNS rebinding / 跨站注入）
- `after_request` 统一加 `X-Content-Type-Options: nosniff` / `Referrer-Policy: no-referrer` / `X-Frame-Options: DENY`，`/api/` 路由 `Cache-Control: no-store`
- 文件名安全：`_safe_serve_filename`（webui）与 `_safe_remote_fname`（sync）拒绝含 `/` `\`、以 `.` `/` `\` `~` `..` 开头的名字；`_find_meme_file` 入口校验，远端 manifest 文件名在 `_fetch_remote_memes` 过滤 + `_pull_worker` 写盘前再防御
- 前端 XSS：`index.js`/`settings.js` 的 `esc()` 转义所有拼入 innerHTML 的外部/动态数据（远端分组名、GitHub 版本号、QQ 昵称、输出目录、弹窗标题/正文等）

### 环境检测
- WSL 检测: `/proc/version` 包含 "microsoft"
- WSL 时设置 `MESA_LOADER_DRIVER_OVERRIDE=llvmpipe`, `LIBGL_ALWAYS_SOFTWARE=1` 等软渲染环境变量

### 启动流程 (关键时序)
- `index.html` `DOMContentLoaded` 分两阶段执行:
  1. 立即: `get_init_data()` 加载数据库数据 → 渲染网格/标签/分组（秒开）
  2. 延迟 300ms 后: `rescan_cache()` → 重新渲染 → `run_auto_sync()` → 重新渲染 → `check_update()`（静默捕获异常）
- **300ms 延时不可移除** — 给 Bottle + pywebview 桥接稳定时间
- **必须先 rescan_cache 再 run_auto_sync** — 确保本地文件与 DB 一致后再对比远端，否则同步产生错误 diff
- **check_update 必须静默** — GitHub API 失败不阻塞启动

### 缓存扫描 (rescan_cache)
- 遍历 `cache_dir`，对每个非 `thumbnails/` 子目录的图片文件:
  1. 按文件名查 DB (`get_by_filename`) 跳过已存在
  2. SHA-256 哈希（64KB 分块）
  3. 按哈希查 DB (`get_by_hash`) 跳过重复内容
- **双重去重** — 文件名去重防止每次启动重复注册，哈希去重防止同图不同名重复
- `_do_import`（拖入/导入对话框）同样有哈希去重，且文件重命名为 `{hash[:16]}{ext}`
- **导入限制**：`config.py` 常量 `_IMPORT_MAX_PX=2560`（最长边）/`_IMPORT_MAX_BYTES=20MiB`，超过即拒绝接收；覆盖 `_do_import`、`scan_cache`、同步 `_pull_worker`、LAN `_import_bytes` 四类接收路径，跳过超限文件并计数（前端 toast 提示）
- **文件夹导入** (`JsApi.import_folder`)：FOLDER 对话框 → `os.walk` 递归收集图片（扩展名过滤）→ 复用 `_do_import`；`make_collection`（前端导入菜单「自动创建分组」勾选，默认开）时以文件夹名 `create_collection` + 批量 `add_to_collection`（同名分组复用，重复导入并入），导入菜单入口 `importFolder()` 复用 `pending` 并发锁

### 剪贴板 (GIF/WebP 直接传送)
- `_copy_gif_windows` 同时写入三个剪贴板格式:
  - **CF_DIB** — BMP 首帧（去掉 14 字节 BMP 头），旧应用兼容
  - **CF_HDROP** — `DROPFILES` 结构体 + 文件 UTF-16 路径，QQ/微信需要此格式才能粘贴动图
  - **自定义 "GIF"** — 原始 GIF 字节，注册 `RegisterClipboardFormatW("GIF")`
- `_copy_webp_windows` 直接传送 WebP 原文件（不再转 GIF）:
  - **CF_HDROP** — 指向 `.webp` 文件路径，QQ/微信原生解码 WebP（含动画+透明）
  - **自定义 "WebP"** — 原始 WebP 字节，注册 `RegisterClipboardFormatW("WebP")`
  - **CF_DIB** — 首帧 BMP 静态回退
- `_copy_png_windows` — 带透明的 PNG 走此路径保留 alpha（CF_HDROP 指向 `.png` 文件 + 自定义 `"PNG"` 格式 + CF_DIB 回退）；不透明 PNG/JPG 仍走 CF_DIB（BMP）路径
- **移除 CF_HDROP 会导致 QQ/微信粘贴 GIF 变静态图**
- **复制处理模式** — config `copy_resize_mode`（0不处理；1webp缩放，默认；2转gif；3转gif隐写原图），仅设置页「复制处理」下拉选择（无主窗口开关）。复制超过 `copy_resize_max`（默认 200px）的静态图时按模式处理（动图 GIF/动画 WebP 不受影响）：`convert_image_mode_1` → `_resize_static_to_webp` 转 WebP 并**缩放到限制内**（唯一缩放原图的模式）；`convert_image_mode_2` → `_static_to_gif` 按**原分辨率**转普通 GIF（不隐写、不缩放）；`convert_image_mode_3` → `_make_stego_gif` 按原分辨率转隐写 GIF（失败原样复制原图，不回退缩放）。处理结果存系统临时目录（**不删除**，CF_HDROP 需在 QQ 粘贴时仍可读取）：`ohmm_resize_<md5>_<max>_q<质量>_v<版本>.webp` / `ohmm_gif_<md5>_v<版本>.gif` / `ohmm_stego_<md5>_v1.gif`；缓存键含编码参数与版本号，改编码逻辑后旧缓存自动失效，命中时校验完整性，同一表情重复复制复用。旧配置迁移：`experimental_stego=true` → mode 3，`copy_resize_enabled=false` → mode 0（仅当旧配置无 `copy_resize_mode` 键时）
- **GIF 隐写（复制模式 3 + 导入自动解码）** — ①复制输出：`copy_resize_mode=3` 时 `_make_stego_gif` **懒加载** `gif_stego.make_stego_gif` 生成携带无损原图的隐写 GIF（与原图同分辨率）再复制，失败原样复制原图；缓存 `ohmm_stego_<md5>_v1.gif`（不删除，CF_HDROP 需存在）。②导入含 `STG3` 的 GIF 时**无论模式与否**都会自动解码，且**只入库还原的原图**（`_try_decode_stego` 解码到临时文件 → 原图正常入库，`from_stego=1`，载体 GIF 不入库、不进缓存目录）。③隐写缓存：复制原图时通过临时缓存 `ohmm_stego_<md5>_v1.gif` 复用（命中即校验，不再重新编码）；`memes.stego_of_hash` 字段与 `get_by_stego_of` 保留用于兼容旧库中已入库的载体行。④前端展示：隐写载体在查询层隐藏（`search`/`count`/`get_recent` 统一加 `stego_of_hash IS NULL` 过滤，仅对旧库残留载体行生效），网格只显示还原后的原图；原图行 `from_stego=1`（`memes.from_stego` 列），卡片正常渲染图像并叠加琥珀色「隐写导入」徽标。⑤本地生成（复制路径）的隐写文件不写入 DB/不同步。`src/gif_stego.py` 支持 `encode`/`decode`/`make_stego_gif`/CLI，`quiet=True` 供应用调用

### 加密降级 (crypto_util)
- 优先 `cryptography.fernet.Fernet` (AES-128-CBC + HMAC)
- 降级: `hashlib.pbkdf2_hmac` 派生密钥 + XOR + base64（防意外泄露，不防专业破解）
- **不能移除 XOR 降级** — 无 `cryptography` 时系统崩溃

### Sync pull 集合合并
- `_apply_remote_collections` 以**并集**方式合并远端分组，不清除本地已有成员
- 远端 manifest 中的 `collections` 用文件名关联（非 ID），跨设备稳定
- `_apply_remote_order` 按远端 manifest 的 `memes` 顺序重排本地 `sort_order`（`reorder_memes`），确保 pull 后本地显示顺序与云端一致，再次 push 不致覆盖云端排序

### 排序同步闭环
- 拖拽排序：`reorder_memes`/`reorder_collections`/`reorder_collection_members` 更新 DB 后即调 `build_manifest()`，本地 `meme-index.json` 保持最新
- push：末尾 `build_manifest()` 按 DB 当前 `sort_order` 重建并上传，云端 manifest 顺序反映本地排序
- pull：`_apply_remote_order` 按云端 manifest 顺序回写本地 `sort_order`，实现双向闭环

### Manifest
- `build()` 递归遍历嵌套分组树，空分组自动 `delete_collection`
- 远端 manifest 中的 `collections` 以嵌套格式存储（`name`/`filenames`/`children`），version 2 旧格式启动时自动转换

### 自定义排序
- `memes.sort_order` 字段存储全局拖拽排序结果（全部视图）；分组/子分组内排序存 `meme_collections.sort_order`
- **模型驱动**：`memes` 数组为唯一真源，拖拽跨槽时先 `moveInArray` 同步模型、再挪 DOM 节点（不再以 DOM 顺序回读重建数组）；`initDragReorder()` 在 `#meme-grid` 上绑定一次
- **Pointer Events + 指针捕获**：`pointerdown/pointermove/pointerup`，拖拽激活（位移 >8px）时才 `setPointerCapture`（避免普通点击被捕获重定向）；无 `PointerEvent` 的旧 WebView 自动回退 mouse 事件（`mousemove/mouseup` 挂 document）；`pointercancel`/`blur` 取消并回滚模型 + 重渲染
- **网格感知插入点**：`gridMetrics()` 按首卡片实测宽/高 + `columnGap` 推算 `cols`，`gridSlotIndex(x,y)` 先定位绝对格子（含 folder-card 占位）再映射到非 folder 的 meme 卡数组索引并 clamp（分组内 folder 卡混排时插槽不串位）
- **FLIP 让位动画**：跨槽时对被挤开卡片记录 First/Last rect，invert 后靠 `#meme-grid.drag-active .meme-card` 的 `transition: transform 200ms` 归位，实时显示空位跟随指针
- 落点持久化：全部视图调用 `reorder_memes(id[])` 更新全局 sort_order；分组/子分组内调用 `reorder_collection_members(collection_id, id[])` 更新 `meme_collections.sort_order`；API 失败回滚 `originalOrder` 并重渲染 + toast
- `canReorderMemes()`: 搜索或标签筛选时禁用；**全局开关 `dragSortEnabled`（标题栏「拖拽排序」图标按钮，位于上传/下载左侧，图标蓝色高亮=开，灰色=关）关闭时禁用排序**；全部（null）与分组（id>0，含子分组）视图可排序，收藏夹/最近使用等特殊集合（-2/-3）不可排
- **拖拽到外部应用**：关闭拖拽排序后 meme 卡**不用 HTML5 拖拽**（WebView2 http 源的 `text/uri-list`/`DownloadURL` 不生成 CF_HDROP，QQ/微信会报"图片拖拽失败"或资源管理器无反应）；改用 **WinForms 原生文件拖拽**（`native_drag.py`）：`pointerdown` 记录起点 → `pointermove` 位移 >8px 时 `JsApi.start_native_drag(id)` → 后端用 `webview.windows[0].native`（主 Form）`Invoke` 在 UI 线程执行 `DoDragDrop`（`DataObject` + `DataFormats.FileDrop` → CF_HDROP）→ 拖到 QQ/微信/桌面是真实本地文件；`native_drag.py` 懒加载 pythonnet/WinForms，非 Windows 或无 .NET 时返回 False，JS 端 toast 提示；`memes` 数组不因原生拖拽改变（`d.natDrag` 跳过排序持久化与 cancel 重置）
- 排序拖拽与原生拖拽共用 `initDragReorder` 的 pointer 事件：`onDown` 按 `canReorderMemes()` 决定 `d.natDrag`（排序关=true），`onMove` 按 natDrag 分支走原生拖拽或排序，`onUp`/`cancelMemeDrag` 对 `d.natDrag` 跳过排序回滚
- `search()` 带 `collection_id` 时按 `meme_collections.sort_order ASC, m.updated_at DESC` 排序（子查询取该 meme 在目标分组内的 sort_order）
- 拖拽后通过 `ignoreClick` 抑制误触发的 `click`（防止误复制），下一次 `pointerdown` 时重置

### 多级分组（最多 3 层）
- `collections.parent_id` 自引用实现嵌套
- `create_subcollection(name, parent_id)` 自动检查深度（`get_collection_depth`），超出 2 层拒绝
- 顶层分组在 `#colbar` 渲染为 tab，选中后展开子分组
- `#tagbar`/`#colbar` 横向溢出：细滚动条可见（`scrollbar-width: thin` + 5px webkit 样式），`initHScroll(barId)` 把滚轮竖向增量转成 `scrollLeft`（按 `deltaMode` 归一化），`DOMContentLoaded` 时对两个栏各绑定一次
- 分组内右键空白区域 → 新建子分组
- 右键表情包 → 加入分组 → 弹窗列出当前大分组下的子分组

### 未分类（虚拟分组）
- **`collection_id = -4`** 标识「未分类」虚拟分组：展示未加入任何分组的表情包（`meme_collections` 无记录），**不写入 DB/manifest，动态生成**
- `MemeDB.search()/count()` 新增 `uncategorized_only` 参数（`NOT EXISTS` 于 `meme_collections`），`search_memes` 中 `collection_id == -4` 路由到该参数，同时过滤隐写载体
- `get_init_data`/`get_collections` 按配置 `show_uncategorized`（默认开）决定是否追加 `-4` 条目（`get_collections` 中放于 `-2`/`-3` 之后）；设置页「分组显示 → 显示未分类分组」开关（`s-show-uncategorized`），保存到 `save_settings` 的 `show_uncategorized`
- 前端走通用集合渲染路径：计数为 0 时自动隐藏（`renderCollections` 的 `count === 0` 过滤）；不可排序（`canReorderMemes` 对负 id 返回 false）；无特殊右键菜单
- 未分类集合内的删除/加入分组等操作经 `refreshCollections` 后计数自动刷新，全部归类后 `-4` 从标签栏消失

### 最近使用
- `recent_uses` 表：`meme_id` + `used_at`
- `copy_meme` 时自动 `record_use`（`INSERT OR REPLACE`）
- `get_init_data` 中 `collection_id = -3` 标识最近使用，`search_memes` 路由到 `get_recent()`
- 前端复制后自动刷新最近使用列表
- 右键「最近使用」分组 → 「清空最近使用」菜单项（`clear_recent` 清空全表）；右键列表内表情 → 「从最近使用中删除」（`remove_from_recent`）

### QQ 表情包导入 (adb_util.py)
- **入口**: `start_qq_import()` — 后台线程执行完整流程
- **流程**: 检测/下载 ADB → `adb start-server` → 轮询 `adb devices` 等待设备（最多 300s） → `adb pull` 拉取 `QQ_Favorite` 目录 → 魔数识别扩展名 → ZIP 打包到临时目录
- **路径回退** (`_find_qq_favorite_dir`): 后缀固定为 `Android/data/com.tencent.mobileqq/Tencent/QQ_Favorite`，依次尝试主存储 `/storage/emulated/0`、`/sdcard`，再枚举 `/storage/` 下其他卷（TF 卡通常挂载 `/storage/XXXX-XXXX`），首个 `ls` 命中的即拉取（不做多卡场景）
- **魔数识别** (`_detect_ext`): 支持 PNG (`\x89PNG`), JPEG (`\xff\xd8`), GIF (`GIF87a`/`GIF89a`), WebP (`RIFF`+`WEBP`), BMP (`BM`)
- **ADB 下载** (`_download_with_progress`): 从 googledownloads.cn （国内同步镜像源） 下载 platform-tools ZIP，解压到 `.adb/platform-tools/`，更新 `dl_progress` 供前端显示下载百分比
- **进度状态** (`_QQ_STATE`): `idle` → `downloading_adb` → `starting_adb` → `waiting_device` → `pulling` → `processing` → `done`/`error`，前端 300ms 轮询 `get_qq_import_progress()`
- **保存**: `save_qq_zip()` 通过系统另存为对话框保存 ZIP 到用户位置
- **前端 UI**: 设置页按钮"从手机版 QQ 缓存导入" + 进度覆盖层（显示阶段 + 进度条 + 错误信息）
- `.adb/` 文件夹同时供 ADB 检测和 QQ 导入共用

### QQNT 提取 (qqnt_extract.py)
- **来源**: 改编自 GPL-3.0 项目 QQFavoriteExtract (main_gui.py)，**GPL-3.0 合规**：该模块按 GPL-3.0 分发（头部含原作者署名与协议链接），引入后整体作品再分发需按 GPL-3.0 处理
- **表情目录**: `<UserDataSavePath>/<QQ号>/nt_qq/nt_data/Emoji/personal_emoji/Ori`，`UserDataSavePath` 从 `C:\Users\Public\Documents\Tencent\QQ\UserDataInfo.ini` 的 `[UserDataSet]` 段读取
- **编码自适应**: `read_file_with_correct_encoding` 按候选编码严格解码，需命中 `[UserDataSet]` 且内容含中文或全 ASCII（`is_content_valid`，注意 `\u4e000` 恒 False 的坑，应为 `\u4e00`）
- **昵称** (`get_user_nickname`): `uapis.cn` API + `%APPDATA%/OhMyMeme/nickname_cache.json` 本地缓存 1 小时；用 `urllib`（无 requests 依赖），失败返回空串
- **复制** (`copy_directory_with_progress`): `os.walk` + `shutil.copy2`，**逐文件容错**（失败跳过继续并 `on_error(src,msg)`，清理半成品），进度走 `on_progress(done,total,src,dst)`/日志走 `on_log(msg)`；返回 `{total,copied,failed,skipped}`；`image_only=True` 时仅复制魔数可识别的图片
- **扩展名修正**: 纯魔数检测（`FILE_SIGNATURES`，兼容无扩展名/错误扩展名），webp 需校验 `RIFF` + `header[8:12]==b'WEBP'`；冲突名跳过不覆盖；返回 `{total,renamed,unrecognized}`
- **无弹窗/sys.exit**: 失败抛异常（`RuntimeError`/`FileNotFoundError`/`FileExistsError`）或返回统计 dict；输出目录已存在且非空抛 `FileExistsError`，`overwrite=True` 才清空后写入；输出目录与源表情目录相同抛 `ValueError` 防误删
- **入口**: `extract_qq_emojis(qq_number, output_dir, ...)`（新增 `image_only`/`overwrite`/`should_stop`）；环境探测 `get_extract_status()` 区分 `config`/`path_missing`/空账号三态；辅助 `get_available_qq_numbers()`/`get_default_output_dir()`
- **GUI 集成**: `webui.py` 的 `_QQNT_STATE`/`_qqnt_worker` 后台驱动 + `SettingsApi.qqnt_*` 方法（`qqnt_check_env`/`qqnt_pick_ini`/`qqnt_pick_userdata`/`qqnt_pick_base`/`qqnt_start`/`qqnt_get_progress`/`qqnt_cancel`/`qqnt_open_dir`）；设置页「从电脑导入」向导（环境/选账号 → 输出位置 → 进度 → 汇总），300ms 轮询 `qqnt_get_progress`；手动选择的 INI/用户数据目录持久化到 `config.json` 的 `qqnt_ini_path`/`qqnt_userdata_path`；`should_stop` 实现取消。**手动重定向始终可见**：`qqntRenderEnv` 在探测成功时也显示「选择配置文件/选择用户数据目录」按钮（`userdata_save_path` 传入时完全覆盖 INI 推导路径），应对多用户 Windows 下 `UserDataInfo.ini` 只记录第一个用户路径的场景

### Telegram 缓存导入 (tg_stickers.py)
- **入口**: `start_tg_import(webui, tdata_path, passcode, convert_webm)` — 后台线程执行完整流程；`tdata_path` 为空时回退到配置 `tg_tdata_path`，再自动检测
- **tdata 路径检测** (`find_tdata_path`): 跨平台回退链 — Windows `%APPDATA%\Telegram Desktop\tdata` → macOS `~/Library/Application Support/Telegram Desktop/tdata` → Linux `~/.local/share/TelegramDesktop/tdata` + Snap/Flatpak 变体；未找到则报 `error_code="no_tdata"` 引导手动指定
- **手动指定目录**: 设置页「手动指定 tdata 目录」按钮（`SettingsApi.pick_tg_tdata`）弹文件夹对话框，`is_valid_tdata()` 校验含 `key_datas`/`key_data`，通过后持久化到 config 键 `tg_tdata_path`（下次启动预填显示）；导入失败弹窗内 `error_code` 为 `no_tdata`/`invalid_tdata`/`no_cache` 时显示「手动选择 tdata 目录」重试按钮
- **解密机制**: Telegram Desktop 缓存使用 AES-IGE（TDF$ 文件）和 AES-CTR（TDEF 文件）加密，本地密钥从 `tdata/key_datas` 读取，通过 PBKDF2-HMAC-SHA512 派生（有本地密码时 100k 迭代，无密码时 1 次）；`bad_key` 错误提示本地密码场景
- **解密流程**: `read_local_key()` 读取密钥 → 遍历 `user_data/cache` + `user_data/media_cache` → `decrypt_tdf_file()`/`decrypt_tdef_file()` 按魔数识别格式解密 → `detect_extension()` 通过文件头识别扩展名 → 仅保留 webp/webm
- **webm 转换** (`convert_webm_to_webp`): 默认开启，ffmpeg 将 webm 转 animated webp，**无损**（`-lossless 1 -quality 100`），保持宽高比（最长边 512，不放大），删除原 webm；转换前 `_check_ffmpeg()` 预检，缺失时报 `error_code="no_ffmpeg"` 中止；**单个转换失败的文件跳过不导入**（`convert_failed` 计数并在完成消息提示）
- **静态版去重** (`dedup_static_against_animated`): Telegram 对同一动态贴纸缓存两份（512 webm 动画 + 320 webp 静态版），入库前用 PIL 识别动画 webp（`n_frames>1`），将每个静态 webp 与所有动画 webp 首帧做**归一化灰度差分**（白底合成 32×32，阈值 diff<0.02，实测匹配组 0.002-0.005 / 非匹配组 >0.1 间隔安全），内容一致的静态版跳过只保留动画版；无动画或 PIL 缺失时原样返回；`.webm` 文件（未转换时）不受影响。实测 127 静态中 45 个被判重跳过，0 误杀 0 漏跳，全量比较耗时 ~2s
- **进度状态** (`_TG_STATE`): `idle` → `scanning` → `loading_key` → `decrypting` → `converting` → `importing` → `done`/`error`/`cancelled`，含 `error_code` 字段，前端 300ms 轮询 `get_tg_import_progress()`
- **入库**: 解密到临时目录后调 `webui._do_import()` 入库，完成后自动清理临时文件
- **取消**: `cancel_tg_import()` 设置标志位，工作线程在每个阶段检查并中止
- **前端 UI**: 设置页「从 Telegram 导入」section（tdata 目录手动指定按钮 + 本地密码输入 + WebM 转换开关）+ 进度覆盖层（错误时 `no_tdata`/`invalid_tdata`/`no_cache` 显示「手动选择 tdata 目录」重试按钮）
- **多账号**: Telegram Desktop 多账号共享 `user_data/cache`，无法区分来源账号，统一提取
- **透明动画（已解决）**: Telegram 视频贴纸 webm 内含有效 VP9+alpha（`yuva420p`）数据，但 ffmpeg **原生 VP9 解码器会静默丢弃 alpha 平面**（解码结果全不透明），导致转换出的动画 webp 背景不透明。修复：`convert_webm_to_webp` 在 `-i` 前加 `-c:v libvpx-vp9` 强制使用 libvpx 解码器保留 alpha。实测 48 个 webm 中 47 个恢复透明，透明像素分布与同表情静态 webp 完全一致

### 微信导入 (wechat_probe.py + wechat_keyfinder)
- **架构**: 独立 C++ 二进制 `wechat_keyfinder` 处理 Windows 进程内存取证（读取微信进程内存提取密钥），Python 侧通过 subprocess + JSON 协议协调完成 DB 解密/SQLite 查询/CDN 下载/入库；仅 Windows
- **目录层级**: 微信文件目录（root，默认 `%USERPROFILE%\Documents\xwechat_files` 或 `\WeChat Files`）→ 账号目录（root 下 `wxid_*` 文件夹，每个微信账号一个）→ `db_storage/emoticon/emoticon.db`（表情库，加密）+ `db_storage/favorite/favorite.db`（收藏库）
- **环境检测** (`inspect_wechat_environment`): 传入路径 basename 以 `wxid_` 开头则视为单账号，否则扫描子目录收集所有 `wxid_*`；每账号 `_inspect_account` 检查 DB 是否存在且为 SQLite header（否则 `encrypted_index`）；返回 `{status, reason, root, root_exists, account_directory_count, accounts: [{id, path, status, reason, db_path}]}`
- **账号选择**: `_pick_account` 未指定且多账号时返回 None，调用方报 `multiple_accounts` 引导前端选择；`list_wechat_stickers`/`start_wechat_import`/`_wechat_worker` 支持 `account_path` 参数指定账号
- **密钥提取**: 二进制扫描微信进程内存，通过特征码定位密钥对象（RVA 偏移在 `config/offsets.json` 配置），XOR 解码 + salt 比对 + HMAC-SHA512 校验。**掩码恢复为主路径**（`find_wechat_key_masked`）：利用 DB 前 16 字节 salt 反推 32 字节 XOR 掩码，按 `x'<96hex>'` 格式识别被掩码的 99 字节密钥缓冲，**无需 RVA**，微信升级不易失效；旧 RVA 特征码扫描仅作回退；`--key <hex64>` 可注入已验证密钥绕开取证
- **DB 解密** (`_decrypt_database`): AES-256-CBC 逐页解密（每页 4096 字节，页 1 带 16 字节偏移，IV 取页尾 80 字节偏移处），首页替换为 "SQLite format 3" header；**合并 WAL**（`_apply_wal`）：微信运行中表结构与记录在 `emoticon.db-wal` 里，按 WAL 帧（24B 头 + 4096B 加密页）解密并回写到对应页，主文件旧快照 + WAL 帧 = 完整数据
- **元数据查询** (`_query_sticker_metadata`): SQLite 查询 `kNonStoreEmoticonTable`（type/md5/aes_key/cdn_url/encrypt_url/extern_url），返回 md5+url+aes_key 列表
- **下载校验** (`_download_sticker`): urllib 下载 → 魔数识别扩展名（PNG/JPG/GIF/WebP/BMP）→ 带 `aes_key` 时 AES-128-CBC 解密（IV=key）；`_detect_image_ext` 校验合法才返回
- **完整性校验**: 二进制发布时嵌入 SHA-256（`_WECHAT_KEYFINDER_SHA256`），执行前 `verify_binary_integrity` 校验，防恶意替换
- **前端 UI**: 设置页「从微信导入」section（目录选择 + 环境检测 + 多账号下拉 + 进度覆盖层）

## 构建 & 测试
```bash
pip install -r requirements.txt
python -m src     # 开发运行
python -m pytest tests/ -v  # 运行测试
ruff check src/   # lint 检查
black src/        # 格式化
python scripts/build.py  # PyInstaller + InnoSetup 完整构建
python scripts/build.py --lang en  # 指定语言构建
```

`make` 命令仅供参考（`make run`/`make test`/`make lint`/`make format`/`make build`），macOS/Linux 下可能不可用，优先使用原生 Python 命令。

## CI (GitHub Actions) — 两个独立 workflow
- **check.yml**: Ubuntu, lint + test, push 和 PR 到任意分支均触发
- **build.yml**: Windows, 仅在 `check` 通过 main 分支后自动触发，也支持 `workflow_dispatch` 手动触发
- 上传 `dist/OhMyMeme-*-setup.exe` 作为 artifact

## 版本管理
- 版本号唯一来源: `src/__init__.py` → `__version__ = "*.*.*"`
- `scripts/build.py` 用正则从该文件提取版本
