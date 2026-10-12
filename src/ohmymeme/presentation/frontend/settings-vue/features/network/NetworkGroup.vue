<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import type { Ref } from 'vue'
import { NCheckbox, NSelect, NInput, NInputNumber, NButton, NModal, NProgress, useDialog } from 'naive-ui'
import { api } from '../../shared/bridge'
import { settings, markDirty, showToast, collectSync, validateSync, resetSignal, toInt, screenLabel } from '../../shared/store'
import { getPluginUI, pluginUILabel, pluginProgressValue } from '../../shared/plugin-ui'

// 解包桥接返回值（api 可能返回 Promise 或同步值）
async function call(method: string, ...args: unknown[]): Promise<any> {
  return await api(method, ...args)
}

const dialog = useDialog()

// ===== LAN 状态 =====
const lanEnable = ref(false)
const lanSecretConfig = ref(false)
const lanStatusText = ref('')
const lanStatusMode = ref<'' | 'ok' | 'error'>('')
let lanPollTimer: ReturnType<typeof setInterval> | null = null

// 刷新 LAN 状态并按运行态启动/停止轮询
async function refreshLanStatus() {
  const r = await call('lan_get_status')
  const ip = await call('lan_get_ip')
  if (r) {
    lanSecretConfig.value = r.allow_secret_config === true
    lanEnable.value = r.status === 'running'
  }
  if (!r || r.status === 'stopped') {
    lanStatusText.value = '● 已停止 (端口 ' + (r ? r.port : 17852) + ')'
    lanStatusMode.value = ''
    if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null }
    return
  }
  if (r.status === 'error') {
    lanStatusText.value = '● 启动失败 ' + (r.last_error || '')
    lanStatusMode.value = ''
    if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null }
    return
  }
  let text = '● 运行中 (端口 ' + r.port + '，IP ' + ip + ')'
  if (r.clients && r.clients.length) {
    text += '  已连接设备：' + r.clients.map((c: any) => c.addr).join('、')
  }
  lanStatusText.value = text
  lanStatusMode.value = 'ok'
  if (lanPollTimer) clearInterval(lanPollTimer)
  lanPollTimer = setInterval(async () => {
    const r2 = await call('lan_get_status')
    if (!r2 || r2.status !== 'running') {
      if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null }
      refreshLanStatus()
    }
  }, 5000)
}

// 开关 LAN 服务（立即生效，不写配置）
async function toggleLan(v: boolean) {
  lanEnable.value = v
  if (v) {
    const r = await call('lan_start', toInt(settings.lan_port, 17852), settings.lan_secret || '')
    if (!r || !r.ok) {
      lanEnable.value = false
      const st = r && r.status ? r.status : {}
      showToast('启动局域网服务失败：' + (st.last_error || '未知错误'))
    }
  } else {
    await call('lan_stop')
  }
  refreshLanStatus()
}

// 开关密钥传输（仅本次会话内存生效，需二次确认）
async function toggleLanSecretConfig(v: boolean) {
  if (v) {
    const ok = await confirmDialog('允许密钥传输', '请勿在公共网络或不信任的网络进行此操作！\n\n开启后配置同步将包含 FTP/S3/R2/WebDAV 等密钥字段，密钥将明文传输给局域网内配对设备。\n仅本次会话有效，不写入配置。是否继续？')
    if (!ok) { lanSecretConfig.value = false; return }
  }
  lanSecretConfig.value = v
  const r = await call('lan_set_allow_secret_config', v === true)
  if (r && r.allow_secret_config !== undefined) lanSecretConfig.value = r.allow_secret_config
}

// 通用确认框（Promise<bool>）
function confirmDialog(title: string, content: string): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    dialog.warning({
      title, content,
      positiveText: '确定', negativeText: '取消',
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false),
      onMaskClick: () => resolve(false),
    })
  })
}

