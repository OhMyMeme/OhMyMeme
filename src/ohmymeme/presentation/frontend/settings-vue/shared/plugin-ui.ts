// 宿主 UI 投影校验：移植自 settings 的 plugin-ui.js，保持同样的"固定快照全量校验 + 参数/进度白名单"契约。
// Vue 版的标签应用改为数据驱动（见 store 的 loadProjection），不再直接改 DOM 节点。
import fixedPluginUIJson from '../../../../../webui/plugin-ui.json'

// 固定宿主快照的闭合结构（唯一合法的 UI 投影基线）
export interface PluginUIActionArgument {
  name: string
  required: boolean
  schema: { type?: string; anyOf?: ReadonlyArray<{ type?: string }> }
  default?: unknown
}

export interface PluginUIAction {
  action: string
  label: string
  arguments: readonly PluginUIActionArgument[]
  progress_fields: readonly string[]
}

export interface PluginUIRow {
  provider: string
  label: string
  icon: string
  screen: string
  handler: string
  actions: readonly PluginUIAction[]
}

export interface PluginUIDocument {
  schema_version: number
  contributions: readonly PluginUIRow[]
}

// 插件 ui.json 声明式注入（/api/plugins/ui 的运行时投影，非固定快照）
export type PluginFieldType =
  | 'string'
  | 'int'
  | 'bool'
  | 'enum'
  | 'path_dir'
  | 'path_file'
  | 'secret'

export interface PluginInjectionField {
  key: string
  type: PluginFieldType
  label: string
  required: boolean
  default?: unknown
  placeholder?: string
  options?: string[]
}

export interface PluginInjectionAction {
  name: string
  label: string
  kind: string
}

export interface PluginPanelInjection {
  point: 'imports.row' | 'plugin_detail.panel'
  label: string
  description?: string
  icon?: string
  fields: PluginInjectionField[]
  actions: PluginInjectionAction[]
}

export interface PluginIframeInjection {
  point: 'plugin_detail.iframe'
  entry: string
  height: number
  label?: string
}

export type PluginInjection = PluginPanelInjection | PluginIframeInjection

export interface PluginUIContribution {
  provider: string
  available: boolean
  enabled: boolean
  injection: PluginInjection
}

// 生成的 JSON 是固定文档；此处仅做一次读取边界断言，运行期仍由 samePluginUI 逐字段校验
export const FIXED_PLUGIN_UI = fixedPluginUIJson as unknown as PluginUIDocument

let pluginUI: PluginUIDocument | null = null

// 整快照与固定宿主数据逐字段比对：禁止多余字段、缺字段或类型变化
function samePluginUI(value: any, expected: any, field = 'ui'): void {
  if (typeof value !== typeof expected || value === null || expected === null) {
    if (value !== expected) throw new Error(field + ': unexpected type')
    return
  }
  if (typeof expected !== 'object') {
    if (value !== expected) throw new Error(field + ': differs from fixed host data')
    return
  }
  if (Array.isArray(value) !== Array.isArray(expected)) throw new Error(field + ': unexpected type')
  const keys = Object.keys(expected)
  for (const key of Object.keys(value)) {
    if (!Object.hasOwn(expected, key)) throw new Error(field + '.' + key + ': forbidden field')
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key)) throw new Error(field + '.' + key + ': missing field')
    samePluginUI(value[key], expected[key], field + '.' + key)
  }
}

// 全量校验通过后才整体替换快照；任一步失败都保留旧快照（供负例单元测试）
export function installPluginUI(value: unknown): void {
  samePluginUI(value, FIXED_PLUGIN_UI)
  pluginUI = JSON.parse(JSON.stringify(value)) as PluginUIDocument
}

export async function loadPluginUI(): Promise<PluginUIDocument> {
  if (pluginUI) return pluginUI
  const response = await fetch('/api/plugin-ui', { cache: 'no-store', credentials: 'same-origin' })
  if (!response.ok) throw new Error('ui: host projection unavailable')
  installPluginUI(await response.json())
  if (!pluginUI) throw new Error('ui: host projection unavailable')
  return pluginUI
}

export function getPluginUI(): PluginUIDocument | null {
  return pluginUI
}

function pluginUIAction(method: string): PluginUIAction | null {
  const known = FIXED_PLUGIN_UI.contributions.some((row) =>
    row.actions.some((action) => action.action === method),
  )
  if (!known) return null
  if (!pluginUI) throw new Error('ui: host projection not ready')
  for (const row of pluginUI.contributions) {
    for (const action of row.actions) {
      if (action.action === method) return action
    }
  }
  return null
}

function pluginArgumentMatches(value: any, schema: PluginUIActionArgument['schema']): boolean {
  if (schema.anyOf) return schema.anyOf.some((item) => pluginArgumentMatches(value, item))
  if (schema.type === 'null') return value === null
  if (schema.type === 'integer') return Number.isInteger(value)
  if (schema.type === 'number') return typeof value === 'number' && Number.isFinite(value)
  return (schema.type === 'string' || schema.type === 'boolean') && typeof value === schema.type
}

export function checkPluginUIArguments(method: string, args: unknown[]): void {
  const action = pluginUIAction(method)
  if (!action) return
  if (args.length > action.arguments.length) throw new Error('args: too many arguments')
  action.arguments.forEach((argument, index) => {
    if (index >= args.length && !argument.required) return
    if (!pluginArgumentMatches(args[index], argument.schema)) {
      throw new Error('args.' + argument.name + ': invalid type')
    }
  })
}

export function pluginUILabel(actionName: string): string {
  const action = pluginUIAction(actionName)
  if (!action) throw new Error('action.' + actionName + ': unavailable')
  return action.label
}

export function pluginProgressValue(
  method: string,
  state: Record<string, unknown>,
  field: string,
): unknown {
  const action = pluginUIAction(method)
  if (!action) throw new Error('action.' + method + ': unavailable')
  if (!action.progress_fields.includes(field)) {
    throw new Error('progress_fields.' + field + ': unavailable')
  }
  return state[field]
}
