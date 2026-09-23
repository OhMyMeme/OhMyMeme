# OhMyMeme 子进程插件体系落地计划

状态：规划已确认，实施进行中。实施时以本文为基线；在实施完成前 `README.md`、`AGENTS.md`、`docs/project-structure.md` 中的现行插件边界描述仍然有效，不得提前改写。

## 0. 实施状态（2026-09-22）

已完成：

- M0 运行时骨架：`src/ohmymeme/core/plugins/runtime/`（protocol/channel/process_tree/manager/worker/seeding）；协议文档 `docs/plugin-worker-protocol.md`；worker 入口 `src/ohmymeme/plugin_worker.py` 与 `bootstrap.main` 的 `--plugin-worker` 分流；conformance 与端到端测试 `tests/test_plugin_runtime.py`。
- M0 种子：官方九包首启懒加载种子到 `data_dir/plugins/<id>/<fingerprint>/`，`installed.json` 原子注册表；`PluginRuntimeManager` 默认解析器负责种子。
- M1 source.qqnt：`app/runtime_imports.py` 的 `RuntimeImportWorker` 接管 qqnt；`window_manager` 旧 `_QQNT_STATE/_qqnt_worker/start_qqnt_extract` 路径已删除；`tests/test_qqnt_runtime.py` 覆盖库内 sink、外部导出、取消、去重、inspect。
- M2 source.telegram / source.douyin / source.wechat：四导入 provider 全部走 `_RUNTIME_PROVIDERS`；`helper.wechat` RPC 由宿主提供 helper 操作内副本；`tests/adapters/importers/test_wechat_runtime.py` 用真实假 helper 脚本覆盖 inspect/list/失败脱敏/取消；微信低层 helper 生命周期在 `tests/adapters/importers/test_wechat.py` 直接单测。
- M3 同步：新增 `sync.open/sync.call/sync.close` 会话 RPC 与宿主 `RuntimeSyncSession`；保留宿主 staging/布尔校验/列表过滤/脱敏与 push-pull 编排；worker 侧恢复 Path 参数；移除 `connect_ftp` 旧连接 ABI；`tests/test_plugin_sync.py` 用本地会话夹具重写，loopback WebDAV 经 worker 全链路通过。
- M3 LAN：新增 `lan.open/accept/discovery/connection` RPC 与 `RuntimeLanTransport/RuntimeLanConnection` 代理；宿主保留加密、审批、命令与协调器所有权；`tests/test_lan.py` 端到端经真实 worker 通过。
- M4（部分）：`disabled_plugins` 配置键与严格 bridge DTO；启动时统一门控导入/同步/LAN；`/api/plugins` 只读目录路由；设置页「插件」分组（列表 + 启用/禁用，重启生效）与保存/重置集成。
- M4 安装/卸载/重载：`seeding.install_plugin/uninstall_plugin/installed_plugins`（meta 最小化仅 id/version/entry；官方 ID 拒绝；版本目录原子切换；不做包安全校验）；`/api/plugins/install|uninstall|reload|rollback` POST 路由；设置页文件选择安装、卸载确认、重载与版本切换；`tests/test_plugin_install.py` 覆盖元数据/更新/卸载/回滚。
- M5 边界反转（进行中）：README/AGENTS/project-structure 的“不提供”声明改为“不提供 marketplace 或不受信任插件沙箱；第三方插件仅支持本地 ZIP 安装、卸载与重启生效的启用管理”；`plugin_docs_check.py` 的 `DOCUMENT_FACTS`/`UNSUPPORTED_EXTENSION_FEATURES` 与两个 fixture 同步更新。
- 质量门现状：`black --check src/`、`ruff check src/`、`basedpyright` 全绿；相关 404 项测试通过（见各文件）。

未完成（下一步）：

