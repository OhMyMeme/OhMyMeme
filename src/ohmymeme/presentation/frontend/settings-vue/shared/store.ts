import { reactive, ref } from 'vue'
import { api } from './bridge'
import { loadPluginUI } from './plugin-ui'

// 设置窗口共享状态：原始 settings dict、脏标记、当前导航分组
export const settings = reactive<Record<string, any>>({})
export const activeGroup = ref('base')
export const dirty = ref(false)
export const pluginUILabels = reactive<Record<string, string>>({})
// 由插件面板维护的禁用插件 id 列表，save() 读取后随 save_settings 一起提交
export const disabledPlugins = ref<string[]>([])

export function markDirty() {
  dirty.value = true
}

// 全局 toast：复用静态 #toast 节点，与原 settings 行为一致
let toastTimer: ReturnType<typeof setTimeout> | undefined
export function showToast(msg: string) {
  const el = document.getElementById('toast')
  if (!el) return
  el.textContent = msg
  el.classList.add('show')
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => el.classList.remove('show'), 1600)
}

// 同步后端表单校验：缺字段返回提示并中止保存（契约与原 validateSync 一致）
function validateSync(s: Record<string, any>): boolean {
  if (s.sync_type === 'ftp') {
    if (!String(s.ftp_host || '').trim()) { showToast('请输入 FTP 服务器地址'); return false }
    const port = parseInt(s.ftp_port)
    if (!port || port < 1 || port > 65535) { showToast('端口号无效（1-65535）'); return false }
  }
  if (s.sync_type === 's3') {
    if (!String(s.s3_endpoint || '').trim()) { showToast('请输入 Endpoint URL'); return false }
    if (!String(s.s3_bucket || '').trim()) { showToast('请输入 Bucket 名称'); return false }
  }
  if (s.sync_type === 'r2') {
    if (!String(s.r2_account_id || '').trim()) { showToast('请输入 Cloudflare Account ID'); return false }
    if (!String(s.r2_bucket || '').trim()) { showToast('请输入 Bucket 名称'); return false }
  }
  if (s.sync_type === 'webdav') {
    if (!String(s.webdav_url || '').trim()) { showToast('请输入 WebDAV URL'); return false }
  }
  return true
}

// 组装 save_settings 载荷：从响应式 settings 读取（而非扫 DOM），键与原实现逐一对齐
export async function save(): Promise<void> {
  const s = settings
  const sync = {
    sync_auto_fetch_index: s.sync_auto_fetch_index === true,
    sync_auto_sync: s.sync_auto_sync === true,
    sync_type: s.sync_type || '',
    sync_delete_remote: s.sync_delete_remote === true,
    sync_remove_local: s.sync_remove_local === true,
    sync_hide_upload_warning: s.sync_hide_upload_warning === true,
    ftp_host: s.ftp_host || '',
    ftp_port: parseInt(s.ftp_port) || 21,
    ftp_user: s.ftp_user || '',
    ftp_password: s.ftp_password || '',
    ftp_path: s.ftp_path || '/',
    s3_endpoint: s.s3_endpoint || '',
    s3_region: s.s3_region || '',
    s3_bucket: s.s3_bucket || '',
    s3_access_key: s.s3_access_key || '',
    s3_secret_key: s.s3_secret_key || '',
    s3_path: s.s3_path || '',
    s3_addressing_style: s.s3_addressing_style || 'virtual',
    s3_signature_version: s.s3_signature_version || 's3',
    r2_account_id: s.r2_account_id || '',
    r2_access_key_id: s.r2_access_key_id || '',
    r2_secret_access_key: s.r2_secret_access_key || '',
    r2_bucket: s.r2_bucket || '',
    r2_path: s.r2_path || '',
    webdav_url: s.webdav_url || '',
    webdav_user: s.webdav_user || '',
    webdav_password: s.webdav_password || '',
    webdav_path: s.webdav_path || '',
  }
  if (!validateSync(sync)) return
  await api('save_settings', {
    hotkey: s.hotkey || 'Ctrl+Alt+N',
    hotkey_show_at_mouse: s.hotkey_show_at_mouse === true,
    auto_play_gif: s.auto_play_gif !== false,
    hover_to_play: s.hover_to_play === true,
    try_original_image: s.try_original_image === true,
    copy_resize_mode: parseInt(String(s.copy_resize_mode ?? 1), 10),
    auto_start: s.auto_start === true,
    silent_start: s.silent_start === true,
    show_uncategorized: s.show_uncategorized !== false,
    record_recent_use: s.record_recent_use !== false,
    show_startup_animation: s.show_startup_animation !== false,
    disabled_plugins: [...disabledPlugins.value],
    lan_port: parseInt(s.lan_port) || 17852,
    lan_secret: s.lan_secret || '',
    ...sync,
  })
  showToast('设置已保存')
  dirty.value = false
}

// 恢复默认：后端返回默认 dict 后覆盖响应式状态（LAN 停止等副作用由 network 组件 watch 处理）
export const resetSignal = ref(0)
export async function reset(): Promise<void> {
  const s = api('reset_settings')
  const resolved = s && typeof s.then === 'function' ? await s : s
  if (!resolved) return
  Object.keys(settings).forEach((k) => delete settings[k])
  Object.assign(settings, resolved)
  await api('lan_stop')
  await api('lan_set_allow_secret_config', false)
  resetSignal.value++
  showToast('已恢复默认设置')
  dirty.value = false
}

// 拉取后端设置并填充共享状态
export async function loadSettings(): Promise<boolean> {
  const s = api('get_settings')
  const resolved = s && typeof s.then === 'function' ? await s : s
  if (!resolved) return false
  Object.keys(settings).forEach((k) => delete settings[k])
  Object.assign(settings, resolved)
  dirty.value = false
  return true
}

// 加载宿主 UI 投影并提取数据驱动标签（导入行/同步后端下拉/LAN 区标题）
export async function loadProjection(): Promise<void> {
  const snapshot = await loadPluginUI()
  for (const contribution of snapshot.contributions) {
    pluginUILabels[(contribution as any).screen] = (contribution as any).label
  }
}
