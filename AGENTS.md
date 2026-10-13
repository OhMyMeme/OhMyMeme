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
- **Vue 3 + Naive UI + Lucide**（两窗口独立 Vite IIFE 入口，共用主题与设计 token；界面图标统一用 `@lucide/vue`）
- **PIL/Pillow** (缩略图, 剪贴板图像)
- **pystray** (托盘, 惰性导入避免 headless CI 崩溃)
- **InnoSetup** (Windows 安装包) / **PyInstaller** (打包)
- **GitHub Actions** (lint+test on Ubuntu, build+installer on Windows/Linux/macOS)

## 开发工具链
- `mise.toml` 与 `mise.lock` 是共享工具链版本的来源；使用 `mise install python node npm --locked` 安装锁定版本
- 使用 `mise run <task>` 执行项目工作流；运行 `mise tasks ls` 查看可用任务
- `mise.local.toml`、`mise.local.lock` 及其他本地 mise 状态不得提交
- 前端类型门禁采用 `tsconfig.json` 的严格配置：主窗口 `app/`/`features/` 的 TS/Vue、`main/shared` TS、设置窗口与 `tests/frontend` TS 纳入根文件；`main/app/main.ts` 与 `main/shared/bridge.ts` 暂不作为根文件，被 import 的 bridge 仍进入依赖检查；`main_window_virtual` 接线测试不再临时排除，类型检查不等于运行时 Bridge 数据验证

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
- 新增依赖同时更新 `requirements.txt` 和 `environment.yml`；开发质量依赖更新 `requirements-dev.txt`
- **PR 贡献必须确保 `mise run lint && mise run typecheck-python && mise run test-python && mise run typecheck-frontend && mise run test-frontend && mise run test-contracts && mise run build-frontend && mise run e2e && mise run package-smoke` 全部通过**，CI 会检查这些门禁

## 关键目录

完整的仓库文件树、目录职责、生成文件标记和依赖方向见 [`docs/project-structure.md`](docs/project-structure.md)；本文档继续作为行为约束和开发规范的权威来源。

```
src/              # 源码根与固定运行时静态资产
  ohmymeme/       # 唯一 Python 业务包
    app/          # CLI 入口、Container、Catalog 与 Settings
    core/         # 纯领域值/规则、Config、Crypto、SQLite、资产、导入和 Manifest
      plugins/    # 插件 manifest、contracts、ports、policy、registry 与运行时边界
    services/     # 更新、同步与局域网服务
    integrations/ # 平台能力与外部导入适配器
    presentation/ # pywebview、Bottle 与前端源码
  wechat_keyfinder/ # 微信密钥提取 C++ 辅助二进制源码（CMake 构建）
  ohmymeme/presentation/frontend/ # 两窗口前端源码（Vue 3 + Naive UI）
    shared/      # 两窗口共用 Naive 主题、设计 token 与转义/Markdown 工具
    main/        # 主窗口（Vite 构建，产物到 src/webui/dist/ohmymeme.js）
      app/       # App.vue provider 壳、MainWindow 启动/生命周期、Vite 入口与主窗口样式
      features/  # memes/collections/tags/sorting/imports/sync/updates/lan/dialogs
      shared/    # 唯一 pywebview bridge、转义/焦点工具、TS 类型与 generated DTO
    settings-vue/ # 设置窗口（Vite 构建，产物到 src/webui/dist/settings-vue.js）
      app/       # App.vue provider 壳与初始化、SettingsShell 导航装配、Vite 入口与布局样式
      features/  # about/backup/base/danger/import/logs/network/plugins
      shared/    # 设置窗口受控桥接、plugin-ui 校验、store 与 markdown
  webui/          # 前端静态文件
    vue.html      # 主窗口唯一入口（Vue）
    vue-settings.html # 设置窗口入口（Vue）
    import-frame.js   # 插件详情页 iframe 协议 SDK 资产
    plugin-ui.json    # 宿主固定插件 UI 投影
    dist/         # [generated] Vite 构建产物（gitignored）：ohmymeme.js + settings-vue.js
plugins/          # 九个官方插件源码与打包输入（不随应用分发，需按需导入）
  source.qqnt/    # QQNT 源插件
  source.telegram/ # Telegram 源插件
  source.douyin/  # 抖音源插件
  source.wechat/  # 微信源插件
  sync.ftp/       # FTP 同步插件
  sync.s3/        # S3 同步插件
  sync.r2/        # R2 同步插件
  sync.webdav/    # WebDAV 同步插件
  transport.lan/  # 局域网传输插件
config/
  offsets.json    # wechat_keyfinder 易变参数（版本号等，微信升级时只改此文件）
  plugin-manifest.json # 九个官方插件的 canonical 分发清单
scripts/
  build.py        # PyInstaller + InnoSetup 构建脚本 (i18n zh/en)
  plugin_docs_check.py # Todo16 固定插件文档/入口/边界离线校验
  plugin_packaging.py # 九个官方插件的元数据、ZIP 打包/安装与 source/frozen parity 校验
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
  frontend/meme_cache.test.ts # vitest: useMemes 连续缓存模型纯逻辑（分页/裁剪/远跳/代次/重试/pin）
  frontend/main_window_virtual.test.ts # vitest: MainWindow 虚拟网格接线桩（全局槽位/自研 marquee/自动滚动与补页/drop/取消代次/saving/footer 重试/回顶/手势禁用/卸载；mock 手动挂载区间）
  frontend/grid_interaction.test.ts # vitest: gridInteraction 纯函数（框选矩形/XOR/槽位/速度曲线/落点顺序）
  fixtures/grid_slot_probe.cjs # Node 全局槽位同源探针（读 gridInteraction.ts）
```

## js_api 桥接规范
- Todo11 固定 UI 边界：`api/ui_contributions.py` 严格校验宿主 `src/webui/plugin-ui.json`，生产 Bottle `/api/plugin-ui` 只返回有效快照；设置窗口在挂载外壳前整体校验该投影并加载设置，原来源行/同步面板/固定 API 参数与进度读取实际消费该数据。数据从 Todo6 action 矩阵生成，`plugin_ui_dispatch.py --check` 校验 schema/fixture/产物一致性；保持原 SVG、文本、布局、公开 Bridge/取消/结果，手机版 QQ/ADB 不参与。固定九条投影之外，另开声明式 UI 注入白名单：插件 `ui.json` 只声明 `imports.row`/`plugin_detail.panel` 与 `plugin_detail.iframe`，字段类型受白名单约束、宿主渲染；详情页 iframe 需用户显式加载、`sandbox="allow-scripts"`、严格 CSP、固定 postMessage 协议与 `ui.action` 动作 allowlist。禁止 UI 记录持久化到 Config、任意额外字段、任意 HTML/JS 注入宿主 DOM、动态 Bridge 或通用 renderer/DSL。
- 子进程运行时：`core/plugins/runtime/`（protocol/channel/process_tree/manager/worker/seeding）负责 worker 生命周期与固定 RPC；四个导入源经 operation RPC 执行，`app/runtime_imports.py` 保持宿主导入 worker 的公开形状但执行体在 worker。宿主保留 coordinator 线程、sink、昵称缓存与外部导出投影，插件只写 operation staging。
- `plugins/sync.{ftp,s3,r2,webdav}` 在后端会话 RPC（`sync.open/call/close`）中执行网络实现；`services/sync/backends.py` 保留宿主 staging、布尔校验、列表过滤、脱敏与 push/pull 编排。leases、manifest/order、hash 和 pull commit 全留宿主；`connect_ftp` 旧连接 ABI 已删除。
- `plugins/transport.lan` 在 worker 内持有 socket/UDP 发现/IP_PKTINFO；宿主经 `RuntimeLanTransport/RuntimeLanConnection` 代理读写字节，`services/lan/server.py` 保留安全/审批/命令与协调器所有权。
- `plugins/source.wechat` 持有账号/SQLite/WAL/CDN 算法与 helper JSON 协议；宿主 `integrations/imports/wechat.py` 只保留 helper 持久缓存/SHA-256/offsets 策略，经 `helper.wechat` RPC 提供 operation 内副本。helper 由插件在 worker 内 `Popen`，随 worker 整树回收。
- `plugins/source.telegram`/`plugins/source.douyin` 持有解密/转换/远程协议与 ABogus；passcode/cookie 仅按操作注入 worker，不进入持久 Config；旧 integration 仅保留 `__getattr__` 命名代理。
- `plugins/source.qqnt` 持有提取算法；宿主经固定 `inspect` 查询注入昵称回调，缓存与外部导出投影仍在宿主。
- `JsApi` 暴露给主窗口，`SettingsApi` 暴露给设置窗口
- JS 调用: `pywebview.api.methodName(...args)` → 自动序列化
- JS 辅助函数: `async function api(method, ...args) { return await pywebview.api[method](...args); }`
- 返回类型: `str` / `int` / `bool` / `dict` / `list`，错误返回 `None` 或 `{"ok": false, "error": "..."}`
- 图片传输: 缩略图通过 `/api/thumb/{id}` HTTP 路径渲染，不通过 JS API JSON
- 固定插件动作边界位于 `presentation/desktop/api/plugin_dispatch.py`：四个导入 provider 经 runtime 调度，sync/LAN 仍由宿主固定映射处理；ADB/手机版 QQ 不进入该边界。公开方法/默认值/返回对象/取消/进度/固定 UI 必须保持兼容。`pick_wechat_root` 是零参数方法。
- 插件在独立 worker 进程中运行，宿主只传窄配置、按操作密钥与 operation 临时目录；禁止把完整 Config、WebUI、DB 或宿主持久路径传给插件，禁止任意 execute、动态 Bridge 注册或 HTML/脚本/UI DSL。安装仅限本地 ZIP（`seeding.install_plugin`，meta 最小化：仅 id/version/entry，官方 ID 不得占用；不做包安全校验），卸载仅限第三方，重载 = 停止 worker 后按磁盘版本重新加载。
- ABI/action 矩阵由 `scripts/plugin_abi_matrix.py --write` 从固定动作、Bridge/facade 和实际调用方生成至 `docs/plugin-{abi,action}-matrix.json`，`--check` 校验 `schemas/plugin/abi-matrix.schema.json` 并执行离线 facade/dispatcher 探针；未知 action、错参数、无效结果及 provider 缺失/禁用/不兼容必须拒绝或返回原哨兵，不得调用其他 provider。