- M4 余项：市场索引客户端、版本回滚 UI 与全局热重载入口确认（当前重载按单个插件停止 worker，下次动作重新加载）。
- M5 余项：`plugin_docs_check.py` 的离线校验报告需要用新版 inventory 复跑；进程内 legacy 适配层（`legacy_imports.HostImportWorker`/`LegacyImportSession`、旧 integrations shim、`PluginRegistry` 路径）与 `plugin_docs_check` 边界声明收口。

已知仓库既有问题（与本迁移无关，但影响整仓门禁）：

- 开发环境需先安装九个 editable 插件（`python scripts/plugin_packaging.py --install-editable-official plugins/...`），否则 `ohmymeme_plugin_*` 不可导入、大量既有测试失败。
- 陈旧测试导致收集错误：`tests/test_import_concurrency.py`、`tests/test_phash.py`、`tests/test_single_instance.py`、`tests/test_wechat_env.py`（引用旧 `src/*` 布局）。
- `tests/test_plugin_license_matrix.py`、`tests/test_storage_migration.py`、`tests/test_core.py` 的 Hotkey/Backup 用例在干净检出上同样失败（证据/工具已退役或 API 漂移）。
- Windows 检出 `core.autocrlf=true` 会使生成物 `bridge.ts` 为 CRLF，`tests/contracts/test_pywebview_bridge.py` 的 LF 断言需先跑 `mise run generate-schemas` 归一化。

## 1. 决策基线

| 序号 | 决策 | 说明与影响 |
| --- | --- | --- |
| 1 | 立刻进程化，不保留当前 runtime | 九个官方插件与所有第三方插件统一在独立 worker 进程运行；不设计、不保留进程内 runtime 兼容层；每个插件迁移完成即删除其进程内实例化路径，最终代码中不存在双路径 |
| 2 | 只支持 Python 插件 | worker 使用应用自带 Python 运行时；插件为纯 Python 包；不支持其他语言、不引入外部解释器 |
| 3 | 未签名包允许安装，安装前显式确认 | 安装确认弹窗展示插件信息与风险提示后才能落盘 |
| 4 | 不建立签名体系 | 不做 Ed25519、证书、发布者密钥、市场复签；包内不要求签名文件 |
| 5 | 不设网络与权限白名单，自由安装 | 不做网络域名允许列表，不做宿主侧网络代理强制；安装确认是唯一门槛 |
| 6 | 本文为落地计划 | 实施时按本文里程碑推进，并同步门禁与文档 |

风险声明（必须与安装确认文案、本文档一起出现）：

- 子进程只提供崩溃隔离、资源限制与接口边界，**不是安全沙箱**。插件仍以当前用户权限运行，可读写用户文件、访问网络。
- 无签名 + 自由安装意味着供应链风险（下载源被篡改、恶意插件）没有技术缓解，只能依赖 HTTPS、来源核对与用户确认。
- 宿主保证不向插件传递持久 Config 对象、数据库连接、WebUI 或宿主路径对象；不承诺对恶意插件的防护。

明确不做（非目标）：WASM 沙箱、跨语言插件协议、签名与审核体系、插件注入 HTML/JS/动态 Bridge、插件 UI DSL。

## 2. 目标架构

### 2.1 拓扑

```
宿主进程（pywebview + Bottle + SQLite + 缓存 + manifest）
 ├── PluginRuntimeManager     启动 / 监管 / 心跳 / 退避 / 熔断 / 整树回收
 ├── RpcChannel（每插件一条） Content-Length 帧 + JSON-RPC 2.0 over stdio
 ├── OperationBroker          staging 目录 / 配置与密钥注入 / sink / 进度 / 取消
 ├── PluginRegistry           bundled + installed / 版本指针 / 启用状态 / quarantine
 └── 固定 Host Actions        setup.js 触发 → 宿主调度 → 既有 Bridge 返回结构不变
        │  spawn + handshake
        ▼
worker 进程（每个插件一个，惰性启动）
 ├── 插件 Python 包（bundled 或 data_dir/plugins/<id>/<version>）
 ├── worker 内置 SDK：RPC / staging / 取消 / 心跳 / 日志
 └── 插件自建子进程（ffmpeg、微信 helper 等，随 worker 整树回收）
```