// ===== 云端同步 =====
// 后端下拉选项从宿主 UI 投影消费，不硬编码 provider 标签
const SYNC_SCREENS = ['ftp', 's3', 'r2', 'webdav'] as const
const syncTypeOptions = computed<{ label: string; value: string }[]>(() => {
  const ui = getPluginUI()
  const options: { label: string; value: string }[] = [{ label: '无', value: '' }]
  if (!ui) return options
  for (const screen of SYNC_SCREENS) {
    const row = ui.contributions.find((item) => item.screen === screen)
    if (row) options.push({ label: row.label, value: screen })
  }
  return options
})

// 当前选中后端是否被宿主投影接纳（决定表单显隐）
function selectedScreen(): string | null {
  const t = settings.sync_type || ''
  const ui = getPluginUI()
  if (!ui) return null
  const found = ui.contributions.find((row) => row.provider.startsWith('sync.') && row.screen === t)
  return found ? found.screen : null
}
const showFtp = computed(() => selectedScreen() === 'ftp')
const showS3 = computed(() => selectedScreen() === 's3')
const showR2 = computed(() => selectedScreen() === 'r2')
const showWebdav = computed(() => selectedScreen() === 'webdav')
const showSyncExtra = computed(() => !!(settings.sync_type || ''))

const s3AddrOptions = [
  { label: '虚拟主机型 (Virtual-hosted)', value: 'virtual' },
  { label: '路径型 (Path-style)', value: 'path' },
]
const s3SigOptions = [
  { label: 'V2（兼容 OSS）', value: 's3' },
  { label: 'V4（AWS S3）', value: 's3v4' },
]

const syncStatus = ref('')
// 测试按钮文案取自宿主投影；投影缺失时回退
const testLabel = (() => {
  try { return pluginUILabel('sync_test') } catch { return '测试连接' }
})()
const testing = ref(false)

// 测试同步连接：sync_test 返回字符串（'ok' 表示成功），不是 {ok} 对象
async function testSync() {
  const sync = collectSync()
  if (!validateSync(sync)) return
  await call('save_settings', sync)
  testing.value = true
  const r = await call('sync_test')
  testing.value = false
  syncStatus.value = r === 'ok' ? '连接成功' : '连接失败: ' + (r || '未知错误')
}

// 检查同步状态：真实方法为 check_sync_status，返回同步差异明细
async function checkSyncStatus() {
  const sync = collectSync()
  if (!validateSync(sync)) return
  await call('save_settings', sync)
  const r = await call('check_sync_status')
  if (!r || !r.ok) { syncStatus.value = '检查失败: ' + ((r && r.error) || '未知错误'); return }
  if (r.synced) {
    syncStatus.value = '本地云端已同步（本地 ' + r.local_count + ' 个，云端 ' + r.remote_count + ' 个）'
    showToast('本地云端已同步')
    return
  }
  let msg = '本地共 ' + r.local_count + ' 个，云端共 ' + r.remote_count + ' 个'
  if (r.local_extra > 0) msg += '，本地多余 ' + r.local_extra + ' 个'
  if (r.local_missing > 0) msg += '，本地缺少 ' + r.local_missing + ' 个'
  syncStatus.value = msg
  showToast('同步状态：' + msg)
}

// ===== 孤儿文件 =====
let orphanFiles: any[] = []
const orphanStatus = ref('')
const orphanDeleteDisabled = ref(true)

async function scanOrphans() {
  orphanStatus.value = '扫描中...'
  const r = await call('get_remote_orphans', false)
  if (!r || !r.ok) { orphanStatus.value = '扫描失败: ' + ((r && r.error) || '未知错误'); return }
  orphanFiles = r.orphans || []
  orphanStatus.value = orphanFiles.length ? '发现 ' + orphanFiles.length + ' 个孤儿文件' : '无孤儿文件'
  orphanDeleteDisabled.value = orphanFiles.length === 0
}

async function deleteOrphans() {
  if (!orphanFiles.length) return
  const r = await call('get_remote_orphans', true)
  if (!r || !r.ok) { orphanStatus.value = '删除失败: ' + ((r && r.error) || '未知错误'); return }
  orphanStatus.value = '已删除 ' + r.removed + ' 个孤儿文件'
  orphanFiles = []
  orphanDeleteDisabled.value = true
}

