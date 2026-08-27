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
- **GitHub Actions** (lint+test on Ubuntu, build+installer on Windows/Linux/macOS)

## 核心原则
- **不得重构该项目** — 仅做最小必要修改，不改变现有架构、设计模式、代码组织
- **尽量不创建新文件** — 优先修改现有文件
- **增改同步** — 增加新功能或创建新文件后，同步修改 `README.md` 和 `AGENTS.md` 中对应描述
- **关联文件同步** — 修改后检查是否需要同步更新 `.gitignore`、`Makefile`、`pyproject.toml`、`requirements.txt`、`environment.yml` 等关联文件
- 使用中文回答用户的问题

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
  douyin.py        # 抖音表情包下载导入（ABogus 签名 + curl_cffi TLS 指纹 + WebP 原格式入库）
  abogus.py        # ABogus 签名算法（纯 Python，GPL-3.0，源自 TikTokDownloader）
  douyin_dl.py     # 抖音下载 CLI 测试入口（独立运行，不依赖 GUI）
  wechat_probe.py  # 微信收藏表情导入（helper 二进制提取密钥 + AES-CBC 解密 DB + CDN 下载，仅 Windows）
  wechat_keyfinder/ # 微信密钥提取 C++ 辅助二进制源码（CMake 构建）
  vue-src/       # Vue 3 前端源码（Vite 构建，产物到 webui/dist/ohmymeme.js）
    App.vue      # 根组件：标题栏/搜索/侧边栏/面包屑/标签栏/网格/分页
    main.ts      # 入口：挂载 + window.focusSearch 全局（快捷键呼出聚焦搜索）
    style.css    # 主窗口样式（CSS 变量主题，蓝色 #3b82f6）
    types/       # TS 类型定义 (Meme/Collection/Tag)
    utils/       # api 桥接 + esc + renderMarkdown
    composables/ # useMemes 状态 / useDragSort 拖拽 / useContextMenu / useCollectionBuilder
    components/  # Pager/TagEditor/ImportMenu/ImportProgressOverlay/SyncOverlay/
                 # ContextMenu/CollectionBuilder/CollectionTreeNode/UpdateDialog/SimilarImportDialog
  webui/          # 前端静态文件
    vue.html      # 主窗口入口（Vue），Bottle 优先加载
    dist/ohmymeme.js # Vite 构建产物（gitignored）
    settings.html # 设置窗口 HTML（vanilla，两列布局：左导航+右内容）
    settings.css  # 设置窗口样式
    settings.js   # 设置窗口逻辑（设置项/同步/导入向导）
    index.html/index.css/index.js  # 旧主窗口（已备份至 webui-backup/，不再使用）
config/
  offsets.json    # wechat_keyfinder 易变参数（版本号等，微信升级时只改此文件）
scripts/
  build.py        # PyInstaller + InnoSetup 构建脚本 (i18n zh/en)
  launcher.py     # PyInstaller 入口
  hooks/          # 自定义 PyInstaller hooks（Linux GTK: WebKit2/Soup typelib 收集，内置无对应 hook）
    hook-gi.repository.WebKit2.py
    hook-gi.repository.Soup.py
tests/
  test_core.py    # unittest 风格: Version/Config/Crypto/Database
  test_abogus.py  # unittest 风格: ABogus 签名算法 SM3/RC4/签名
  test_douyin_dl.py # unittest 风格: 抖音下载 CLI (签名URL/verifyFp)
  test_tg_stickers.py # unittest 风格: Telegram webm转换/取消/进度/dedup (mock Popen)
  test_updater.py   # unittest 风格: 非阻塞版本检查缓存机制 (mock check_latest)
  test_startup.py # pytest 风格: 全生命周期集成测试
  test_phash.py   # pytest 风格: 感知哈希(pHash)算法单元测试 (需 PIL)
  test_import_concurrency.py # pytest 风格: _do_import 并发去重 (同图1条/异图都可导)
  fixtures/grid_slot_probe.cjs # Node 网格拖拽槽位回归探针
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
- macOS 跳过托盘：pystray 在 macOS 需在主线程抢占 NSApplication runloop，与 pywebview 主循环冲突（会导致窗口无法启动或段错误），与 Linux GTK 冲突同理

### 全局快捷键
- 三级降级: `keyboard` → `pynput` → 200ms 轮询 (`keyboard.is_pressed`)
- **运行期失效自愈**：`keyboard` 0.13.5 的 `GenericListener` 处理线程（`processing_thread`）一旦因未捕获异常崩溃即永久失效（进程存活、界面正常但热键无响应，需重启软件才恢复）。`GlobalHotkey` 两道防线：①`_try_keyboard` 用 `make_safe` 把回调包成 `_safe_callback`，吞掉回调异常，防止其杀死 `processing_thread`；②注册后启动 daemon 守护线程（`_start_keyboard_watchdog`，`KEYBOARD_WATCH_INTERVAL`=5s）周期检查 `keyboard._listener` 的 `listening_thread`/`processing_thread` 是否存活，任一死亡即 `_reregister_keyboard`（`remove_hotkey` → 置 `listener.listening=False` → `start_if_necessary()` → 重新 `add_hotkey`）自动重挂。**热键事件日志**：`_get_file_logger` 惰性创建独立 logger，把注册/回调异常/线程死亡/自愈重挂等事件追加到 `data_dir/hotkey.log`（`_log_hotkey_event` 同步写文件+控制台，初始化失败降级为常规 logger 不阻塞）。**重注册与注销的正确性**：`_reregister_keyboard` 返回 bool 且与 `unregister` 持同一 `_reregister_lock` 串行化——`add_hotkey` 失败时置 `_reregister_pending=True` 并返回 False（不记录成功、守护下轮继续重试），成功才清 pending 并记成功事件；注销已开始（回调已清空或停止事件已置位）时重注册直接返回 False 不重新挂热键。**生命周期代次 token**：`_watchdog_gen` 在 `register` 增加、`unregister` 递增；`_start_keyboard_watchdog` 捕获当前代次并由 `_reregister_keyboard(listener, gen)` 在锁内校验 `gen == _watchdog_gen`，旧 watchdog（旧代次）的重注册操作直接返回 False，杜绝注销后立即重新注册时旧线程对新热键的误操作。
- macOS 跳过 `keyboard` 库（darwin 后端需 root 权限，报 `Error 13` 且 root 下会段错误），直接走 `pynput`（CGEventTap，需辅助功能权限）
- WSL 无法捕获全局快捷键
- 配置 `hotkey_show_at_mouse` 默认 `false`；仅 Windows 生效。开启后仅在全局热键将隐藏主面板显示时，按鼠标所在显示器工作区依次尝试 `(cursor_x, cursor_y)`、`(right-width, cursor_y)`、`(cursor_x, bottom-height)`、`(right-width, bottom-height)`，仅使用首个完整容纳窗口的候选位置；出错或没有可用位置时不移动。托盘保持普通切换，热键回调仍为零参数。
- WebUI 维护非持久的快捷键显示会话状态：仅隐藏主窗口被全局快捷键显示后，成功复制或成功原生向外文件拖拽才会自动隐藏；任意 hide、普通/托盘显示、LAN/其他 show、内部排序拖拽及失败交互均不会触发该自动隐藏。