## 官方插件文档与重组边界

- `config/plugin-manifest.json` 是唯一的 canonical 清单。固定 provider/入口点为 `ohmymeme.plugins.v1:source.qqnt = ohmymeme_plugin_qqnt:create_plugin`、`ohmymeme.plugins.v1:source.telegram = ohmymeme_plugin_telegram:create_plugin`、`ohmymeme.plugins.v1:source.douyin = ohmymeme_plugin_douyin:create_plugin`、`ohmymeme.plugins.v1:source.wechat = ohmymeme_plugin_wechat:create_plugin`、`ohmymeme.plugins.v1:sync.ftp = ohmymeme_plugin_sync_ftp:create_plugin`、`ohmymeme.plugins.v1:sync.s3 = ohmymeme_plugin_sync_s3:create_plugin`、`ohmymeme.plugins.v1:sync.r2 = ohmymeme_plugin_sync_r2:create_plugin`、`ohmymeme.plugins.v1:sync.webdav = ohmymeme_plugin_sync_webdav:create_plugin`、`ohmymeme.plugins.v1:transport.lan = ohmymeme_plugin_lan:create_plugin`。
- 零参数 `create_plugin()` 每次都返回独立状态实例。registry 在加载前核验 ID、入口点和 API；缺失、禁用或不兼容只返回该固定动作的旧失败哨兵，绝不回退或替换其他 provider。
- 宿主拥有 SQLite、缓存、manifest、Config、UI、原生能力与 LAN 安全边界。插件仅接收窄配置、限域密钥和 operation 临时目录，不接收持久 Config、缓存或存储路径；持久配置、数据库、图片存储、manifest 提交、Bridge/UI、原生窗口/剪贴板/拖拽、LAN 密钥协商/审批/加密/命令均不得移入插件。
- OperationCoordinator 管理 provider 的启动、取消和资源回收。宿主先注册线程、helper 子进程、socket 和临时资源，再允许阻塞；operation drain 后才释放宿主 lease 和临时目录。passcode、Cookie 与同步凭据是 transient operation secret，不进入持久 Config 或日志。
- 分发模型：官方插件不随冻结产物/安装包分发，也不随应用启动自动种子。导入有两种方式：GitHub 仓库导入（公开仓库根目录 `plugins/{plugin-id}/`，含 `plugin.json` 与 `<package_root>/` 或 `src/<package_root>/` 包目录；默认 ref 匹配当前版本 tag，404 回落 HEAD，直连失败经 GitHub 镜像 `github.dpik.top`/`gh.dpik.top`/`gh-proxy.org` 重试，归档限额 50MB/解压 20MB 并拒绝符号链接与路径穿越）与本地 ZIP（`OhMyMeme-plugin-<id>-v<version>.zip`，由 `--pack-zips` 生成，随 Release 附件发布）。两种方式共用安装事务：canonical 身份校验、原子版本切换与 state 记录（含 source 元数据）；未导入时相关入口隐藏或返回原失败哨兵，旧 `origin=="bundled"` 平铺种子副本在启动时清理。
- `scripts/plugin_packaging.py` 校验官方 source/frozen staging 的模块、入口元数据、manifest 和许可证文件，并提供 `--pack-zips`（发布 ZIP 附件）、`--install-dev`（按真实安装事务装入指定 data_dir）与仓库 `plugins/<id>/plugin.json` 门禁；source/frozen staging 一致性只覆盖源码、入口元数据与 staging，不等同于对最终冻结可执行文件的实际构建验证。官方插件脱离安装包后，`docs/plugin-license-matrix.json`、`NOTICE`、`LICENSES/`、`THIRD-PARTY-NOTICES/` 的 frozen 证据范围重界定待后续跟进；这些文件仍是当前许可证和发布范围的证据入口。
- 九个 provider 的 source/frozen 分发基线由 `scripts/plugin_packaging.py` 校验，只覆盖源码、入口元数据与 staging，不等同于对最终冻结可执行文件的实际构建验证。`scripts/plugin_docs_check.py` 消费 inventory、`config/plugin-manifest.json` 和 `README.md`/`AGENTS.md`/`docs/project-structure.md`；其无效输入为 `fixtures/plugin-parity/inventory-invalid.json`、`fixtures/plugin-parity/docs-invalid/README.md` 与 `fixtures/plugin-parity/docs-conflicting-nonfeatures/README.md`。
- 外部下载的微信 helper 及其 CMake/OpenSSL 输入不随制品交付；本地 helper 源码映射不构成外部 helper EXE 的来源到二进制可复现性证明。不得把 source/frozen staging 或许可证证据表述为最终 helper 或最终冻结可执行文件的实际构建证明。
- 不提供 marketplace 或不受信任插件沙箱。
- 第三方插件仅支持本地 ZIP 安装、卸载与重启生效的启用管理；不增加动态 provider 发现、任意执行、动态 Bridge 或通用插件 DSL。UI 仅限声明式 UI 注入白名单与插件详情页沙箱 iframe。

## 关键实现细节

### 系统托盘
- `TrayManager` 在 daemon 线程运行
- 惰性导入: `_pystray_ok()` 避免 headless CI (X11 `DisplayNameError`)
- WSL 自动跳过托盘
- macOS 跳过托盘：pystray 在 macOS 需在主线程抢占 NSApplication runloop，与 pywebview 主循环冲突（会导致窗口无法启动或段错误），与 Linux GTK 冲突同理

### 全局快捷键
- 三级降级: `keyboard` → `pynput` → 200ms 轮询 (`keyboard.is_pressed`)
- **运行期失效自愈**：`keyboard` 0.13.5 的 `GenericListener` 处理线程（`processing_thread`）一旦因未捕获异常崩溃即永久失效（进程存活、界面正常但热键无响应，需重启软件才恢复）。`GlobalHotkey` 两道防线：①`_try_keyboard` 用 `make_safe` 把回调包成 `_safe_callback`，吞掉回调异常，防止其杀死 `processing_thread`；②注册后启动 daemon 守护线程（`_start_keyboard_watchdog`，`KEYBOARD_WATCH_INTERVAL`=5s）周期检查 `keyboard._listener` 的 `listening_thread`/`processing_thread` 是否存活，任一死亡即 `_reregister_keyboard`（`remove_hotkey` → 置 `listener.listening=False` → `start_if_necessary()` → 重新 `add_hotkey`）自动重挂；③（Windows）**钩子心跳探针**：WH_KEYBOARD_LL 会被系统静默摘除（睡眠恢复/回调超时/显示切换），此时线程仍在泵消息、存活检查不可见——`_hook_health_check` 每 `KEYBOARD_PROBE_INTERVAL`(30s) 经 `keybd_event` 注入一次无害 F15 探针，`KEYBOARD_PROBE_TIMEOUT`(15s) 内钩子未上报任何键盘事件（`keyboard.hook` 观察者刷新 `_hook_last_seen`，用户自身按键也算）即判定钩子失效，`_restart_keyboard_listener` 以 `PostThreadMessageW(WM_QUIT)` 结束旧监听线程（其钩子随线程退出被系统移除；线程拒不退出则中止重启避免双钩子导致热键触发两次）→ `start_if_necessary()` 重装钩子 → 重挂热键，约 45s 内自愈。**热键事件日志**：`_get_file_logger` 惰性创建独立 logger，把注册/回调异常/线程死亡/自愈重挂等事件追加到 `data_dir/hotkey.log`（`_log_hotkey_event` 同步写文件+控制台，初始化失败降级为常规 logger 不阻塞）。**pytest 下禁用文件日志**（`PYTEST_CURRENT_TEST` 环境变量守卫）——TestHotkeyWatchdog/test_startup 会触发注册/重注册日志，夹具错误（如 inject-fail）曾污染真实 hotkey.log 被误读为运行期自愈失败（真实自愈必先记录「监听/处理线程已退出」，日志中无此行即无真实失效）。**重注册与注销的正确性**：`_reregister_keyboard` 返回 bool 且与 `unregister` 持同一 `_reregister_lock` 串行化——`add_hotkey` 失败时置 `_reregister_pending=True` 并返回 False（不记录成功、守护下轮继续重试），成功才清 pending 并记成功事件；注销已开始（回调已清空或停止事件已置位）时重注册直接返回 False 不重新挂热键。**生命周期代次 token**：`_watchdog_gen` 仅在 `unregister` 递增（`register`/`_try_keyboard` 不递增——同一实例重复 register 时旧 watchdog 仍受 `unregister` 已递增的代次约束），`_start_keyboard_watchdog` 捕获当前代次并由 `_reregister_keyboard(listener, gen)`/`_restart_keyboard_listener(listener, gen)` 在锁内校验 `gen == _watchdog_gen`，旧 watchdog（旧代次）的重注册操作直接返回 False，杜绝注销后立即重新注册时旧线程对新热键的误操作。
- macOS 跳过 `keyboard` 库（darwin 后端需 root 权限，报 `Error 13` 且 root 下会段错误），直接走 `pynput`（CGEventTap，需辅助功能权限）
- WSL 无法捕获全局快捷键
- 配置 `hotkey_show_at_mouse` 默认 `false`；仅 Windows 生效。开启后仅在全局热键将隐藏主面板显示时，按鼠标所在显示器工作区依次尝试 `(cursor_x, cursor_y)`、`(right-width, cursor_y)`、`(cursor_x, bottom-height)`、`(right-width, bottom-height)`，仅使用首个完整容纳窗口的候选位置；出错或没有可用位置时不移动。托盘保持普通切换，热键回调仍为零参数。
- WebUI 维护非持久的快捷键显示会话状态：仅隐藏主窗口被全局快捷键显示后，成功复制或成功原生向外文件拖拽才会自动隐藏；任意 hide、普通/托盘显示、LAN/其他 show、内部排序拖拽及失败交互均不会触发该自动隐藏。

