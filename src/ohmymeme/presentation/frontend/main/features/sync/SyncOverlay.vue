<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../../shared/bridge'

const emit = defineEmits<{
  synced: []
  done: []
}>()

const progressVisible = ref(false)
const progressTitle = ref('同步中...')
const progressFile = ref('准备中')
const progressPct = ref('0%')
const progressSpeed = ref('')
const progressBar = ref('0%')

const doneVisible = ref(false)
const doneTitle = ref('同步完成')
const doneDetail = ref('')

const warningVisible = ref(false)
const warningResolve = ref<((ok: boolean) => void) | null>(null)
const warnHide = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

function formatSpeed(bytesPerSec: number) {
  if (bytesPerSec >= 1048576) return (bytesPerSec / 1048576).toFixed(1) + ' MB/s'
  if (bytesPerSec >= 1024) return (bytesPerSec / 1024).toFixed(1) + ' KB/s'
  return bytesPerSec.toFixed(0) + ' B/s'
}

function showToast(msg: string) {
  const el = document.getElementById('toast')
  if (!el) return
  el.textContent = msg
  el.classList.add('show')
  setTimeout(() => el.classList.remove('show'), 1600)
}

async function showUploadWarning(): Promise<boolean> {
  const s = await api('get_settings')
  if (!s) return true
  if (!s.sync_delete_remote) return true
  if (s.sync_hide_upload_warning) return true
  return new Promise(resolve => {
    warningResolve.value = resolve
    warnHide.value = false
    warningVisible.value = true
  })
}

async function confirmWarning() {
  if (warnHide.value) {
    await api('save_settings', { sync_hide_upload_warning: true })
  }
  warningVisible.value = false
  warningResolve.value?.(true)
  warningResolve.value = null
}

function cancelWarning() {
  warningVisible.value = false
  warningResolve.value?.(false)
  warningResolve.value = null
}

async function start(method: string, title: string, progressSetting: string, doneSetting: string) {
  const s = await api('get_settings')
  const showProgress = s ? s[progressSetting] !== false : true
  const showDone = s ? s[doneSetting] !== false : true

  const warnOk = await showUploadWarning()
  if (!warnOk) return

  if (showProgress) {
    progressTitle.value = title
    progressFile.value = '准备中...'
    progressPct.value = '0%'
    progressSpeed.value = ''
    progressBar.value = '0%'
    progressVisible.value = true
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = setInterval(async () => {
      const p = await api('get_sync_progress')
      if (!p || p.status === 'idle') return
      progressFile.value = p.current_file || ''
      progressPct.value = (p.progress || 0) + '%'
      progressBar.value = (p.progress || 0) + '%'
      if (p.speed) progressSpeed.value = formatSpeed(p.speed)
    }, 300)
  }

  const r = await api(method)
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }

  if (showProgress) progressVisible.value = false

  if (r && r.ok) {
    const cnt = r.uploaded || r.downloaded || 0
    showToast('完成: ' + cnt + ' 个')
    if (showDone) {
      doneTitle.value = title + '完成'
      doneDetail.value = '成功 ' + cnt + ' 个'
      doneVisible.value = true
    }
    emit('synced')
    emit('done')
  } else {
    showToast('失败: ' + ((r && r.error) || '未知错误'))
  }
}

function hideProgress() {
  progressVisible.value = false
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function hideDone() {
  doneVisible.value = false
}

defineExpose({ start, hideProgress, hideDone })
</script>

<template>
  <!-- 进度浮层 -->
  <div v-if="progressVisible" id="sync-progress-overlay">
    <div class="sync-box">
      <div class="sync-title">{{ progressTitle }}</div>
      <div class="sync-file">{{ progressFile }}</div>
      <div class="sync-bar-wrap">
        <div class="sync-bar" :style="{ width: progressBar }"></div>
      </div>
      <div class="sync-meta">
        <span>{{ progressPct }}</span>
        <span style="margin-left: 12px">{{ progressSpeed }}</span>
      </div>
      <button class="btn btn-secondary btn-sm" @click="hideProgress">后台运行</button>
    </div>
  </div>

  <!-- 完成浮层 -->
  <div v-if="doneVisible" id="sync-done-overlay">
    <div class="sync-box">
      <div class="sync-title">{{ doneTitle }}</div>
      <div class="sync-detail">{{ doneDetail }}</div>
      <button class="btn btn-primary" @click="hideDone">关闭</button>
    </div>
  </div>

  <!-- 上传警告 -->
  <div v-if="warningVisible" class="sync-warning-overlay" @click.self="cancelWarning">
    <div class="sync-box">
      <div class="sync-title">上传确认</div>
      <p class="sync-warning-text">上传会将本地的完整状态同步到远端，包括新增、更新和删除操作。远程文件将被覆盖，建议先下载备份。</p>
      <label class="sync-warning-label">
        <input v-model="warnHide" type="checkbox" style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer"> 不再提醒
      </label>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary" @click="cancelWarning">取消</button>
        <button class="btn btn-primary" @click="confirmWarning">继续上传</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
#sync-progress-overlay, #sync-done-overlay, .sync-warning-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 500;
  animation: fadeIn 0.15s ease;
}

.sync-box {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 24px 28px;
  width: 420px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  text-align: center;
}

.sync-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 4px;
}

.sync-file {
  font-size: 12px;
  color: var(--fg-secondary);
  margin-bottom: 12px;
  word-break: break-all;
}

.sync-bar-wrap {
  width: 100%;
  height: 8px;
  background: var(--bg);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}

.sync-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s;
}

.sync-meta {
  font-size: 11.5px;
  color: var(--muted);
  margin-bottom: 16px;
}

.sync-detail {
  font-size: 13px;
  color: var(--fg-secondary);
  line-height: 1.6;
  margin-bottom: 18px;
}

.sync-warning-text {
  font-size: 13px;
  color: var(--fg-secondary);
  line-height: 1.6;
  margin: 8px 0 16px;
}

.sync-warning-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--muted);
  margin-bottom: 16px;
  user-select: none;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