### 窗口
- 主窗口 ~960×640 frameless, 设置窗口 460×560 frameless
- Windows 全局热键显示位置仅在隐藏到显示的转换时计算，使用鼠标所在显示器工作区；不改变托盘激活或其他窗口显示路径
- 自定义 JS 拖拽: 鼠标事件 → `pywebview.api.move_window(dx, dy)`
- 增量回退（Windows/macOS）用 `screenX/screenY`（**勿改 `clientX/clientY`** — clientX 是相对窗口坐标，窗口自身滞后位移会被下一次 mousemove 当作反向增量回传，形成反馈振荡导致高频抖动）；Linux 走合成器原生拖动不经过此路径
- **Linux 拖拽必须走合成器**：`w.move()` 在 Wayland 下无效（合成器不允许客户端自定位），mousedown 时 JS 调 `start_window_drag()` → 后端 `GLib.idle_add(native.begin_move_drag, ...)` 交给合成器交互式拖动；时间戳用 `Gdk.CURRENT_TIME`（GDK 文档允许未知时间时用它，X11 回填最近输入事件时间、Wayland 不参与）
- `#titlebar` 上可拖拽 (排除 `.title-btn` 按钮区域)
- 侧边栏折叠按钮 `.sidebar-toggle` 位于搜索框左侧（`#search-wrap` 内），点击折叠/展开 `#sidebar`；搜索框 `flex:1` 随侧边栏 180px↔48px 动态伸缩

### 数据库
- 7 表: `memes`, `tags`, `meme_tags`, `collections`, `meme_collections`, `favorites`, `recent_uses`
  - `tags`/`meme_tags`：DB 层方法（`get_all_tags`/`set_meme_tags`/`get_meme_tags`/`search` 标签筛选），已启用；右键表情「打标签」弹出标签编辑器（`showTagEditor`：点选已有标签/搜索过滤/输入新建，回车添加），`_set_tags` 覆盖式写入；`_prune_orphan_tags` 在 `_set_tags` 与 `delete_meme` 中清理无任何表情使用的孤儿标签（tagbar 不残留幽灵标签）
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
- `hotkey_show_at_mouse` 默认 `false`，控制 Windows 上全局热键显示隐藏主面板时是否按鼠标位置放置
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
- **WebDAV 目录创建去重**: `_push_worker` 同一批次所有文件都上传到 `memes/`，只在循环前 `ensure_remote_dir` 一次；`_WebDAVBackend.ensure_remote_dir` 对**每个目录 URL**在 `_dav_dirs_lock` 内原子执行「缓存检查 + MKCOL + 缓存写入」，成功/405/复核命中均写 `_dav_dirs` 缓存，多 worker 并发对同一目录也只发一次 MKCOL——避免重复 MKCOL 触发远端锁。**`push()` 每次在拿到 `_sync_run_lock` 后先清空 `_dav_dirs`**，避免命中上一次同步缓存、跳过已被删除远端目录的 MKCOL。
- `_sync_lock` (`threading.Lock`) 保护 `_sync_state` 写操作；`_increment_sync_progress()` 提供原子递增
- `_chunk_list(lst, n)` 将文件列表均匀切分给各线程
- **push 动态 manifest 维护**: `push()` 上传过程中每 `_HEARTBEAT_INTERVAL`（5s）用「远端已有 + 本次已确认上传」快照增量更新远端 manifest（`_build_push_manifest` + `_upload_manifest_data`，失败仅告警不中断）；部分失败中断前也上传该快照（避免远端有文件却无有效 manifest）；成功路径在合并远端独有项后补入已上传但不在本地清单的项（去重 guard），保本地被清空等边角。manifest 只列确认上传成功的文件，不产生幻影条目
- **孤儿清理互斥与进度**: `cleanup_remote_orphans(delete=True)` 删除前非阻塞获取 `_sync_run_lock`（被 push/pull 占用时返回「同步正在进行中」，绝不并发删除）；删除循环复用 `_sync_state`（`direction="delete"`，更新 current_file/files_done/files_total/progress，状态 deleting→done），前端复用 `#sync-progress-overlay` 轮询展示；扫描（delete=False）不互斥
- **远端文件名校验**: `_safe_remote_fname()` 拒绝路径穿越/绝对路径/隐藏名；`_fetch_remote_memes` 解析远端 manifest 时过滤不安全文件名（含非 dict 条目），`_pull_worker` 下载前二次校验
- **S3 后端 OSS 兼容**: boto3 客户端固定 `signature_version='s3'`（V2 签名，boto3 的 V4 与 chunked encoding 强耦合，OSS 不支持）；寻址方式由 `s3_addressing_style` 配置控制（默认 `"virtual"`，可选 `"path"`），映射到 `BotoConfig(s3={"addressing_style": ...})`；阿里云 OSS 仅支持 virtual-hosted style（bucket 作子域名），path-style 请求被拒绝；设置页 S3 表单「寻址方式」下拉框切换

### 更新
- GitHub API 查询: `/releases/latest` → `/releases?per_page=5` 回退
- **仅检查稳定版**：`_parse_release` 跳过 prerelease 与含 `nightly` 的 tag（保证软件更新绝不指向非正式版）；`_parse_version` 跳过非数字段（如 `0.6.0-nightly`）
- **非阻塞检查**：`check_latest_cached(force=False)` 是唯一入口——**`_ensure_check_started` 先查 `_check_running`（在跑则一律返回 `pending`，含 force 刷新未完成时，绝不命中旧 `_check_result`），再对非 force + 新鲜缓存（`_CHECK_TTL`=24h）直接返回**；无缓存/缓存过期/`force=True` 触发后台 daemon 线程跑 `check_latest()` 填 `_check_result`+`_check_result_at`（`_check_lock` 保护，幂等只启动一次），立即返回 `pending: true`（永不阻塞网络 3.8s~20s+）。**generation token**：`reset_check_cache()` 推进 `_check_generation`，后台 `_task` 完成时仅当代号匹配才写结果，防在途旧任务覆盖 reset 后新状态。`webui.py` 的 `JsApi.check_update`/`SettingsApi.check_update` 支持 `(debug, force)` 透传；前端 `App.vue` 的 `checkUpdateAndPrompt`（onMounted/24h 定时）首发 `force=true`、pending 时转 `checkUpdateResult` 非 force 轮询，`settings.js` 的 `checkUpdate` 首发 force、while 轮询暂取非 force——避免完成后再次 force 触发新检查造成永久 pending。**这解决了启动期间 `check_update` 同步阻塞曾导致的界面交互卡顿，及缓存不失效时 24h 定时器形同虚设的问题**
- 镜像并发: `_urlopen_mirror` / `_urlretrieve_mirror` 用 `ThreadPoolExecutor` + `as_completed`
- 镜像列表: `github.dpik.top` → `gh.dpik.top` → `gh-proxy.org` → 自建镜像（仅用于版本查询）→ 直连 GitHub
- 下载进度: `start_download()` → 后台线程 → JS 每 500ms 轮询 `get_download_progress()`
- Linux 更新: `_pick_asset_url` 选取 `.AppImage` 资产；`run_installer` Linux 分支 chmod +x 后直接 `Popen`（AppImage 是 ELF 非 shell 脚本），无 `/dev/fuse` 时追加 `--appimage-extract-and-run` 回退（`_needs_appimage_fallback`）；下载默认文件名走 `_default_asset_name()`（Linux 为 `OhMyMeme-v{version}-x86_64.AppImage`）
- macOS 更新: `_pick_asset_url` 按当前架构选取 `.dmg` 资产（arm64/x86_64）；`run_installer` 走 `_install_dmg_macos`（`hdiutil attach` → `ditto` 复制 `.app` 到 `/Applications` → 打开应用程序目录）；`_default_asset_name()` 为 `OhMyMeme-v{version}-{arch}.dmg`

