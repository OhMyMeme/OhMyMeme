# OhMyMeme 完整插件平台规划

日期：2026-10-09。

状态：完整实施规划，尚未开始本规划中的业务代码实施。本文中的 SDK、接口名、清单 v2、扩展点和示例均为目标契约，不代表当前程序已经提供。

本轮交付规划文档，不安装依赖、不改业务代码、不提交或推送。后续按里程碑实施与验收，不能把“已写规划”标记为“平台已完成”。

## 0. 阅读方式与文档效力

- 第 1 节描述按当前源码确认的基线；第 2～12 节定义目标；第 13～15 节规定实施和验收。
- 本文是从“固定官方插件化”走向“完整第三方插件平台”的后续总规划。
- [旧子进程计划](plugin-runtime-plan.md)和[旧 UI 注入计划](plugin-ui-injection-plan.md)保留历史决策及实施记录；其中市场、固定设置页导入、配置声明位置等旧设想不直接作为本平台的实施要求。
- [README](../README.md)、[AGENTS](../AGENTS.md)与[项目结构](project-structure.md)的现行行为约束仍有效。只有对应里程碑落地、验证后，才同步修改“当前支持能力”的描述。
- 动态业务 provider 注册是本规划的目标；任意 Python 方法调用、动态 pywebview Bridge、宿主 DOM 注入不是目标。开放业务接口与放开内部对象是两件事。
- 本规划不开展安全审计。能力授权、输入校验和信任提示仅作为平台功能契约设计；不声称现有 worker 能隔离恶意代码。

## 1. 当前基线与缺口

### 1.1 可以复用的底座

| 已有能力 | 当前证据入口 | 复用方式 |
| --- | --- | --- |
| 每插件独立 worker、stdio RPC、握手、心跳、退避、空闲回收、进程树关闭 | [runtime](../src/ohmymeme/core/plugins/runtime/manager.py)、[worker](../src/ohmymeme/core/plugins/runtime/worker.py) | 扩展现有单一运行时，不另建进程内或第二套插件引擎 |
| 官方种子、第三方 ZIP、活动版本、重载、版本切换 | [seeding](../src/ohmymeme/core/plugins/runtime/seeding.py)、[Bottle 路由](../src/ohmymeme/presentation/desktop/bottle_app.py) | 升级安装事务与元数据，不改变用户数据根 |
| 主窗口导入注册、四类 UI 贡献、插件 iframe | [UI 声明](../src/ohmymeme/core/plugins/runtime/ui_injection.py)、[导入网关](../src/ohmymeme/presentation/desktop/api/ui_contributions.py) | 形成统一贡献目录和前端 SDK |
| 私有配置命名空间与 secret 加密保存 | [配置](../src/ohmymeme/core/config.py)、[UI 配置](../src/ohmymeme/core/plugins/runtime/ui_config.py) | 补配置声明、版本迁移和操作级注入 |
| 图库应用服务、导入 sink、备份、资源 lease、持久写入协调 | [图库](../src/ohmymeme/app/library.py)、[导入](../src/ohmymeme/app/runtime_imports.py)、[任务](../src/ohmymeme/app/operation_coordinator.py) | 通过宿主 SDK 调用这些服务，不复制业务算法 |
| JSON Schema、生成 DTO、Bridge/架构测试和发布契约 | [生成器](../scripts/generate_bridge_schemas.py)、[任务配置](../mise.toml) | 增补平台契约与第三方 conformance，不削弱既有门禁 |

### 1.2 必须打通的固定接线

| 当前边界 | 缺口 | 目标 |
| --- | --- | --- |
| [registry.require](../src/ohmymeme/core/plugins/registry.py)核验九个 canonical 身份 | 任意第三方业务 provider 不能按标准角色接入 | 官方身份与业务角色解耦 |
| [PluginPolicy](../src/ohmymeme/core/plugins/policy.py)按官方 ID 准备配置、密钥与能力 | 第三方动作没有同等上下文 | 声明驱动的受控宿主上下文 |
| 第三方 `ui.action` 只调用 `handle_ui_action(name, payload)` | UI 注册不等于后台任务或入库 | query/task/session 三种执行模型 |
| [TaskKind](../src/ohmymeme/core/domain/sync.py)和任务互斥组为固定枚举 | 新插件任务需要改宿主枚举 | 命名空间任务 ID 与宿主效果级协调 |
| [SYNC_CONFIGS](../src/ohmymeme/core/plugins/network_config.py)固定四种同步后端，LAN 固定 `transport.lan` | 新同步、传输需要新增宿主分支 | 标准后端与传输 provider 注册 |
| 两套 iframe 消息形状、名称推断进度、有限的 UI 注入点 | 插件作者仍依赖宿主实现细节 | 统一 SDK、显式任务和命令绑定 |
| 图库能力在宿主 Bridge/应用服务内部 | 插件无法标准化读图、打标签、分组和处理选区 | 版本化图库、资产和交互 API |

上述是接入缺口，不是说项目没有任务、持久配置或生命周期管理。现有机制要泛化并接通第三方，而不是重新实现。

## 2. 平台目标与范围

### 2.1 “完整”的定义

外部开发者只使用公开 SDK 和插件包，就能实现下列功能；除增加该插件自身文件外，不修改宿主 Python、Vue、设置页、枚举或打包白名单：

1. 新软件、本地目录或在线服务的表情来源：选择来源、扫描、提取/下载、进度取消、去重入库、分组。
2. 已有图库的 AI 标签、OCR、自动分类、批量整理：读取被授权图片、提出或提交元数据变更。
3. 图片处理、格式导入与导出：转换、压缩、裁剪、动图处理，保留原图，生成新资产或导出用户选择的位置。
4. 搜索扩展与虚拟视图：语义搜索、相似检索、插件分类结果，不绕过宿主筛选和分页。
5. 新远程同步后端与传输方式：实现标准 I/O，复用宿主同步、提交和会话策略。
6. 命令与界面扩展：导入列表、右键、批量工具、工具栏、侧边栏页面、设置面板、快捷键与声明式主题。
7. 事件自动化：用户明确启用后，在导入等事件发生时触发插件任务。
8. 完整管理：安装、配置、授权、启停、任务查看、日志、更新、重载、回滚、卸载。
9. 开发交付：模板、SDK 文档、离线校验、调试、打包、契约测试以及源码/冻结运行验证。

### 2.2 边界内开放，而非任意访问

| 归宿主所有 | 归插件所有 |
| --- | --- |
| 应用 SQLite、图片持久提交、缓存根、缩略图、manifest、lease、事务与恢复 | 来源协议、提取/解析/下载、处理算法、搜索/AI 算法 |
| 主窗口壳、宿主 DOM、固定 Bridge、窗口、剪贴板、拖拽、选择器 | 自己的声明与 iframe 内 HTML/CSS/JS |
| 用户授权、插件状态、任务调度、配置和密钥注入、资源回收 | 自身设置需求、按操作收到的配置/密钥、临时产物 |
| 同步 diff、hash、排序/分组应用、pull commit | 后端远程 I/O、传输字节流 |
| LAN 认证、设备审批、加密、命令与文件验证 | 发现、监听、连接与字节读写 |

