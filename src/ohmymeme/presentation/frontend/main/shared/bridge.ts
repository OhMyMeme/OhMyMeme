import type {
  Collection,
  JsonObjectModel,
  JsonValue,
  Meme,
} from './generated/bridge'

export { esc, renderMarkdown } from '../../shared/markdown'

export type MainBridgeResults = {
  readonly [method: string]: JsonValue
  readonly search_memes: readonly Meme[]
  readonly count_memes: number
  readonly get_tags: readonly string[]
  readonly get_meme_tags: readonly string[]
  readonly get_init_data: JsonObjectModel
  readonly get_collections: readonly Collection[]
  readonly get_child_collections: readonly Collection[]
  readonly get_collection_members: readonly JsonValue[]
  readonly get_meme_path: string
  readonly get_meme_paths: JsonObjectModel
  readonly sync_test: string
  readonly lan_get_ip: string
  readonly get_current_version: string
  readonly start_native_drag: boolean
  readonly copy_meme: JsonObjectModel
  readonly open_settings: boolean
}

type RuntimeApi = {
  readonly [method: string]: (...args: JsonValue[]) => JsonValue | Promise<JsonValue>
}

declare global {
  var pywebview: { readonly api?: RuntimeApi } | undefined
}

const listMethods = [
  'search_memes', 'get_tags', 'get_meme_tags', 'get_collections',
  'get_child_collections', 'get_collection_members',
] as const
const stringMethods = ['sync_test', 'lan_get_ip', 'get_current_version'] as const
const booleanMethods = ['start_native_drag', 'open_settings'] as const
const objectMethods = [
  'get_init_data', 'get_meme_paths', 'copy_meme', 'get_settings',
  'get_download_progress', 'get_sync_progress', 'sync_push', 'sync_pull',
  'run_auto_sync', 'import_memes', 'import_folder', 'import_from_clipboard',
  'download_update', 'check_connectivity', 'download_original_image',
] as const

function includes<T extends string>(values: readonly T[], value: string): boolean {
  return values.some((item) => item === value)
}

function decodeMainResult(method: string, value: JsonValue | undefined): JsonValue | null {
  if (value === undefined) return null
  if (includes(listMethods, method) && !Array.isArray(value)) return null
  if (includes(stringMethods, method) && typeof value !== 'string') return null
  if (includes(booleanMethods, method) && typeof value !== 'boolean') return null
  if (includes(objectMethods, method) && (value === null || Array.isArray(value) || typeof value !== 'object')) return null
  return value
}

export async function api<M extends keyof MainBridgeResults>(
  method: M,
  ...args: JsonValue[]
): Promise<MainBridgeResults[M] | null>
export async function api(method: string, ...args: JsonValue[]): Promise<JsonValue | null>
export async function api(method: string, ...args: JsonValue[]): Promise<JsonValue | null> {
  if (typeof pywebview === 'undefined' || !pywebview.api) return null
  const runtimeApi = pywebview.api
  const handler = runtimeApi[method]
  if (typeof handler !== 'function') return null
  try {
    return decodeMainResult(method, await handler(...args))
  } catch (error) {
    if (error instanceof Error) console.error('API error:', method, error.message)
    else console.error('API error:', method, error)
    return null
  }
}

export function bridgeReady(): boolean {
  return typeof pywebview !== 'undefined' && !!pywebview.api
}

let _focusTarget: HTMLElement | null = null

export function rememberFocus() {
  _focusTarget = document.activeElement instanceof HTMLElement ? document.activeElement : null
}

export function restoreFocus() {
  const el = _focusTarget
  _focusTarget = null
  if (el && el.isConnected) el.focus()
}

export function trapTabFocus(box: HTMLElement, e: KeyboardEvent) {
  if (e.key !== 'Tab') return
  const items = box.querySelectorAll<HTMLElement>('button, input, select, textarea, [tabindex]:not([tabindex="-1"])')
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  const active = document.activeElement
  if (e.shiftKey && (active === first || !box.contains(active))) {
    e.preventDefault(); last?.focus()
  } else if (!e.shiftKey && (active === last || !box.contains(active))) {
    e.preventDefault(); first?.focus()
  }
}