### 局域网互联 (lan.py)
- **入口**: `lan.start(port, secret)` / `lan.stop()`，`get_status()` 供设置页轮询；`set_allow_secret_config()` 控制是否允许密钥传输（仅内存生效），`set_confirm_callback()` 注入设备确认回调（WebUI 提供）
- **UDP 发现**: 绑定 `0.0.0.0:port`，收到 `{"t":"discover"}` → 单播回 `{"t":"hello","name","os","ver","need_secret"}`（**不含任何密钥信息**）；启用 `IP_PKTINFO`（Linux/Windows）后用 `recvmsg` 取广播到达接口（Linux `ipi_spec_dst` 得接口 IP、Windows 8 字节 `in_pktinfo` 只有接口索引无 spec_dst），`sendmsg` 把回包源地址钉在该接口（Windows 用 `IP_UNICAST_IF`+`connect`+`getsockname` 由索引反查接口 IP，发送时 `ipi_addr` 字段填源地址），虚拟网卡/多网卡环境回包不会走错接口或带上虚拟适配器 IP；`recvmsg` 不可用或非 Linux/Windows 退化 `recvfrom`/`sendto`
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
- 前端 XSS：`utils/api.ts` 的 `esc()`/`renderMarkdown()` 转义所有拼入 innerHTML 的外部/动态数据（远端分组名、GitHub 版本号、QQ 昵称、输出目录、弹窗标题/正文等）；设置窗口 `settings.js` 同理
- **键盘无障碍（主窗口）**：全局 `:focus-visible` 焦点环（2px `var(--primary)`）；meme 卡/文件夹卡 `role="button" tabindex="0"` + Enter/Space 复制或打开分组，标签栏 span 同理（`aria-pressed`）；标题栏图标按钮全部带 `aria-label`；弹窗焦点管理：`utils/api.ts` 的 `rememberFocus()`/`restoreFocus()`/`trapTabFocus()`（模块级 `_focusTarget` 记录打开前焦点、关闭归还、Tab 在弹窗内循环），InputDialog/TagEditor 打开聚焦输入框、ConfirmDialog 默认聚焦「取消」（危险操作需显式点「确定」）、CollectionBuilder 聚焦 `#cb-name`；`#meme-grid.sort-enabled .meme-card:focus-visible` 为 2px 实线焦点环
- **键盘无障碍（设置窗口）**：`settings.css` 全局 `:focus-visible` 焦点环（2px `var(--accent)`）；`.btn/.import-row/.nav-item/.title-btn:focus-visible` 用 box-shadow 双环、`.nav-item.danger:focus-visible` 红色环、`.check-row input[type="checkbox"]:focus-visible`；危险按钮统一 `.btn-danger-outline` 类（hover 变红 + 红色 focus 环，取代内联 `border-color:#ef4444`）；覆盖层焦点管理：`settings.js` 的 `rememberSettingsFocus()`/`restoreSettingsFocus()`/`trapSettingsFocus()`/`visibleSettingsOverlay()`（模块级 `_settingsFocusTarget` + `_SETTINGS_OVERLAY_IDS` 列表），各覆盖层（danger/sync 进度与完成/QQ/QQNT/TG/抖音/微信/上传确认/更新弹窗）打开时记住焦点、打开后聚焦首元素、关闭归还；全局 keydown 先对可见覆盖层做 Tab 循环陷阱，再按 Escape 依次关 danger→dy→tg→wechat→qq→qqnt→sync-progress→sync-done→关设置窗口；静态覆盖层 `role="dialog" aria-modal="true"`，`#toast` 加 `role="status" aria-live="polite"`（主窗口 `#toast` 同理）
- **设置窗口 UX**：保存模型—表单控件改动经 `initDirtyTracking()` 置 `_settingsDirty`，`closeSettings()` 变 async，脏时弹「有未保存的更改」确认再关（取消/×/Esc 均触发）；`saveSettings`/`getSettings`/`resetSettings` 成功后清脏；真正立即生效的控件（LAN 开关、密钥传输、存储位置「应用更改」）带 `.immediate-hint`「立即生效」标注；状态色收敛为 token：`--success: #22c55e`/`--danger: #ef4444`，JS 用 `setStatusColor()` 切 `.status-ok/.status-error` 类（不再写死 `#4caf50/#f44336`），HTML/CSS 内联色改 `var(--danger)`；复制处理下拉用 `.select-row`（label span + select），不再包 `.check-row`
- **关于页**：设置窗口左侧导航末项「关于」（`data-group="about"`）收纳从基础设置迁出的版本更新区块（`s-ver-current`/`btn-check-update`/`s-update-status`，逻辑不变）；页面含大号 OhMyMeme logo（`.about-logo`，span 用 `--accent`，复刻主窗口标题栏效果）、版本号+检查更新，及贡献者名单（`.about-contributors` 深色卡片）。贡献者头像不走外部直连：`/api/contributors` 路由（webui.py Bottle）用 urllib 抓取 `contributor.starsfire.top/TNTXZ/OhMyMeme` 的 SVG（该服务忽略 `?bg=` 参数且无 CORS 头，浏览器直接 fetch 会失败），用 `svg.replace` 剥离白色背景 `<rect>` 后以 `image/svg+xml` 返回，使圆形头像直接落在深色页面上；`onerror` 时隐藏图片并显示「贡献者名单加载失败」回退文案
- **对比度（H2）**：`--muted: #8a94a8`（在 bg/surface 上 ≥5:1）；实心主按钮/激活态文字/选中态 outline 用 `--primary-strong: #1d4ed8`（白色文字 6.7:1、`--primary-light` 背景文字 5.49:1）；`--primary #3b82f6` 仅用于 hover 高亮，不作小字/浅底文字色

### 环境检测
- WSL 检测: `/proc/version` 包含 "microsoft"
- WSL 时设置 `MESA_LOADER_DRIVER_OVERRIDE=llvmpipe`, `LIBGL_ALWAYS_SOFTWARE=1` 等软渲染环境变量