插件调用业务方法，不获得数据库连接、完整 Config、WebUI 对象、应用持久根或任意宿主对象 getter。读取原图通过受控资产投影，写入经过应用服务。插件私有持久数据也由宿主存储 API 管理。

### 2.3 非目标

- 不替换 Python、Bottle、pywebview、Vue 3 或设置页 vanilla 技术栈。
- 不把应用核心功能或数据库搬到插件，不重构无关目录。
- 不开放任意 SQL、任意宿主 Python 调用、任意脚本注入或通用 UI DSL。
- 不新增跨语言运行时、WASM、安全沙箱、签名/审核、付费商城或在线 marketplace。
- 不要求用户在应用运行期间使用 pip/npm 安装插件依赖，不修改应用或系统共享 Python 环境。
- 不为了平台化改变既有用户数据路径、同步 manifest、备份 ZIP、LAN 协议或更新合同。
- 在线索引/市场不是“完整业务能力”的前置条件，若以后需要单独规划。

## 3. 关键架构决策

| 编号 | 本规划采用的方案 | 原因 |
| --- | --- | --- |
| D01 | 复用一个子进程运行时，官方与第三方共享平台接入机制 | 不维护两套行为和生命周期 |
| D02 | 保留九个官方 ID 与 canonical 分发清单；业务角色不再以官方 ID 为白名单 | 兼容官方发布证据，同时开放新 provider |
| D03 | 只读取已安装注册表、明确的开发目录和官方分发声明 | 不扫描任意环境 entry point，不自动执行未知目录代码 |
| D04 | 宿主 SDK 方法集固定、版本化；插件 action/provider/command ID 可以声明注册 | 动态贡献不等于动态 Bridge 或任意 execute |
| D05 | 清单统一声明动作参数、结果和模式，UI 只引用动作 | 不让前后端分别定义同一业务契约 |
| D06 | 短查询、后台任务、长连接会话分开 | 不用同步 UI 请求承载长时间导入或同步 |
| D07 | 先申请任务和资源，再执行/提交；副作用归宿主应用服务 | 保留当前取消、存储切换、备份和关闭正确性 |
| D08 | RPC 传小对象、句柄和任务状态，大文件使用操作工作区 | 复用 staging，不把整库图片转为巨型 JSON/base64 |
| D09 | UI 模板和命令由宿主渲染，复杂页面在 iframe 中运行 | 插件不侵入宿主 Vue/DOM |
| D10 | capability 控制宿主 SDK 调用，不承诺约束 Python 的全部 OS 行为 | worker 是崩溃/资源隔离，不是不可信代码沙箱 |
| D11 | API/清单/UI/传输版本分别维护，使用适配器保留旧 ABI | 不通过全局替换版本号一次破坏旧插件 |
| D12 | 不删除旧兼容入口直到真实调用方和契约证据允许 | 平台化不是顺便清理所有旧代码 |

### 3.1 层次与依赖方向

- `core/plugins/`：清单、角色/方法契约、能力和 scope、注册状态、RPC、worker；不得反向 import app/services/presentation。
- `app/`：平台宿主 broker，接入已有 Library/Import/Backup/Settings/任务服务；负责调用 admission、业务效果协调及结果归一化。
- `services/`：同步与 LAN 编排保留，provider 从注册目录选择。
- `integrations/`：原生能力适配器及已有外部资源策略；平台只提供窄端口。
- `presentation/desktop/`：固定 HTTP/Bridge 网关，身份由宿主会话确定，不拥有图库事务。
- `presentation/frontend/`：贡献渲染、命令路由、任务面板与 iframe SDK；主窗口不加载插件 Python，不直接访问内部服务。
- 插件：只依赖公开 Python SDK、自己的依赖与前端 SDK，不依赖上述内部模块布局。

拟新增公开 Python 入口为 `ohmymeme.plugin_sdk`；公开 TS/JS SDK 由共享契约生成。SDK 只是现有 RPC 的客户端和 DTO，不是另一套运行时。

## 4. 插件清单、身份与注册

### 4.1 包结构

目标 ZIP 布局示例，不是当前安装器已接受的格式：

```text
plugin.json
ui.json                          可选：界面与命令贡献
folder_plugin/                   有 Python 动作时必需
  __init__.py
schemas/
  import-input.json
  import-output.json
  settings.json                  按实际需要提供
ui/                              可选：HTML/CSS/JS/图标
vendor/                          可选：已打包的插件私有依赖
LICENSE
THIRD-PARTY-NOTICES/              携带依赖时按实际许可提供
```

不强制每个插件都拥有 UI 或 Python：后端 provider 可以没有 UI；仅声明主题/页面且没有 Python 动作的包可以不创建 worker。含 Python 动作的包保持零参数 `create_plugin()`。

### 4.2 清单 v2 示例

```json
{
  "schema_version": 2,
  "id": "community.folder",
  "name": "目录来源示例",
  "version": "1.0.0",
  "entry": "folder_plugin:create_plugin",
  "api_version": 2,
  "requires": {
    "sdk": ">=2.0.0 <3.0.0",
    "python": ">=3.12 <3.13"
  },
  "platforms": ["Windows", "Darwin", "Linux"],
  "architectures": ["x86_64", "arm64"],
  "license": "GPL-3.0-only",
  "capabilities": {
    "required": ["sources.read", "imports.submit", "native.pick"],
    "optional": ["collections.write"]
  },
  "providers": [
    {"id": "folder", "type": "import.source", "action_id": "import_folder"}
  ],
  "actions": [
    {
      "id": "import_folder",
      "mode": "task",
      "input_schema": "schemas/import-input.json",
      "output_schema": "schemas/import-output.json",
      "effects": ["library.import"],
      "capabilities": ["sources.read", "imports.submit"]
    }
  ],
  "settings_schema": "schemas/settings.json",
  "ui": "ui.json"
}
```

规范要求：

- 插件 ID 全局唯一；贡献/provider/action/command 使用插件内局部 ID，注册时组成 `(plugin_id, local_id)`，不依赖名称前缀判断身份。
- 第三方不得占用九个官方 ID，也不得替换官方缺失/禁用 provider。新后端是新条目，不是旧后端的静默 fallback。
- `schema_version`、插件版本、SDK 范围、Python ABI、平台架构、能力、动作和资源必须整体验证。
- 输入和结果 schema 只使用平台支持的 JSON Schema 子集及包内引用；不允许远程 schema 解析或可执行校验脚本。
- 基础设置支持现有字段类型，增加默认值、范围、描述和 schema 版本；不扩展为任意表单 DSL。
- `ui.json` v2 引用 `action_id`，不重复定义动作签名；v1 声明仍走兼容适配。
- 新包保留已校验的全部元数据，不能像旧安装器一样只保留 id/version/entry 而丢掉 SDK 信息。
- 一个包可以注册多个角色；角色实现的必需方法、会话语义及 schema 均由宿主的角色契约固定。