### 窗口
- 主窗口 ~960×640 frameless, 设置窗口 720×560 frameless（每次 `_create_settings_window` 以主窗口当前位置居中创建——`x = 主窗口x + (宽-720)//2`，主窗口坐标不可用时交由系统摆放）
- 设置窗口是独立 webview：`open_settings` 每次销毁重建，`focus_settings_window` 仅做 z-order 提升
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
- `MemeDB.search()`: 动态 WHERE, 多标签交集用 `HAVING COUNT = len(tags)`；keyword 除 `filename`/`original_name` LIKE 外同时匹配标签名（`meme_tags` JOIN `tags` 子查询 LIKE），`count()` 同步该逻辑
- `MemeDB.add_tags_to_memes(meme_ids, tags)`: 批量合并追加标签（get-or-create + `INSERT OR IGNORE`，不清空各表情已有标签），返回实际存在的表情数；先过滤出实际存在的 meme id（外键开启时对缺失 id 写 `meme_tags` 会整批失败），批量写包 try/rollback/re-raise；供 JsApi `batch_add_tags` 使用
- `MemeDB.add_memes_to_collection(meme_ids, collection_id)` / `MemeDB.move_memes_to_collection(meme_ids, from_ids, to_id)`: 批量加组/移动的单事务实现（先校验表情 id 与目标分组存在，写入失败 rollback 后抛出）；按 `INSERT OR IGNORE` 实际新增关联计数（重复加入目标不计）；move 仅纳入实际属于 `from_ids` 子树的成员（非成员不受删除或移动影响），从子树删除后再加入目标，提交前级联清理源子树内变空的分组（迭代删除无成员且无子分组的叶子空组直到不动点，支持子组先空父组后空；仅限 from_ids 范围，子树外空分组保留；两处 FK 均 ON DELETE CASCADE，故只删叶子防波及）；供 JsApi `batch_add_to_collection`/`batch_move_to_collection` 使用（JsApi 负责目标解析/创建与「不能移入源分组自身或其子分组」校验——`create_collection` 会复用同名顶层分组，故该校验在目标解析后统一执行；move 成功后无条件重建 manifest——`moved==0` 时成员关系仍可能变化，如成员已在目标、仅从源移除）
- `memes.sort_order`: 自定义排序（拖拽更新），默认 0，查询 `ORDER BY sort_order ASC, updated_at DESC, id ASC`
- `collections.parent_id`: 多级分组支持（最多 3 层），`NULL` 为顶层分组
- `meme_collections.sort_order`: 分组内成员自定义排序
- `recent_uses`: `meme_id` + `used_at`，复制时 `INSERT OR REPLACE`，按 `used_at DESC` 取最近使用