### 启动流程 (关键时序)
- **源码运行自动编译前端**：`main.py` 启动时 `_ensure_vue_frontend()` 检查 `src/webui/dist/ohmymeme.js`，缺失（打包 `frozen` 或已有产物时跳过）则用 `npx.cmd`(Windows)/`npx`(其他) 跑 `vite build` 一次，失败仅告警不阻断启动
- **启动动画**：`App.vue` 挂载时播放 `src/resources/OhMyMeme.mp4`（通过 Bottle 路由 `/resources/<filepath:path>` 提供，`webui.py` 的 `RESOURCES_DIR`，basename 校验防路径穿越，路由须在兜底 `/` 之前注册；PyInstaller 以 `--add-data src/resources` 打包）；`onMounted` 设置 6s 兜底定时器 + `<video>` `@ended` 移除遮罩，`#startup-anim` 全屏遮罩 z-index 2000，`.startup-fade` 0.4s 淡出。**仅启动时播放**：快捷键/托盘仅 toggle 窗口显隐不重载页面，故不会重复播放。设置页「显示启动动画」开关（配置键 `show_startup_animation`，默认开，`useMemes` state 同步）控制：开启时 `loadInitData` 后立即 `startupVideoReady=true` 挂载视频并**并行加载**（无 300ms 延时，动画天然覆盖桥接稳定时间）；关闭时 `dismissStartupAnim()` + `setTimeout(..., 300)` 降级为 300ms 延时。`get_init_data`/`reset_settings`/`get_settings` 均透传该键。**遮罩背景贴合视频边框**：OhMyMeme.mp4 边框为纯黑，`webui.py` 写死 `_STARTUP_BG_COLOR = "#000000"`（不做运行时 ffmpeg 采样，避免影响启动速度），经 `get_init_data` 的 `startup_bg_color` 传给前端，`App.vue` 把该色同时应用到 `#startup-anim` 与 html/body 背景。**可跳过**：点击遮罩立即 `dismissStartupAnim()`；系统 `prefers-reduced-motion: reduce` 时直接跳过动画走 300ms 降级路径（`window.matchMedia` 检测）
- Vue `App.vue` 挂载后:
  1. 立即: `loadInitData()` → `get_init_data()` 加载数据库数据 → 秒开
  2. `checkUpdateAndPrompt()` 立即执行（与 rescan/同步并行）
  3. **动画开启**：视频播放期间即并行 `rescan_cache()` → `run_auto_sync()` → 重新搜索/标签/分组（无延时）；**动画关闭**：降级 `setTimeout(..., 300)` 后执行上述步骤
  4. `setInterval` 每 24h 再跑一次更新检测
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
- **感知哈希相似去重**（`download_original_image` 单图导入路径）：`memes.perceptual_hash` 列（TEXT 存 16 进制，旧库自动 ALTER 迁移）持久化每张图的 64 位感知哈希（`_perceptual_hash`，8x8 可分离 DCT pHash，比均值哈希对浅色/低信息图判别力更强）。导入时哈希未命中则 `_find_similar_candidates` **只算新图 phash + 从 DB 读存量 phash 比对**（整数 XOR，微秒级），`perceptual_hash` 为空的旧库行惰性回填：缺失 ≤`_PHASH_SYNC_BACKFILL_MAX`(5) 同步回填，超过则丢后台线程（`_PHASH_BACKFILLING` 防重入，start 异常复位），本次只比对已填的。`_build_cache_index` 一次性构建文件索引避免逐行 walk（仅在有缺失时执行）。汉明距离 `_PHASH_SIMILAR_DIST<=12` 视为近似，**全库比对无截断漏检**。命中候选时将文件复制到独立临时文件登记 `_PENDING_SIMILAR`（token 随机、TTL 300s 过期时在 pop/next-register 时删除临时文件），返回 `similar_pending`，前端 `SimilarImportDialog` 弹窗让用户选：保留新图 / 保留旧图 / 跳过（discard）/ 都保留（keep_both），经 `JsApi.resolve_similar_import(token, action)` 决定导入或放弃。哈希精确命中返回 `duplicate` 提示「已存在」。`_do_import`/`scan_cache` 新建时写入 `perceptual_hash`（`add_meme` 内部转 hex，规避 64 位溢出 SQLite INTEGER）。两条单图交互路径都启用：`download_original_image`（URL 拖放/下载原图）与 `/api/upload/`（File 拖放，单张时走 `_import_with_similar_decision`）；批量路径（多文件拖放/文件夹/同步 pull/LAN）不做感知去重（多文件走 `_do_import` 避免逐个打断）。`_do_import` 去重关键区（`get_by_hash`检查→copy2→`add_meme`→回查）由模块级 `_IMPORT_LOCK` 串行化：并发拖入完全相同字节的图也不产生重复记录（测试 `test_import_concurrency.py`）
- **导入限制**：`config.py` 常量 `_IMPORT_MAX_PX=2560`（最长边）/`_IMPORT_MAX_BYTES=20MiB`，超过即拒绝接收；覆盖 `_do_import`、`scan_cache`、同步 `_pull_worker`、LAN `_import_bytes` 四类接收路径，跳过超限文件并计数（前端 toast 提示）
- **文件夹导入** (`JsApi.import_folder`)：FOLDER 对话框 → `os.walk` 递归收集图片（扩展名过滤）→ **后台线程导入**（`start_import_job` + `_IMPORT_JOB_STATE`，前端 `ImportProgressOverlay` 300ms 轮询进度条 + 取消，取消时 `progress_cb` 返回 False 中断 `_do_import`，保留实际进度）→ `make_collection`（前端导入菜单「自动创建分组」勾选，默认开）时以文件夹名 `create_collection` + 批量 `add_to_collection`（同名分组复用，重复导入并入）。`import_memes`（文件对话框）同样后台化，走同一 job；`import_from_clipboard`（剪贴板，通常单张瞬时）保持同步返回 id。`_do_import` 提供可选 `progress_cb`（逐文件回调，返回 False 中断）
- **渠道自动分组**：3 个入库渠道导入后调 `WebUI.ensure_import_collection(ids, 固定名)` 自动归入固定名分组——TG→「Telegram」、抖音→「抖音」、微信→「微信」；同一渠道不同时间导入复用同名分组。QQ（导出 ZIP 到外部）、QQNT（提取到输出文件夹）不入库故不建组。`create_collection` 现为「先按 name+parent_id 查已存在→返回既有 id，否则 INSERT」——**不再产生重复空分组**（仓库同名字段多次导入只一个分组，成员靠 meme_collections 的 PRIMARY KEY 去重），测试 `test_ensure_collection_same_name_reused`/`empty_args`

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
- 排序相关的 `reorder_memes`/`reorder_collections`/`reorder_collection_members` 更新 DB 后即调 `build_manifest()`，本地 `meme-index.json` 保持最新
- push：末尾 `build_manifest()` 按 DB 当前 `sort_order` 重建并上传，云端 manifest 顺序反映本地排序
- pull：`_apply_remote_order` 按云端 manifest 顺序回写本地 `sort_order`，实现双向闭环

### Manifest
- `build()` 递归遍历嵌套分组树，空分组自动 `delete_collection`
- 远端 manifest 中的 `collections` 以嵌套格式存储（`name`/`filenames`/`children`），version 2 旧格式启动时自动转换

