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
│   └── offsets.json                               微信辅助程序的版本偏移配置
├── docs/                                         [source]
│   ├── project-structure.md                       本项目结构地图
│   └── wechat_keyfinder_protocol.md               Python 与微信 C++ 辅助程序协议
├── resource/                                     [source]
│   └── picture.gif                                README 展示图片
├── scripts/                                      [source]
│   ├── build.py                                   PyInstaller、前端检查和安装包构建
│   ├── build_settings.mjs                         拼接 settings JS 源文件
│   ├── launcher.py                                PyInstaller 启动器
│   ├── merge-dev-to-main.bat                      Windows 分支合并辅助脚本
│   ├── package_lifecycle.py                       构建产物生命周期验证
│   ├── package_smoke.py                           打包布局和发布契约验证
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
│   │   │   ├── gif_stego.py                        GIF 隐写编码、解码和原图恢复
│   │   │   ├── imports.py                          图片校验、去重、导入事务
│   │   │   └── manifest.py                         meme-index.json 生成、恢复和投影
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
│   │   │       ├── main/                            Vue 3 主窗口
│   │   │       │   ├── app/
│   │   │       │   │   ├── App.vue                  根组件、启动动画和生命周期
│   │   │       │   │   ├── MainWindow.vue           主窗口布局和组件组合
│   │   │       │   │   ├── main.ts                  Vue/Vite 入口
│   │   │       │   │   └── style.css                主窗口样式、主题和动画
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
│   │   │       │   │   ├── sorting/                  拖拽排序
│   │   │       │   │   │   └── useDragSort.ts
│   │   │       │   │   ├── sync/                     同步进度
│   │   │       │   │   │   └── SyncOverlay.vue
│   │   │       │   │   ├── tags/                     标签编辑
│   │   │       │   │   │   └── TagEditor.vue
│   │   │       │   │   └── updates/                  更新弹窗
│   │   │       │   │       └── UpdateDialog.vue
│   │   │       │   └── shared/                       前端共享边界
│   │   │       │       ├── bridge.ts                 唯一 pywebview bridge、焦点和转义工具
│   │   │       │       └── types.ts                  前端领域类型
│   │   │       └── settings/                         Vanilla JS 设置窗口源码
│   │   │           ├── entry.mjs                     settings 源文件拼接入口
│   │   │           ├── core/
│   │   │           │   ├── init.js                   设置初始化和 dirty tracking
│   │   │           │   ├── runtime.js                设置运行时状态
│   │   │           │   └── window.js                 设置窗口生命周期
│   │   │           └── features/
│   │   │               ├── base.js                   基础设置
│   │   │               ├── danger.js                 危险操作
│   │   │               ├── lan.js                    局域网设置
│   │   │               ├── logs.js                   日志查看和导出
│   │   │               ├── storage.js                存储位置和迁移
│   │   │               ├── update.js                 更新检查
│   │   │               ├── imports/
│   │   │               │   ├── douyin.js              抖音导入
│   │   │               │   ├── qq.js                  手机 QQ 导入
│   │   │               │   ├── qqnt.js                QQNT 导入
│   │   │               │   ├── telegram.js            Telegram 导入
│   │   │               │   └── wechat.js              微信导入
│   │   │               └── sync/
│   │   │                   ├── operations.js           同步操作和进度
│   │   │                   └── settings.js             远程同步配置
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
│   │   ├── vue.html                                 当前主窗口入口
│   │   ├── settings.html                            设置窗口 HTML
│   │   ├── settings.css                             设置窗口样式
│   │   ├── settings.js                              [generated] settings 运行时脚本
│   │   ├── index.html                               [legacy] 旧主窗口入口
│   │   ├── index.css                                [legacy] 旧主窗口样式
│   │   ├── index.js                                 [legacy] 旧主窗口脚本
│   │   ├── test-vue/                                前端测试/演示页面
│   │   │   ├── index.html
│   │   │   └── ohmymeme-ui.js
│   │   └── dist/                                    [generated] Vite 构建目录
│   │       └── ohmymeme.js                          Vue IIFE 构建产物
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
│   ├── fixtures/
│   │   ├── grid_slot_probe.cjs                       网格拖拽槽位探针
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

主窗口 Vue 代码只能通过 `frontend/main/shared/bridge.ts` 调用 Python API；设置窗口由模块化 Vanilla JS 源码构建为 `src/webui/settings.js`。`src/webui/` 和 `src/resources/` 是运行时静态资源，不是 Python 包。

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
- 设置窗口：先看 `frontend/settings`，再看 `scripts/build_settings.mjs` 和 `src/webui/settings.js`。
- 构建：先看 `package.json`、`vite.config.ts`，再看 `scripts/build.py`、安装器和 workflow。
- 微信辅助程序：按 `config/offsets.json` → `wechat_keyfinder/` → `integrations/imports/wechat.py` → 协议文档阅读。

详细行为约束仍以 `AGENTS.md`、协议文档和各测试文件为准；本文档只负责说明目录结构和职责边界。
