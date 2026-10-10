// 设置窗口 pywebview 桥接：移植自 settings 的 decoder.js + runtime.js，运行时契约保持一致
import { checkPluginUIArguments } from './plugin-ui'

declare const pywebview: any

class BridgeDecodeError extends Error {
  method: string
  constructor(method: string, message: string) {
    super(`bridge response rejected for ${method}: ${message}`)
    this.name = 'BridgeDecodeError'
    this.method = method
  }
}

const bridgeBooleanMethods = new Set([
  'open_adb_folder', 'open_adb_help', 'qqnt_open_dir', 'start_download',
  'run_downloaded_installer', 'start_window_drag',
])
const bridgeStringMethods = new Set(['lan_get_ip', 'get_current_version', 'sync_test'])
const bridgeVoidMethods = new Set([
  'save_settings', 'cancel_qq_import', 'cancel_tg_import', 'cancel_douyin_import',
  'cancel_wechat_import', 'qqnt_cancel', 'close_settings', 'move_window',
  'refresh_memes', 'refresh_tags', 'refresh_collections',
])

function isPlainObject(value: any): boolean {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function decodeBridgeResult(method: string, value: any): any {
  if (value && typeof value.then === 'function') {
    return value.then(
      (resolved: any) => {
        try { return decodeBridgeResult(method, resolved) }
        catch (error) { console.error(error); return null }
      },
      (error: any) => { console.error(error); return null },
    )
  }
  if (bridgeVoidMethods.has(method)) {
    if (value !== null && value !== undefined) throw new BridgeDecodeError(method, 'expected void')
    return null
  }
  if (bridgeBooleanMethods.has(method)) {
    if (typeof value !== 'boolean') throw new BridgeDecodeError(method, 'expected boolean')
    return value
  }
  if (bridgeStringMethods.has(method)) {
    if (typeof value !== 'string') throw new BridgeDecodeError(method, 'expected string')
    return value
  }
  if (!isPlainObject(value)) throw new BridgeDecodeError(method, 'expected object')
  return value
}

export function api(method: string, ...args: any[]): any {
  if (typeof pywebview === 'undefined' || !pywebview.api || typeof pywebview.api[method] !== 'function') {
    return null
  }
  try {
    checkPluginUIArguments(method, args)
    return decodeBridgeResult(method, pywebview.api[method](...args))
  } catch (e) {
    console.error('api error', method, e)
    return null
  }
}

export function esc(s: any): string {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