### 2.2 插件来源

- `bundled`：九个官方包，随冻结包分发，从打包目录加载，ID 即 canonical ID。
- `installed`：用户安装或市场下载，位于 `data_dir/plugins/<id>/<version>`，由 `plugin.json` 描述。
- registry 合并两个来源；第三方 ID 不得等于九个官方 ID；同 ID 安装视为更新。
- 不再要求第三方通过 pip、`entry_points` 或 editable 安装；`entry_points` 仅保留官方包构建期元数据。

### 2.3 所有权边界

宿主保留 SQLite、图片缓存、manifest 提交、Config、WebUI、原生能力、LAN 安全与审批；worker 只接收窄配置、限域密钥和 operation 临时目录（含 staging）。manifest/order/lease/hash 与 pull commit 仍由宿主拥有，不随网络代码进入 worker。

### 2.4 数据面

- RPC 只传元数据、小载荷与文件路径；大文件与批量图片走宿主发放的 staging 目录。
- 导入：worker 把产物写入 staging，宿主 sink 完成校验、去重与入库。
- 同步：后端方法（测试连接/列举/上传/下载/删除/建目录）在 worker 内执行，宿主保留 push/pull 编排与 manifest 维护；下载产物先落 staging 再提交缓存。
- 传输：worker 持有 socket 与 UDP 发现，宿主保留握手、加密、审批与命令。

### 2.5 与现有固定表面的关系

Bridge 方法名、参数、返回结构、错误哨兵、固定 UI 快照（`src/webui/plugin-ui.json` 九贡献）保持不变；插件管理作为宿主新功能独立加入，不进入九贡献投影。

## 3. Worker 运行时（Python 专用）

### 3.1 入口

- 冻结包：`OhMyMeme.exe --plugin-worker --plugin-id <id> --source <bundled|installed> --token <nonce>`，在单实例互斥与窗口初始化之前分流。
- 源码运行：`python -m ohmymeme.plugin_worker` 加同一组参数。
- 参数仅含插件标识与握手 token；不通过 argv/env 传密钥。

### 3.2 加载

- bundled：从打包路径 import 官方包模块。
- installed：把版本目录加入 `sys.path`，按 `plugin.json` 的 `entry`（`module:factory`）import；重复安装校验模块名与 ID 一致。
- 统一调用零参数 `create_plugin()` 获取独立状态实例。

### 3.3 ABI

沿用 `ohmymeme.core.plugins.contracts`：`PluginDescriptor`、`PluginCapabilities`、`ImportPluginContext`、`SyncPluginContext`、`LanPluginContext`、`PluginLifecycle`、`ImportSink`、`ImportProvider`、`SyncProvider`。worker 内构建上下文代理对象，使插件保持"像本地调用"的写法；插件业务代码不因进程化而改写（参考 go-plugin 的同进程语义设计）。

### 3.4 上下文代理

| 插件侧对象 | worker 实现 |
| --- | --- |
| `sink.import_path/import_bytes/import_batch` | RPC 调用宿主 sink，结果原样返回 |
| `progress(...)` | RPC 通知，宿主汇总为现有进度状态 |
| `is_cancelled()` | 本地标志，由宿主 `operation.cancel` 置位 |
| `operation.settings/secrets` | 启动时由宿主注入的内存代理；非密钥可写回并提交，密钥只读 |
| `operation.temporary` | worker 内真实临时目录（受路径校验） |
| `operation.redact/protect_secret` | worker 本地脱敏 + 宿主出口二次脱敏 |
| `context.request/resources` | `operation.start` 参数携带；微信 helper 副本等路径由宿主生成后只传路径 |

### 3.5 配置与密钥