### 配置
- `%APPDATA%/OhMyMeme/config.json` (Win), JSON 格式
- 密钥字段 (ftp_password, s3_secret_key 等) 用 Fernet 加密存储
- 全局单例: `get_config()`, `get_db()`
- `hotkey_show_at_mouse` 默认 `false`，控制 Windows 上全局热键显示隐藏主面板时是否按鼠标位置放置
- `cache_dir`（表情包图片目录）可自定义：配置键 `cache_dir` 非空时 `Config.cache_dir` 返回该路径，否则默认 `data_dir/cache`；设置页「存储位置」通过 `SettingsApi.pick_storage_dir`/`apply_storage_dir` 切换，`apply_storage_dir` 可选把旧目录文件递归迁移（跳过 `thumbnails`）；**切换后旧文件不再可见**，故未迁移时必须确保文件已存在于新目录；`_storage_dir_validation` 拒绝相对/相同/上下级目录以及 `data_dir`/`thumbnail_dir` 及其上下级（受保护路径）；DB/缩略图/manifest 仍留在 `data_dir`，数据库只存文件名，文件在新目录时按 basename 自动解析；`reset_settings` 恢复默认时保留 `cache_dir`。迁移为**后台三阶段幂等**设计（避免跨盘长拷贝时进程被杀导致分裂状态）：①复制阶段源只读（`O_EXCL` 排他写入，dst 已存在且大小一致视为已复制跳过——幂等；失败/取消仅清理本次新副本，源完好无分裂，不回滚）；②写配置（唯一切换点，此后新目录已完整）；③删源（失败仅残留旧目录冗余，不阻断）。迁移开始写 `data_dir/storage_migration.json` 清单、完成后删除；`main.py` 启动时若检测到未完成清单则后台幂等续跑（强杀/断电后重启自愈）。取消由 move 回滚改为删新副本，消除回滚自身失败风险

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
- **非阻塞检查**：`check_latest_cached(force=False)` 是唯一入口——**`_ensure_check_started` 先查 `_check_running`（在跑则一律返回 `pending`，含 force 刷新未完成时，绝不命中旧 `_check_result`），再对非 force + 新鲜缓存（`_CHECK_TTL`=24h）直接返回**；无缓存/缓存过期/`force=True` 触发后台 daemon 线程跑 `check_latest()` 填 `_check_result`+`_check_result_at`（`_check_lock` 保护，幂等只启动一次），立即返回 `pending: true`（永不阻塞网络 3.8s~20s+）。**generation token**：`reset_check_cache()` 推进 `_check_generation`，后台 `_task` 完成时仅当代号匹配才写结果，防在途旧任务覆盖 reset 后新状态。`webui.py` 的 `JsApi.check_update`/`SettingsApi.check_update` 支持 `(debug, force)` 透传；前端 `MainWindow.vue` 的 `checkUpdateAndPrompt`（onMounted/24h 定时）首发 `force=true`、pending 时转 `checkUpdateResult` 非 force 轮询，设置窗口 `features/about/AboutGroup.vue` 的 `checkUpdate` 首发 force、轮询暂取非 force——避免完成后再次 force 触发新检查造成永久 pending。**这解决了启动期间 `check_update` 同步阻塞曾导致的界面交互卡顿，及缓存不失效时 24h 定时器形同虚设的问题**
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
- **多线程服务器**：`bottle.run` 通过 `server_class=_ThreadedWSGIServer`（`ThreadingMixIn + WSGIServer`，`daemon_threads=True`）启用多线程——Bottle 默认 wsgiref 单线程串行处理，慢请求（`/api/contributors` 外网抓取、`/api/thumb` 现场生成缩略图）会阻塞其他路由投递，导致设置页 `settings-vue.js` 等静态资源排队、JS 监听未注册期间窗口可见但拖动/点击全部无效
- `/api/contributors` 结果带 1h TTL 缓存（模块级 `_CONTRIBUTORS_CACHE`，刷新在 `_CONTRIBUTORS_LOCK` 内单飞：**取锁后刷新时间并重查退避期**，等待中的并发请求不再重复抓取；刷新失败一律退避 60s 重试——有旧缓存回退旧缓存，无缓存冷启动失败返回 502，不再每个请求都反复触发 10s 慢抓取），设置页该图片加 `loading="lazy"`（位于默认隐藏的「关于」section，仅切换到该分组时才发起请求）；缩略图生成写盘为先写临时文件再 `os.replace` 原子替换（多线程下并发请求同一未缓存缩略图不再交错写产生永久损坏的缓存文件）
- `after_request` 统一加 `X-Content-Type-Options: nosniff` / `Referrer-Policy: no-referrer` / `X-Frame-Options: DENY`，`/api/` 路由 `Cache-Control: no-store`
- 文件名安全：`_safe_serve_filename`（webui）与 `_safe_remote_fname`（sync）拒绝含 `/` `\`、以 `.` `/` `\` `~` `..` 开头的名字；`_find_meme_file` 入口校验，远端 manifest 文件名在 `_fetch_remote_memes` 过滤 + `_pull_worker` 写盘前再防御
- 前端 XSS：两窗口共用 `frontend/shared/markdown.ts` 的 `esc()`/`renderMarkdown()`；通过现有 Bridge/Markdown 模块导出，动态文本默认使用 Vue 转义，仅转义后的更新说明允许 `v-html`
- **键盘无障碍（主窗口）**：全局 `:focus-visible` 焦点环（2px `var(--primary)`）；meme 卡/文件夹卡 `role="button" tabindex="0"` + Enter/Space 复制或打开分组（整理模式下卡片 Enter/Space 为勾选切换），标签栏 span 同理（`aria-pressed`）；标题栏图标按钮全部带 `aria-label`；弹窗焦点管理：`frontend/main/shared/bridge.ts` 的 `rememberFocus()`/`restoreFocus()`/`trapTabFocus()`（模块级 `_focusTarget` 记录打开前焦点、关闭归还、Tab 在弹窗内循环），InputDialog/TagEditor 打开聚焦输入框、ConfirmDialog 默认聚焦「取消」（危险操作需显式点「确定」）、CollectionBuilder 聚焦 `#cb-name`；`#meme-grid.sort-enabled .meme-card:focus-visible` 为 2px 实线焦点环
- **键盘无障碍（设置窗口）**：Naive 组件自带焦点样式，设置窗口布局与 `.nav-item.danger`/`.immediate-hint`/`.status-ok`/`.status-error` 等类在 `frontend/settings-vue/app/style.css`；`SettingsShell.vue` 处理全局按键（Esc 关闭设置窗口、弹窗打开时不触发；Ctrl+Enter 保存），弹窗与覆盖层焦点交由 Naive `NModal`；全局提示走 Naive `NMessage`（设置窗口 `store.ts` 的 `showToast` 由 `SettingsShell` 在 `NMessageProvider` 内注册的 `useMessage` 实例驱动；主窗口各组件直接 `useMessage`，`#toast` DOM 已移除）
- **设置窗口 UX**：表单控件改动经 `shared/store.ts` 的 `markDirty()` 置脏；`SettingsShell.vue` 在脏时关闭弹 Naive 确认「有未保存的更改」再关（取消/×/Esc 均触发），`save()`/`reset()` 成功后清脏；真正立即生效的控件（LAN 开关、密钥传输、存储位置「应用更改」）带 `.immediate-hint`「立即生效」标注；状态色收敛为 token `--success`/`--danger`，用 `.status-ok`/`.status-error` 类切换；复制处理等下拉走 Naive `NSelect`
- **关于页**：设置窗口左侧导航末项「关于」由 `frontend/settings-vue/features/about/AboutGroup.vue` 渲染：大号 OhMyMeme logo（`.about-logo`，span 用 `--accent`，复刻主窗口标题栏效果）、版本号+检查更新，更新对话框为 Naive `NModal`（下载进度/重试），及贡献者名单（`.about-contributors` 深色卡片）。贡献者头像不走外部直连：`/api/contributors` 路由（webui.py Bottle）用 urllib 抓取 `contributor.starsfire.top/TNTXZ/OhMyMeme` 的 SVG（该服务忽略 `?bg=` 参数且无 CORS 头，浏览器直接 fetch 会失败），用 `svg.replace` 剥离白色背景 `<rect>` 后以 `image/svg+xml` 返回，使圆形头像直接落在深色页面上；`@error` 时隐藏图片并显示「贡献者名单加载失败」回退文案
- **色彩体系（H2）**：完全采用 Radix Colors（dark）原生色阶与档位语义（vendor 自 `@radix-ui/colors` 3.0.0、值未修改，单处维护于 `frontend/shared/tokens.ts`，运行时注入 `:root`）；CSS/组件直接使用原生变量（`--gray-*`/`--blue-*`/`--red-*`/`--blue-a3` 等），无自定义语义别名；文字 11/12 档、实心控件 9 档（hover 10）、选中底 5 档或 alpha 3 档、边框 6/7 档。已知取舍：Radix 原生实心 blue-9 配白字为 3.26:1，低于 WCAG AA 4.5（Radix 为 APCA 体系），如恢复 AA 需改用 blue-7/blue-8 档

### 环境检测
- WSL 检测: `/proc/version` 包含 "microsoft"
- WSL 时设置 `MESA_LOADER_DRIVER_OVERRIDE=llvmpipe`, `LIBGL_ALWAYS_SOFTWARE=1` 等软渲染环境变量

### 启动流程 (关键时序)
- **单实例互斥（防多开）**：`main()` 在 logging 配置后、`OhMyMemeApp()` 创建前调 `platform_util.acquire_single_instance()`——Windows 用 `CreateMutexW("OhMyMeme_SingleInstance")`（`GetLastError()==ERROR_ALREADY_EXISTS` 即已有实例，句柄存模块级 `_single_instance_handle` 防 GC，进程退出内核自动释放，崩溃安全），POSIX（Linux/macOS/WSL）对 `tempdir/ohmymeme-<uid>.lock` `fcntl.flock(LOCK_EX|LOCK_NB)`（fd 保持打开）；已有实例运行时 Windows 弹 MessageBoxW「OhMyMeme 已在运行」后 `sys.exit(0)`，其余平台仅日志退出；互斥机制自身异常一律返回 True 不阻塞正常启动。Bottle 端口随机分配不构成冲突防线，故必须显式互斥
- **源码运行自动编译前端**：`app/bootstrap.py` 启动时 `_ensure_vue_frontend()` 检查 `src/webui/dist/ohmymeme.js` 与 `src/webui/dist/settings-vue.js`，按缺失项分别跑 `vite build` 与 `vite build --config vite.settings.config.ts`（冻结运行跳过），失败仅告警不阻断启动；对应产物缺失时页面返回 503 构建提示
- **启动动画**：`MainWindow.vue` 挂载时播放 `src/resources/OhMyMeme.mp4`（通过 Bottle 路由 `/resources/<filepath:path>` 提供，`webui.py` 的 `RESOURCES_DIR`，basename 校验防路径穿越，路由须在兜底 `/` 之前注册；PyInstaller 以 `--add-data src/resources` 打包）；`onMounted` 设置 6s 兜底定时器 + `<video>` `@ended` 移除遮罩，`#startup-anim` 全屏遮罩 z-index 2000，`.startup-fade` 0.4s 淡出。**仅启动时播放**：快捷键/托盘仅 toggle 窗口显隐不重载页面，故不会重复播放。设置页「显示启动动画」开关（配置键 `show_startup_animation`，默认开，`useMemes` state 同步）控制：开启时 `loadInitData` 后立即 `startupVideoReady=true` 挂载视频并**并行加载**（无 300ms 延时，动画天然覆盖桥接稳定时间）；关闭时 `dismissStartupAnim()` + `setTimeout(..., 300)` 降级为 300ms 延时。`get_init_data`/`reset_settings`/`get_settings` 均透传该键。**遮罩背景贴合视频边框**：OhMyMeme.mp4 边框为纯黑，`webui.py` 写死 `_STARTUP_BG_COLOR = "#000000"`（不做运行时 ffmpeg 采样，避免影响启动速度），经 `get_init_data` 的 `startup_bg_color` 传给前端，`MainWindow.vue` 把该色同时应用到 `#startup-anim` 与 html/body 背景。**可跳过**：点击遮罩立即 `dismissStartupAnim()`；系统 `prefers-reduced-motion: reduce` 时直接跳过动画走 300ms 降级路径（`window.matchMedia` 检测）
- Vue `MainWindow.vue` 挂载后:
  1. 立即: `loadInitData()` → `get_init_data()` 加载数据库数据 → 秒开
  2. `checkUpdateAndPrompt()` 立即执行（与 rescan/同步并行）
  3. **动画开启**：视频播放期间即并行 `rescan_cache()` → `run_auto_sync()` → 重新搜索/标签/分组（无延时）；**动画关闭**：降级 `setTimeout(..., 300)` 后执行上述步骤。桥接调用偶发失败不再清空已有数据：`search`/`refreshCollections` 仅接受合法响应（`null` 视为失败，保留旧值并退避重试 ≤3 次），`loadInitData` 校验响应结构、失败重试后才提示，`rescan_cache`/`run_auto_sync` 失败写入后端日志（`api('log')`）
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