### 自定义排序
- `memes.sort_order` 字段存储全局展示顺序；前端可拖拽排序仅在正 ID 分组/子分组内进行，成员顺序存 `meme_collections.sort_order`
- **分页展示**：`search_memes` 支持 `offset`/`limit`（`MEME_PAGE=200`，前端 index.js 与后端 webui.py 同步维护）；`count_memes`（后端 `count()`/`count_recent()`）统计总数供前端 `renderPager()` 在 `#grid-wrap` 底部渲染翻页条（`<` 上一页/页码窗口含 `…`/`>` 下一页/`>>` 末页）；`refreshMemes()` 重置回第 1 页并重新 count，`goToPage(p)` 按 `offset=(p-1)*MEME_PAGE` 拉取（过期响应用 `memeGen` 丢弃），当前页无数据时回退到可用末页；`memePage`/`memeTotal`/`memePageCount` 维护分页状态；`memes` 数组是已加载子集；`loadMoreMemes()` 保留（含 sort-enter 入场动画）供兼容/测试，主流程不再由滚动触发
- **模型驱动**：`memes` 数组为唯一真源，拖拽跨槽时先 `moveInArray` 同步模型、再挪 DOM 节点（不再以 DOM 顺序回读重建数组）；`initDragReorder()` 在 `#meme-grid` 上绑定一次
- **Pointer Events + 指针捕获**：`pointerdown/pointermove/pointerup`，拖拽激活（位移 >8px）时才 `setPointerCapture`（避免普通点击被捕获重定向）；无 `PointerEvent` 的旧 WebView 自动回退 mouse 事件（`mousemove/mouseup` 挂 document）；`pointercancel`/`blur` 取消并回滚模型 + 重渲染
- **网格感知插入点**：`gridMetrics()` 按首卡片实测宽/高 + `columnGap` 推算 `cols`，`gridSlotIndex(x,y)` 先定位绝对格子（含 folder-card 占位）再映射到非 folder 的 meme 卡数组索引并 clamp（分组内 folder 卡混排时插槽不串位）
- **FLIP 让位动画**：跨槽时对被挤开卡片记录 First/Last rect，invert 后靠 `#meme-grid.drag-active .meme-card` 的 `transition: transform 200ms` 归位，实时显示空位跟随指针
- 落点持久化：前端可拖拽排序仅在正 ID 分组/子分组内调用 `reorder_collection_members(collection_id, id[])` 更新 `meme_collections.sort_order`；`reorder_memes(id[])` 仍用于维护全局 `sort_order`；API 失败回滚 `originalOrder` 并重渲染 + toast
- `canReorderMemes()`: 搜索或标签筛选时禁用；**全局开关 `dragSortEnabled`（标题栏「拖拽排序」图标按钮，位于上传/下载左侧，图标蓝色高亮=开，灰色=关）关闭时禁用排序**；仅正 ID 分组（含子分组）、全部（null）与未分类（-4）视图可排序，收藏夹/最近使用等特殊集合（-2/-3）不可排
- **整理/多选模式拆分（互斥）**：`sortEnabled`（拖拽排序）与 `selectMode`（多选）为两个独立标题栏按钮状态，开启一个自动关闭另一个（`toggleSort`/`toggleSelect` 用 `drag.enable()/drag.disable()` 而非 `drag.toggle()`）。排序模式：drag-select `:click-option-to-select=false`，点击卡不复制不勾选，仅拖拽换位；多选模式：drag-select `:click-option-to-select=true` 支持点选/框选，`#batch-bar`（`v-if="selectMode"`：全选当前页/取消选择/批量删除）显示，`#meme-grid.select-enabled` 生效。ESC 顺序：右键菜单 → 多选 → 整理 → 隐藏窗口；`handleCopy`/`onCardPointerDown`/`onDocPointerMove` 均以 `sortEnabled || selectMode` 守卫（多选/整理中不复制、不走原生拖拽）
- **排序视觉反馈**：`renderGrid()` 按 `canReorderMemes()` 切换 `sort-enabled`；启用时仅普通 meme 卡（排除 `.folder-card` 和 `.dragging`）最终显示 `scale(0.95)`、3px `var(--border-light)` 描边及 3px 偏移。稳定卡使用独立 `rotate` 属性作轻微快速晃动，且必须排除 `.drag-active`、`.sort-enter`、`.folder-card` 和 `.dragging`；`prefers-reduced-motion: reduce` 时禁用晃动。不得用 `transform` 实现晃动，避免覆盖拖拽和 FLIP 的变换。正在拖拽的卡内联变换固定为最终 `translate(...) scale(0.90)`，与现有透明度、阴影和 FLIP 效果并存，CSS 与内联变换不得叠加。多选模式选中态独立：`#meme-grid.select-enabled .meme-card.selected` 为 `2px solid var(--primary-strong)` outline（与整理模式选中态规则并存，后者仅作用于 `sort-enabled`）。开启工具栏排序开关时沿用现有入场反馈，只有明确关闭该开关才保留当前卡片播放退场动画。搜索、标签、分组或虚拟分组导致的资格变化均按普通刷新处理，不播放退场动画；文件夹卡不显示排序反馈
- **拖拽到外部应用**：关闭拖拽排序后 meme 卡**不用 HTML5 拖拽**（WebView2 http 源的 `text/uri-list`/`DownloadURL` 不生成 CF_HDROP，QQ/微信会报"图片拖拽失败"或资源管理器无反应）；改用 **WinForms 原生文件拖拽**（`native_drag.py`）：`pointerdown` 记录起点 → `pointermove` 位移 >8px 时 `JsApi.start_native_drag(id)` → 后端用 `webview.windows[0].native`（主 Form）`Invoke` 在 UI 线程执行 `DoDragDrop`（`DataObject` + `DataFormats.FileDrop` → CF_HDROP）→ 拖到 QQ/微信/桌面是真实本地文件；`DoDragDrop` 返回 `DragDropEffects.None`（拖回取消）时 `start_native_drag` 返回 False，不触发 `schedule_hide`；`native_drag.py` 懒加载 pythonnet/WinForms，非 Windows 或无 .NET 时返回 False，JS 端 toast 提示；**原生拖拽进行中回拖到窗口**用全局 `nativeDragActive` 标志抑制 drop 导入处理器（dragenter/dragover/dragleave/drop 均忽略，视为取消，不弹导入浮层）；`nativeDragActive` 在 `pointermove` 位移 >8px 触发原生拖拽**前**置 true，`start_native_drag` Promise `.then/.catch` 中重置，拖拽期间（后端 `DoDragDrop` 阻塞 UI 线程）保持 true，确保拖回窗口不会误触发导入
- 排序拖拽与原生拖拽共用 `onCardPointerDown`/`onDocPointerMove` pointer 事件：`onCardPointerDown` 按 `sortEnabled && canReorder()` 决定走 `drag.onPointerDown`（排序）还是记录 `nativeDragStart`（原生拖拽），`onDocPointerMove` 按 `drag.dragState.memeId` 是否存在分支，`onDocPointerUp`/`onDocPointerCancel` 对原生拖拽仅清 `nativeDragStart` 跳过排序回滚
- `search()` 带 `collection_id` 时按 `meme_collections.sort_order ASC, m.updated_at DESC` 排序（子查询取该 meme 在目标分组内的 sort_order）
- 拖拽后通过 `ignoreClick` 抑制误触发的 `click`（防止误复制），下一次 `pointerdown` 时重置

### 多级分组（最多 3 层）
- `collections.parent_id` 自引用实现嵌套
- `create_subcollection(name, parent_id)` 自动检查深度（`get_collection_depth`），超出 2 层拒绝
- 顶层分组在 `#colbar` 渲染为 tab，选中后展开子分组
- `#tagbar`/`#colbar` 横向溢出：细滚动条可见（`scrollbar-width: thin` + 5px webkit 样式），`initHScroll(barId)` 把滚轮竖向增量转成 `scrollLeft`（按 `deltaMode` 归一化），`DOMContentLoaded` 时对两个栏各绑定一次
- 分组内右键空白区域 → 新建子分组
- 右键表情包 → 加入分组 → 弹窗列出当前大分组下的子分组