非密钥配置继续存 `plugins.<id>.*`；密钥沿用 Fernet 加密存储、按操作注入；worker 不读取 config.json。第三方插件若需要新配置键，在 `plugin.json` 声明类型，宿主按声明渲染表单并存储。

### 3.6 子进程后代

ffmpeg、微信 helper 等由插件在 worker 内启动。宿主通过 Job Object（Windows）或进程组（POSIX）对 worker 整树 kill，取消、卸载、崩溃重启统一处理；不再由宿主代替插件托管 helper 生命周期，但宿主仍提供 helper 副本路径与 SHA-256 校验结果。

### 3.7 日志

worker 的 stderr 按行进入宿主 logger，附插件前缀并执行宿主脱敏；每插件保留 `data_dir/plugin-workspaces/<id>/worker.log`（滚动）；调试模式可保留协议原文。

## 4. RPC 协议 v1

- 帧：`Content-Length: N\r\n\r\n<UTF-8 JSON>`；stdout 只走协议，stderr 只走日志。
- 消息：JSON-RPC 2.0；进度与日志用通知；错误码使用标准区间加宿主域错误对象，并映射到现有失败哨兵语义。
- 握手：worker 发 `hello {protocol_version, plugin_id, plugin_version, api_version, capabilities, pid, nonce}`；宿主校验来源、ID、ABI 与 token 后回 `welcome {session, config, secrets, staging_root, limits}`；校验失败回 `reject {code, message}` 并终止进程。不兼容给出人类可读原因（协议版本、API 版本、来源缺失）。
- 方法表（固定集合，禁止扩展注册）：
  - host→worker：`initialize`、`operation.start`、`operation.cancel`、`operation.drain`、`config.get`、`config.set`、`shutdown`、`ping`
  - worker→host：`progress`、`log`、`stage.path`、`sink.import_path`、`sink.import_bytes`、`sink.import_batch`、`operation.finished`、`pong`
- 操作模型：每插件同一时刻至多一个操作；`op_id` 由宿主生成；取消后宽限期内未结束即 kill；drain 等待 staging 清理与 sink 提交完成。
- 限额：单帧上限、握手超时、心跳超时、取消宽限、并发插件数上限；导入类操作不设硬墙钟，用进度停滞检测。

## 5. 进程生命周期与隔离

- 启动：首次动作时惰性启动；空闲 TTL 后退出；手工重载直接换进程。
- 心跳：周期 `ping`，超时判定挂起并 kill；崩溃检测由通道 EOF 与退出码双通道确认。
- 退避：崩溃后按 1s/2s/4s 重启，10 分钟内 3 次即熔断并 quarantine，展示原因；在途操作标记失败，绝不循环重启。
- 回收：Windows Job Object（`KILL_ON_JOB_CLOSE`，可加内存上限）；POSIX `setsid` + `killpg`；宿主退出时先关管道再收 worker，保证无孤儿。
- 资源：内存上限（Windows Job Object；POSIX 可选 rlimit）、插件进程数上限、单插件并发 1、空闲回收。
- Windows 说明：worker 使用同一可执行文件启动，需要重启应用才能生效；旧版状态栏残留属于启动竞态，与本进度无冲突（相关修复已有方案，见第 7 节）。

## 6. 安装、卸载、更新与热重载

### 6.1 包格式

`*.omplugin`（zip）：

```
plugin.json          清单
<package>/           插件 Python 包
LICENSE              许可证文本
```

无签名文件；安装时计算 SHA-256 记录到注册表用于后续一致性检查（不用于信任判定）。

### 6.2 plugin.json 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| id | 是 | 唯一 ID，不得与官方 ID 相同；建议 `community.<name>` |
| name | 是 | 显示名 |
| version | 是 | 语义化版本 |
| api_version | 是 | 目标宿主 API 版本（当前 1） |
| kind | 是 | source / sync / transport |
| entry | 是 | `module:create_plugin` |
| capabilities | 否 | 声明式能力列表，展示与宿主记录用（非安全边界） |
| license | 否 | 许可证标识 |
| description | 否 | 简介 |

