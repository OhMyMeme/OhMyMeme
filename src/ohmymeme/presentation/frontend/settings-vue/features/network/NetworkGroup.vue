<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { NCheckbox, NSelect, NInput, NButton, NModal, useDialog } from 'naive-ui'
import { api } from '../../shared/bridge'
import { settings, markDirty, showToast, collectSync, validateSync } from '../../shared/store'
import { getPluginUI, pluginUILabel, pluginProgressValue } from '../../shared/plugin-ui'

// 解包桥接返回值（可能为 Promise 或同步值）
async function call(method: string, ...args: any[]): Promise<any> {
  const p = api(method, ...args)
  return p && typeof p.then === 'function' ? await p : p
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
  if (r) lanSecretConfig.value = r.allow_secret_config === true
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
    const port = parseInt(settings.lan_port) || 17852
    const secret = settings.lan_secret || ''
    const r = await call('lan_start', port, secret)
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
// 后端下拉选项，仅保留宿主 UI 投影中声明的 sync.* 后端
const syncTypeOptions = computed(() => {
  const base = [{ label: '无', value: '' }]
  const names: Record<string, string> = { ftp: 'FTP', s3: 'S3 兼容存储', r2: 'Cloudflare R2', webdav: 'WebDAV' }
  const ui = getPluginUI()
  const screens = ui ? ui.contributions.filter((row: any) => row.provider.startsWith('sync.')).map((row: any) => row.screen) : []
  for (const key of ['ftp', 's3', 'r2', 'webdav']) {
    if (screens.includes(key)) base.push({ label: names[key] as string, value: key })
  }
  return base
})

// 当前选中后端是否被宿主投影接纳（决定表单显隐）
function selectedScreen(): string | null {
  const t = settings.sync_type || ''
  const ui = getPluginUI()
  const found = ui ? ui.contributions.find((row: any) => row.provider.startsWith('sync.') && row.screen === t) : null
  return found ? (found as any).screen : null
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
const testLabel = ref('测试连接')

// 测试同步连接
async function testSync() {
  const sync = collectSync()
  if (!validateSync(sync)) return
  await call('save_settings', sync)
  testLabel.value = '测试中...'
  const r = await call('sync_test')
  testLabel.value = pluginUILabel('sync_test')
  if (r && r.ok) syncStatus.value = '连接成功'
  else syncStatus.value = '连接失败: ' + ((r && r.error) || '未知错误')
}

// 检查同步状态
async function checkSyncStatus() {
  const sync = collectSync()
  if (!validateSync(sync)) return
  await call('save_settings', sync)
  const r = await call('get_sync_status')
  if (!r || !r.ok) { showToast('同步状态：' + ((r && r.error) || '获取失败')); return }
  const msg = '本地 ' + (r.local_count || 0) + ' 个，远端 ' + (r.remote_count || 0) + ' 个'
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

// 上传前确认（仅在删除远端且未勾选不再提醒时）
function showUploadWarning(): Promise<boolean> {
  const sync = collectSync()
  if (!sync.sync_delete_remote) return Promise.resolve(true)
  if (sync.sync_hide_upload_warning) return Promise.resolve(true)
  return new Promise<boolean>((resolve) => {
    dialog.warning({
      title: '上传确认',
      content: '上传会将本地的完整状态同步到远端，包括新增、更新和删除操作。远程文件将被覆盖，建议先下载备份。',
      positiveText: '继续上传', negativeText: '取消',
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false),
      onMaskClick: () => resolve(false),
    })
  })
}

const pushBusy = ref(false)
const pullBusy = ref(false)

// 带进度的同步执行（push/pull 共用）
async function doSyncWithProgress(method: string, title: string, progressKey: string, doneKey: string, busy: { value: boolean }) {
  const sync = collectSync()
  if (!validateSync(sync)) return
  const warnOk = await showUploadWarning()
  if (!warnOk) return
  await call('save_settings', sync)

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
      progressFile.value = pluginProgressValue('get_sync_progress', s, 'current_file') || ''
      progress.value = pluginProgressValue('get_sync_progress', s, 'progress') || 0
      if (s.speed) progressSpeed.value = formatSpeed(s.speed)
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

  try { (window as any).pywebview?.api?.refresh_memes?.() } catch (_) {}
  try { (window as any).pywebview?.api?.refresh_tags?.() } catch (_) {}
  try { (window as any).pywebview?.api?.refresh_collections?.() } catch (_) {}
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

onMounted(() => {
  refreshLanStatus()
})
onUnmounted(() => {
  if (lanPollTimer) clearInterval(lanPollTimer)
  if (syncPollTimer) clearInterval(syncPollTimer)
})
</script>

<template>
  <div class="section">
    <div class="section-title">局域网互联</div>
    <p style="font-size:11.5px;color:var(--muted);margin-bottom:10px;line-height:1.6">与手机版 OhMyMeme 在同一局域网内配对，互相同步表情包与配置</p>
    <div class="form-group">
      <label>端口</label>
      <input :value="settings.lan_port" @input="settings.lan_port = ($event.target as HTMLInputElement).value; markDirty()">
    </div>
    <div class="form-group">
      <label>连接密钥</label>
      <input type="password" placeholder="留空表示同一局域网无需密钥" :value="settings.lan_secret" @input="settings.lan_secret = ($event.target as HTMLInputElement).value; markDirty()">
    </div>
    <label class="check-row" style="margin-bottom:12px">
      <NCheckbox :checked="lanEnable" @update:checked="toggleLan" />开启互联访问<span class="immediate-hint">立即生效</span>
    </label>
    <label class="check-row" style="margin-bottom:12px">
      <NCheckbox :checked="lanSecretConfig" @update:checked="toggleLanSecretConfig" />允许密钥传输（配置同步时包含 FTP/S3/R2/WebDAV 密码等密钥字段）<span class="immediate-hint">立即生效，仅本次会话</span>
    </label>
    <div style="display:flex;gap:8px">
      <button class="btn btn-secondary btn-sm btn-flex" @click="refreshLanStatus">刷新状态</button>
    </div>
    <div class="s-net-status" :class="{ 'status-ok': lanStatusMode === 'ok', 'status-error': lanStatusMode === 'error' }" style="font-size:11.5px;margin-top:6px;line-height:1.8">{{ lanStatusText }}</div>
  </div>

  <div class="section">
    <div class="section-title">云端同步</div>
    <label class="check-row">
      <NCheckbox :checked="settings.sync_auto_fetch_index === true" @update:checked="(v: boolean) => { settings.sync_auto_fetch_index = v; markDirty() }" />启动时自动获取远端索引
    </label>
    <label class="check-row" style="margin-bottom:12px">
      <NCheckbox :checked="settings.sync_auto_sync === true" @update:checked="(v: boolean) => { settings.sync_auto_sync = v; markDirty() }" />启动时自动同步
    </label>

    <div class="form-group">
      <label>存储类型</label>
      <NSelect :value="settings.sync_type || ''" :options="syncTypeOptions" @update:value="(v: string) => { settings.sync_type = v; markDirty() }" />
    </div>

    <div v-show="showSyncExtra">
      <label class="check-row">
        <NCheckbox :checked="settings.sync_delete_remote === true" @update:checked="(v: boolean) => { settings.sync_delete_remote = v; markDirty() }" />上传时删除远端文件
      </label>
      <label class="check-row">
        <NCheckbox :checked="settings.sync_remove_local === true" @update:checked="(v: boolean) => { settings.sync_remove_local = v; markDirty() }" />下载时删除本地多余文件
      </label>
      <label class="check-row" style="margin-bottom:12px">
        <NCheckbox :checked="settings.sync_hide_upload_warning === true" @update:checked="(v: boolean) => { settings.sync_hide_upload_warning = v; markDirty() }" />上传前不再提醒
      </label>
      <label class="check-row">
        <NCheckbox :checked="settings.show_upload_progress !== false" @update:checked="(v: boolean) => { settings.show_upload_progress = v }" />上传时显示进度条
      </label>
      <label class="check-row">
        <NCheckbox :checked="settings.show_upload_done !== false" @update:checked="(v: boolean) => { settings.show_upload_done = v }" />上传完毕显示提示
      </label>
      <label class="check-row">
        <NCheckbox :checked="settings.show_download_progress !== false" @update:checked="(v: boolean) => { settings.show_download_progress = v }" />下载时显示进度条
      </label>
      <label class="check-row">
        <NCheckbox :checked="settings.show_download_done !== false" @update:checked="(v: boolean) => { settings.show_download_done = v }" />下载完毕显示提示
      </label>
    </div>

    <div v-show="showFtp">
      <div class="form-group"><label>FTP 服务器</label><input placeholder="ftp.example.com" :value="settings.ftp_host" @input="settings.ftp_host = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="ftp-row">
        <div class="form-group"><label>端口</label><input :value="settings.ftp_port" @input="settings.ftp_port = ($event.target as HTMLInputElement).value; markDirty()"></div>
        <div class="form-group"><label>用户名</label><input placeholder="anonymous" :value="settings.ftp_user" @input="settings.ftp_user = ($event.target as HTMLInputElement).value; markDirty()"></div>
      </div>
      <div class="form-group"><label>密码</label><input type="password" :value="settings.ftp_password" @input="settings.ftp_password = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>远程路径</label><input :value="settings.ftp_path" @input="settings.ftp_path = ($event.target as HTMLInputElement).value; markDirty()"></div>
    </div>

    <div v-show="showS3">
      <div class="form-group"><label>Endpoint URL</label><input placeholder="https://s3.amazonaws.com" :value="settings.s3_endpoint" @input="settings.s3_endpoint = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>寻址方式</label><NSelect :value="settings.s3_addressing_style || 'virtual'" :options="s3AddrOptions" @update:value="(v: string) => { settings.s3_addressing_style = v; markDirty() }" /></div>
      <div class="form-group"><label>签名版本</label><NSelect :value="settings.s3_signature_version || 's3'" :options="s3SigOptions" @update:value="(v: string) => { settings.s3_signature_version = v; markDirty() }" /></div>
      <div class="ftp-row">
        <div class="form-group"><label>Region</label><input placeholder="us-east-1" :value="settings.s3_region" @input="settings.s3_region = ($event.target as HTMLInputElement).value; markDirty()"></div>
        <div class="form-group"><label>Bucket</label><input placeholder="my-bucket" :value="settings.s3_bucket" @input="settings.s3_bucket = ($event.target as HTMLInputElement).value; markDirty()"></div>
      </div>
      <div class="form-group"><label>Access Key</label><input :value="settings.s3_access_key" @input="settings.s3_access_key = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>Secret Key</label><input type="password" :value="settings.s3_secret_key" @input="settings.s3_secret_key = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>路径前缀（可选）</label><input placeholder="ohmymeme" :value="settings.s3_path" @input="settings.s3_path = ($event.target as HTMLInputElement).value; markDirty()"></div>
    </div>

    <div v-show="showR2">
      <div class="form-group"><label>Cloudflare Account ID</label><input placeholder="32 位十六进制字符串" :value="settings.r2_account_id" @input="settings.r2_account_id = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>R2 Access Key ID</label><input :value="settings.r2_access_key_id" @input="settings.r2_access_key_id = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>R2 Secret Access Key</label><input type="password" :value="settings.r2_secret_access_key" @input="settings.r2_secret_access_key = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>Bucket 名称</label><input placeholder="my-bucket" :value="settings.r2_bucket" @input="settings.r2_bucket = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>路径前缀（可选）</label><input placeholder="ohmymeme" :value="settings.r2_path" @input="settings.r2_path = ($event.target as HTMLInputElement).value; markDirty()"></div>
    </div>

    <div v-show="showWebdav">
      <div class="form-group"><label>WebDAV URL</label><input placeholder="https://example.com/remote.php/dav/files/user" :value="settings.webdav_url" @input="settings.webdav_url = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>用户名</label><input :value="settings.webdav_user" @input="settings.webdav_user = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>密码</label><input type="password" :value="settings.webdav_password" @input="settings.webdav_password = ($event.target as HTMLInputElement).value; markDirty()"></div>
      <div class="form-group"><label>远程路径（可选）</label><input placeholder="ohmymeme" :value="settings.webdav_path" @input="settings.webdav_path = ($event.target as HTMLInputElement).value; markDirty()"></div>
    </div>

    <div v-show="showSyncExtra">
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn btn-secondary btn-sm btn-flex" @click="testSync">{{ testLabel }}</button>
        <button class="btn btn-secondary btn-sm btn-flex" @click="checkSyncStatus">检查同步状态</button>
        <button class="btn btn-primary btn-sm btn-flex" :disabled="pushBusy" @click="syncPush">{{ pushBusy ? '同步中...' : '上传到远端' }}</button>
        <button class="btn btn-primary btn-sm btn-flex" :disabled="pullBusy" @click="syncPull">{{ pullBusy ? '同步中...' : '从远端下载' }}</button>
      </div>
      <div style="margin-top:6px">{{ syncStatus }}</div>
      <div style="display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap">
        <span style="font-size:12px;color:var(--muted)">云端孤儿文件</span>
        <button class="btn btn-secondary btn-sm" @click="scanOrphans">扫描</button>
        <button class="btn btn-danger-outline btn-sm" :disabled="orphanDeleteDisabled" @click="deleteOrphans">删除孤儿</button>
        <span style="font-size:11.5px;color:var(--muted)">{{ orphanStatus }}</span>
      </div>
    </div>
  </div>

  <NModal :show="showProgress" :mask-closable="false" :closable="false" :close-on-esc="false">
    <div style="background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:420px;border:1px solid var(--border);box-shadow:var(--shadow-lg);text-align:center">
      <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:4px">{{ progressTitle }}</div>
      <div style="font-size:12px;color:var(--fg-secondary);margin-bottom:12px;word-break:break-all">{{ progressFile }}</div>
      <div style="width:100%;height:8px;background:var(--bg);border-radius:4px;overflow:hidden;margin-bottom:6px">
        <div :style="{ width: progress + '%', height: '100%', background: 'var(--accent)', borderRadius: '4px', transition: 'width .3s' }"></div>
      </div>
      <div style="font-size:11.5px;color:var(--muted);margin-bottom:16px"><span>{{ progress }}%</span><span style="margin-left:12px">{{ progressSpeed }}</span></div>
      <button class="btn btn-secondary btn-sm" @click="hideSyncProgress">后台运行</button>
    </div>
  </NModal>

  <NModal :show="showDone" :mask-closable="false" :closable="false" :close-on-esc="false">
    <div style="background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:380px;border:1px solid var(--border);box-shadow:var(--shadow-lg);text-align:center">
      <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:8px">{{ doneTitle }}</div>
      <div style="font-size:13px;color:var(--fg-secondary);line-height:1.6;margin-bottom:18px">{{ doneDetail }}</div>
      <button class="btn btn-primary" @click="hideSyncDone">关闭</button>
    </div>
  </NModal>
</template>
