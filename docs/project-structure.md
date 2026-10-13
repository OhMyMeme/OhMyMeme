# OhMyMeme 项目结构

本文档是仓库目录和代码职责的快速地图。文件树中的标记含义如下：

- `[source]`：源码或运行时静态资源
- `[test]`：测试、协议样例或测试 fixture
- `[generated]`：由构建命令生成，不应手工维护
- `[legacy]`：保留用于兼容，但不是当前主要入口
- `[local]`：本地工具、缓存或 Agent 工作状态

## 文件树

```text
OhMyMeme/
├── .github/                                      [source]
│   ├── PR-tg-import.md                            Telegram 导入相关 PR 说明
│   └── workflows/
│       ├── check.yml                              mise 质量门禁、lint、测试和前端构建
│       ├── build.yml                              Windows/Linux/macOS 正式版构建
│       └── nightly.yml                            dev 分支 Nightly 构建和发布
├── config/                                       [source]
│   ├── offsets.json                               微信辅助程序的版本偏移配置
│   └── plugin-manifest.json                       九个官方插件的 canonical 分发清单
├── plugins/                                      [source]
│   ├── source.qqnt/                               QQNT 官方源插件（源码与打包输入）
│   ├── source.telegram/                           Telegram 官方源插件（源码与打包输入）
│   ├── source.douyin/                             抖音官方源插件（源码与打包输入）
│   ├── source.wechat/                             微信官方源插件（源码与打包输入）
│   ├── sync.ftp/                                  FTP 官方同步插件（源码与打包输入）
│   ├── sync.s3/                                   S3 官方同步插件（源码与打包输入）
│   ├── sync.r2/                                   R2 官方同步插件（源码与打包输入）
│   ├── sync.webdav/                               WebDAV 官方同步插件（源码与打包输入）
│   └── transport.lan/                             局域网官方传输插件（源码与打包输入）
├── docs/                                         [source]
│   ├── plugin-distribution-plan.md                官方插件按需分发与导入方案（GitHub / 本地 ZIP）
│   ├── plugin-runtime-plan.md                     子进程插件体系落地计划与实施状态
│   ├── plugin-ui-injection-plan.md                插件 UI 注入点规划（声明式 + iframe，已实施）
│   ├── project-structure.md                       本项目结构地图
│   └── wechat_keyfinder_protocol.md               Python 与微信 C++ 辅助程序协议
├── fixtures/                                     [test]
│   └── plugin-parity/                             插件边界与 parity 离线 fixture
│       ├── inventory-invalid.json                  Todo1 inventory 失效样例
│       ├── settings-ui-baseline.html               历史设置窗口 HTML 基线（仅固定 SVG/文案与历史兼容证据，不参与生产或构建）
│       ├── docs-invalid/                           Todo16 固定文档失效样例
│       └── docs-conflicting-nonfeatures/           Todo16 矛盾非功能声明样例
├── resource/                                     [source]
│   └── picture.gif                                README 展示图片
├── scripts/                                      [source]
│   ├── build.py                                   PyInstaller、前端检查和安装包构建
│   ├── launcher.py                                PyInstaller 启动器
│   ├── merge-dev-to-main.bat                      Windows 分支合并辅助脚本
│   ├── package_lifecycle.py                       构建产物生命周期验证
│   ├── package_smoke.py                           打包布局和发布契约验证
│   ├── plugin_docs_check.py                        固定插件文档/入口/边界离线校验
│   ├── plugin_packaging.py                        九包元数据/ZIP 打包/开发安装与 source/frozen 验证
│   ├── hooks/                                    PyInstaller GTK 自定义 hook
│   │   ├── hook-gi.repository.Soup.py
│   │   └── hook-gi.repository.WebKit2.py
│   ├── installer/                                 平台安装包脚本
│   │   ├── windows.iss                            InnoSetup Windows 安装包模板
│   │   ├── linux/
│   │   │   └── build.sh                           AppImage、deb、rpm 构建
│   │   └── macos/
│   │       └── Info.plist                         macOS App Bundle 元数据
│   └── nuitka/
│       └── build.py                               备用 Nuitka 构建脚本
├── src/                                          [source]
│   ├── adb-help.txt                               ADB 使用说明
│   ├── ohmymeme/                                  唯一正式 Python 业务包
│   │   ├── __init__.py                            版本号和包元信息
│   │   ├── __main__.py                            python -m ohmymeme 入口
│   │   ├── app/                                   应用层和组合根
│   │   │   ├── __init__.py
│   │   │   ├── bootstrap.py                       启动流程、参数和生命周期
│   │   │   ├── catalog.py                         表情、标签、分组查询协调
│   │   │   ├── container.py                        应用对象组装和资源所有权
│   │   │   └── settings.py                         应用设置访问
│   │   ├── cli/                                   独立命令行入口
│   │   │   ├── __init__.py
│   │   │   └── douyin_dl.py                        抖音下载 CLI
│   │   ├── core/                                  核心领域和基础设施
│   │   │   ├── __init__.py
│   │   │   ├── assets.py                           数据、缓存、缩略图和 Manifest 路径
│   │   │   ├── config.py                           JSON 配置、默认值和密钥字段
│   │   │   ├── crypto.py                           Fernet 及降级加密
│   │   │   ├── database.py                         SQLite 表、查询、标签、分组和排序
│   │   │   ├── domain/                             严格类型领域值、纯规则和稳定错误
│   │   │   ├── gif_stego.py                        GIF 隐写编码、解码和原图恢复
│   │   │   ├── imports.py                          图片校验、去重、导入事务
│   │   │   ├── manifest.py                         meme-index.json 生成、恢复和投影
│   │   │   └── plugins/                            插件清单、契约、策略、注册和运行时边界
│   │   ├── integrations/                          平台和第三方软件适配
│   │   │   ├── __init__.py
│   │   │   ├── imports/                            外部表情包导入器
│   │   │   │   ├── __init__.py
│   │   │   │   ├── abogus.py                       抖音 ABogus 签名算法
│   │   │   │   ├── adb_qq.py                       手机 QQ ADB 导入
│   │   │   │   ├── douyin.py                       抖音 API、Cookie、下载和导入
│   │   │   │   ├── qqnt.py                         PC QQNT 收藏表情提取
│   │   │   │   ├── telegram.py                     Telegram 解密、转换、去重和导入
│   │   │   │   └── wechat.py                       微信数据库解密、下载和导入
│   │   │   └── platform/                           操作系统能力适配
│   │   │       ├── __init__.py
│   │   │       ├── clipboard.py                    剪贴板和 GIF/WebP/PNG 复制
│   │   │       ├── hotkey.py                       全局快捷键及降级方案
│   │   │       ├── native_drag.py                  Windows 原生文件拖拽
│   │   │       ├── system.py                       开机自启和系统路径操作
│   │   │       └── tray.py                         系统托盘
│   │   ├── presentation/                           表现层和 WebView 桥接
│   │   │   ├── __init__.py
│   │   │   ├── desktop/                            pywebview、Bottle 和桌面 API
│   │   │   │   ├── __init__.py
│   │   │   │   ├── bottle_app.py                   Bottle 应用和路由注册
│   │   │   │   ├── import_workers.py                后台导入任务协调
│   │   │   │   ├── media.py                         图片和缩略图服务
│   │   │   │   ├── security.py                      Host、Origin 和安全响应头校验
│   │   │   │   ├── window_manager.py                JsApi/SettingsApi façade 和窗口生命周期
│   │   │   │   ├── api/                             对外桥接 API
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── lan.py                       LAN API
│   │   │   │   │   ├── memes.py                     表情、标签、收藏和分组 API
│   │   │   │   │   ├── settings.py                  设置窗口 API
│   │   │   │   │   └── sync.py                      同步 API
│   │   │   │   └── routes/                          Bottle HTTP 路由
│   │   │   │       ├── __init__.py
│   │   │   │       ├── contributors.py              贡献者头像代理
│   │   │   │       ├── media.py                     图片和资源路由
│   │   │   │       ├── pages.py                     HTML 页面路由
│   │   │   │       └── upload.py                    上传和导入路由
│   │   │   └── frontend/                            前端源码
│   │   │       ├── shared/                          两窗口共用的主题、设计 token 与文本转义
│   │   │       │   ├── tokens.ts                    Radix Colors 原生色阶与 CSS 变量注入
│   │   │       │   ├── naive-theme.ts               Naive UI 深色主题覆写（读取 tokens.ts）
│   │   │       │   ├── theme.css                    两窗口共用非颜色变量（圆角/阴影/过渡）
│   │   │       │   └── markdown.ts                  转义与受控 Markdown 渲染
│   │   │       ├── main/                            Vue 3 + Naive UI 主窗口
│   │   │       │   ├── app/
│   │   │       │   │   ├── App.vue                  NConfigProvider/provider 壳
│   │   │       │   │   ├── MainWindow.vue           主窗口布局、虚拟网格与重试/回顶接线、启动动画与生命周期
│   │   │       │   │   ├── main.ts                  Vite 入口
│   │   │       │   │   └── style.css                主窗口样式（引入 shared/theme.css）
│   │   │       │   ├── features/                    按功能拆分的 Vue 模块
│   │   │       │   │   ├── collections/              分组树和分组编辑
│   │   │       │   │   │   ├── CollectionBuilder.vue
│   │   │       │   │   │   ├── CollectionTreeNode.vue
│   │   │       │   │   │   └── useCollectionBuilder.ts
│   │   │       │   │   ├── dialogs/                  右键菜单和通用弹窗
│   │   │       │   │   │   ├── ConfirmDialog.vue
│   │   │       │   │   │   ├── ContextMenu.vue
│   │   │       │   │   │   ├── InputDialog.vue
│   │   │       │   │   │   └── useContextMenu.ts
│   │   │       │   │   ├── imports/                  导入菜单
│   │   │       │   │   │   └── ImportMenu.vue
│   │   │       │   │   ├── lan/                      LAN 设备确认
│   │   │       │   │   │   └── showLanDeviceConfirm.ts
│   │   │       │   │   ├── memes/                    表情数据和分页
│   │   │       │   │   │   ├── Pager.vue
│   │   │       │   │   │   └── useMemes.ts
│   │   │       │   │   ├── sorting/                  整理模式
│   │   │       │   │   │   ├── gridInteraction.ts    框选矩形/槽位换算/速度曲线/落点顺序纯函数
│   │   │       │   │   │   └── useDragSort.ts        整理拖拽引擎（全局槽位/自动滚动/持久化门禁）
│   │   │       │   │   ├── sync/                     同步进度
│   │   │       │   │   │   └── SyncOverlay.vue
│   │   │       │   │   ├── tags/                     标签编辑
│   │   │       │   │   │   └── TagEditor.vue
│   │   │       │   │   └── updates/                  更新弹窗
│   │   │       │   │       └── UpdateDialog.vue
│   │   │       │   └── shared/                       主窗口桥接与类型
│   │   │       │       ├── bridge.ts                 唯一 pywebview bridge、转义/焦点工具
│   │   │       │       ├── types.ts                  前端领域类型
│   │   │       │       └── generated/
│   │   │       │           └── bridge.ts             [generated] Bridge DTO 类型
│   │   │       └── settings-vue/                     Vue 3 + Naive UI 设置窗口
│   │   │           ├── app/
│   │   │           │   ├── App.vue                   provider 壳与初始化/重试
│   │   │           │   ├── SettingsShell.vue         导航与分组装配
│   │   │           │   ├── main.ts                   Vite 入口
│   │   │           │   └── style.css                 设置窗口布局样式
│   │   │           ├── features/
│   │   │           │   ├── about/AboutGroup.vue
│   │   │           │   ├── backup/BackupGroup.vue
│   │   │           │   ├── base/BaseGroup.vue
│   │   │           │   ├── danger/DangerGroup.vue
│   │   │           │   ├── import/                   导入分组与各来源向导
│   │   │           │   │   ├── DouyinWizard.vue
│   │   │           │   │   ├── ImportGroup.vue
│   │   │           │   │   ├── QqntWizard.vue
│   │   │           │   │   ├── QqWizard.vue
│   │   │           │   │   ├── TelegramWizard.vue
│   │   │           │   │   └── WechatWizard.vue
│   │   │           │   ├── logs/LogsGroup.vue
│   │   │           │   ├── network/NetworkGroup.vue
│   │   │           │   └── plugins/PluginsGroup.vue
│   │   │           └── shared/
│   │   │               ├── bridge.ts                 设置窗口受控桥接与转义
│   │   │               ├── plugin-ui.ts              宿主 UI 投影校验
│   │   │               ├── store.ts                  设置状态、脏标记与保存
│   │   │               └── markdown.ts               导出两窗口共用的受控 Markdown 工具
│   │   └── services/                                业务服务层
│   │       ├── __init__.py
│   │       ├── updates.py                           GitHub Release 更新服务
│   │       ├── lan/                                  局域网服务
│   │       │   ├── __init__.py
│   │       │   ├── commands.py                       LAN 命令处理
│   │       │   ├── protocol.py                       帧、握手和加密协议
│   │       │   └── server.py                         UDP/TCP 服务和设备确认
│   │       └── sync/                                 远程同步服务
│   │           ├── __init__.py
│   │           ├── backends.py                       FTP/S3/R2/WebDAV 后端
│   │           ├── planning.py                       远端 Manifest 应用计划
│   │           └── service.py                        push/pull、进度和远端清理
│   ├── resources/                                   运行时资源
│   │   ├── OhMyMeme.mp4                             启动动画
│   │   ├── icon.ico                                 Windows 图标
│   │   ├── icon.png                                 通用图标
│   │   └── .gitkeep
│   ├── webui/                                       WebView 静态资源
│   │   ├── vue.html                                 主窗口入口（Vue）
│   │   ├── vue-settings.html                        设置窗口入口（Vue）
│   │   ├── import-frame.js                          插件详情页 iframe 协议 SDK 资产
│   │   ├── plugin-ui.json                           宿主固定插件 UI 投影
│   │   └── dist/                                    [generated] Vite 构建目录
│   │       ├── ohmymeme.js                          主窗口 IIFE 构建产物
│   │       └── settings-vue.js                      设置窗口 IIFE 构建产物
│   └── wechat_keyfinder/                            微信 C++ 辅助程序
│       ├── CMakeLists.txt                            CMake 构建配置
│       └── wechat_keyfinder.cpp                     进程内存密钥提取
├── tests/                                          [test]
│   ├── app/
│   │   └── test_container.py                        Container 对象图和生命周期
│   ├── application/
│   │   └── test_import_service.py                   导入事务、去重和 Manifest 投影
│   ├── architecture/
│   │   └── test_package_boundaries.py               包依赖方向和旧入口约束
│   ├── core/
│   │   └── test_assets.py                            资源路径和缓存路径
│   ├── integration/
│   │   └── test_lan_server.py                        LAN 服务集成测试
│   ├── presentation/
│   │   └── test_desktop_bottle_security.py           Bottle 安全边界
│   ├── protocol/
│   │   └── test_lan_v1_protocol.py                   LAN v1 协议 oracle
│   ├── frontend/                                     Vitest 前端契约（jsdom）
│   │   ├── grid_interaction.test.ts                  gridInteraction 纯函数（框选/槽位/速度/落点顺序）
│   │   ├── main_window_virtual.test.ts               MainWindow 虚拟网格拖拽、框选与 footer 重试/回顶/手势禁用/卸载接线桩（mock 手动挂载区间）
│   │   └── meme_cache.test.ts                        useMemes 连续缓存模型（分页/裁剪/代次/pin）
│   ├── fixtures/
│   │   ├── grid_slot_probe.cjs                       全局槽位同源探针（读 gridInteraction.ts）
│   │   ├── lan-v1-oracle.json                        LAN v1 基准数据
│   │   └── task-17.bin                               二进制测试数据
│   ├── test_abogus.py                                ABogus、SM3、RC4
│   ├── test_adb_util.py                              ADB 路径、下载和取消
│   ├── test_core.py                                  Version/Config/Crypto/Database
│   ├── test_douyin_dl.py                             抖音下载 CLI
│   ├── test_lan.py                                   LAN 发现、握手、文件和配置
│   ├── test_package_smoke.py                         打包布局和发布契约
│   ├── test_startup.py                               启动、窗口和前端静态契约
│   ├── test_sync.py                                  同步、Manifest 和失败恢复
│   ├── test_tg_stickers.py                           Telegram 解密、转换和去重
│   ├── test_updater.py                               更新缓存、下载和后台任务
│   └── test_webdav_backend.py                        WebDAV 后端
├── .omo/                                            [local] Agent 计划和验证状态
│   ├── boulder.json                                 工作计划状态
│   ├── plans/                                       architecture-optimization 等计划
│   ├── drafts/                                      计划草稿
│   ├── notepads/                                    决策、问题和验证记录
│   ├── start-work/                                  启动状态和 evidence ledger
│   └── run-continuation/                            Agent 会话续接 JSON
├── .git/                                            [local] Git 历史、索引和 GitButler 状态
├── .venv/                                           [local] Python 虚拟环境
├── node_modules/                                    [local] npm 依赖
├── .codegraph/                                      [local] 代码索引
├── .pytest_cache/                                   [local] pytest 缓存
├── .ruff_cache/                                     [local] Ruff 缓存
├── __pycache__/                                     [local] Python 字节码缓存
├── AGENTS.md                                       项目开发和 AI 工作规范
├── README.md                                       项目介绍和快速开始
├── HISTORY.md                                      版本历史
├── LICENSE                                         项目许可证
├── .gitignore                                      Git 忽略规则
├── environment.yml                                 Conda 环境依赖
├── mise.toml                                       工具链和项目任务
├── mise.lock                                       工具链锁定信息
├── package.json                                    前端依赖和 npm scripts
├── package-lock.json                               npm 依赖锁定信息
├── tsconfig.json                                   前端严格类型根范围（主窗口 app/features/shared、设置窗口与 TS 测试）
├── vite.config.ts                                  主窗口 Vite 配置（IIFE → ohmymeme.js）
├── vite.settings.config.ts                         设置窗口 Vite 配置（IIFE → settings-vue.js）
├── pyproject.toml                                  Ruff 配置
└── setup.py                                        Python 安装配置
```