### 本地备份与恢复 (backup.py)
- **定位**: 仅 PC 间整库迁移（导出 ZIP → 拷贝 → 恢复），手动触发，不做增量/自动清理/加密包；不碰手机 LAN 端
- **备份** (`create_backup`): 打包 cache_dir 全部原图（跳过 thumbnails，文件名即 hash 前缀跨机稳定）+ memes.db（`MemeDB.backup_to`，sqlite backup API 保证 WAL 一致快照）+ meme-index.json + backup.json 清单（app 版本/导出时间/文件数）；ZIP_STORED 不压缩（图片已是压缩格式）；先写 .tmp 再 os.replace 原子落盘。包结构：`db/memes.db`、`files/<文件名>`、`meme-index.json`、`backup.json`
- **恢复** (`restore_backup`): 仅允许空库（`has_any_data()`——memes/collections/tags/favorites 任一有数据即非空，含 stego 载体行与空分组；SettingsApi 前置校验，落库前 `restore_from` 锁内复查）；恢复 worker 全程持有 `_IMPORT_LOCK`（与 `_do_import`/同步 pull 同锁），恢复期间导入请求阻塞等待；`create_backup` 与 `apply_storage_dir` 均校验备份目录与 cache_dir 不得相同/互为嵌套（防备份递归自包含）；ZIP 安全限制（成员数 ≤100k 且不得重名、单成员解压 ≤64MB、总解压 ≤20GB、仅 STORED/DEFLATED）；解包到 `data_dir/backup_restore_tmp` staging，成员名安全校验（防路径穿越，只取 files/ 下 basename）+ 文件数与 backup.json 核对（防不完整包）→ **候选库先在隔离连接上 `MemeDB.prepare_restore_source`（integrity_check + 必需表存在性 + `_migrate` 预迁移），通过后才移动缓存文件**（记录本次新增文件，`restore_from` 失败即回滚删除；同名覆盖文件内容一致无需还原）→ `MemeDB.restore_from` 经 backup API 原子替换库内容 + `_migrate` 补齐旧版本缺失列 + 重设 WAL → `build_manifest()`；staging 任一步失败自动清理，不留半成品
- **备份目录**: config `backup_dir`（空=默认 data_dir/backups），设置页选择立即生效（校验可创建/可写）
- **SettingsApi**: `backup_get_info`/`backup_pick_dir`/`backup_create`/`backup_delete`（文件名白名单校验防穿越）/`backup_pick_zip`/`backup_restore`/`backup_progress`；后台线程 + 前端 300ms 轮询进度（`_BACKUP_STATE`，与存储迁移同模式），恢复成功后自动 build_manifest
- **设置页 UI**: 独立「备份与恢复」导航分组（日志与关于之间）：备份目录选择、立即备份、备份列表（文件名/大小/删除，删除走 showConfirm 危险确认）、从 ZIP 恢复（pick_zip → showConfirm → 恢复）；`backup-progress-overlay` 进度弹窗（运行中不可关闭，完成后"关闭"按钮 + Esc）；列入 _SETTINGS_OVERLAY_IDS 做 Tab 焦点陷阱
- **测试**: TestBackup 覆盖创建/列表/删除（thumbnails 排除、路径穿越拒绝）、恢复元数据保真（tags/收藏/分组）、孤儿保留与同名覆盖、非空库拒绝（零落盘 + staging 清理）、非法包/非 ZIP（BadZipFile 上抛由 worker 捕获）/文件数不符

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
- **GIF 隐写（复制模式 3 + 导入自动解码）** — ①复制输出：`copy_resize_mode=3` 时 `_make_stego_gif` **懒加载** `gif_stego.make_stego_gif` 生成携带无损原图的隐写 GIF（与原图同分辨率）再复制，失败原样复制原图；缓存 `ohmm_stego_<md5>_v1.gif`（不删除，CF_HDROP 需存在）。②导入含 `STG3` 的 GIF 时**无论模式与否**都会自动解码，且**只入库还原的原图**（`_try_decode_stego` 解码到临时文件 → 原图正常入库，`from_stego=1`，载体 GIF 不入库、不进缓存目录）。③隐写缓存：复制原图时通过临时缓存 `ohmm_stego_<md5>_v1.gif` 复用（命中即校验，不再重新编码）；`memes.stego_of_hash` 字段与 `get_by_stego_of` 保留用于兼容旧库中已入库的载体行。④前端展示：隐写载体在查询层隐藏（`search`/`count`/`get_recent` 统一加 `stego_of_hash IS NULL` 过滤，仅对旧库残留载体行生效），网格只显示还原后的原图；原图行 `from_stego=1`（`memes.from_stego` 列），卡片正常渲染图像并叠加琥珀色「隐写导入」徽标。⑤本地生成（复制路径）的隐写文件不写入 DB/不同步。`ohmymeme.core.gif_stego` 支持 `encode`/`decode`/`make_stego_gif`/CLI，`quiet=True` 供应用调用

### 加密降级 (crypto_util)
- 优先 `cryptography.fernet.Fernet` (AES-128-CBC + HMAC)
- 降级: `hashlib.pbkdf2_hmac` 派生密钥 + XOR + base64（防意外泄露，不防专业破解）
- **不能移除 XOR 降级** — 无 `cryptography` 时系统崩溃

### Sync pull 集合合并
- `_apply_remote_collections` 以**并集**方式合并远端分组，不清除本地已有成员
- 远端 manifest 中的 `collections` 用文件名关联（非 ID），跨设备稳定
- `_apply_remote_order` 按远端 manifest 的 `memes` 顺序重排本地 `sort_order`（`reorder_memes`），确保 pull 后本地显示顺序与云端一致，再次 push 不致覆盖云端排序

### 排序同步闭环
- 排序相关的 `reorder_memes`/`reorder_collections`/`reorder_collection_members` 经 LibraryService 更新 DB 后即调 `build_manifest()`，本地 `meme-index.json` 保持最新。`reorder_memes` 与 `reorder_collection_members` 支持部分 id 置换：保留有效 id 集合在当前全序中的位置集合，按请求顺序回填，并在锁内单事务将整个作用域编号为 `0..N-1`；全局作用于全部 memes，分组仅作用于该分组直接成员。空列表或全部无效 id 不修改数据，重复 id 保留首次出现，更新时间不变；全量有效列表保持原行为。`reorder_collections` 不采用此置换语义。
- push：末尾 `build_manifest()` 按 DB 当前 `sort_order` 重建并上传，云端 manifest 顺序反映本地排序
- pull：`_apply_remote_order` 按云端 manifest 顺序回写本地 `sort_order`，实现双向闭环

### Manifest
- `build()` 递归遍历嵌套分组树，空分组自动 `delete_collection`
- 远端 manifest 中的 `collections` 以嵌套格式存储（`name`/`filenames`/`children`），version 2 旧格式启动时自动转换