### 4.3 注册目录与有效状态

统一生成只读有效目录：插件、provider、action、command、UI、event subscription、格式和主题贡献。

- 静态读取声明不启动 worker；工厂加载失败与声明验证失败分别报告。
- 安装/更新、启停、授权改变、重载、回滚后推进 registry generation，重新计算可用贡献。
- 调用必须绑定插件 ID、版本和 generation，宿主每次复核；旧 iframe/旧句柄不得调用切换后的版本。
- 插件管理始终能展示“缺失依赖/不兼容/未授权/隔离”等原因；主窗口导入仍隐藏缺失、禁用、不支持当前平台和缺少界面资源的来源。
- 同类型 provider 可以并存；用户明确选择活动搜索、同步或传输提供方，不按安装顺序抢占默认项。

## 5. 公共 SDK 与宿主能力

### 5.1 调用形状

- Python SDK：接收宿主注入的 `context`，提供 `library`、`assets`、`imports`、`tasks`、`settings`、`storage`、`events`、`native` 等窄代理。
- 前端 SDK：提供初始化、能力查询、宿主方法调用、插件动作调用、任务订阅、事件订阅、通知、关闭页面与主题上下文。
- 宿主方法名来自平台固定方法表；参数和结果由同一份契约校验，并生成 Python 校验数据、TS DTO 和 API 文档。
- 新 Python 动作采用 `handle_action(action_id, payload, context)`；旧 `handle_ui_action(name, payload)` 不改签名，使用 v1 适配器。
- 不能用 `getattr(host, payload.method)`、任意 module/function 路径、eval 或临时注册 Bridge 实现 SDK。

统一 SDK 结果示例：

```json
{"ok": true, "request_id": "request-1", "result": {"task_id": "task-1"}}
```

```json
{
  "ok": false,
  "request_id": "request-1",
  "error": {
    "code": "permission_denied",
    "message": "未授权图库标签写入",
    "retryable": false,
    "details": {"capability": "tags.write"}
  }
}
```

错误至少覆盖：参数/结果无效、插件不兼容/禁用、能力未授权、过期 generation/句柄、对象不存在、资源忙、任务取消、配额超限、worker 失败及部分提交。SDK v2 错误不替换旧 Bridge 的 None/bool/原错误哨兵。

### 5.2 宿主方法与效果矩阵

下列名称为规划接口族，M0 必须形成逐方法参数/结果表后才能编码。

| 接口族 | 完整目标能力 | 权限与效果 | 应用层落点 |
| --- | --- | --- | --- |
| `application` | 版本、平台、SDK 能力、当前插件状态；打开宿主页面 | 只返回公开信息，不返回全部配置 | Container/表现层窄端口 |
| `library` | 按 ID 读取、分页搜索/count、收藏/最近/未分类、分组和标签过滤 | `library.read`；响应不含持久路径 | LibraryQueries/Catalog |
| `assets` | 图片元信息、缩略图、原图操作内只读副本、受控导出 | `assets.read`/`assets.export`，读 lease 与有界资源 | AssetPaths/媒体与文件适配器 |
| `tags` | 单图读取、覆盖设置、批量追加/移除 | `tags.write`；明确追加与覆盖差异 | LibraryService |
| `collections` | 创建/重命名/删除、嵌套、成员追加/移除/移动/替换、分页查询 | `collections.write`；保留深度/后代/空组规则 | LibraryService |
| `memes` | 重命名、收藏显式设置、删除、最近记录、分页槽位排序 | 分开 `memes.write`、`favorites.write`、`library.delete`、`ordering.write` | LibraryService，不直连 DB |
| `imports` | 操作产物提交、精确去重、数量/尺寸限制、批量结果、自动分组 | `imports.submit`，写 admission/lease | ImportService/sink |
| `tasks` | 启动已声明动作、查询/订阅、取消、结果与日志 | 任务归属检查，效果级互斥 | OperationCoordinator/runtime |
| `settings` | 自身配置读取/保存、版本、默认值及操作级 secret | 自身命名空间；密钥不回显到通用 UI | Config/PluginPolicy |
| `storage` | 自身 JSON/小对象、操作内私有文件投影、提交/列举/删除、空间使用 | `storage.private`，配额与原子提交 | 宿主插件存储适配器 |
| `sources` | 用户选择的文件/目录枚举、元信息与操作内投影 | `sources.read`，来源授权句柄 | 来源文件与原生选择适配器 |
| `native` | 文件/目录/另存为、确认、打开允许的 URL/输出、剪贴板、复制和原生拖拽请求 | 独立 capability；需要界面的动作保留用户交互上下文 | 平台适配器与窗口 owner |
| `commands` | 执行声明命令、获取受控选区/分组上下文、快捷键注册状态 | `ui.commands`/`native.hotkey`；命令冲突显式拒绝 | 表现层命令注册表 |
| `events` | 订阅允许事件、取消订阅、补取当前快照 | `events.subscribe`，按插件 scope 过滤 | 宿主事件 broker |
| `sync` | 列出/选择 backend、连接测试、push/pull、进度、取消、经确认的清理 | 普通同步与删除远程能力分开 | 现有 SyncService |
| `transport` | 发现、连接、监听、会话状态与取消 | 仅标准会话/字节端口，宿主审批与协议保持 | 现有 LAN 与传输应用适配 |
| `backup` | 信息、经用户确认的备份/空库恢复与任务 | `backup.manage`；沿用资源互斥及 ZIP 合同 | BackupService |
| `preferences` | 公共字段的读取/修改、打开存储迁移/更新等宿主流程 | 明确字段白名单，危险变更交宿主确认 | Settings/宿主流程 |
| `tools` | 使用平台工具或包内声明工具并登记进程 | 限定工具 ID 与参数契约，不提供任意 shell execute | 现有工具/进程资源端口 |

“开放”包含请求现有宿主功能，不代表插件能自行恢复非空库、改变数据根或关闭应用。备份恢复、存储迁移、远端删除等操作必须经过宿主现有前置条件和确认流程。

### 5.3 资产与来源句柄

- UI 得到来源句柄或资产引用，不直接得到应用 cache/data/config 路径。
- 原生选择器由宿主打开，返回绑定插件/任务/读写范围的句柄；取消是明确结果，不伪装为空目录。
- worker 可将授权输入物化到操作目录；原图读副本、输出 staging 和用户选定导出目标分开。
- 文件类 RPC 只传引用、相对工作区路径和有界元信息；图片字节走文件或有界流。
- 查询、任务或会话结束后清理操作投影；CF_HDROP/剪贴板和原生拖拽使用的文件必须按宿主现有生命周期保留，不能复制成功就删掉。
- 存储切换后旧 sink 继续使用共享 AssetPaths，不缓存旧根；过期句柄被拒绝，不悄悄指向另一文件。