## 运行时数据

应用运行时数据不放在仓库目录中：

```text
%APPDATA%/OhMyMeme/                              Windows 配置和密钥
%LOCALAPPDATA%/OhMyMeme/                         数据库、缓存、缩略图和 Manifest
```

数据库保存表情元数据，图片通常位于 `cache/`，缩略图位于 `thumbnails/`，同步索引为 `meme-index.json`。

## 依赖方向

```text
__main__.py
    ↓
app/bootstrap.py
    ↓
app/container.py
    ├── core/                 配置、数据库、文件、导入和 Manifest
    ├── services/             同步、LAN、更新
    ├── integrations/         平台和第三方导入
    └── presentation/         WebView、Bottle、API 和前端
```

主窗口 Vue 代码只能通过 `frontend/main/shared/bridge.ts` 调用 Python API，设置窗口只能通过 `frontend/settings-vue/shared/bridge.ts`；两个入口分别由 `vite.config.ts` 与 `vite.settings.config.ts` 构建为 `src/webui/dist/ohmymeme.js` 和 `src/webui/dist/settings-vue.js`，共用 `frontend/shared/` 的 Naive 主题与设计 token。`src/webui/` 和 `src/resources/` 是运行时静态资源，不是 Python 包。

## 官方插件重组边界

`config/plugin-manifest.json` 是唯一的 canonical 清单，固定九个 provider 的顺序和 `ohmymeme.plugins.v1` 入口点：`source.qqnt`/`ohmymeme_plugin_qqnt:create_plugin`、`source.telegram`/`ohmymeme_plugin_telegram:create_plugin`、`source.douyin`/`ohmymeme_plugin_douyin:create_plugin`、`source.wechat`/`ohmymeme_plugin_wechat:create_plugin`、`sync.ftp`/`ohmymeme_plugin_sync_ftp:create_plugin`、`sync.s3`/`ohmymeme_plugin_sync_s3:create_plugin`、`sync.r2`/`ohmymeme_plugin_sync_r2:create_plugin`、`sync.webdav`/`ohmymeme_plugin_sync_webdav:create_plugin`、`transport.lan`/`ohmymeme_plugin_lan:create_plugin`。完整可复制的入口点见 [README 的官方插件扩展边界](../README.md#官方插件扩展边界)。

零参数 `create_plugin()` 每次都返回独立状态实例。宿主拥有 SQLite、缓存、manifest、Config、UI、原生能力与 LAN 安全边界；插件仅接收窄配置、限域密钥和 operation 临时目录，不接收持久 Config、缓存或存储路径。`OperationCoordinator 管理 provider 的启动、取消和资源回收`，所以线程、子进程、socket、临时目录、数据库连接和持久写入仍由宿主创建、登记、drain 和关闭。

九包源码位于 `plugins/`，`scripts/plugin_packaging.py` 比较 source/frozen staging 的模块、入口元数据、manifest 与许可证文件，并生成发布 ZIP（`--pack-zips`）、执行开发安装（`--install-dev`）与仓库 `plugins/<id>/plugin.json` 门禁。source/frozen staging 一致性只覆盖源码、入口元数据与 staging，不等同于对最终冻结可执行文件的实际构建验证。`scripts/plugin_docs_check.py` 使用 inventory 和固定文档事实检查这些声明，负例位于 `fixtures/plugin-parity/inventory-invalid.json`、`fixtures/plugin-parity/docs-invalid/README.md` 与 `fixtures/plugin-parity/docs-conflicting-nonfeatures/README.md`。

官方插件不随冻结产物/安装包分发，也不随应用启动自动加载：在设置「插件」中从 GitHub 仓库（公开仓库根目录 `plugins/{plugin-id}/` 契约）或本地 ZIP 导入后才可用（`core/plugins/runtime/github_source.py` + `seeding` 安装事务），未导入时相关入口隐藏或返回原失败哨兵；旧 `origin=="bundled"` 平铺种子副本启动时清理。发布 ZIP 由 `--pack-zips` 生成并随 Release 附件发布。

许可证和发布范围由 `docs/plugin-license-matrix.json`、`NOTICE`、`LICENSES/` 与 `THIRD-PARTY-NOTICES/` 记录。外部下载的微信 helper 及其 CMake/OpenSSL 输入不随制品交付；本地 helper 源码映射不构成外部 helper EXE 的来源到二进制可复现性证明。

不提供 marketplace 或不受信任插件沙箱。
第三方插件仅支持本地 ZIP 安装、卸载与重启生效的启用管理。UI 侧开放声明式 UI 注入白名单（插件 `ui.json` 只声明导入区行与插件详情面板，字段类型受宿主白名单约束并整条校验），以及插件详情页沙箱 iframe（显式加载、CSP、postMessage 动作 allowlist）；不提供任意 HTML/JS 注入宿主 DOM、动态 provider 发现或动态 Bridge。

## 推荐阅读顺序

```text
README.md
  → mise.toml / package.json
  → src/ohmymeme/__main__.py
  → app/bootstrap.py → app/container.py
  → core/database.py / core/imports.py / core/manifest.py
  → services/ 和 integrations/
  → presentation/desktop/
  → presentation/frontend/
  → tests/
```

按功能修改时：

- 后端：先看 `app` 或 `core`，再看对应 service/integration 和测试。
- 主窗口 UI：先看 `frontend/main/app`，再看对应 `features`、`shared/bridge.ts` 和桌面 API。
- 设置窗口：先看 `frontend/settings-vue/app` 和 `shared/bridge.ts`，再看 `features/`、`shared/plugin-ui.ts` 与桌面 `SettingsApi`。
- 构建：先看 `package.json`、`vite.config.ts`/`vite.settings.config.ts`，再看 `scripts/build.py`、安装器和 workflow。
- 微信辅助程序：按 `config/offsets.json` → `wechat_keyfinder/` → `integrations/imports/wechat.py` → 协议文档阅读。

详细行为约束仍以 `AGENTS.md`、协议文档和各测试文件为准；本文档只负责说明目录结构和职责边界。
