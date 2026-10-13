# OhMyMeme 官方插件按需分发与导入方案

日期：2026-10-13。

状态：方案已确认（决策按推荐项落定），尚未开始实施。实施前 `README.md`、`AGENTS.md`、`docs/project-structure.md` 与门禁脚本仍按现行的“官方插件随包分发、首启种子”描述生效；落地完成并验证后再按第 10 节同步文档与门禁。

本规划承接 [完整插件平台规划](plugin-platform-plan.md) 与 [子进程插件体系落地计划](plugin-runtime-plan.md)：只调整官方插件的分发与加载时机，不改变插件平台目标、worker 运行时、九个 canonical 身份/入口 ABI 与宿主编排边界。

## 1. 目标与范围

- 官方九插件不再随安装包（PyInstaller/nuitka 产物与各平台安装包）发布。
- 应用启动与运行不再自动种子/自动可用；`data_dir/plugins` 由用户导入建立。
- 仅当用户显式导入后才可用，导入有两种方式：
  1. GitHub 仓库导入（主路径）：公开仓库，插件代码位于仓库根目录 `plugins/{plugin-id}/`。
  2. 本地 ZIP 导入（离线/手动/私有分发）。
- 复用现有机制：`PluginRuntimeManager` worker 生命周期、`seeding` 状态与安装事务、`disabled_plugins` 门控、回滚/重载/卸载管理、宿主 staging/manifest/安全边界。
- 非目标：marketplace、在线插件索引、签名体系、私有仓库 token、插件自动更新检查（如以后需要另立规划）。

## 2. 决策基线

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D01 | 官方插件脱离安装包 | 冻结产物不再收集插件模块、dist-info 与 staging；各平台安装包自然不含插件 |
| D02 | 运行期不自动种子 | 删除 `seed_official_plugins` 相关链路；插件可用性只由用户导入后的 state + 版本目录决定 |
| D03 | 两种导入共用一套安装事务 | GitHub 与本地 ZIP 都经“校验 → 暂存 → 原子切换 → 写 state”，不维护第二条加载路径 |
| D04 | 只做 canonical 身份校验，不内嵌哈希 | 官方 ID 仅当 id/entry/package_root/api_version/capabilities 与 canonical manifest 完全一致才接受；无签名体系，用户确认是唯一门槛（与现有第三方安装同信任级） |
| D05 | 官方仓库新增 `plugins/{id}/plugin.json` | 生成物，`plugin_packaging.py --check` 校验其与 `config/plugin-manifest.json`/入口一致；使官方与第三方共用同一仓库契约 |
| D06 | 官方导入默认 ref 跟应用版本 | 默认尝试 `v{__version__}` tag，缺失回落 `HEAD` 并提示；用户可显式指定 ref |
| D07 | 网络复用现有 GitHub 镜像 | 直连失败按 `github.dpik.top → gh.dpik.top → gh-proxy.org → 直连` 重试；仅公开仓库，不引入 token |
| D08 | 记录来源与内容哈希 | state 记录 `source`（repo/ref/tree sha256）；版本目录 `{version}`（tag）或 `{version}-{sha7}`（分支/sha 导入），同版本不同内容按新版本处理 |
| D09 | Release 仍附九个官方 ZIP | GitHub 导入为主路径；ZIP 附件作为离线/手动渠道，沿用同一契约 |
| D10 | 迁移清理旧 bundled 副本 | 旧版平铺 `origin=="bundled"` 目录在新构建无法被 worker import；首启清理并提示重新导入，不自动重排、不自动可用 |
| D11 | 官方包允许卸载 | 用户导入即用户可卸；禁用语义不变（重启生效）；九个 canonical ID/入口 ABI 不变 |
| D12 | 宿主边界不变 | 编排、manifest/hash/排序/提交、安全与 UI 仍归宿主；插件只承载自身代码与声明 |

## 3. 分发形态

### 3.1 GitHub 仓库契约

```text
{owner}/{repo}/
  plugins/
    {plugin-id}/
      plugin.json              必需：id/name/version/entry/api_version/package_root/capabilities
      LICENSE                  建议：插件自身许可与来源声明
      {package_root}/          规范布局：包目录直接放在插件目录下
      或 src/{package_root}/   兼容布局：本仓库现状（plugins/{id}/src/{pkg}/）
```

- 应用只认仓库根目录 `plugins/{plugin-id}/`，找不到即拒绝（`layout_mismatch`），不接受"整个仓库就是一个插件"等其他布局。
- 包目录按 `entry` 的模块名查找：优先 `plugins/{id}/{pkg}/`，其次 `plugins/{id}/src/{pkg}/`；只复制该包目录进版本目录，满足 worker 的 `sys.path.insert(0, 版本目录)` + `import {pkg}` 加载方式。
- 官方仓库默认 `OhMyMeme/OhMyMeme`；`plugin.json` 为生成物，九条内容与 `config/plugin-manifest.json` 保持一致。