### 6.3 安装管线

1. 用户选择包（或市场下载到临时目录）。
2. 确认弹窗：插件名、ID、版本、kind、能力声明、来源路径、风险声明；未签名提示不可关闭地展示。
3. zip 安全检查：成员数上限、单成员/总解压上限、拒绝路径穿越与符号链接、拒绝可执行文件解压后越界。
4. `plugin.json` 校验：字段、ID 规则、kind、api_version、entry 语法。
5. 原子落盘 `data_dir/plugins/<id>/<version>`，注册表（`data_dir/plugins/installed.json`）更新并回读校验。
6. 可选立即启动 worker 并加载。

### 6.4 ID 与冲突规则

- 禁止使用九个官方 ID（`source.qqnt`、`source.telegram`、`source.douyin`、`source.wechat`、`sync.ftp`、`sync.s3`、`sync.r2`、`sync.webdav`、`transport.lan`）。
- 同 ID 视为更新：先安装新版本目录，drain 后切换 active 指针。
- 每个 kind 同时只允许一个活动实例；source/sync/transport 的多插件在 UI 中分别列出。

### 6.5 更新与回滚

保留上一版本目录；`active` 指针决定加载版本；更新失败或新 worker 启动失败自动切回旧版本并提示。回滚对用户可见、可手动触发。

### 6.6 卸载

drain 在途操作 → 停止并等待 worker 退出 → 删除版本目录与 active 指针 → 询问是否保留 `plugins.<id>.*` 配置；卸载不删除已入库数据。

### 6.7 热重载

- 代码重载 = 优雅停止 worker 后按新版本目录重启（不做 Python 模块级热替换）。
- 配置重载走 `config.set` 通知，即时生效。
- 更新/回滚/重载均在有任务运行时先提示 drain。

### 6.8 市场

静态索引（可放 GitHub Releases/Pages），条目含 id、版本、api_version、kind、sha256、下载地址、说明。无签名、无审核背书；客户端做兼容过滤、展示来源与哈希、用户确认后安装；支持下架列表（仅提示，不强制）。不做自动安装。

## 7. UI 规划（宿主所有）

- 设置窗口新增「插件」导航组：
  - 列表：名称、ID、来源（官方/第三方）、版本、kind、状态（运行/停止/隔离）、启用开关、崩溃计数。
  - 详情：配置表单（由声明类型渲染）、能力声明、日志查看、重载/回滚/卸载。
  - 安装：本地文件选择 + 确认弹窗；市场页（浏览、搜索、兼容标记、安装）。
- 导入设置页的第三方来源以动态行展示（宿主渲染），官方五行顺序与行为不变。
- 错误呈现：quarantine 原因、握手失败原因、崩溃次数、版本回滚记录。
- 不变式：插件不得注入 HTML/JS/动态 Bridge；主窗口不加载插件代码；管理 UI 是宿主功能，不进入固定九贡献。
- （说明）启动早期窗口布局相关的既有修复继续沿用，本节不改变启动动画与拖拽逻辑。

## 8. 宿主改造清单