### 5.4 能力声明与授权

- 授权分为宿主 SDK 能力、操作来源/资产范围、用户确认三个层次；必需能力拒绝时对应功能不可用，可选能力拒绝时明确降级。
- 安装、首次调用或能力增加时展示请求；更新不能静默获得新能力。
- 每次宿主调用复核身份、版本、有效状态、能力、scope、schema 和资源 admission，不只在前端检查。
- `effects` 是宿主认识的固定枚举，例如 library.read/library.import/library.metadata/library.delete/sync/session；不是插件自选任意锁名。
- 不以这些授权声称可以阻止受信 Python 插件直接使用 OS/网络。平台不建立宿主网络代理、域名白名单或不可信代码沙箱。

## 6. 后台任务、提交与生命周期

### 6.1 三种执行模型

| 模式 | 场景 | 行为 |
| --- | --- | --- |
| query | 检测环境、读取信息、短查询 | 有界超时；只读或明确的短操作，不把同步接口当长任务 |
| task | 导入、AI、处理、导出、后台同步 | 返回 task ID；有进度、取消、日志、结果、工作区和资源登记 |
| session | 远程 backend、传输连接、显式启用的事件监听 | 显式 open/close、idle pin、deadline 与断开处理 |

任务 ID 由宿主生成，绑定插件/动作/版本/运行代次；不再为每个插件新增 `TaskKind.IMPORT_xxx`。内建 TaskKind 保留兼容映射，任务协调内部逐步接入通用任务描述和宿主效果组。

### 6.2 标准任务流

1. 从有效目录解析动作与 provider，校验输入和能力。
2. 取得任务 admission，决定资源冲突；停止/关闭/迁移中明确返回 busy/closed。
3. 创建任务记录、资源 scope、工作区和配置/密钥快照，登记清理责任。
4. 惰性启动 worker，注入上下文，执行已声明 action/provider。
5. worker 报告阶段、done/total、字节和消息；未知总量不伪造百分比或 ETA。
6. worker 产物交宿主；宿主验证、去重、事务提交、维护 manifest 和结果。
7. 持久提交之后发布变更事件，宿主 UI 按事件刷新；不依赖插件自行操作 Vue 状态。
8. 返回最终结果并 drain；完成资源释放前任务不可当作已回收。

状态统一为 pending/running/completed/failed/cancelled；现有 done/error 等 UI 状态由适配器投影。进度统一使用 0～100，无法计算时返回未确定值，不能从 action 名字后缀推断。

### 6.3 资源与并发

- 复用现有 DB/Config lease、导入锁、持久写入协调、备份/迁移互斥和关闭 drain。
- 插件扫描、网络和计算尽量在持久提交锁外进行；批量提交按有界批次取得写 admission，不能在长网络等待中占有数据库写锁。
- 同插件默认一个普通后台任务；同步 backend 可以有多个独立会话，但每会话状态隔离并受总数上限约束。
- 单个任务被取消时不直接回收其他活动会话；无法可靠单任务终止时先标记该 worker 所有受影响会话，再统一回收并报告。
- 线程、子进程、socket、临时资源先登记，后阻塞。心跳不延长业务空闲 TTL；活动任务、查询、订阅及会话不能被错误淘汰。
- query 默认超时、取消宽限、退出 deadline、队列/会话/资源配额在 M0 冻结；复用当前有界取消和退出策略，不为长期导入设置任意短硬超时。

### 6.4 提交结果、重试与部分成功

- 图片内容去重继续使用现有 SHA-256，不新造一套去重算法或哈希体系。
- 单图失败返回原因；批量返回已提交 ID、精确重复 ID、拒绝与失败项、计数。取消保留已提交部分。
- 元数据变更明确追加/覆盖/移动语义；批量操作不能悄悄只处理第一页。
- UI/传输重试使用宿主 request/task 记录避免重复副作用；副作用完成但响应丢失时，可查询结果，不自动重放。
- DB 已提交但 manifest 更新失败时不能谎称 DB 已回滚；返回已提交事实和投影状态，由宿主恢复 manifest。
- 处理插件默认生成新资产，不覆盖原图。危险删除、导出覆盖和未来原图替换必须有独立能力、明确确认与恢复语义。
- SDK 提交的标签/分组变更只能引用当前真实对象；慢 AI 结果应用前重新确认对象存在和所需版本条件。

## 7. 业务 provider 契约

### 7.1 角色目录

| 类型 | 插件负责 | 宿主负责 | 完成条件 |
| --- | --- | --- | --- |
| `import.source` | inspect、枚举、提取/下载、暂存与进度 | 任务、输入 scope、图片校验、去重、入库与分组 | 任意非官方来源完整导入闭环 |
| `media.processor` | 处理授权图片，输出新产物和明确元数据建议 | 选区、只读投影、产物验证、导入/导出及应用建议 | 批量转换与 AI 标签无需直接 DB |
| `format.importer` | 解析新容器/非直接支持的媒体，产出受支持图片 | 导入限制、规范化与持久提交 | 新格式由插件转换，不要求修改核心解码器 |
| `format.exporter` | 把授权资产组织为目标文件/容器 | 读取 scope、目标选择、碰撞确认与最终复制 | 导出不覆盖用户未授权文件 |
| `search.provider` | 查询、索引、返回 meme ID/分数/分页信息 | 库范围、标签/分组过滤、去重、对象有效性与显示 | 语义搜索不绕过宿主过滤或伪造图库对象 |
| `sync.backend` | 标准远程文件 I/O 与连接会话 | diff、manifest/hash、上传/下载编排、pull commit | 新后端进入设置与标题栏既有同步流程 |
| `transport.provider` | peer 发现、监听、连接与字节 I/O | 用户审批、认证/帧协议、命令与提交 | 非 LAN 实现不取得 DB 或任意远程命令入口 |
| `automation` | 声明订阅与动作，处理事件 | 用户启用、事件过滤、任务配额、防循环与退出 | 导入后自动分类有可见任务且可停止 |
| `command` / UI / theme | 命令动作、页面与白名单主题值 | 注册、上下文、布局、焦点与快捷键冲突 | 不触碰宿主 DOM 也能接入主要操作位置 |

### 7.2 导入来源

- 原生 picker 通过前端 SDK/宿主执行；来源 action 接收句柄及经过 schema 校验的参数。
- 扫描和下载仅输出到工作区，提交必须调用 imports SDK。
- 自动分组由提交返回的真实 ID 发起；精确重复可以按明确策略复用成员，不产生重复空组。
- 自动批量导入默认只做精确去重；感知相似处理必须声明策略或请求宿主交互，不能后台自动删除“相似图”。
- provider 失败、被禁用、平台不支持时拒绝本 provider；不调用其他官方来源兜底。

### 7.3 处理、AI 与搜索