// ===== 同步进度 =====
const showProgress = ref(false)
const progressTitle = ref('')
const progressFile = ref('')
const progress = ref(0)
const progressSpeed = ref('')
const showDone = ref(false)
const doneTitle = ref('')
const doneDetail = ref('')
let syncPollTimer: ReturnType<typeof setInterval> | null = null
let syncBg = false

function formatSpeed(bytesPerSec: number): string {
  if (bytesPerSec >= 1048576) return (bytesPerSec / 1048576).toFixed(1) + ' MB/s'
  if (bytesPerSec >= 1024) return (bytesPerSec / 1024).toFixed(1) + ' KB/s'
  return bytesPerSec.toFixed(0) + ' B/s'
}

// 上传前确认（仅在删除远端且未勾选不再提醒时；保留「不再提醒」NCheckbox）
const warningShow = ref(false)
const warningHide = ref(false)
let warningResolve: ((v: boolean) => void) | null = null

function showUploadWarning(): Promise<boolean> {
  const sync = collectSync()
  if (!sync.sync_delete_remote) return Promise.resolve(true)
  if (sync.sync_hide_upload_warning) return Promise.resolve(true)
  warningHide.value = false
  warningShow.value = true
  return new Promise<boolean>((resolve) => { warningResolve = resolve })
}

// 用户确认后：勾选不再提醒则持久化 sync_hide_upload_warning，再继续上传
async function confirmUploadWarning() {
  const resolve = warningResolve
  warningResolve = null
  if (warningHide.value) {
    settings.sync_hide_upload_warning = true
    markDirty()
    await call('save_settings', { sync_hide_upload_warning: true })
  }
  warningShow.value = false
  resolve?.(true)
}

function cancelUploadWarning() {
  const resolve = warningResolve
  warningResolve = null
  warningShow.value = false
  resolve?.(false)
}

const pushBusy = ref(false)
const pullBusy = ref(false)

type SyncProgressKey = 'show_upload_progress' | 'show_download_progress'
type SyncDoneKey = 'show_upload_done' | 'show_download_done'

// 带进度的同步执行（push/pull 共用）
async function doSyncWithProgress(
  method: string,
  title: string,
  progressKey: SyncProgressKey,
  doneKey: SyncDoneKey,
  busy: Ref<boolean>,
) {
  const sync = collectSync()
  if (!validateSync(sync)) return
  const warnOk = await showUploadWarning()
  if (!warnOk) return
  await call('save_settings', collectSync())

  const wantProgress = settings[progressKey] !== false
  const wantDone = settings[doneKey] !== false

  busy.value = true
  syncStatus.value = ''
  syncBg = false

  if (wantProgress) {
    progressTitle.value = title
    progressFile.value = '准备中...'
    progress.value = 0
    progressSpeed.value = ''
    showProgress.value = true
    syncPollTimer = setInterval(async () => {
      const s = await call('get_sync_progress')
      if (!s || s.status === 'idle') return
      progressFile.value = String(pluginProgressValue('get_sync_progress', s, 'current_file') ?? '')
      progress.value = Number(pluginProgressValue('get_sync_progress', s, 'progress') ?? 0)
      if (s.speed) progressSpeed.value = formatSpeed(Number(s.speed))
    }, 300)
  }

  const r = await call(method)
  busy.value = false
  if (syncPollTimer) { clearInterval(syncPollTimer); syncPollTimer = null }
  if (wantProgress && !syncBg) showProgress.value = false

  if (r && r.ok) {
    const uploaded = r.uploaded || r.downloaded || 0
    const skipped = r.skipped || 0
    const errors = r.errors || 0
    syncStatus.value = '完成: 成功 ' + uploaded + ', 跳过 ' + skipped + ', 错误 ' + errors
    if (wantDone) {
      doneTitle.value = title + '完成'
      doneDetail.value = '成功 ' + uploaded + ' 个'
      showDone.value = true
    }
  } else {
    let msg = '失败: ' + ((r && r.error) || '未知错误')
    const ff = (r && r.failed_files) || []
    if (ff.length) {
      const errs = ff.filter((f: any) => f.status !== 'unknown')
      const unknowns = ff.filter((f: any) => f.status === 'unknown')
      const parts: string[] = []
      if (errs.length) parts.push('失败 ' + errs.length + ' 个: ' + errs.slice(0, 5).map((f: any) => f.filename || '?').join(', '))
      if (unknowns.length) parts.push(unknowns.length + ' 个删除结果不确定，将在下次同步时复核')
      msg += '（' + parts.join('；') + '）'
    }
    syncStatus.value = msg
  }

  // 刷新主窗口：统一走 shared/bridge.api，禁止直调 pywebview
  api('refresh_memes')
  api('refresh_tags')
  api('refresh_collections')
}

