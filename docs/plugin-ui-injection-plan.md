# 插件 UI 注入点规划（声明式 + iframe 混合）

状态：已实施（U1–U4 已落地；本文件保留决策基线与验收范围，实施细节见代码与测试）。

## 1. 决策基线

| 项 | 决策 |
| --- | --- |
| 自定义 UI 形态 | 混合：常规用宿主渲染的声明式组件；复杂交互仅在插件详情页允许沙箱 iframe |
| 首期注入点 | 设置页「导入」固定行（状态/置灰/声明字段）与「插件详情」面板 |
| 贡献声明位置 | 插件包内独立 `ui.json`（`plugin.json` 保持最小：id/version/entry） |
| 既有固定快照 | `src/webui/plugin-ui.json` 九条继续作为官方固定行来源；本规划只新增“插件注入贡献”通道，不替换它 |

## 2. 贡献契约（ui.json）

```json
{
  "version": 1,
  "injections": [
    {
      "point": "imports.row",
      "label": "我的来源",
      "description": "从本地目录导入",
      "icon": "generic",
      "fields": [
        {"key": "source_dir", "type": "path_dir", "label": "源目录", "required": true},
        {"key": "download", "type": "bool", "label": "下载原图", "default": true}
      ],
      "actions": [
        {"name": "start", "label": "开始导入", "kind": "import"},
        {"name": "status", "label": "查询状态", "kind": "query"}
      ]
    },
    {
      "point": "plugin_detail.panel",
      "label": "连接设置",
      "fields": [{"key": "endpoint", "type": "string", "label": "服务地址"}],
      "actions": [{"name": "save", "label": "保存", "kind": "config"}]
    },
    {
      "point": "plugin_detail.iframe",
      "entry": "ui/index.html",
      "height": 420
    }
  ]
}
```

字段类型白名单：`string` / `int` / `bool` / `enum(options)` / `path_dir` / `path_file` / `secret`；不接受 HTML、CSS、脚本或任意键名。注入点枚举与每个点允许的字段/动作集合由宿主 schema 冻结，未知注入点或额外字段整条贡献拒绝（仅该贡献，不影响插件运行）。

## 3. 宿主接口

- `GET /api/plugins/ui`：聚合所有已安装插件的有效贡献（含来源插件 ID、注入点、字段、动作），无效 `ui.json` 只记录 quarantine 原因，不返回半成品。
- 声明式渲染：设置页按注入点渲染；导入区行显示插件启用/可用状态（禁用置灰并提示“重启生效”），字段值随动作 payload 上送。
- 动作 RPC：worker 新增固定方法 `ui.action {name, payload}`，`name` 必须在该插件 `ui.json` 的 actions allowlist 内；结果必须是 JSON 对象，沿用现有脱敏与错误哨兵。
- iframe 资源路由：`GET /api/plugins/<id>/ui/<path>`，只允许包内相对路径（basename 防穿越、禁符号链接），响应加 CSP（`default-src 'self'; script-src 'self'`）与 `X-Frame-Options: SAMEORIGIN`。

## 4. iframe 沙箱模型（仅插件详情页）

- `<iframe sandbox="allow-scripts">`，不开放 `allow-same-origin`，插件页面无法读取宿主 DOM/Cookie/Storage。
- 消息协议固定：`{type:"ready"|"call"|"result"|"error", id, name, payload}`；宿主只接受注册动作名，按尺寸/频率限额，`payload` 仅 JSON。
- iframe 只能经 `postMessage` 调宿主注册动作 → 宿主再走 `ui.action` RPC；不提供任何 Bridge 直通、不能注入主窗口。
- 该通道默认关闭，用户在插件详情页显式点击“加载自定义界面”后才创建 iframe。

## 5. 文档与门禁反转（实施时执行）

- `AGENTS.md`/`README.md`/`docs/project-structure.md`：把“禁止任意 UI 注入/通用 renderer/DSL”改为“声明式贡献白名单 + 详情页沙箱 iframe”，其余禁止项（动态 Bridge、HTML 注入宿主、插件改主窗口）保留。
- `schemas/plugin/ui-contribution.schema.json` 与 `scripts/plugin_ui_dispatch.py --check`：官方九条固定快照校验不变；新增 `schemas/plugin/plugin-ui.schema.json` 与 fixtures 校验注入贡献。
- `scripts/plugin_docs_check.py`：新增/调整文档事实与负例 fixture（声明式白名单、iframe 沙箱、动作 allowlist）。
- 测试：schema 校验（未知注入点/额外字段/路径穿越/超大消息）、渲染快照、`ui.action` allowlist 与脱敏、iframe 消息协议（正常/越权/超限）、禁用状态置灰。

## 6. 里程碑

| 阶段 | 内容 |
| --- | --- |
| U1 | ui.json 契约 + `/api/plugins/ui` + 声明式导入区行（含官方行状态/置灰）：契约校验 `core/plugins/runtime/ui_injection.py`；`GET /api/plugins/ui` 聚合；`POST /api/plugins/ui/action` + worker `ui.action` allowlist；设置页导入区注入渲染与禁用/缺失置灰；`tests/test_plugin_ui_injection.py` 覆盖。 |
| U2 | 插件详情声明式配置面板 + 配置读写 |
| U3 | 插件详情 iframe 沙箱与消息桥（显式加载、限额、CSP） |
| U4 | 文档/门禁反转与 fixtures，跑 `mise run check` |

## 7. 风险与未决

- iframe 的安全依赖独立 origin/CSP 策略，需确定资源路由是否单独端口或仅路径隔离。
- `ui.action` 引入新的插件 ABI 面，需要同步 ABI/action 矩阵与 worker allowlist 测试。
- 声明式 schema 的字段类型扩展需克制，避免演化为通用 DSL。