- AI 不是额外一种特权运行时，使用普通 processor/search/automation + 网络依赖 + 自身密钥。
- 标签等建议可以先预览再应用；自动应用是另一个明确授权选项，默认不自动覆盖原标签。
- 处理结果的尺寸、类型、内容必须经现有 ImportService 验证；插件 MIME/扩展名不是唯一可信依据。
- 搜索 provider 返回真实 meme 引用，不返回任意 HTML；总量未知时显式报告，不伪造成确定 count。
- 私有索引通过 storage SDK 持久化，可重建；不改变宿主 memes/tags/collections 表结构。

### 7.4 同步后端

以[现有 RemoteBackendPort](../src/ohmymeme/services/sync/ports.py)为迁移起点：connect、ensure_remote_dir、upload_file、download_file、file_exists、delete_file、list_files、test_connection、close。

- M6 固定每个方法的输入、结果、错误、取消和会话关闭语义；v1 的历史 None/bool 结果由适配器保留。
- 清单声明配置 schema 与 secret 字段，UI 自动渲染，新 provider 不需要修改 `SYNC_CONFIGS` 或 `toggleSyncType` 分支。
- 明确读/写/删支持；只读后端只能显示拉取，不把未实现的上传或远端清理显示为可用。
- 每个并发 worker/连接拥有独立 backend 会话与凭据快照，关闭后清除操作密钥。
- 上传、下载仍经宿主 staging；网络 provider 不获得持久图片根。
- 保持远端 `{root}/memes/`、`meme-index.json`、分组并集合并和排序闭环。

### 7.5 传输

- 通用化发现、peer 信息、监听、连接、receive/send/timeout/close；大数据有界分块，不逐字节 RPC。
- 原 LAN provider 继续走既有手机兼容协议；新 transport 只替换传输层，不允许增加任意宿主远程命令。
- 若某新传输需要不同会话协议，必须单独声明并由宿主接入已定义协议适配，不能通过插件绕过审批和持久化边界。
- 监听服务属于应用会话，不属于设置窗口或 iframe 生命周期；隐藏窗口不关闭已授权服务。

## 8. UI、命令与前端 SDK

### 8.1 扩展点 v2

| 扩展点 | 内容 | 宿主行为 |
| --- | --- | --- |
| `imports.row` / `imports.iframe` | 来源入口、参数和复杂向导 | 只在主窗口统一导入入口出现 |
| `plugin_detail.panel` / `plugin_detail.iframe` | 插件配置与详情 | 保留现有管理位置和显式加载 |
| `commands` | 可复用命令定义 | 绑定动作、标题、图标、参数与上下文 |
| `context.meme` / `context.collection` / `batch.actions` | 单图、分组和选区命令引用 | 与宿主菜单合并，保持原有操作 |
| `toolbar.action` | 命令或页面入口 | 插件区/溢出菜单，不占用关闭、导入、同步等保留按钮 |
| `sidebar.view` / `views.page` | 自定义页面或受控图库虚拟视图 | 宿主管路由和焦点，页面自身使用 iframe |
| `settings.panel` / `settings.iframe` | 类型/功能配置页面 | 插件设置区或对应 provider 设置，不恢复设置页导入导航 |
| `meme.detail.panel` | 选中资产的附加信息 | 宿主只传授权元信息和引用 |
| `shortcuts` | 命令的窗口内/全局快捷键 | 宿主管冲突、保留组合键、注册/注销 |
| `theme.tokens` | 命名颜色/外观 token | 白名单值，用户明确选择，不执行全局 CSS/JS |

可见性只支持固定上下文条件，例如选择数量、所属视图、支持的媒体类型和 capability。不得把任意表达式或 JS 函数字符串作为宿主可执行 DSL。

### 8.2 统一前端协议

- 导入 iframe 和详情 iframe 共用一套 v2 消息规范及 SDK；v1 args/payload 形状由边缘适配器转换。
- SDK 的初始化包含插件、版本、frame ID、generation、已授权能力、主题、语言和宿主允许的命令上下文。
- 宿主只接受已登记 frame 的消息，忽略过期 frame；调用、取消、订阅/退订、错误都有明确协议。
- action 调用与 host SDK 调用分开；iframe 不能直接使用 `pywebview.api` 或提交任意 method。
- UI 贡献不进入 Config；设置值与运行状态分开保存。
- 任务进度由 task ID 与事件驱动，不通过 `progress$` 等名字约定判断。
- 页面关闭只清理 frame 订阅/临时资源；任务是否后台继续由用户选择，不一律取消或一律保留。

### 8.3 插件前端构建

- 原生 HTML/CSS/JS 和 Vue/其他框架构建产物均可，只要符合 SDK 和资源约束；不共享宿主 Vue 内部实例或组件私有状态。
- 插件资源路由支持清单内的相对 HTML/CSS/JS/图标及构建依赖，而不只返回单个 HTML。
- 本地 SDK 脚本和资源允许列表随包验证；不要求 CDN、外网脚本或任意 CSP 放开。
- `sandbox="allow-scripts"` 与宿主 DOM 隔离保持；主题通过 token 传递。
- 宿主通用表单支持真正的 v2 路径选择器、默认值、类型/必填/范围校验、处理禁用态与明确错误。v1 path 字段文本语义不悄悄改变。
- 插件页面必须满足标题、键盘焦点、Escape、Tab、加载失败/重试、任务离开确认和 reduced-motion 基线；自定义 UI 不绕过宿主危险操作确认。

## 9. 事件与自动化

### 9.1 首批公共事件

| 事件族 | 数据 | 语义 |
| --- | --- | --- |
| `library.imported` / `library.changed` / `library.deleted` | 有界 ID 集、revision、变更类型、origin | 持久提交后发送，失败事务不发送成功事件 |
| `tags.changed` / `collections.changed` | 真实对象引用、类型与 revision | 批量变更合并为有界通知 |
| `tasks.changed` | task ID、状态和进度快照 | 当前插件或用户明确授权的任务范围 |
| `selection.changed` / `view.changed` | 选区、当前分组、查询上下文 | UI 会话事件，离开页面后失效 |
| `plugin.changed` / `settings.changed` | 自身 generation、有效状态/配置版本 | 不包含密钥原文或其他插件配置 |
| `application.closing` | drain deadline | 只用于停止/清理，不允许开始新持久写入 |

### 9.2 可靠性与循环控制

- 每条事件含 event ID、序号、origin、causation ID 和可用的 revision；消费者可能收到重复通知，必须可去重。
- 不承诺持久事件队列或 exactly-once。断线/重载后拿快照与 revision；溢出时发 resync-required，不静默漏掉图库变化。
- 高频进度、选区、批量数据事件可合并；队列有容量和背压，不能把整库数据塞进通知。
- 自动化默认关闭，用户启用才注册长期订阅；默认忽略自身副作用产生的事件，因果链有有界深度。
- 自动化动作仍使用标准 tasks API、效果锁、取消与配额；不能在事件回调里直接持久写入。
- UI、worker、插件停用/卸载时统一退订，活动订阅在 runtime 中显式 pin，防止误回收与泄漏。

