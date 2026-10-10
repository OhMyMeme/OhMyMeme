// 宿主 UI 投影校验：移植自 settings 的 plugin-ui.js，保持同样的"固定快照全量校验 + 参数/进度白名单"契约。
// Vue 版的标签应用改为数据驱动（见 usePluginUI），不再直接改 DOM 节点。
import fixedPluginUI from '../../../../../webui/plugin-ui.json'

export type PluginUI = typeof fixedPluginUI

let pluginUI: PluginUI | null = null

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

function installPluginUI(value: any): void {
  samePluginUI(value, fixedPluginUI)
  pluginUI = JSON.parse(JSON.stringify(value))
}

export async function loadPluginUI(): Promise<PluginUI> {
  if (pluginUI) return pluginUI
  const response = await fetch('/api/plugin-ui', { cache: 'no-store', credentials: 'same-origin' })
  if (!response.ok) throw new Error('ui: host projection unavailable')
  installPluginUI(await response.json())
  return pluginUI!
}

export function getPluginUI(): PluginUI | null {
  return pluginUI
}

function pluginUIAction(method: string): any {
  const known = fixedPluginUI.contributions.flatMap((row: any) => row.actions).some((row: any) => row.action === method)
  if (!known) return null
  if (!pluginUI) throw new Error('ui: host projection not ready')
  return pluginUI.contributions.flatMap((row: any) => row.actions).find((row: any) => row.action === method)
}

function pluginArgumentMatches(value: any, schema: any): boolean {
  if (schema.anyOf) return schema.anyOf.some((item: any) => pluginArgumentMatches(value, item))
  if (schema.type === 'null') return value === null
  if (schema.type === 'integer') return Number.isInteger(value)
  if (schema.type === 'number') return typeof value === 'number' && Number.isFinite(value)
  return (schema.type === 'string' || schema.type === 'boolean') && typeof value === schema.type
}

export function checkPluginUIArguments(method: string, args: any[]): void {
  const action = pluginUIAction(method)
  if (!action) return
  if (args.length > action.arguments.length) throw new Error('args: too many arguments')
  action.arguments.forEach((argument: any, index: number) => {
    if (index >= args.length && !argument.required) return
    if (!pluginArgumentMatches(args[index], argument.schema)) {
      throw new Error('args.' + argument.name + ': invalid type')
    }
  })
}

export function pluginUILabel(method: string): string {
  return pluginUIAction(method).label
}

export function pluginProgressValue(method: string, state: any, field: string): any {
  if (!pluginUIAction(method).progress_fields.includes(field)) {
    throw new Error('progress_fields.' + field + ': unavailable')
  }
  return state[field]
}