| 模块 | 动作 | 要点 |
| --- | --- | --- |
| `core/plugins/manifest.py` | 修改 | bundled 清单保持九个 canonical 条目；新增 installed 来源描述与合并逻辑 |
| `core/plugins/registry.py` | 修改 | 由"描述符 + entry_points"改为"bundled + installed 注册表 + 版本指针 + 状态机" |
| `core/plugins/runtime/`（新增） | 新增 | `manager.py`（进程与状态）、`channel.py`（帧与 RPC）、`handshake.py`、`worker.py`（worker 入口）、`staging.py`、`schema.py`（插件配置声明） |
| `core/plugins/contracts.py` | 冻结 | 插件 ABI 不改签名；worker 侧代理实现放 runtime |
| `core/plugins/policy.py` | 修改 | 保留脱敏与操作临时目录；配置改为按插件声明校验；密钥注入不变 |
| `presentation/desktop/api/plugin_dispatch.py` | 修改 | `HostDispatcher` 改为按 runtime 路由；失败哨兵、参数校验、进度字段保持 |
| `presentation/desktop/api/facade_base.py` | 保持 | Bridge 入口不变，仅底层调用对象变化 |
| `presentation/desktop/import_workers.py` | 修改 | 宿主线程/coordinator 保留；provider 调用改走 runtime；昵称缓存与外部导出投影留在宿主 |
| `services/sync/backends.py` | 修改 | 后端类变为 RPC 代理，方法签名不变 |
| `services/sync/service.py` | 修改 | push/pull 编排、manifest、state、锁保持；后端调用链换 RPC |
| `services/lan/server.py` | 修改 | 安全/审批/命令/lease 保持；socket 与发现进 worker，监听/会话注册改为登记 worker 与操作 |
| `core/config.py` | 修改 | 新增 `disabled_plugins`（可选）与 `plugins.<id>.*` 声明式配置；不存运行状态 |
| `main.py` / `scripts/launcher.py` | 修改 | 增加 `--plugin-worker` 分流，先于单实例互斥与窗口初始化 |
| `scripts/build.py` | 修改 | worker 入口加入 hiddenimports；第三方插件不入冻结包 |
| `scripts/plugin_abi_matrix.py` | 修改 | 探针改用 fake runtime；通用插件管理动作加入矩阵 |
| `scripts/plugin_ui_dispatch.py` | 保持 | 九贡献快照不变；管理动作排除出 UI 投影 |
| `scripts/plugin_packaging.py` | 修改 | 官方包 staging 规则不变；新增 installed 包校验入口 |
| `scripts/plugin_docs_check.py` | 实施时反转 | `UNSUPPORTED_EXTENSION_FEATURES` 与 fixtures 改为新边界断言 |
| 进程内实例化路径 | 删除 | `_import_workers` 缓存、`HostActionAdapter` 直连 provider、`get_backend` 直构等按插件迁移即删，最终清零 |

Bridge 新增固定动作（草案，实施时冻结）：`plugins_list`、`plugin_install`、`plugin_uninstall`、`plugin_set_enabled`、`plugin_reload`、`plugin_rollback`、`plugin_get_config`、`plugin_set_config`、`plugin_get_logs`、`plugin_check_updates`；如采用只读 HTTP 路由 + Bridge 变更动作的组合，需在 action 矩阵与契约中同步登记。

## 9. 里程碑

| 里程碑 | 内容 | 退出条件 |
| --- | --- | --- |
| M0 | 协议 v1 冻结；runtime 骨架（manager/channel/handshake/worker 入口）；conformance 测试用假 worker | 协议文档 + 协议测试通过；现有全部门禁不变 |
| M1 | 试点插件（建议 source.douyin，备选 sync.ftp）端到端进程化 | 该插件全部现有测试在 worker 模式下通过；删除其进程内路径；矩阵/契约更新 |
| M2 | 其余 source 插件（telegram/qqnt/wechat）迁移；helper 与 ffmpeg 整树回收 | 四个来源的导入与取消/进度 parity；helper 无孤儿 |
| M3 | sync 四后端与 transport.lan 迁移 | 同步/局域网功能 parity；LAN 数据路径压测并确定实现（见未决项） |
| M4 | 安装/卸载/更新/热重载 + 插件页 + 市场骨架 | 安装攻击用例、回滚、确认流程与 UI 测试通过 |
| M5 | 文档边界反转、门禁更新、进程内代码清零、市场（可选） | `plugin_docs_check` 新断言通过；仓库无进程内 provider 实例化 |

每步落地前后都必须通过：`mise run lint`、`typecheck-python`、`test-python`、`typecheck-frontend`、`test-frontend`、`test-contracts`、`build-frontend`、`e2e`、`package-smoke`。