## 10. 配置、私有数据、依赖与管理

### 10.1 配置和 secret

- 保留 `plugins.<id>.*` 命名空间与现有加密方式；不把 schema/UI 描述存进 Config。
- 动作开始前按声明与授权注入自身非密钥快照和本次必需 secret；不注入其他插件密钥、完整 config.json 或共享 LAN 密钥。
- secret 配置保存后通用 UI 仅获得“已配置”，留空默认保持；清空是显式动作。
- 临时 Cookie/passcode 只存在本次任务，输出与错误按已注入秘密脱敏，结束清除。
- 设置迁移只在实际 schema 变化且无法直接兼容时使用：旧值快照、声明的受控迁移动作、输出验证、原子保存；失败保留旧值。
- 插件版本回滚与配置 schema 必须兼容或使用对应快照；不得让旧代码读取已不可解析配置后伪装启动成功。

### 10.2 插件私有存储

- 提供有界 JSON/文件对象存储，按插件命名空间隔离；secret 不进入普通 storage。
- worker 使用操作内投影和提交 API，不获得应用或插件私有持久根路径。
- 私有索引/缓存可重建；卸载时允许用户保留或删除自身配置/私有数据，不删除已入库图片。
- 现有整库备份 ZIP 合同保持；插件配置/私有数据如需迁移，通过另一个明确导出流程处理，不静默附带密钥或改变 backup.json 语义。

### 10.3 依赖和工具策略

- 基础运行时是应用提供的 Python；插件声明 Python ABI、OS、CPU 架构与 SDK 范围。
- 纯 Python 依赖可随包 vendoring；native 扩展只能携带匹配目标的构建产物，在 worker 加载，不能在宿主主进程载入。
- 不运行安装脚本、不自动联网 pip/npm、不修改共享环境；缺依赖/ABI 不匹配时报告不可用。
- 重依赖 AI/OCR、native wheel 与包内工具必须有实际源运行和冻结运行验证；仅声明平台标签不能证明兼容。
- 外部工具使用已声明工具 ID、明确来源和版本、受控参数与进程树回收；不开放泛用 shell execute。
- 开发与打包工具链遵守项目 mise；用户安装包内的运行能力不依赖安装 mise。
- 包内许可证与 notices 覆盖实际携带的依赖。宿主官方许可证矩阵不自动背书外部插件。

### 10.4 管理生命周期

| 动作 | 目标行为 |
| --- | --- |
| 安装 | 静态验证包/schema/资源/平台/能力，展示身份与信任提示，暂存后原子登记；不覆盖正在使用的目录 |
| 启用 | 校验必需能力与兼容，加载探针成功后发布贡献；失败保留可解释状态 |
| 禁用 | 停止新 admission，处理活动任务/会话，drain 后撤销贡献、frame、订阅和快捷键 |
| 更新 | 新版本先暂存/探针，用户选择等待完成或取消旧任务，再切 active/generation；失败保留旧版本 |
| 重载 | 停止旧执行体后按活动版本重新启动，不做 Python 模块热替换 |
| 回滚 | 切回已验证版本和兼容配置；不会自动撤销已经入库的数据或外部副作用 |
| 卸载 | 先 drain/停止，再删版本；询问私有数据保留；图库数据保留 |
| 崩溃/熔断 | 任务结果可见、会话失败、原因可读；不无限重启或吞掉已提交部分 |
| 应用退出 | 停止新任务与持久写入，取消/drain/整树回收，释放数据根和所有 lease |

插件管理 UI 显示：版本与角色、兼容/授权状态、活动任务/会话、崩溃原因、日志、重载/更新/回滚/卸载以及当前生效配置版本。用户应能区分“已安装”“已启用”“运行中”“被隔离”。

## 11. 兼容、版本与官方迁移

### 11.1 四种版本不能混用

| 版本 | 规划策略 |
| --- | --- |
| 清单 schema | v2 新契约，v1 最小包保留兼容解析 |
| SDK/插件 API | 新 SDK major 2；当前 `api_version=1` 经适配继续支持已有能力，新插件使用匹配描述符的 v2 |
| UI 贡献 | v2 引用标准 action/command，v1 四类贡献保持读取与边缘转换 |
| worker 传输协议 | Content-Length/JSON-RPC 帧不因新业务接口自动升版；加法扩展通过握手能力协商，只有破坏性线路变化才升级 |

禁止直接把全局 `PLUGIN_API_VERSION` 从 1 改成 2 而使九个官方包同时失效。加载校验针对版本化描述符与已支持 API 集合，仍拒绝 ID/入口/API 不匹配。

旧第三方包可以继续做当前 UI action，不自动获得新的图库/原生/后台能力。新 SDK 功能需要 v2 声明与授权。兼容适配在一个 runtime 和一个业务服务链内完成，不保留第二套执行引擎。

### 11.2 已发布行为保持

- 主窗口导入唯一入口、官方四来源的参数/结果/失败哨兵与取消/进度。
- 原 JsApi/SettingsApi 固定 Bridge 和调用方；新 SDK 不要求旧调用方立即迁移。
- 九个官方 ID、入口点、canonical 清单原始格式与分发证明；平台描述符可以由构建期适配生成，不直接改 canonical bytes。
- 用户数据位置、SQLite/缓存/缩略图、manifest 文件名和版本、同步布局、集合并集及排序闭环。
- LAN 手机兼容协议、设备确认、配置与密钥分享规则。
- 原备份恢复条件和 ZIP 结构、更新稳定版规则及制品名称。
- GPL/notice/native payload 和外部微信 helper 的发布范围；不得把插件平台验证说成 helper 来源证明。

### 11.3 官方插件收口

逐个角色迁移，先第三方证明通用契约，再由官方包消费同一机制：

1. 导入四来源使用标准任务/context/sink；保留 QQNT 外部导出与昵称缓存、TG 转换、微信 helper 的宿主策略。
2. 四同步包使用标准 backend 描述与配置，移除用于选路的官方类型分支，不移走 sync 编排。
3. LAN 使用标准 transport，会话安全/审批/命令仍在宿主。
4. 本地/文件夹/剪贴板/手机 QQ 保持宿主内建能力，可以消费同一贡献/任务契约，但不伪装成新增官方 worker provider。
5. 旧 Bridge/UI 路径成为薄适配器。仅当引用和测试证明允许，才删除过期适配；不能在本轮规划中删用户工作。

## 12. 实施文件落点

优先修改已有文件；只有职责确实缺失时新增。以下是落点，不要求按每个 API 新建一个模块。