### 自定义排序
- `memes.sort_order` 字段存储全局展示顺序；前端可拖拽排序在全部/未分类视图走全局 `sort_order`，正 ID 分组（含子分组）内成员顺序存 `meme_collections.sort_order`（与 `canReorder()` 资格一致：未搜索、未按标签筛选）
- **分页与虚拟化**：后端 `offset`/`limit` 与初始化 200 条保持不变（`frontend/main/features/memes/useMemes.ts`）；`useMemes` 使用每页 200 项、常规最多 2000 项的连续已加载槽位区间 `[lo,hi)`，`slots` 长度为 `total`，区间外为 `undefined`。相邻滚动按页扩展并向视口反方向裁剪，远跳直接接管目标附近窗口；过期响应按查询/窗口代次丢弃，失败保留成功缓存并有限退避重试。MainWindow 使用 `virtua/vue` 的行级 `Virtualizer`，`#grid-wrap` 为唯一滚动容器并关闭 `overflow-anchor`，`#meme-grid` 外层保留；folder-grid 不虚拟化并纳入 `startMargin`，未加载槽位为同尺寸静态骨架。footer 显示共 N 项及加载/失败状态，保留 `aria-live="polite"`；失败按钮经 `retryRange` 在当前查询代次重放分页、首屏、初始化或计数失败，不清选择、不额外 search。`#grid-wrap` 的 `scrollTop` 超过两倍 `clientHeight` 时显示可键盘聚焦的回顶按钮：使用 `VirtualizerHandle.scrollTo(0)` 包含 folder 头块，handle 暂缺或滚动调用异常时仅归零仍挂载的滚动容器；框选/排序 armed/active 与保存期间禁用重试与回顶，按钮避开底部整理工具栏且不参与虚拟布局；无 `.grid-spacer`/顺序追加分支。尺寸硬约束：表情卡等宽等高，列数由 `ResizeObserver` 按容器宽/最小卡宽 112px/间隙 10px 推导并以未变换布局尺寸校准，行距 = 卡高 + 10px；更改卡片/名字/图片尺寸须同步检查虚拟化与槽位数学。
- **模型驱动**：`slots` 与连续 `loadedSlice` 为唯一数据真源；整理拖拽使用全局槽位数学，只从已挂载真卡发起并落到已挂载真卡。边缘自动滚动按需扩展连续窗口，drop 提交扩展后完整窗口顺序给后端位置保持置换；不得把 DOM 局部索引写入 `slots`
- **整理缓存预算**：普通缓存预算 2000 项；活动拖拽扩展 pin 临时保护开始窗口与连续移动路径，可能超过预算；结束后恢复视口预算。不得声称自动滚动手势内缓存恒定 2000 项
- **Pointer Events + 指针捕获**：`pointerdown/pointermove/pointerup`，拖拽/框选激活（位移 >8px）时才 `setPointerCapture`（避免普通点击被捕获重定向）；无 `PointerEvent` 的旧 WebView 由框选回退 mouse 事件（`mousemove`/`mouseup` 挂 document，两套起手不会同时启动），拖拽引擎按窄 `PointerSample` 驱动；`pointercancel`/`blur` 取消并回滚模型 + 重渲染。活动整理拖拽在稳定 `#grid-wrap` 捕获指针，以独立预览保护离屏源卡；rAF 边缘滚动在指针静止时继续运行。相邻加载不取消，查询/布局/`total` 变化、远跳、ESC、blur/`pointercancel` 取消；保存中冻结事件与分页，旧回调不得覆盖新查询
- **网格感知插入点**：MainWindow 采集未变换卡宽/步距与滚动后的内容原点（`originY = wrapTop + clientTop + startMargin - scrollTop`），`frontend/main/features/sorting/gridInteraction.ts` 的纯函数 `gridSlotIndex(geometry,x,y,total)` 直接给出全局绝对槽位；越界、末行空列与非法几何一律 `null`，不做 DOM 卡数钳制（旧 `gridMetrics()`/clamp 已删除）
- **FLIP 让位动画**：写入预览前记录可见真卡的未变换槽位原点，`nextTick` 后仅对更新前后均可见的非拖动真卡做位移归零（`.drag-flip`）；活动拖拽期间动态 `move-class` 禁用行级 `TransitionGroup` 自身 move 动画，避免双 FLIP 叠加，终态回到普通卡 `scale(0.95)` 且不覆盖独立 `rotate`
- 落点持久化：正 ID 分组内调用 `reorder_collection_members(collection_id, id[])` 更新 `meme_collections.sort_order`，全部/未分类走 `reorder_memes(id[])` 维护全局 `sort_order`；API 失败且原会话上下文仍有效时恢复基准顺序、toast 并按数据库重同步（旧代次只清会话，不 search、不 toast）
- `canReorder()`: 搜索或标签筛选时禁用；**全局开关（标题栏「整理」纯图标按钮，激活态蓝色底 + `aria-pressed`）关闭时禁用排序与框选**；仅正 ID 分组（含子分组）、全部（null）与未分类（-4）视图可排序，收藏夹/最近使用等特殊集合（-2/-3）不可排
- **标题栏动作布局**：标题栏可见按钮一律纯图标（整理开关、导入、⋯ 更多、关闭），含义靠 `title`/`aria-label` 与激活态；上传到远端/从远端下载/重新扫描/设置收进「⋯」菜单（菜单项为图标+文字，同步｜维护｜应用三类之间以分割线分隔）
- **整理模式（点选 + 拖拽换位 + 自研框选）**：标题栏单一开关 `sortEnabled`（`toggleSort` 用 `drag.enable()/drag.disable()`，关闭时清空选择）。开启后：单击/回车=勾选切换（`onCardClick` 接管，已激活手势抑制随后 click，避免拖拽换位/框选抬起后的 click 误勾选）、空白拖拽为自研可见区框选（仅命中当前挂载且已加载真卡；以起手选择快照 XOR 命中集合，框内重复项反选，框外/离屏选择保留，空白点击不清空，不使用修饰键；框选滚动即取消，不做跨视口连续框选）、卡片拖拽 >8px=换位（仅 `canReorder()` 视图：正 ID 分组/全部/未分类且未搜索/未按标签筛选；其余视图退化为纯点选）、点击不复制、不显示快捷收藏、禁用原生文件拖拽；底部悬浮工具栏 `#organize-bar`（`role="toolbar"`，absolute 吸附网格区底部居中、不参与布局）：已选 N 项 / 全选（按当前查询全量取 id，不受已加载范围限制）/ 取消选择 / 批量删除 /（可排时）「拖动卡片调整顺序」提示 / 退出整理，活动手势期间三者以 `interactionBusy` 禁用；ESC 顺序：LAN 确认 → 右键菜单 → 取消活动框选/排序手势（第一次不退出整理）→ 退出整理 → 隐藏窗口；`handleCopy`/`onCardPointerDown`/`onDocPointerMove` 均以 `sortEnabled` 守卫。点选/全选/批量删除按 id Set 工作，不因页淘汰取消选择。注：批量加入分组/打标签/移动到分组当前无前端入口（后端亦无 `batch_*` 接口），如需恢复属独立功能
- **整理模式视觉反馈**：MainWindow 按 `canReorder()` 绑定 `#meme-grid` 的 `sort-enabled`；启用时仅普通 meme 卡（排除 `.folder-card` 和 `.dragging`）最终显示 `scale(0.95)`、3px `var(--gray-7)` 描边及 3px 偏移。稳定卡使用独立 `rotate` 属性作轻微快速晃动，且必须排除 `.drag-active`、`.sort-enter`、`.folder-card` 和 `.dragging`；`prefers-reduced-motion: reduce` 时禁用晃动。不得用 `transform` 实现晃动，避免覆盖拖拽和 FLIP 的变换。独立拖动预览使用最终 `translate(...) scale(0.90)`，真实槽位保持等尺寸占位；FLIP 只作用可见真卡。整理模式选中态：`#meme-grid.select-enabled .meme-card.selected` 为 `2px solid var(--blue-9)` outline（`select-enabled` 随整理模式开启；`sort-enabled` 的可拖视觉规则独立并存）。开启工具栏整理开关时沿用现有入场反馈，只有明确关闭该开关才保留当前卡片播放退场动画。搜索、标签、分组或虚拟分组导致的资格变化均按普通刷新处理，不播放退场动画；文件夹卡不显示排序反馈
- **拖拽到外部应用**：关闭整理模式后 meme 卡**不用 HTML5 拖拽**（WebView2 http 源的 `text/uri-list`/`DownloadURL` 不生成 CF_HDROP，QQ/微信会报"图片拖拽失败"或资源管理器无反应）；改用 **WinForms 原生文件拖拽**（`native_drag.py`）：`pointerdown` 记录起点 → `pointermove` 位移 >8px 时 `JsApi.start_native_drag(id)` → 后端用 `webview.windows[0].native`（主 Form）`Invoke` 在 UI 线程执行 `DoDragDrop`（`DataObject` + `DataFormats.FileDrop` → CF_HDROP）→ 拖到 QQ/微信/桌面是真实本地文件；`DoDragDrop` 返回 `DragDropEffects.None`（拖回取消）时 `start_native_drag` 返回 False，不触发 `schedule_hide`；`native_drag.py` 懒加载 pythonnet/WinForms，非 Windows 或无 .NET 时返回 False，JS 端 toast 提示；**原生拖拽进行中回拖到窗口**用全局 `nativeDragActive` 标志抑制 drop 导入处理器（dragenter/dragover/dragleave/drop 均忽略，视为取消，不弹导入浮层）；`nativeDragActive` 在 `pointermove` 位移 >8px 触发原生拖拽**前**置 true，`start_native_drag` Promise `.then/.catch` 中重置，拖拽期间（后端 `DoDragDrop` 阻塞 UI 线程）保持 true，确保拖回窗口不会误触发导入
- 排序拖拽与原生拖拽共用 `onCardPointerDown`/`onDocPointerMove` pointer 事件：`onCardPointerDown` 按 `sortEnabled && canReorder()` 决定走 `drag.onPointerDown`（排序）还是记录 `nativeDragStart`（原生拖拽），`onDocPointerMove` 按 `drag.dragState.memeId` 是否存在分支，`onDocPointerUp`/`onDocPointerCancel` 对原生拖拽仅清 `nativeDragStart` 跳过排序回滚
- `search()` 带 `collection_id` 时按成员 `sort_order ASC, m.updated_at DESC, m.id ASC` 排序（子查询取该 meme 在目标分组内的 sort_order）；成员排序值并列时先按更新时间倒序，再按 id 升序。
- 拖拽后通过 `ignoreClick` 抑制误触发的 `click`（防止误复制），下一次 `pointerdown` 时重置