### 主窗口 UI/UX
- **折叠侧边栏分组可辨识**：`CollectionTreeNode.vue` 在折叠态（`collapsed`）以 `.tree-avatar`（26px 圆角块，取分组名首 1-2 字符，`avatarText` computed）替代统一文件夹图标，active 行高亮；展开态保持原图标
- **功能发现性**：meme 卡左上 `.fav-btn` 心形快捷收藏（hover/active/focus-visible 显示，selectMode/sortEnabled 时隐藏，`@click.stop`+`@pointerdown.stop`，调 `JsApi.toggle_favorite` 并本地翻转 `meme.favorited` 后 `refreshCollections`）；侧边栏树行 hover 显示 `.tree-more`「⋯」按钮（展开态，`@click.stop` 发 folder-context 复用右键菜单）
- **空状态**：`#empty` 从 kaomoji 改为 SVG 插画（`.empty-svg`）+「导入表情包」按钮（`showImportMenu`）
- **搜索清除**：搜索框右侧 `.search-clear`「×」按钮（`v-if="state.searchQuery"`，点击 `clearSearch()` 清空并 `search()`），输入框 `padding-right:32px` 防文字被按钮遮挡
- **垂直空间压缩**：titlebar 38px、`#search-wrap` padding 6px 12px、`#search` padding 7px 12px、`#tagbar` padding 4px 12px + max-height 52px、`#breadcrumb` padding 2px 12px、`#grid-wrap` padding 10px、pager padding 5px 10px
- **标题栏统一**：主/设置窗口关闭按钮均为 `×`；拖拽排序图标为上下箭头（非汉堡线）
- **右键子菜单点击展开**：`ContextMenu.vue` 的「加入小分组/新建子分组」从 hover 触发改为 click 切换（`onItemClick`，展开时锚定点击项右缘 `getBoundingClientRect().right + 4`，再次点击 `hide-submenu` 收起），保留越界 clamp，`has-submenu` 项显示 `▸` 指示符

### 未分类（虚拟分组）
- **`collection_id = -4`** 标识「未分类」虚拟分组：展示未加入任何分组的表情包（`meme_collections` 无记录），**不写入 DB/manifest，动态生成**
- `MemeDB.search()/count()` 新增 `uncategorized_only` 参数（`NOT EXISTS` 于 `meme_collections`），`search_memes` 中 `collection_id == -4` 路由到该参数，同时过滤隐写载体
- `get_init_data`/`get_collections` 按配置 `show_uncategorized`（默认开）决定是否追加 `-4` 条目（`get_collections` 中放于 `-2`/`-3` 之后）；设置页「分组显示 → 显示未分类分组」开关（`s-show-uncategorized`），保存到 `save_settings` 的 `show_uncategorized`
- 前端走通用集合渲染路径：计数为 0 时自动隐藏（`renderCollections` 的 `count === 0` 过滤）；可拖拽排序（复用全局 `sort_order`，走 `reorder_memes` 持久化，`canReorderMemes` 对 -4 返回 true）；无特殊右键菜单
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
- **前端 UI**: 设置页「导入」分组下 `.import-row` 列表行（硬编码 SVG 图标 + 名称），点击手机版 QQ 行直接开始导入并弹进度覆盖层；其余导入来源点击先弹配置对话框再开始
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
- **GUI 集成**: `webui.py` 的 `_QQNT_STATE`/`_qqnt_worker` 后台驱动 + `SettingsApi.qqnt_*` 方法（`qqnt_check_env`/`qqnt_pick_ini`/`qqnt_pick_userdata`/`qqnt_pick_base`/`qqnt_start`/`qqnt_get_progress`/`qqnt_cancel`/`qqnt_open_dir`）；设置页「电脑版 QQ（QQNT）」`.import-row` 点击开向导（环境/选账号 → 输出位置 → 进度 → 汇总），300ms 轮询 `qqnt_get_progress`；手动选择的 INI/用户数据目录持久化到 `config.json` 的 `qqnt_ini_path`/`qqnt_userdata_path`；`should_stop` 实现取消。**手动重定向始终可见**：`qqntRenderEnv` 在探测成功时也显示「选择配置文件/选择用户数据目录」按钮（`userdata_save_path` 传入时完全覆盖 INI 推导路径），应对多用户 Windows 下 `UserDataInfo.ini` 只记录第一个用户路径的场景