### 3.2 本地 ZIP 契约

- 维持现有第三方包约定：ZIP 根 = `plugin.json` + 包目录（子目录形式）+ `LICENSE`（建议）。
- 官方 ZIP 命名 `OhMyMeme-plugin-{plugin-id}-v{version}.zip`，由发布流水线生成并随 Release 附件发布。
- ZIP 与 GitHub 两种来源共用同一校验与落盘逻辑；官方 ID 一律走 D04 身份校验。

## 4. GitHub 导入流程

1. 输入 `owner/repo`（或粘贴完整 URL）+ 可选 ref + 插件 id；官方九条提供下拉，第三方手填。
2. 预览（`/api/plugins/github/inspect`）：下载 zipball → 只抽取 `plugins/{id}/` 子树 → 解析 `plugin.json` → 返回 id/version/entry/tree sha256/ref/commit 摘要（尽力经 GitHub API 获取，限流失败不阻断）。
3. 用户确认后安装：compose 版本目录（包目录嵌套 + `plugin.json` + `LICENSE`）→ 暂存校验（身份、资源路径、限额）→ 原子替换版本目录 → 写 state（origin/kind/package_root/capabilities/source）。
4. 下载与限额：归档 ≤50MB、解压 ≤20MB、单文件/条目数有上限；拒绝符号链接、绝对路径、`..` 路径；仅允许 `github.com`/`codeload.github.com` 主机，重定向逐跳校验；按 `(repo, ref)` 在临时目录缓存归档，预览与安装不重复下载。
5. 错误分类：`not_found` / `rate_limited` / `layout_mismatch` / `identity_mismatch` / `too_large` / `network`；全部为回收前失败，不产生残留目录。
6. 直连失败按 D07 镜像列表重试；镜像不可用时提示改用本地 ZIP。

## 5. 宿主与运行时改造

- `core/plugins/runtime/seeding.py`
  - 删除自动种子链：`seed_official_plugins`/`_locate_package`/`_repo_plugins_root`。
  - 抽出公共"暂存安装事务"：ZIP 与 GitHub 共用；`_validate_meta` 放行官方 ID（D04 校验）并在版本记录写入 `kind/package_root/capabilities`（worker 的 `operation.require` 依赖 capabilities，缺失会拒绝导入操作）。
  - `uninstall_plugin` 支持官方 ID（D11）。
- `core/plugins/runtime/manager.py`：`_default_resolver` 只解析不再种子；`plugin_missing` 语义不变。
- 新增 GitHub 下载模块（`core/plugins/runtime/` 内，纯 urllib，不依赖 app 层）：拉取、抽取、限额、镜像重试、缓存；可注入下载器供测试。
- `presentation/desktop/window_manager.py`
  - `/api/plugins` 去掉种子调用；官方行输出 `installed` 状态（state 有记录且目录存在）。
  - 新增 `/api/plugins/github/inspect|install` 路由。
  - 迁移：首启检测 `origin=="bundled"` 的记录与目录，清理并记录提示；`data_dir/plugins` 空态起步。
- 未装状态出口：导入行沿用"包缺失即隐藏"（`ImportGroup.rowHidden`）；同步 push/pull、LAN 开关复用现有 `provider_unavailable`/`plugin_missing` 错误；设置页补"官方插件未安装"提示与去「插件」页导入的引导。
- 设置页 `PluginsGroup.vue`：两个入口（「从 GitHub 导入」「从文件导入 ZIP」）+ 官方九条常驻列表（未安装/已安装/已禁用 + 安装、卸载、启用/禁用、回滚、预览确认对话框）。

## 6. 构建与发布链

- `scripts/build.py` 与 `scripts/nuitka/build.py`：移除 `stage_official_plugins` 进包的 `--paths`/`--collect-submodules`/dist-info `--add-data`；`config/plugin-manifest.json` 保留在应用内作为身份表（不含插件代码）；`build/plugin-staging` 不再产出。
- `scripts/plugin_packaging.py`：
  - 新增 `--pack-zips --out dist/plugins`：生成九个官方 ZIP（D09）与各插件 `plugin.json`。
  - 新增 `--check` 校验仓库内 `plugins/{id}/plugin.json` 与 canonical manifest/入口一致（D05 门禁）。
- `scripts/package_smoke.py`：预期文件清单删除插件条目，改为断言"产物不含插件；插件 ZIP 存在于发布附件集合"。
- `scripts/plugin_license_matrix.py` / `scripts/build_notice_bundle.py`：证据范围从"frozen 官方集"改为"应用制品 + 发布插件 ZIP"双轨，重新生成 `docs/plugin-license-matrix.json`；不改变逐字节/UTF-8 哈希边界。
- `scripts/plugin_docs_check.py` / `scripts/plugin_abi_matrix.py`：同步文档事实与矩阵输入。
- CI（`build.yml`/`nightly.yml`）：构建产出并上传 `dist/plugins/*.zip`（Release 附件）；安装包产物不含插件。