### 多级分组（最多 3 层）
- `collections.parent_id` 自引用实现嵌套
- `create_subcollection(name, parent_id)` 自动检查深度（`get_collection_depth`），超出 2 层拒绝
- **分组名自然排序回退**：`MemeDB.get_collections`/`get_child_collections` 仅按 `sort_order ASC` 查询后用 Python `_name_sort_key` 稳定排序——`sort_order` 相同（未拖拽）时数字段按整数（1,2,10 而非 1,10,2）、中文按拼音（`pypinyin` 惰性导入，缺失时退回原名小写码点序），替代原 SQL `ORDER BY name` 的二进制码点序
- 顶层分组在 `#colbar` 渲染为 tab，选中后展开子分组
- `#tagbar`/`#colbar` 横向溢出：细滚动条可见（`scrollbar-width: thin` + 5px webkit 样式），`initHScroll(barId)` 把滚轮竖向增量转成 `scrollLeft`（按 `deltaMode` 归一化），`DOMContentLoaded` 时对两个栏各绑定一次
- 分组内右键空白区域 → 新建子分组
- 右键表情包 → 加入分组 → 弹窗列出当前大分组下的子分组

### 主窗口 UI/UX
- **折叠侧边栏分组可辨识**：`CollectionTreeNode.vue` 在折叠态（`collapsed`）以 `.tree-avatar`（26px 圆角块，取分组名首 1-2 字符，`avatarText` computed）替代统一文件夹图标，active 行高亮；展开态保持原图标
- **功能发现性**：meme 卡左上 `.fav-btn` 心形快捷收藏（hover/active/focus-visible 显示，selectMode/sortEnabled 时隐藏，`@click.stop`+`@pointerdown.stop`，调 `JsApi.toggle_favorite` 并本地翻转 `meme.favorited` 后 `refreshCollections`）；侧边栏树行 hover 显示 `.tree-more`「⋯」按钮（展开态，`@click.stop` 发 folder-context 复用右键菜单）
- **空状态**：`#empty` 从 kaomoji 改为 SVG 插画（`.empty-svg`）+「导入表情包」按钮（`showImportMenu`）
- **搜索清除**：搜索框右侧 `.search-clear`「×」按钮（`v-if="state.searchQuery"`，点击 `clearSearch()` 清空并 `search()`），输入框 `padding-right:32px` 防文字被按钮遮挡
- **垂直空间压缩**：titlebar 38px、`#search-wrap` padding 6px 12px、`#search` padding 7px 12px、`#tagbar` padding 4px 12px + max-height 52px、`#breadcrumb` padding 2px 12px、`#grid-wrap` padding 10px、grid-foot padding 12px 0 6px
- **标题栏统一**：主/设置窗口关闭按钮均为 `×`；整理模式图标为上下箭头（非汉堡线）
- **右键菜单为 Naive `NDropdown`**：`ContextMenu.vue` 以 `trigger="manual"` + `:x/:y` 定位，菜单项映射为 `options`（子菜单用 `children`，危险项经 `render-label` 红字，禁用项 `disabled`，越界自动翻转）；打开期间拦截系统右键菜单，选择/点外/键盘关闭统一经 `update:show`/`onClickoutside` 回传 `ctx.hide()`
- **加入分组子菜单随菜单预加载**：表情右键「加入小分组」（正 ID 分组视图内）/文件夹右键「新建子分组」在打开菜单时经 `buildSubgroupItems()` 预取 `get_child_collections(activeCollection)`，作为 NDropdown 选项 `children`（「新建小分组」+ 当前分组子分组）；「添加分组」任意视图可用（走 CollectionBuilder）；`subgroup-*`/`__new-subgroup__` 动作分发不变
- **CollectionBuilder 分组下拉（Naive `NAutoComplete`）**：名称输入框聚焦即展开候选（`:get-show` = 聚焦且候选非空）；输入非空时首项为「名称」创建新分组（`render-label` 显示「创建新分组」提示），其余为顶层正 ID 分组；选择创建项走 `createNew`（保留已输入名称），选择已有分组走 `selectCollection`（加载成员并回填名称）；`selectedName` 与输入框显示值保持一致避免 watch 误判手动改名；`#cb-dropdown`/`.cb-dd-*` 自绘下拉已移除

### 未分类（虚拟分组）
- **`collection_id = -4`** 标识「未分类」虚拟分组：展示未加入任何分组的表情包（`meme_collections` 无记录），**不写入 DB/manifest，动态生成**
- `MemeDB.search()/count()` 新增 `uncategorized_only` 参数（`NOT EXISTS` 于 `meme_collections`），`search_memes` 中 `collection_id == -4` 路由到该参数，同时过滤隐写载体
- `get_init_data`/`get_collections` 按配置 `show_uncategorized`（默认开）决定是否追加 `-4` 条目（`get_collections` 中放于 `-2`/`-3` 之后）；设置页「分组显示 → 显示未分类分组」开关（`s-show-uncategorized`），保存到 `save_settings` 的 `show_uncategorized`
- 前端走通用集合渲染路径：计数为 0 时自动隐藏（`MainWindow.vue` 过滤 `count === 0` 的分组）；可拖拽排序（复用全局 `sort_order`，走 `reorder_memes` 持久化，`canReorder()` 对 -4 返回 true）；无特殊右键菜单
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
- **进度状态** (`_TG_STATE`): `idle` → `scanning` → `loading_key` → `decrypting` → `converting` → `importing` → `done`/`error`/`cancelled`，含 `error_code` 字段，前端 300ms 轮询 `get_tg_import_progress()`。**ETA 展示**：`_TG_STATE["elapsed_s"]` 由 worker 起点 `_TG_T0` 计算，`_refresh_tg_elapsed()` 在 `_update_tg`/`get_tg_progress` 内按运行中状态推进（idle/结束不推进）；设置窗口 `features/import/TelegramWizard.vue` 的 ETA 据 `elapsed_s` + `progress` 线性外推「已用 X · 预计剩余 Y」（`formatDuration()` 折算分钟/秒），随轮询刷新、overlay 打开时清空
- **入库**: 解密到临时目录后调 `webui._do_import()` 入库，完成后自动清理临时文件
- **取消**: `cancel_tg_import()` 设置标志位，工作线程在每个阶段检查并中止
- **前端 UI**: 设置页「导入」分组下 `.import-row` 列表行（硬编码 SVG 图标 + 名称），点击对应行弹出该软件的导入对话框（Telegram：tdata 目录手动指定 + 本地密码 + WebM 转换开关 → 进度覆盖层，错误时 `no_tdata`/`invalid_tdata`/`no_cache` 显示「手动选择 tdata 目录」重试按钮）
- **多账号**: Telegram Desktop 多账号共享 `user_data/cache`，无法区分来源账号，统一提取
- **透明动画（已解决）**: Telegram 视频贴纸 webm 内含有效 VP9+alpha（`yuva420p`）数据，但 ffmpeg **原生 VP9 解码器会静默丢弃 alpha 平面**（解码结果全不透明），导致转换出的动画 webp 背景不透明。修复：`convert_webm_to_webp` 在 `-i` 前加 `-c:v libvpx-vp9` 强制使用 libvpx 解码器保留 alpha。实测 48 个 webm 中 47 个恢复透明，透明像素分布与同表情静态 webp 完全一致

