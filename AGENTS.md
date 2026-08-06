# OhMyMeme — AI Agent Guide

## 项目概述
轻量化跨平台表情包管理系统，突破表情包数量限制，支持全局快捷键呼出、搜索复制、FTP/S3/R2 同步。

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
  sync.py         # 同步后端 (FTP/S3/R2)
  tray.py         # TrayManager (pystray, 惰性导入)
  hotkey.py       # GlobalHotkey (三级降级: keyboard→pynput→轮询)
  clipboard_util.py # 剪贴板操作 (Win32 ctypes / macOS osascript / Linux xclip)
  gif_stego.py     # GIF 增量隐写（实验性：粘贴表情大小 + 无损还原原图）
  crypto_util.py  # 加密 (Fernet + PBKDF2, 降级 XOR)
  manifest.py     # meme-index.json 构建/加载
  platform_util.py # 平台工具 (WSL检测, 开机自启)
  adb_util.py      # ADB 自动检测/下载 + QQ 表情包缓存导入（ADB 拉取 + 魔数识别扩展名 + ZIP 打包）
  qqnt_extract.py  # QQNT 本地收藏表情提取（GPL-3.0 衍生模块，纯函数 + 回调接口，无 UI 依赖）
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
  - `tags`/`meme_tags` 已建表并有 DB 层方法（`get_all_tags`/`set_meme_tags`/`search` 标签筛选），但**当前无 UI 入口创建标签，表实际为空**，标签功能未启用（骨架保留，后续可能复用）
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

### 更新
- GitHub API 查询: `/releases/latest` → `/releases?per_page=5` 回退
- 镜像并发: `_urlopen_mirror` / `_urlretrieve_mirror` 用 `ThreadPoolExecutor` + `as_completed`
- 镜像列表: `github.dpik.top` → `gh.dpik.top` → `gh-proxy.org` → 自建镜像（仅用于版本查询）→ 直连 GitHub
- 下载进度: `start_download()` → 后台线程 → JS 每 500ms 轮询 `get_download_progress()`

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

### Manifest
- `build()` 递归遍历嵌套分组树，空分组自动 `delete_collection`
- 远端 manifest 中的 `collections` 以嵌套格式存储（`name`/`filenames`/`children`），version 2 旧格式启动时自动转换

### 自定义排序
- `memes.sort_order` 字段存储拖拽排序结果
- **模型驱动**：`memes` 数组为唯一真源，拖拽跨槽时先 `moveInArray` 同步模型、再挪 DOM 节点（不再以 DOM 顺序回读重建数组）；`initDragReorder()` 在 `#meme-grid` 上绑定一次
- **Pointer Events + 指针捕获**：`pointerdown/pointermove/pointerup`，拖拽激活（位移 >8px）时才 `setPointerCapture`（避免普通点击被捕获重定向）；无 `PointerEvent` 的旧 WebView 自动回退 mouse 事件（`mousemove/mouseup` 挂 document）；`pointercancel`/`blur` 取消并回滚模型 + 重渲染
- **网格感知插入点**：`gridMetrics()` 按首卡片实测宽/高 + `columnGap` 推算 `cols`，`gridSlotIndex(x,y)` 用 `row*cols+col` 定位目标槽并 clamp
- **FLIP 让位动画**：跨槽时对被挤开卡片记录 First/Last rect，invert 后靠 `#meme-grid.drag-active .meme-card` 的 `transition: transform 200ms` 归位，实时显示空位跟随指针
- 落点持久化：顺序变化时调用 `reorder_memes(id[])` 批量更新 sort_order；API 失败回滚 `originalOrder` 并重渲染 + toast
- 拖拽后通过 `ignoreClick` 抑制误触发的 `click`（防止误复制），下一次 `pointerdown` 时重置

### 多级分组（最多 3 层）
- `collections.parent_id` 自引用实现嵌套
- `create_subcollection(name, parent_id)` 自动检查深度（`get_collection_depth`），超出 2 层拒绝
- 顶层分组在 `#colbar` 渲染为 tab，选中后展开子分组
- 分组内右键空白区域 → 新建子分组
- 右键表情包 → 加入分组 → 弹窗列出当前大分组下的子分组

### 最近使用
- `recent_uses` 表：`meme_id` + `used_at`
- `copy_meme` 时自动 `record_use`（`INSERT OR REPLACE`）
- `get_init_data` 中 `collection_id = -3` 标识最近使用，`search_memes` 路由到 `get_recent()`
- 前端复制后自动刷新最近使用列表

### QQ 表情包导入 (adb_util.py)
- **入口**: `start_qq_import()` — 后台线程执行完整流程
- **流程**: 检测/下载 ADB → `adb start-server` → 轮询 `adb devices` 等待设备（最多 300s） → `adb pull` 拉取 `QQ_Favorite` 目录 → 魔数识别扩展名 → ZIP 打包到临时目录
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
- **GUI 集成**: `webui.py` 的 `_QQNT_STATE`/`_qqnt_worker` 后台驱动 + `SettingsApi.qqnt_*` 方法（`qqnt_check_env`/`qqnt_pick_ini`/`qqnt_pick_userdata`/`qqnt_pick_base`/`qqnt_start`/`qqnt_get_progress`/`qqnt_cancel`/`qqnt_open_dir`）；设置页「从电脑导入」向导（环境/选账号 → 输出位置 → 进度 → 汇总），300ms 轮询 `qqnt_get_progress`；手动选择的 INI/用户数据目录持久化到 `config.json` 的 `qqnt_ini_path`/`qqnt_userdata_path`；`should_stop` 实现取消

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