## 10. 测试矩阵

- 协议：帧边界、坏 JSON、未知方法、版本拒绝、超大帧、握手 token 错误。
- 生命周期：取消、drain、崩溃退避、熔断 quarantine、重载/回滚、宿主退出无孤儿、Windows 整树 kill。
- 安装：zip 穿越/炸弹/链接、字段缺失、ID 冲突、同 ID 更新、卸载 drain、确认流程。
- 功能 parity：四个 source 导入（含微信 helper、TG webm 转换、QQNT 导出投影）、四个 sync 后端、LAN 握手与文件传输、脱敏输出。
- 性能：批量导入 RPC 帧与 staging 复制开销、sync 大文件、LAN 帧大小与并发。
- e2e：安装示例插件、插件页启停/卸载、导入动态行。
- 证据：矩阵生成器（abi/action/ui/license/packaging）全部在 worker 模型下重新校验。

## 11. 文档与证据同步

- 实施时更新 `README.md`（官方插件扩展边界段）、`AGENTS.md`（桥接规范与插件边界段）、`docs/project-structure.md`（重组边界段），并反转 `plugin_docs_check.py` 的固定断言与三个负例 fixture。
- M0 产出 `docs/plugin-worker-protocol.md`（协议全文），本文档保留为总计划。
- 许可证：第三方插件不由本仓库分发；市场只承载索引与下载链接；现有 `docs/plugin-license-matrix.json`、`NOTICE`、`LICENSES/`、`THIRD-PARTY-NOTICES/` 的证据范围与 hash 策略不变。
- 版本号：worker 协议版本与插件 API 版本分别维护；不兼容变更必须同时推进 `PLUGIN_API_VERSION` 与协议版本并在文档记录。

## 12. 风险与未决

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 性能 | 批量图片与同步大文件经 RPC/staging 有额外拷贝；LAN 每帧往返 | staging 与缓存同盘优先 rename；LAN 压测后决定数据路径实现 |
| 隔离误读 | 子进程被当作沙箱 | 安装确认与文档统一使用"崩溃/资源隔离"表述并明示风险 |
| 冻结布局 | worker 定位 bundled 包与 helper 的路径依赖 PyInstaller 布局 | M0 先做冻结 smoke；路径解析集中在 runtime |
| 防火墙 | worker 联网可能触发系统提示 | 沿用同一可执行文件启动；首次联网行为纳入 M3 验证 |
| 调试体验 | 进程化后断点与日志链路变长 | `--plugin-worker --debug` 手动启动、协议原文日志、假 worker 工具 |
| 测试改造量 | 现有 in-process 探针与测试需重写 | 按插件逐个迁移、每个里程碑只改对应测试 |
| 供应链 | 无签名、无白名单 | 明确为已接受的用户风险；提供来源与哈希展示，不声称防护 |

未决项：

1. bundled 插件提供给 worker 的方式：直接从打包目录加载，还是首次启动复制到 `data_dir/plugins` 作为种子（倾向前者，避免双份与版本漂移）。
2. worker 是否允许 `import ohmymeme.*`：决定 2 下插件不可避免依赖宿主基础模块（`core/imports`、`core/adapters/fetch_policy`、`core/plugins/network_config`、`import_runtime`）；倾向允许并冻结该子集为 worker ABI 一部分。
3. LAN 数据路径：字节流经 RPC 代理（宿主保留加密）还是 worker 内跑会话循环（宿主只做握手/审批回调）；M3 压测后定稿。
4. 每插件进程上限与空闲 TTL 默认值。
5. 第三方插件依赖策略：一期禁止运行时 pip 安装，插件只能携带纯 Python 代码；是否允许内置二进制附带按第 3.6 节处理。
6. 配置 schema 复杂度：一期只支持 string/int/bool/enum/path 与密钥只读展示。