| 位置 | 必需调整 |
| --- | --- |
| `core/plugins/manifest.py` / `contracts.py` | 增加版本化平台描述、角色/动作/能力契约，canonical 分发身份保持 |
| `core/plugins/registry.py` / `runtime/seeding.py` | 合并 bundled/installed/dev 有效目录、完整元数据、generation、安装/切换事务 |
| `core/plugins/policy.py` / `runtime/ui_config.py` | 声明驱动配置/secret/scope，旧官方映射改为兼容适配 |
| `core/plugins/runtime/{manager,worker,channel,protocol}.py` | 固定 SDK host-call/action-call、task/session/event 生命周期与能力协商 |
| `app/plugin_host.py`（拟新增） | 统一身份、方法契约、admission 与已有应用服务接入；不放领域算法 |
| `ohmymeme/plugin_sdk.py`（拟新增） | 稳定 Python 客户端/公开入口，无 DB/desktop 依赖 |
| `app/{library,library_queries,runtime_imports,operation_coordinator,operations}.py` | SDK 业务投影、通用任务/effects、提交后事件，保留现有规则 |
| `services/sync/{ports,backends,service}.py` / `services/lan/` | provider 动态选择、标准会话适配与现有编排/协议兼容 |
| `presentation/desktop/{bottle_app,window_manager}.py` / `api/` | 唯一固定路由网关、原生窄端口、旧 Bridge 适配 |
| `frontend/main/shared/` / `frontend/settings/` / `webui/import-frame.js` | 同一 SDK、贡献/命令/任务 UI 和 v1 frame 适配；SDK 运行资产应由构建生成 |
| `frontend/main/features/{imports,dialogs,memes,collections,sync}/` | 注册菜单、选区上下文、第三方搜索/处理结果与刷新 |
| `schemas/plugin/` / `scripts/generate_bridge_schemas.py` | 平台 manifest/UI/action/SDK schema 与确定性生成，旧 Bridge schema 不被替换 |
| `scripts/{plugin_packaging,plugin_abi_matrix,plugin_ui_dispatch,plugin_docs_check,build}.py` | 保留官方固定门，增加第三方契约和新旧能力事实，不吞掉旧失败 |
| `plugins/` / `tests/` / `fixtures/` | 官方迁移、外部示例插件、离线 conformance、故障与兼容回归 |
| `README.md` / `AGENTS.md` / `docs/project-structure.md` | 按里程碑同步已交付事实，不提前宣布完整平台完成 |

新增 schema、公开 SDK 或示例时同步对应文档。仅在实际新增运行/开发依赖时修改 requirements/environment/package 文件；本规划不引入依赖、数据表迁移、额外哈希或构建工具。

## 13. 里程碑与工作包

全部实施里程碑当前状态为“未开始”。负责人和日历日期尚未指派；依赖和退出条件固定，不能用未估算日期冒充承诺。

| 里程碑 | 工作包 | 依赖 | 交付与退出条件 |
| --- | --- | --- | --- |
| M0 契约冻结 | PP-01 当前/目标事实和兼容表；PP-02 逐方法 schema、版本/角色/effects/错误/限额 | 本规划 | 每个目标角色与能力都有契约、拒绝场景和测试映射；明确 v1 适配范围 |
| M1 描述与管理 | PP-03 清单/贡献 v2；PP-04 注册 generation；PP-05 安装/授权/切换/drain | M0 | 第三方声明进入有效目录，更新失败不破坏旧版本，旧包/官方种子不回归 |
| M2 SDK 宿主边界 | PP-06 Python/JS SDK 与固定 broker；PP-07 config/secret/source/asset/storage/native 基础 | M1 | 同样的 schema 在 worker/UI 两侧执行，拒绝越域/过期调用，配置与选择器真实接通 |
| M3 第三方导入闭环 | PP-08 通用 tasks/effects；PP-09 import/context/sink/结果；PP-10 独立目录来源样例 | M2 | 新来源仅靠 ZIP 完成 picker→扫描→取消/进度→入库/去重/分组→刷新，存储切换/退出正确 |
| M4 图库与事件 | PP-11 图库读写/资产完整 SDK；PP-12 event/automation；PP-13 AI 标签/处理/搜索接口 | M3 | 批量不截断，失败/部分成功真实，事件只在提交后发送，慢结果/循环/退订有回归 |
| M5 UI 与命令 | PP-14 两端统一 frame SDK/资源；PP-15 菜单/工具栏/侧栏/设置/详情/主题/快捷键；PP-16 通用任务中心 | M2、M3、M4 | 所有扩展点真实消费声明与命令，键盘/焦点/关闭/后台行为一致，无硬编码来源或动作名称推断 |
| M6 provider 全面接入 | PP-17 generic backend/transport；PP-18 processor/format/search/session 契约；PP-19 独立后端/传输样例 | M4、M5 | 新 provider 不改枚举/设置表单/构建白名单，实际调用标准会话，partial/read-only 能力真实 |
| M7 官方统一 | PP-20 四来源；PP-21 四同步；PP-22 LAN/内建适配和旧 ABI | M3、M6 | 九官方消费同一平台契约，特殊策略不丢失，官方 identity/parity/许可证门保持 |
| M8 开发交付 | PP-23 init/check/pack/dev/conformance；PP-24 SDK/示例/故障诊断；PP-25 依赖/平台与版本矩阵 | M1～M7 | 外部开发者不 import 宿主内部模块也能独立打包，示例在不改宿主条件下通过合同 |
| M9 发布验收 | PP-26 全套回归；PP-27 源码/真实冻结/升级回滚；PP-28 文档与证据收口 | M8 | 第 14 节全部验收项有证据，区分 fixture/真实运行/外部服务，不再以静态 UI 或 staging 当完成 |

主路径为 M0→M1→M2→M3→M4/M5→M6→M7→M8→M9。M4/M5 可以在满足接口依赖后分工，但本文不代表已经派发并行代理或会话。

### 13.1 每个工作包的完成记录

必须记录：工作包 ID、范围与文件、API/schema 变更、旧调用方兼容、单元/契约验证、实际运行证据、未验证事项和阻塞。没有对应证据只能是“进行中”或“阻塞”，不能仅因作者宣称完成就更新状态。

### 13.2 逐步开放，而非停留在 MVP

- M3 是第一个完整闭环，但不是“完整平台交付”。
- M4/M5/M6 的图库、事件、命令、处理/搜索、格式、同步和传输都属于本次目标，不是完成导入后可省略的未来事项。
- M7 必须证明官方与第三方走同一机制，不能留下第三方只用简化 `ui.action`、官方独享业务接口的双轨。
- M8/M9 不能用一份 README 或 contract-only smoke 代替可开发、可安装、可运行和可升级的证据。

## 14. 验收矩阵与发布门

### 14.1 独立插件能力验收

样例是实际插件包，不是在测试里直接访问 Container、DB 或修改宿主注册表来制造成功。外部网络/AI 可用明确 fixture 验证协议，但必须标注，不能声称真实云服务可用。