### 抖音表情包导入 (douyin.py + abogus.py)
- **架构**: 纯协议驱动（无浏览器自动化），`ohmymeme.integrations.imports.abogus` 提供 ABogus 签名算法绕过抖音 WAF，`curl_cffi` 模拟 Chrome 124 TLS 指纹绕过 JA3/JA4 检测
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
- **环境检测** (`inspect_wechat_environment`): 传入路径 basename 以 `wxid_` 开头或 `_find_emoticon_db` 命中则视为单账号，否则扫描子目录收集 `wxid_*` 前缀或含表情库的账号目录；每账号 `_inspect_account` 检查 DB 是否存在且为 SQLite header（否则 `encrypted_index`）；返回 `{status, reason, root, root_exists, account_directory_count, accounts: [{id, path, status, reason, db_path}]}`
- **账号选择**: `_pick_account` 未指定且多账号时返回 None，调用方报 `multiple_accounts` 引导前端选择；`list_wechat_stickers`/`start_wechat_import`/`_wechat_worker` 支持 `account_path` 参数指定账号
- **密钥提取**: 二进制扫描微信进程内存，通过特征码定位密钥对象（RVA 偏移在 `config/offsets.json` 配置），XOR 解码 + salt 比对 + HMAC-SHA512 校验。`offsets.json` 由 `build.py` `--add-data` 打包进产物 `config/` 目录（冻结后 `_offsets_path` 解析到 `_internal/config/offsets.json`，缺失时 helper 报 `config_invalid`）。**掩码恢复为主路径**（`find_wechat_key_masked`）：利用 DB 前 16 字节 salt 反推 32 字节 XOR 掩码，按 `x'<96hex>'` 格式识别被掩码的 99 字节密钥缓冲，**无需 RVA**，微信升级不易失效；旧 RVA 特征码扫描仅作回退；`--key <hex64>` 可注入已验证密钥绕开取证。**多进程**：未指定 `--pid` 时枚举所有 `Weixin.exe` 逐个尝试，掩码恢复天然命中运行目标账号的进程（`key_not_found` 表示均未命中）
- **账号目录识别不依赖 `wxid_` 前缀**：`_find_account_dirs` 收集「`wxid_` 前缀子目录 ∪ `_find_emoticon_db` 命中（`db_storage/emoticon/emoticon.db` 或 `Msg/emoticon.db` 存在）的子目录」；`_find_emoticon_db` 两个固定候选未命中时在 `db_storage` 一层内兜底查 `emoticon.db`（`db_storage/emoticon.db` 或 `db_storage/*/emoticon.db`，覆盖布局差异）；`inspect_wechat_environment` 对用户所选目录本身同理放宽（前缀或含表情库即视为单账号目录）。`_inspect_account` 在 db 缺失时附带 `db_files`（`db_storage` 内实际存在的 `.db` 清单，有界 30 条），前端 `no_database` 时翻译为中文提示并展示该清单用于诊断真实布局；检测到微信 3.x 旧版布局（账号目录含 `Msg/Multi` 或 `Msg/MicroMsg.db`，表情库为 `Msg/Emotion.db`）时返回 `unsupported_version`/`wechat_3x_unsupported`，前端引导升级微信 4.x（Emotion.db 的 `CustomEmotion` 表、3.x SQLCipher 页布局与密钥内存格式均与 4.x 不同，整条链路不支持）。测试 `tests/test_wechat_env.py`
- **DB 解密** (`_decrypt_database`): AES-256-CBC 逐页解密（每页 4096 字节，页 1 带 16 字节偏移，IV 取页尾 80 字节偏移处），首页替换为 "SQLite format 3" header；**合并 WAL**（`_apply_wal`）：微信运行中表结构与记录在 `emoticon.db-wal` 里，按 WAL 帧（24B 头 + 4096B 加密页）解密并回写到对应页，主文件旧快照 + WAL 帧 = 完整数据
- **元数据查询** (`_query_sticker_metadata`): SQLite 查询 `kNonStoreEmoticonTable`（type/md5/aes_key/cdn_url/encrypt_url/extern_url），返回 md5+url+aes_key 列表
- **下载校验** (`_download_sticker`): urllib 下载 → 魔数识别扩展名（PNG/JPG/GIF/WebP/BMP）→ 带 `aes_key` 时 AES-128-CBC 解密（IV=key）；`_detect_image_ext` 校验合法才返回。**防 SSRF**：仅允许白名单 CDN 主机（`vweixinf.tc.qq.com`/`wxapp.tc.qq.com`），解析后拒绝回环/私网/链路本地地址，重定向逐目标复检
- **完整性校验**: `verify_binary_integrity` 执行前校验二进制 SHA-256，未配置真实哈希（占位符 `PLACEHOLDER_UPDATE_ON_RELEASE`）时**默认拒绝执行**；开发/本地测试可用环境变量 `OHMYMEME_INSECURE_SKIP_HELPER_HASH=1` 跳过。**发布前必须**用 `certutil -hashfile wechat_keyfinder.exe SHA256` 计算真实哈希填入 `_WECHAT_KEYFINDER_SHA256` 并移除占位符
- **前端 UI**: 设置页「导入」分组下 `.import-row` 列表行（硬编码 SVG 图标 + 名称），点击微信行弹出对话框（目录选择 + 环境检测 + 多账号下拉 → 进度覆盖层）

## 构建 & 测试
- Todo14 许可证门使用 `scripts/build_notice_bundle.py` 与 `scripts/plugin_license_matrix.py`：前者按两份 Todo14 研究记录逐字节生成/校验 `THIRD-PARTY-NOTICES/license-evidence.json`、根 `NOTICE`、`LICENSES/` 和 helper 本地源码映射，并在 `--write` 时从当前已校验 frozen staging 材料化 `docs/plugin-license-matrix.json`；后者从 `setup.py`、九包 `pyproject.toml`、requirements/environment、GPL 来源、bundle 和实际 frozen metadata 解析并对照矩阵。矩阵/报告 `hash_policy` 规定受控源码、文档、pyproject 与 staging 元数据使用 UTF-8/LF 规范化哈希；许可、NOTICE、wheel RECORD、二进制和 canonical `plugin-manifest.json` 均保留逐字节哈希，后者必须是精确 LF canonical bytes。legacy `License` 字段必须原样记录，只有完整文本可支持的 `evidence_expression` 才可用于发布范围，不能伪造成 PEP 639 元数据。cryptography、Pillow 和 curl-cffi 的 native payload 按对应 Windows wheel 的 PyPI 摘要、WHEEL、RECORD、完整分发 notices 及可用 SBOM/DELVEWHEEL 验证；这是分发级记录，不得声称上游库 link-map。缺失/变更 bundle、RECORD 映射、轮子摘要、NOASSERTION 的已交付运行时、未知分发或错误外部范围必须 `REJECTED`。PyInstaller/Nuitka frozen 目标必须携带 `ohmymeme/LICENSE`、`NOTICE`、`LICENSES/` 和 `THIRD-PARTY-NOTICES/`；`curl_cffi` 保持交付，只有 `gmssl` 因缺少完整许可证文本被排除，source.douyin 保持 `provider_unavailable` 哨兵。外部下载微信 helper 和其 CMake/OpenSSL 输入不随制品传送；本地 `0.6.3` GPL 源码映射绝不等同于外部二进制的来源证明。
```bash
mise install python node npm --locked
mise run setup
mise run run
mise run check
python scripts/build.py  # PyInstaller + InnoSetup 完整构建
python scripts/build.py --lang en  # 指定语言构建
```
- `mise run package-smoke -- --contract-only` 只校验 Windows x64、AppImage、deb、rpm、macOS arm64/x86_64 的构建/安装/启动/升级/回滚/卸载定义，不执行产物生命周期。
- **构建自动编译 Vue 前端**: `build.py` 的 `ensure_vue_frontend()` 在打包前检查 `src/webui/dist/ohmymeme.js` 与 `src/webui/dist/settings-vue.js`（被 gitignore，CI 全新检出缺失），缺失时自动 `npm ci`（有 lockfile，否则 `npm install`）→ 分别 `npx vite build` 与 `npx vite build --config vite.settings.config.ts`，失败则中止构建；构建机需 node/npm（GitHub Actions runner 预装），dist 已存在时直接跳过
- **Linux 打包（GTK）**: `--linux` 时 `build.py` 自动传 `--additional-hooks-dir scripts/hooks`（收集 WebKit2/Soup typelib）并 `--collect-all gi`，把 PyGObject/GTK 打进产物，脱离系统 python3-gi 运行；构建机需装 `python3-gi gir1.2-webkit2-4.1 libgirepository1.0-dev libgirepository-2.0-dev gobject-introspection` 并 `pip install PyGObject`（对应 `build.yml`/`nightly.yml` build-linux job）；**PyGObject ≥3.52 硬依赖 girepository-2.0**（Ubuntu 24.04 对应 `libgirepository-2.0-dev`），只装 1.0-dev 会在 meson 元数据阶段报 `Dependency 'girepository-2.0' is required but not found`；deb `Depends: python3-gi, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0`

**前端架构**：主窗口与设置窗口均为 Vue 3 + Naive UI（`ohmymeme/presentation/frontend/main/` 与 `frontend/settings-vue/`，共用 `frontend/shared/` 的 Naive 主题，分别由 `vite.config.ts`/`vite.settings.config.ts` 构建 IIFE 单文件到 `src/webui/dist/`），每个窗口独立 webview。修改对应窗口前端后需重新构建（`npm run build` 或对应配置）再运行。

`make` 命令仅供参考（`make run`/`make test`/`make lint`/`make format`/`make build`），macOS/Linux 下可能不可用，优先使用原生 Python 命令。

## CI (GitHub Actions) — 三个独立 workflow
- **check.yml**: Ubuntu，统一运行 lint、类型、单元/契约/浏览器测试、前端构建和发布契约 smoke，push 和 PR 到任意分支均触发
- **build.yml**: Windows + Linux + macOS 三平台，仅在 `check` 通过 main 分支后自动触发，也支持 `workflow_dispatch` 手动触发
  - `build-windows`: InnoSetup 安装包 `dist/OhMyMeme-*-setup.exe`
  - `build-linux`: AppImage/deb/rpm（`--linux`）
  - `build-macos`: `.app` + `.dmg`（`--macos`，PyInstaller `--windowed` + iconutil 生成 icns）；矩阵双架构 `arm64`（macos-latest）+ `x86_64`（macos-15-intel），产物 `OhMyMeme-v*-{arch}.dmg`
- **nightly.yml**: Windows + Linux + macOS 三平台每日定时（UTC 20:00）+ `workflow_dispatch`，从 `dev` 分支构建非正式版（`--nightly`，版本号为 `nightly`）并发布为 `nightly` prerelease；`ohmymeme.services.updates` 的 `_parse_release` 跳过 prerelease 与含 `nightly` 的 tag，**软件更新绝不会指向 nightly**
- 上传 `dist/OhMyMeme-*-setup.exe` / `dist/OhMyMeme-v*-x86_64.AppImage` 等作为 artifact

## 版本管理
- 版本号唯一来源: `src/ohmymeme/__init__.py` → `__version__ = "*.*.*"`
- `scripts/build.py` 用正则从该文件提取版本；`--version`/`--nightly` 会临时改写 `__init__.py` 构建，完成后恢复