### Telegram 缓存导入 (tg_stickers.py)
- **入口**: `start_tg_import(webui, tdata_path, passcode, convert_webm)` — 后台线程执行完整流程；`tdata_path` 为空时回退到配置 `tg_tdata_path`，再自动检测
- **tdata 路径检测** (`find_tdata_path`): 跨平台回退链 — Windows `%APPDATA%\Telegram Desktop\tdata` → macOS `~/Library/Application Support/Telegram Desktop/tdata` → Linux `~/.local/share/TelegramDesktop/tdata` + Snap/Flatpak 变体；未找到则报 `error_code="no_tdata"` 引导手动指定
- **手动指定目录**: 设置页「手动指定 tdata 目录」按钮（`SettingsApi.pick_tg_tdata`）弹文件夹对话框，`is_valid_tdata()` 校验含 `key_datas`/`key_data`，通过后持久化到 config 键 `tg_tdata_path`（下次启动预填显示）；导入失败弹窗内 `error_code` 为 `no_tdata`/`invalid_tdata`/`no_cache` 时显示「手动选择 tdata 目录」重试按钮
- **解密机制**: Telegram Desktop 缓存使用 AES-IGE（TDF$ 文件）和 AES-CTR（TDEF 文件）加密，本地密钥从 `tdata/key_datas` 读取，通过 PBKDF2-HMAC-SHA512 派生（有本地密码时 100k 迭代，无密码时 1 次）；`bad_key` 错误提示本地密码场景
- **解密流程**: `read_local_key()` 读取密钥 → 遍历 `user_data/cache` + `user_data/media_cache` → `decrypt_tdf_file()`/`decrypt_tdef_file()` 按魔数识别格式解密 → `detect_extension()` 通过文件头识别扩展名 → 仅保留 webp/webm
- **webm 转换** (`convert_webm_to_webp`): 默认开启，ffmpeg 将 webm 转 animated webp，**有损 q80**（`-lossless 0 -quality 80`，无损编码实测 11-35s/个过慢改用有损，贴纸场景质量几乎无损），`-loop 1` 循环播放，保持宽高比（最长边 512，不放大），删除原 webm；转换前 `_check_ffmpeg()` 预检，缺失时报 `error_code="no_ffmpeg"` 中止；**单个转换失败的文件跳过不导入**（`convert_failed` 计数并在完成消息提示）。**并行转换**：`_tg_worker` 内用 `ThreadPoolExecutor(max_workers=min(os.cpu_count(), 4))` 受控并发，实测单张 ~1.7s → 4 路约 2.9x 加速（千张 30 分 → ~11 分）；进度 `done/convert_failed` 在 `_TG_LOCK` 内原子累加，非 webm（webp）直接透传并计入进度；进度条按 `done/total`（total=全部待处理含 webp）平滑递增。**取消/回收**：`convert_webm_to_webp` 用 `Popen`+有界 `communicate(timeout)`，受 `_TG_ACTIVE_PROC` 集合（`_TG_LOCK` 保护）跟踪活动进程；`cancel_tg_import()` / `_reset_state()` 对所有运行中进程 `terminate()`；`_reap_proc()` 统一回收——kill 后无条件 `wait`（纠 zombie），wait 超时二次 SIGKILL 兜底，**仅进程实际退出（`poll()` 非 None）才从 `_TG_ACTIVE_PROC` 移除**；转换循环 `finally` 用 `executor.shutdown(wait=True, cancel_futures=True)` 等待已启动 future 退出，避免与 temp_dir 清理/下次导入交错。**ETA 用 `time.monotonic()`**（`_TG_T0` 起点与计算同单调时钟）。**防双 worker**：`start_tg_import` 在 `_TG_LOCK` 内检查后立即 `_update_tg(status="scanning")` 占位运行态，线程在锁外创建，并发第二次调用在锁内见 scanning 即返回 False
- **静态版去重** (`dedup_static_against_animated`): Telegram 对同一动态贴纸缓存两份（512 webm 动画 + 320 webp 静态版），入库前用 PIL 识别动画 webp（`n_frames>1`），将每个静态 webp 与所有动画 webp 首帧做**归一化灰度差分**（白底合成 32×32，阈值 diff<0.02，实测匹配组 0.002-0.005 / 非匹配组 >0.1 间隔安全），内容一致的静态版跳过只保留动画版；无动画或 PIL 缺失时原样返回；`.webm` 文件（未转换时）不受影响。实测 127 静态中 45 个被判重跳过，0 误杀 0 漏跳，全量比较耗时 ~2s
- **进度状态** (`_TG_STATE`): `idle` → `scanning` → `loading_key` → `decrypting` → `converting` → `importing` → `done`/`error`/`cancelled`，含 `error_code` 字段，前端 300ms 轮询 `get_tg_import_progress()`。**ETA 展示**：`_TG_STATE["elapsed_s"]` 由 worker 起点 `_TG_T0` 计算，`_refresh_tg_elapsed()` 在 `_update_tg`/`get_tg_progress` 内按运行中状态推进（idle/结束不推进）；前端 `settings.js` 的 `updateTgEta()` 据 `elapsed_s` + `progress` 线性外推「已用 X · 预计剩余 Y」（`formatDuration()` 折算分钟/秒），`tg-import-eta` 元素随轮询刷新、overlay 打开时清空
- **入库**: 解密到临时目录后调 `webui._do_import()` 入库，完成后自动清理临时文件
- **取消**: `cancel_tg_import()` 设置标志位，工作线程在每个阶段检查并中止
- **前端 UI**: 设置页「导入」分组下 `.import-row` 列表行（硬编码 SVG 图标 + 名称），点击对应行弹出该软件的导入对话框（Telegram：tdata 目录手动指定 + 本地密码 + WebM 转换开关 → 进度覆盖层，错误时 `no_tdata`/`invalid_tdata`/`no_cache` 显示「手动选择 tdata 目录」重试按钮）
- **多账号**: Telegram Desktop 多账号共享 `user_data/cache`，无法区分来源账号，统一提取
- **透明动画（已解决）**: Telegram 视频贴纸 webm 内含有效 VP9+alpha（`yuva420p`）数据，但 ffmpeg **原生 VP9 解码器会静默丢弃 alpha 平面**（解码结果全不透明），导致转换出的动画 webp 背景不透明。修复：`convert_webm_to_webp` 在 `-i` 前加 `-c:v libvpx-vp9` 强制使用 libvpx 解码器保留 alpha。实测 48 个 webm 中 47 个恢复透明，透明像素分布与同表情静态 webp 完全一致

### 抖音表情包导入 (douyin.py + abogus.py)
- **架构**: 纯协议驱动（无浏览器自动化），`src/abogus.py` 提供 ABogus 签名算法绕过抖音 WAF，`curl_cffi` 模拟 Chrome 124 TLS 指纹绕过 JA3/JA4 检测
- **入口**: `start_douyin_import(webui, cookie)` — 后台线程执行完整流程，下载全部表情包
- **签名算法** (`abogus.py`): 纯 Python 实现，源自 GPL-3.0 项目 TikTokDownloader。流程：参数 SM3 哈希 → 与 UA 指纹/浏览器指纹/时间戳拼接 → RC4 加密 → 自定义 Base64 编码表输出。`gmssl.sm3` 做国密哈希
- **TLS 指纹绕过**: `curl_cffi.requests.Session(impersonate="chrome124")` 模拟 Chrome 124 的 JA3/JA4/H2 指纹，WAF 视为合法浏览器
- **Cookie 认证**: 用户从浏览器复制完整 Cookie 字符串 → 解析 key=value 注入 Session。额外自动预置基础 Cookie（ttwid、verifyFp、s_v_web_id、msToken）无需登录也可获取部分接口数据
- **API**: `GET /aweme/v1/web/im/resource/list/aggregation` 分页拉取自定义表情列表，参数 `scenes=CUSTOM_STICKER_PAGE`，每页 100 个
- **URL 签名**: 每个请求需附加 `a_bogus` 参数，由 ABogus 算法对 URL 参数 + HTTP 方法 + 浏览器指纹计算得出
- **下载**: 优先取 `animate_url.url_list`（动图），回退 `static_url`，`curl_cffi` 保持 `impersonate="chrome124"` 下载
- **入库**: 下载为临时文件 → 调 `webui._do_import()` 哈希去重入库 → 原始 WebP 格式保存（不转 GIF，保留最佳画质和最小体积）
- **进度状态** (`_DOUYIN_STATE`): `idle` → `running`（含 message/progress/done/total）→ `done`/`error`/`cancelled`，前端 300ms 轮询 `get_douyin_import_progress()`
- **取消**: `cancel_douyin_import()` 设置标志位，工作线程检查后中止
- **错误码**: `login_failed`（Cookie 无效）、`sign_failed`（403 签名失败）、`no_stickers`（无表情数据）
- **前端 UI**: 设置页「导入」分组下 `.import-row` 列表行（硬编码 SVG 图标 + 名称），点击抖音行弹出对话框（Cookie 输入框 + 下载按钮 → 进度覆盖层），下载全部表情
- **GPL-3.0 合规**: `abogus.py` 按 GPL-3.0 分发（头部含原作者署名与协议链接），整体作品再分发需按 GPL-3.0 处理