## 7. 开发与测试

- 显式开发流（不再自动可用）：
  - `mise run plugins:pack`：调用打包器生成九个 ZIP。
  - `mise run plugins:install-dev`：把仓库插件按真实安装事务装进当前 `data_dir`。
- 测试：
  - conftest 共享 fixture 用真实安装事务安装官方包；替换全部 `seed_official_plugins` 调用点（`test_review_regressions.py`、runtime/sync/lan/qqnt/wechat/ui 等）。
  - GitHub 导入用注入的本地假下载器覆盖：inspect/安装/镜像回退/限额/路径穿越/身份拒绝/缓存；离线 fixture 归档，不依赖真实网络。
  - e2e 覆盖"全新无插件 → 导入 → 功能可用"与 GitHub 对话框路径。
- 真实 GitHub 仓库的联调只作为发布前手工证据记录，不进入常规测试网络依赖。

## 8. 里程碑

| 阶段 | 内容 | 退出条件 |
| --- | --- | --- |
| P0 安装事务与契约 | 公共暂存安装、官方身份校验、capabilities 入库、`plugin.json` 生成与 `--check` | 官方 ZIP 可装、非法身份被拒，均有测试 |
| P1 去种子与迁移 | seeding/manager/window_manager 改造、bundled 清理迁移、未装态 UI 引导 | 全新 data_dir 无插件；旧 data_dir 升级后干净且提示可用 |
| P2 GitHub 导入 | 下载模块、inspect/install 路由、设置页对话框与预览 | 离线 fixture 全通过；真实官方仓库手工验证通过 |
| P3 构建与发布链 | build/nuitka/CI/ZIP 附件、许可证/smoke/docs 脚本同步 | 产物不含插件；九个 ZIP 可获取；全部门禁通过 |
| P4 文档与验收 | README/AGENTS/project-structure、发布说明模板、验收矩阵执行 | 第 9 节全部有证据；区分手工/离线 fixture 证据 |

## 9. 验收矩阵

| 编号 | 场景 | 必须证明 |
| --- | --- | --- |
| A01 | 安装包不含插件 | 冻结产物无插件模块/dist-info/staging；package-smoke 断言生效 |
| A02 | 全新安装默认无插件 | 导入行隐藏、同步/LAN 提示"插件未安装"；`data_dir/plugins` 空 |
| A03 | 本地 ZIP 导入官方包 | 导入后导入/同步/LAN 可用；重启后仍可用；卸载后恢复未装态 |
| A04 | GitHub 导入 | 预览→确认→安装→可用；错误 id/身份不符/超限/网络失败被拒且无残留 |
| A05 | 旧版升级迁移 | bundled 记录与目录清理、提示出现、重新导入后功能恢复 |
| A06 | 管理语义 | 启用/禁用/回滚/卸载与现有一致；官方包可卸（D11） |
| A07 | 证据同步 | 许可证矩阵、NOTICE、docs 检查、ABI/action 矩阵更新且门禁通过 |

## 10. 文档与门禁同步清单（落地时执行）

- `README.md`：官方插件扩展边界段落改为"官方插件以独立 ZIP/GitHub 仓库按需导入，不随安装包分发、不自动加载"。
- `AGENTS.md`：官方插件文档与重组边界、关键目录、构建说明同步分发模型。
- `docs/project-structure.md`：`plugins/` 与 `docs/` 段落、脚本职责描述同步。
- `docs/plugin-runtime-plan.md` 的实施状态段与 `docs/plugin-ui-injection-plan.md` 的状态行一并复核修正。
- `scripts/plugin_docs_check.py` 的 `DOCUMENT_FACTS`/`UNSUPPORTED_EXTENSION_FEATURES` 与失效 fixture 同步更新。

## 11. 风险与未决

| 风险 | 处理原则 |
| --- | --- |
| 无签名：身份校验不等于来源证明 | 明确写入安装确认与文档；不新增沙箱承诺；用户确认是唯一门槛 |
| GitHub 可用性/限流（国内网络） | D07 镜像重试 + 归档缓存；离线场景走本地 ZIP |
| 依赖仍由应用侧提供（boto3/curl-cffi/ffmpeg/微信 helper） | 插件包只含代码；维持"宿主供体"约定，未来独立升级另立规划 |
| 升级体验断裂（旧用户功能消失） | 发布说明写明步骤；首启提示 + 设置页引导导入 |
| zipball 全仓下载偏大（含应用资源） | 归档上限与缓存缓解；如需可另立"按文件稀疏下载"优化 |
| 许可证证据范围变化引发 REJECTED | P3 先重界定矩阵输入再跑门禁，保留逐字节哈希边界 |
