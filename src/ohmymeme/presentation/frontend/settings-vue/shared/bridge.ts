// 设置窗口受控 pywebview 桥接，保持固定返回形状。
import { checkPluginUIArguments } from './plugin-ui'

export { esc } from '../../shared/markdown'

declare const pywebview: any

class BridgeDecodeError extends Error {
  method: string
  constructor(method: string, message: string) {
    super(`bridge response rejected for ${method}: ${message}`)
    this.name = 'BridgeDecodeError'
    this.method = method
  }
}

const bridgeBooleanMethods = new Set<string>([
  'open_adb_folder', 'open_adb_help', 'qqnt_open_dir', 'start_download',
  'run_downloaded_installer', 'start_window_drag',
])
const bridgeStringMethods = new Set<string>(['lan_get_ip', 'get_current_version', 'sync_test'])
const bridgeVoidMethods = new Set<string>([
  'save_settings', 'cancel_qq_import', 'cancel_tg_import', 'cancel_douyin_import',
  'cancel_wechat_import', 'qqnt_cancel', 'close_settings', 'move_window',
  'refresh_memes', 'refresh_tags', 'refresh_collections',
])

function isPlainObject(value: any): boolean {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

// 桥接就绪判定：供单元测试与初始化重试使用（不注册任何额外运行时全局）
export function bridgeReady(): boolean {
  return typeof pywebview !== 'undefined' && !!pywebview.api
}

// 结果按方法固定形状解码；Promise 在解析后再解码，失败返回 null
export function decodeBridgeResult(method: string, value: any): any {
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