### 微信导入 (wechat_probe.py + wechat_keyfinder)
- **架构**: 独立 C++ 二进制 `wechat_keyfinder` 处理 Windows 进程内存取证（读取微信进程内存提取密钥），Python 侧通过 subprocess + JSON 协议协调完成 DB 解密/SQLite 查询/CDN 下载/入库；仅 Windows
- **目录层级**: 微信文件目录（root，默认 `%USERPROFILE%\Documents\xwechat_files` 或 `\WeChat Files`）→ 账号目录（root 下 `wxid_*` 文件夹，每个微信账号一个）→ `db_storage/emoticon/emoticon.db`（表情库，加密）+ `db_storage/favorite/favorite.db`（收藏库）
- **环境检测** (`inspect_wechat_environment`): 传入路径 basename 以 `wxid_` 开头则视为单账号，否则扫描子目录收集所有 `wxid_*`；每账号 `_inspect_account` 检查 DB 是否存在且为 SQLite header（否则 `encrypted_index`）；返回 `{status, reason, root, root_exists, account_directory_count, accounts: [{id, path, status, reason, db_path}]}`
- **账号选择**: `_pick_account` 未指定且多账号时返回 None，调用方报 `multiple_accounts` 引导前端选择；`list_wechat_stickers`/`start_wechat_import`/`_wechat_worker` 支持 `account_path` 参数指定账号
- **密钥提取**: 二进制扫描微信进程内存，通过特征码定位密钥对象（RVA 偏移在 `config/offsets.json` 配置），XOR 解码 + salt 比对 + HMAC-SHA512 校验。**掩码恢复为主路径**（`find_wechat_key_masked`）：利用 DB 前 16 字节 salt 反推 32 字节 XOR 掩码，按 `x'<96hex>'` 格式识别被掩码的 99 字节密钥缓冲，**无需 RVA**，微信升级不易失效；旧 RVA 特征码扫描仅作回退；`--key <hex64>` 可注入已验证密钥绕开取证。**多进程**：未指定 `--pid` 时枚举所有 `Weixin.exe` 逐个尝试，掩码恢复天然命中运行目标账号的进程（`key_not_found` 表示均未命中）
- **DB 解密** (`_decrypt_database`): AES-256-CBC 逐页解密（每页 4096 字节，页 1 带 16 字节偏移，IV 取页尾 80 字节偏移处），首页替换为 "SQLite format 3" header；**合并 WAL**（`_apply_wal`）：微信运行中表结构与记录在 `emoticon.db-wal` 里，按 WAL 帧（24B 头 + 4096B 加密页）解密并回写到对应页，主文件旧快照 + WAL 帧 = 完整数据
- **元数据查询** (`_query_sticker_metadata`): SQLite 查询 `kNonStoreEmoticonTable`（type/md5/aes_key/cdn_url/encrypt_url/extern_url），返回 md5+url+aes_key 列表
- **下载校验** (`_download_sticker`): urllib 下载 → 魔数识别扩展名（PNG/JPG/GIF/WebP/BMP）→ 带 `aes_key` 时 AES-128-CBC 解密（IV=key）；`_detect_image_ext` 校验合法才返回。**防 SSRF**：仅允许白名单 CDN 主机（`vweixinf.tc.qq.com`/`wxapp.tc.qq.com`），解析后拒绝回环/私网/链路本地地址，重定向逐目标复检
- **完整性校验**: `verify_binary_integrity` 执行前校验二进制 SHA-256，未配置真实哈希（占位符 `PLACEHOLDER_UPDATE_ON_RELEASE`）时**默认拒绝执行**；开发/本地测试可用环境变量 `OHMYMEME_INSECURE_SKIP_HELPER_HASH=1` 跳过。**发布前必须**用 `certutil -hashfile wechat_keyfinder.exe SHA256` 计算真实哈希填入 `_WECHAT_KEYFINDER_SHA256` 并移除占位符
- **前端 UI**: 设置页「导入」分组下 `.import-row` 列表行（硬编码 SVG 图标 + 名称），点击微信行弹出对话框（目录选择 + 环境检测 + 多账号下拉 → 进度覆盖层）

## 构建 & 测试
```bash
pip install -r requirements.txt
npm install                 # Vue 前端依赖（开发时）
npx vite build              # 构建 Vue 前端 → webui/dist/ohmymeme.js
python -m src     # 开发运行
python -m pytest tests/ -v  # 运行测试
ruff check src/   # lint 检查
black src/        # 格式化
python scripts/build.py  # PyInstaller + InnoSetup 完整构建
python scripts/build.py --lang en  # 指定语言构建
```
- **构建自动编译 Vue 前端**: `build.py` 的 `ensure_vue_frontend()` 在打包前检查 `src/webui/dist/ohmymeme.js`（被 gitignore，CI 全新检出缺失），缺失时自动 `npm ci`（有 lockfile，否则 `npm install`）→ `npx vite build`，失败则中止构建；构建机需 node/npm（GitHub Actions runner 预装），dist 已存在时直接跳过
- **Linux 打包（GTK）**: `--linux` 时 `build.py` 自动传 `--additional-hooks-dir scripts/hooks`（收集 WebKit2/Soup typelib）并 `--collect-all gi`，把 PyGObject/GTK 打进产物，脱离系统 python3-gi 运行；构建机需装 `python3-gi gir1.2-webkit2-4.1 libgirepository1.0-dev libgirepository-2.0-dev gobject-introspection` 并 `pip install PyGObject`（对应 `build.yml`/`nightly.yml` build-linux job）；**PyGObject ≥3.52 硬依赖 girepository-2.0**（Ubuntu 24.04 对应 `libgirepository-2.0-dev`），只装 1.0-dev 会在 meson 元数据阶段报 `Dependency 'girepository-2.0' is required but not found`；deb `Depends: python3-gi, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0`

**前端架构**：主窗口为 Vue 3（`vue-src/`，Vite 构建 IIFE 单文件），设置窗口仍为 vanilla（`webui/settings.*`，独立 webview）。修改主窗口前端后需 `npx vite build` 再运行。

`make` 命令仅供参考（`make run`/`make test`/`make lint`/`make format`/`make build`），macOS/Linux 下可能不可用，优先使用原生 Python 命令。

## CI (GitHub Actions) — 三个独立 workflow
- **check.yml**: Ubuntu, lint + test, push 和 PR 到任意分支均触发
- **build.yml**: Windows + Linux + macOS 三平台，仅在 `check` 通过 main 分支后自动触发，也支持 `workflow_dispatch` 手动触发
  - `build-windows`: InnoSetup 安装包 `dist/OhMyMeme-*-setup.exe`
  - `build-linux`: AppImage/deb/rpm（`--linux`）
  - `build-macos`: `.app` + `.dmg`（`--macos`，PyInstaller `--windowed` + iconutil 生成 icns）；矩阵双架构 `arm64`（macos-latest）+ `x86_64`（macos-15-intel），产物 `OhMyMeme-v*-{arch}.dmg`
- **nightly.yml**: Windows + Linux + macOS 三平台每日定时（UTC 20:00）+ `workflow_dispatch`，从 `dev` 分支构建非正式版（`--nightly`，版本号为 `nightly`）并发布为 `nightly` prerelease；`updater.py` 的 `_parse_release` 跳过 prerelease 与含 `nightly` 的 tag，**软件更新绝不会指向 nightly**
- 上传 `dist/OhMyMeme-*-setup.exe` / `dist/OhMyMeme-v*-x86_64.AppImage` 等作为 artifact

## 版本管理
- 版本号唯一来源: `src/__init__.py` → `__version__ = "*.*.*"`
- `scripts/build.py` 用正则从该文件提取版本；`--version`/`--nightly` 会临时改写 `__init__.py` 构建，完成后恢复