function syncPush() { doSyncWithProgress('sync_push', '上传中...', 'show_upload_progress', 'show_upload_done', pushBusy) }
function syncPull() { doSyncWithProgress('sync_pull', '下载中...', 'show_download_progress', 'show_download_done', pullBusy) }

// 后台运行：隐藏进度弹窗、停止轮询
function hideSyncProgress() {
  syncBg = true
  showProgress.value = false
  if (syncPollTimer) { clearInterval(syncPollTimer); syncPollTimer = null }
}

// 完成弹窗关闭后重载窗口（与原 hideSyncDone 一致）
function hideSyncDone() {
  showDone.value = false
  location.reload()
}

// 恢复默认后刷新 LAN 状态（reset 里已停止 LAN 并关闭密钥传输）
watch(resetSignal, () => { refreshLanStatus() })

onMounted(() => {
  refreshLanStatus()
})
onUnmounted(() => {
  if (lanPollTimer) clearInterval(lanPollTimer)
  if (syncPollTimer) clearInterval(syncPollTimer)
  cancelUploadWarning()
})
</script>

<template>
  <div class="section">
    <div class="section-title">{{ screenLabel('lan') || '局域网互联' }}</div>
    <p style="font-size:11.5px;color:var(--gray-11);margin-bottom:10px;line-height:1.6">与手机版 OhMyMeme 在同一局域网内配对，互相同步表情包与配置</p>
    <div class="form-group">
      <label>端口</label>
      <NInputNumber
        :value="settings.lan_port ?? 17852"
        :min="1"
        :max="65535"
        :show-button="false"
        :input-props="{ id: 's-lan-port' }"
        @update:value="(v) => { settings.lan_port = v ?? 17852; markDirty() }"
      />
    </div>
    <div class="form-group">
      <label>连接密钥</label>
      <NInput
        type="password"
        placeholder="留空表示同一局域网无需密钥"
        :value="settings.lan_secret || ''"
        :input-props="{ id: 's-lan-secret' }"
        @update:value="(v) => { settings.lan_secret = v; markDirty() }"
      />
    </div>
    <div class="check-row" style="margin-bottom:12px">
      <NCheckbox :checked="lanEnable" @update:checked="toggleLan">开启互联访问</NCheckbox>
      <span class="immediate-hint">立即生效</span>
    </div>
    <div class="check-row" style="margin-bottom:12px">
      <NCheckbox :checked="lanSecretConfig" @update:checked="toggleLanSecretConfig">允许密钥传输（配置同步时包含 FTP/S3/R2/WebDAV 密码等密钥字段）</NCheckbox>
      <span class="immediate-hint">立即生效，仅本次会话</span>
    </div>
    <div style="display:flex;gap:8px">
      <NButton size="small" style="flex:1" @click="refreshLanStatus">刷新状态</NButton>
    </div>
    <div class="s-net-status" :class="{ 'status-ok': lanStatusMode === 'ok', 'status-error': lanStatusMode === 'error' }" style="font-size:11.5px;margin-top:6px;line-height:1.8">{{ lanStatusText }}</div>
  </div>

  <div class="section">
    <div class="section-title">云端同步</div>
    <div class="check-row">
      <NCheckbox :checked="settings.sync_auto_fetch_index === true" @update:checked="(v) => { settings.sync_auto_fetch_index = v; markDirty() }">启动时自动获取远端索引</NCheckbox>
    </div>
    <div class="check-row" style="margin-bottom:12px">
      <NCheckbox :checked="settings.sync_auto_sync === true" @update:checked="(v) => { settings.sync_auto_sync = v; markDirty() }">启动时自动同步</NCheckbox>
    </div>

    <div class="form-group">
      <label>存储类型</label>
      <NSelect :value="settings.sync_type || ''" :options="syncTypeOptions" @update:value="(v) => { settings.sync_type = String(v ?? ''); markDirty() }" />
    </div>

    <div v-show="showSyncExtra">
      <div class="check-row">
        <NCheckbox :checked="settings.sync_delete_remote === true" @update:checked="(v) => { settings.sync_delete_remote = v; markDirty() }">上传时删除远端文件</NCheckbox>
      </div>
      <div class="check-row">
        <NCheckbox :checked="settings.sync_remove_local === true" @update:checked="(v) => { settings.sync_remove_local = v; markDirty() }">下载时删除本地多余文件</NCheckbox>
      </div>
      <div class="check-row" style="margin-bottom:12px">
        <NCheckbox :checked="settings.sync_hide_upload_warning === true" @update:checked="(v) => { settings.sync_hide_upload_warning = v; markDirty() }">上传前不再提醒</NCheckbox>
      </div>
      <div class="check-row">
        <NCheckbox :checked="settings.show_upload_progress !== false" @update:checked="(v) => { settings.show_upload_progress = v }">上传时显示进度条</NCheckbox>
      </div>
      <div class="check-row">
        <NCheckbox :checked="settings.show_upload_done !== false" @update:checked="(v) => { settings.show_upload_done = v }">上传完毕显示提示</NCheckbox>
      </div>
      <div class="check-row">
        <NCheckbox :checked="settings.show_download_progress !== false" @update:checked="(v) => { settings.show_download_progress = v }">下载时显示进度条</NCheckbox>
      </div>
      <div class="check-row">
        <NCheckbox :checked="settings.show_download_done !== false" @update:checked="(v) => { settings.show_download_done = v }">下载完毕显示提示</NCheckbox>
      </div>
    </div>

    <div v-show="showFtp">
      <div class="form-group"><label>FTP 服务器</label><NInput placeholder="ftp.example.com" :value="settings.ftp_host || ''" :input-props="{ id: 's-ftp-host' }" @update:value="(v) => { settings.ftp_host = v; markDirty() }" /></div>
      <div class="ftp-row">
        <div class="form-group"><label>端口</label><NInputNumber :value="settings.ftp_port ?? 21" :min="1" :max="65535" :show-button="false" :input-props="{ id: 's-ftp-port' }" @update:value="(v) => { settings.ftp_port = v ?? 21; markDirty() }" /></div>
        <div class="form-group"><label>用户名</label><NInput placeholder="anonymous" :value="settings.ftp_user || ''" :input-props="{ id: 's-ftp-user' }" @update:value="(v) => { settings.ftp_user = v; markDirty() }" /></div>
      </div>
      <div class="form-group"><label>密码</label><NInput type="password" :value="settings.ftp_password || ''" :input-props="{ id: 's-ftp-pass' }" @update:value="(v) => { settings.ftp_password = v; markDirty() }" /></div>
      <div class="form-group"><label>远程路径</label><NInput :value="settings.ftp_path || ''" :input-props="{ id: 's-ftp-path' }" @update:value="(v) => { settings.ftp_path = v; markDirty() }" /></div>
    </div>

    <div v-show="showS3">
      <div class="form-group"><label>Endpoint URL</label><NInput placeholder="https://s3.amazonaws.com" :value="settings.s3_endpoint || ''" :input-props="{ id: 's3-endpoint' }" @update:value="(v) => { settings.s3_endpoint = v; markDirty() }" /></div>
      <div class="form-group"><label>寻址方式</label><NSelect :value="settings.s3_addressing_style || 'virtual'" :options="s3AddrOptions" @update:value="(v) => { settings.s3_addressing_style = String(v ?? 'virtual'); markDirty() }" /></div>
      <div class="form-group"><label>签名版本</label><NSelect :value="settings.s3_signature_version || 's3'" :options="s3SigOptions" @update:value="(v) => { settings.s3_signature_version = String(v ?? 's3'); markDirty() }" /></div>
      <div class="ftp-row">
        <div class="form-group"><label>Region</label><NInput placeholder="us-east-1" :value="settings.s3_region || ''" :input-props="{ id: 's3-region' }" @update:value="(v) => { settings.s3_region = v; markDirty() }" /></div>
        <div class="form-group"><label>Bucket</label><NInput placeholder="my-bucket" :value="settings.s3_bucket || ''" :input-props="{ id: 's3-bucket' }" @update:value="(v) => { settings.s3_bucket = v; markDirty() }" /></div>
      </div>
      <div class="form-group"><label>Access Key</label><NInput :value="settings.s3_access_key || ''" :input-props="{ id: 's3-access-key' }" @update:value="(v) => { settings.s3_access_key = v; markDirty() }" /></div>
      <div class="form-group"><label>Secret Key</label><NInput type="password" :value="settings.s3_secret_key || ''" :input-props="{ id: 's3-secret-key' }" @update:value="(v) => { settings.s3_secret_key = v; markDirty() }" /></div>
      <div class="form-group"><label>路径前缀（可选）</label><NInput placeholder="ohmymeme" :value="settings.s3_path || ''" :input-props="{ id: 's3-path' }" @update:value="(v) => { settings.s3_path = v; markDirty() }" /></div>
    </div>

    <div v-show="showR2">
      <div class="form-group"><label>Cloudflare Account ID</label><NInput placeholder="32 位十六进制字符串" :value="settings.r2_account_id || ''" :input-props="{ id: 'r2-account-id' }" @update:value="(v) => { settings.r2_account_id = v; markDirty() }" /></div>
      <div class="form-group"><label>R2 Access Key ID</label><NInput :value="settings.r2_access_key_id || ''" :input-props="{ id: 'r2-access-key-id' }" @update:value="(v) => { settings.r2_access_key_id = v; markDirty() }" /></div>
      <div class="form-group"><label>R2 Secret Access Key</label><NInput type="password" :value="settings.r2_secret_access_key || ''" :input-props="{ id: 'r2-secret-access-key' }" @update:value="(v) => { settings.r2_secret_access_key = v; markDirty() }" /></div>
      <div class="form-group"><label>Bucket 名称</label><NInput placeholder="my-bucket" :value="settings.r2_bucket || ''" :input-props="{ id: 'r2-bucket' }" @update:value="(v) => { settings.r2_bucket = v; markDirty() }" /></div>
      <div class="form-group"><label>路径前缀（可选）</label><NInput placeholder="ohmymeme" :value="settings.r2_path || ''" :input-props="{ id: 'r2-path' }" @update:value="(v) => { settings.r2_path = v; markDirty() }" /></div>
    </div>

    <div v-show="showWebdav">
      <div class="form-group"><label>WebDAV URL</label><NInput placeholder="https://example.com/remote.php/dav/files/user" :value="settings.webdav_url || ''" :input-props="{ id: 'wd-url' }" @update:value="(v) => { settings.webdav_url = v; markDirty() }" /></div>
      <div class="form-group"><label>用户名</label><NInput :value="settings.webdav_user || ''" :input-props="{ id: 'wd-user' }" @update:value="(v) => { settings.webdav_user = v; markDirty() }" /></div>
      <div class="form-group"><label>密码</label><NInput type="password" :value="settings.webdav_password || ''" :input-props="{ id: 'wd-pass' }" @update:value="(v) => { settings.webdav_password = v; markDirty() }" /></div>
      <div class="form-group"><label>远程路径（可选）</label><NInput placeholder="ohmymeme" :value="settings.webdav_path || ''" :input-props="{ id: 'wd-path' }" @update:value="(v) => { settings.webdav_path = v; markDirty() }" /></div>
    </div>

    <div v-show="showSyncExtra">
      <div style="display:flex;gap:8px;margin-top:14px">
        <NButton size="small" style="flex:1" :loading="testing" @click="testSync">{{ testLabel }}</NButton>
        <NButton size="small" style="flex:1" @click="checkSyncStatus">检查同步状态</NButton>
        <NButton size="small" type="primary" style="flex:1" :loading="pushBusy" @click="syncPush">上传到远端</NButton>
        <NButton size="small" type="primary" style="flex:1" :loading="pullBusy" @click="syncPull">从远端下载</NButton>
      </div>
      <div id="s-sync-status">{{ syncStatus }}</div>
      <div style="display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap">
        <span style="font-size:12px;color:var(--gray-11)">云端孤儿文件</span>
        <NButton size="small" @click="scanOrphans">扫描</NButton>
        <NButton size="small" type="error" tertiary :disabled="orphanDeleteDisabled" @click="deleteOrphans">删除孤儿</NButton>
        <span style="font-size:11.5px;color:var(--gray-11)">{{ orphanStatus }}</span>
      </div>
    </div>
  </div>

  <NModal :show="warningShow" :mask-closable="false" @update:show="(v) => { if (!v && warningResolve) cancelUploadWarning() }">
    <div style="background:var(--gray-2);border-radius:var(--radius-lg);padding:24px 28px;width:380px;border:1px solid var(--gray-6);box-shadow:var(--shadow-lg)">
      <div style="font-size:15px;font-weight:600;color:var(--gray-12);margin-bottom:8px">上传确认</div>
      <p style="font-size:13px;color:var(--gray-11);line-height:1.6;margin-bottom:16px">上传会将本地的完整状态同步到远端，包括新增、更新和删除操作。远程文件将被覆盖，建议先下载备份。</p>
      <div class="check-row" style="margin-bottom:16px">
        <NCheckbox :checked="warningHide" @update:checked="(v) => warningHide = v">不再提醒</NCheckbox>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <NButton @click="cancelUploadWarning">取消</NButton>
        <NButton type="primary" @click="confirmUploadWarning">继续上传</NButton>
      </div>
    </div>
  </NModal>

  <NModal :show="showProgress" :mask-closable="false" :closable="false" @update:show="(v) => { if (!v) hideSyncProgress() }">
    <div style="background:var(--gray-2);border-radius:var(--radius-lg);padding:24px 28px;width:420px;border:1px solid var(--gray-6);box-shadow:var(--shadow-lg);text-align:center">
      <div style="font-size:14px;font-weight:600;color:var(--gray-12);margin-bottom:4px">{{ progressTitle }}</div>
      <div style="font-size:12px;color:var(--gray-11);margin-bottom:12px;word-break:break-all">{{ progressFile }}</div>
      <NProgress type="line" :percentage="progress" :show-indicator="false" :height="8" />
      <div style="font-size:11.5px;color:var(--gray-11);margin-bottom:16px;margin-top:6px"><span>{{ progress }}%</span><span style="margin-left:12px">{{ progressSpeed }}</span></div>
      <NButton size="small" @click="hideSyncProgress">后台运行</NButton>
    </div>
  </NModal>

  <NModal :show="showDone" :mask-closable="false" :closable="false" @update:show="(v) => { if (!v) showDone = false }">
    <div style="background:var(--gray-2);border-radius:var(--radius-lg);padding:24px 28px;width:380px;border:1px solid var(--gray-6);box-shadow:var(--shadow-lg);text-align:center">
      <div style="font-size:14px;font-weight:600;color:var(--gray-12);margin-bottom:8px">{{ doneTitle }}</div>
      <div style="font-size:13px;color:var(--gray-11);line-height:1.6;margin-bottom:18px">{{ doneDetail }}</div>
      <NButton type="primary" @click="hideSyncDone">关闭</NButton>
    </div>
  </NModal>
</template>