| 编号 | 验收场景 | 必须证明 |
| --- | --- | --- |
| A01 | 新目录/在线来源 ZIP | 不改宿主即可入口/参数/picker/进度/取消/精确去重/自动分组；新版本更新/回滚可用 |
| A02 | 标签/分类命令 | 读取授权选区，预览并批量应用；缺失 ID/失败事务/已有标签不被误清；分组规则与 manifest 一致 |
| A03 | 图片处理与格式 | 处理大于一页的集合，原图保留，产物真实入库；拒绝超限/坏图；取消保留明确已提交部分 |
| A04 | 导出插件 | 选择目标、文件碰撞确认、输出内容验证；失败不覆盖无授权文件，不泄漏临时产物 |
| A05 | 搜索 provider/虚拟视图 | 真实对象、分页、标签/分组筛选、不确定总量与失效结果处理；无直接 DB |
| A06 | 新同步 backend | 只加插件包就出现配置/选择项；连接、push/pull、并发会话、取消、删除权限和远端 manifest 正确 |
| A07 | 新传输 provider | 回环 discovery/connect/read/write/close，拒绝未经宿主审批命令；旧手机 LAN 协议不回归 |
| A08 | 事件自动化 | 用户显式启用，导入后处理、任务可见、重复/循环/背压/重载/退出退订正确 |
| A09 | UI 全扩展点 | 导入、详情、菜单、工具栏、侧栏、设置、选区、主题、快捷键逐项真实运行；声明无效/禁用时正确拒绝 |
| A10 | 私有配置/存储 | secret 保存与限域注入、普通 UI 不回显、版本兼容、配额、卸载保留选项正确 |
| A11 | 管理与故障 | 安装/启停/更新/重载/回滚/卸载、factory 失败、进程崩溃/挂起/取消/退出，无孤儿和 stale frame 调用 |
| A12 | 旧行为/官方 | 九 provider、既有 Bridge/schema/ABI、UI、导入规则、排序、备份、迁移、LAN 与更新回归 |

所有目标 provider 类型和 UI 点都需覆盖，不能用一个 Echo action、一张表单截图或单一 importer 替代完整平台验收。

### 14.2 验证层级

1. 静态/schema：输入/结果、声明引用、角色方法、scope、版本、平台、无内部依赖。
2. 单元与代码流程：broker、资源 admission、提交/失败、变更事件和 v1 适配。
3. 契约：真实 worker + 宿主 SDK、任务/会话/取消、frame 协议；拒绝分支不能产生副作用。
4. UI：实际构建 Vue/设置页/插件页面，键盘、焦点、选择器上下文、后台任务、有效目录变化。
5. 进程与生命周期：取消、崩溃、重载、升级、退出、存储切换、长会话/订阅，无泄漏。
6. 发布：应用源码和真实冻结产物安装第三方包，验证依赖/native payload、更新/回滚/卸载。
7. 外部服务/设备：真实云端、手机/桌面客户端、原生拖拽/剪贴板分别列证据与平台限制。

本文只规划这些验证；本次文档工作不自动启动浏览器、集成、性能或安全审计。实施中的日常检查按最小相关测试执行；到 M9 或明确授权的验收阶段再执行完整门禁与实际产物测试。

### 14.3 项目门禁

最终 PR/平台发布按现有项目要求执行，不降低标准：

```powershell
mise run lint
mise run typecheck-python
mise run test-python
mise run typecheck-frontend
mise run test-frontend
mise run test-contracts
mise run build-frontend
mise run e2e
mise run package-smoke
```

- 新平台测试加入对应门禁；不只是打印 PASS，须断言真实调用/拒绝/结果。
- package-smoke 当前为构建/安装等合同验证，不能替代最终可执行文件运行。
- 已退役的许可证环境证据缺失与既有跳过应单列；不把 skipped 算通过，也不凭本规划重新制造旧证据。
- 只有实际改到分发范围的里程碑才重建许可证/NOTICE/staging 证据，保持现有规范化与逐字节哈希边界。

### 14.4 平台完成判定

同时满足：

- A01～A12 有明确结果；每个目标角色和能力完成契约/实现/验证。
- 新插件只增插件包，不新增宿主 action 分支、TaskKind、同步类型表、前端来源按钮或 PyInstaller 特定插件白名单。
- 插件 SDK 文档和示例不要求 import `ohmymeme.app`、内部 services、desktop、DB 或 Config。
- 官方与第三方复用相同业务 SDK、资源和生命周期，旧 ABI 有适配和回归。
- 真实源码/冻结安装、更新/回滚、卸载与关闭验证完成；外部未测范围明确保留，不宣称全平台全服务可用。
- README/AGENTS/结构/协议/schema/矩阵准确描述已交付事实，历史计划与当前契约不混用。

## 15. 风险、实施约束与下一步

| 风险 | 处理原则 | 归属 |
| --- | --- | --- |
| 平台范围扩大导致宿主重构失控 | 复用现有服务/单一 runtime；以工作包和能力矩阵收口，不顺便迁移 UI 技术栈 | 所有阶段 |
| 类型/效果/能力契约只存在于文档 | M0 schema 与拒绝测试先行，随后才能公开 SDK | M0/M2 |
| 长计算占锁、取消后仍提交、关闭后写入 | 标准任务/context/lease/admission，提交前复核；部分结果真实 | M3/M4 |
| 事件循环/帧泄漏/旧版本调用 | generation、因果链、退订、背压与 snapshot-resync | M4/M5 |
| 官方特殊流程被泛化丢失 | QQNT 导出、TG/微信 helper、WebDAV/S3/R2、LAN 各自保留差异化回归 | M7 |
| 依赖在源码可用但冻结失败 | 明确 ABI/平台/许可证，真实冻结安装验证；不以 staging 证明最终运行 | M8/M9 |
| 升级破坏配置或已经发生的副作用 | 暂存/探针/drain/切换，配置兼容快照；不承诺回滚已入库或远端变化 | M1/M9 |
| 把受信插件能力授权误当安全沙箱 | 明确信任模型与 scope 的功能含义，不额外开展安全审计或作防护背书 | 文档与管理 UI |

### 15.1 需要在 M0 定稿的工程参数

这些不阻塞规划交付，但阻塞对应代码公开：

- 逐方法输入/结果 schema、字段上限、资源配额、query 超时、取消宽限和 session 上限。
- SDK v2 与旧 API 的精确兼容范围、弃用通知与最低支持版本，宿主发布版本号由届时实际发布确定。
- native payload 目标矩阵与可交付工具/依赖集合，基于真实构建结果而非推测。
- M0～M9 负责人、工作量及日历安排；本规划不预估无证据的完成日期。

### 15.2 首个实施切片

从 M0 开始：冻结一个非官方目录来源的 manifest/action/context/tasks/imports/native 契约及失败矩阵，落成 schema 和契约测试设计；再推进 M1/M2，最后在 M3 完成真实闭环。

不能直接复制某个官方 SettingsApi 新增第三方方法作为最终方案，也不能仅把全部 Bridge 暴露给 iframe。完成导入试点后，继续 M4～M9 的全部目标，不以试点成功提前宣布完整平台完成。
