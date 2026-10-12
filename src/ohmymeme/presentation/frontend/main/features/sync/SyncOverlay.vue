<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NButton, NProgress, NCheckbox, useMessage } from 'naive-ui'
import { api } from '../../shared/bridge'
import type { SettingsData } from '../../shared/generated/bridge'

const emit = defineEmits<{
  synced: []
  done: []
}>()

const message = useMessage()

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

// NProgress 需要数值百分比，从 progressBar 字符串解析
const progressValue = computed(() => {
  const n = parseFloat(progressBar.value)
  return Number.isFinite(n) ? n : 0
})

function formatSpeed(bytesPerSec: number) {
  if (bytesPerSec >= 1048576) return (bytesPerSec / 1048576).toFixed(1) + ' MB/s'
  if (bytesPerSec >= 1024) return (bytesPerSec / 1024).toFixed(1) + ' KB/s'
  return bytesPerSec.toFixed(0) + ' B/s'
}

function showToast(msg: string) {
  message.info(msg, { duration: 1600 })
}

async function showUploadWarning(): Promise<boolean> {
  const s = await api('get_settings') as unknown as Pick<SettingsData, 'sync_delete_remote' | 'sync_hide_upload_warning'> | null
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

// NModal 遮罩点击等关闭统一按取消处理
function onWarningShowChange(show: boolean) {
  if (!show) cancelWarning()
}

async function start(method: string, title: string, progressSetting: string, doneSetting: string) {
  // 动态设置键只投影为布尔开关的读取
  const s = await api('get_settings') as unknown as { [key: string]: boolean | undefined } | null
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
      const p = await api('get_sync_progress') as unknown as { status?: string; current_file?: string; progress?: number; speed?: number } | null
      if (!p || p.status === 'idle') return
      progressFile.value = p.current_file || ''
      progressPct.value = (p.progress || 0) + '%'
      progressBar.value = (p.progress || 0) + '%'
      if (p.speed) progressSpeed.value = formatSpeed(p.speed)
    }, 300)
  }

  const r = await api(method) as unknown as { ok?: boolean; uploaded?: number; downloaded?: number; error?: string } | null
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
  <NModal
    :show="progressVisible"
    :close-on-esc="false"
    :mask-closable="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
  >
    <div
      id="sync-progress-overlay"
      class="sync-box"
      role="dialog"
      aria-modal="true"
      @keydown.esc.stop="hideProgress"
    >
      <div class="sync-title">{{ progressTitle }}</div>
      <div class="sync-file">{{ progressFile }}</div>
      <NProgress
        class="sync-bar"
        :percentage="progressValue"
        :height="8"
        :border-radius="4"
        :fill-border-radius="4"
        :show-indicator="false"
        color="var(--blue-9)"
        rail-color="var(--gray-1)"
      />
      <div class="sync-meta">
        <span>{{ progressPct }}</span>
        <span style="margin-left: 12px">{{ progressSpeed }}</span>
      </div>
      <NButton size="small" @click="hideProgress">后台运行</NButton>
    </div>
  </NModal>

  <!-- 完成浮层 -->
  <NModal
    :show="doneVisible"
    :close-on-esc="false"
    :mask-closable="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
  >
    <div
      id="sync-done-overlay"
      class="sync-box"
      role="dialog"
      aria-modal="true"
      @keydown.esc.stop="hideDone"
    >
      <div class="sync-title">{{ doneTitle }}</div>
      <div class="sync-detail">{{ doneDetail }}</div>
      <NButton type="primary" @click="hideDone">关闭</NButton>
    </div>
  </NModal>

  <!-- 上传警告 -->
  <NModal
    :show="warningVisible"
    :close-on-esc="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
    @update:show="onWarningShowChange"
  >
    <div
      class="sync-box"
      role="dialog"
      aria-modal="true"
      @keydown.esc.stop="cancelWarning"
    >
      <div class="sync-title">上传确认</div>
      <p class="sync-warning-text">上传会将本地的完整状态同步到远端，包括新增、更新和删除操作。远程文件将被覆盖，建议先下载备份。</p>
      <div class="sync-warning-label">
        <NCheckbox v-model:checked="warnHide">不再提醒</NCheckbox>
      </div>
      <div class="sync-warning-actions">
        <NButton @click="cancelWarning">取消</NButton>
        <NButton type="primary" @click="confirmWarning">继续上传</NButton>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.sync-box {
  background: var(--gray-2);
  border-radius: var(--radius-lg);
  padding: 24px 28px;
  width: 420px;
  border: 1px solid var(--gray-6);
  box-shadow: var(--shadow-lg);
  text-align: center;
}

.sync-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-12);
  margin-bottom: 4px;
}

.sync-file {
  font-size: 12px;
  color: var(--gray-11);
  margin-bottom: 12px;
  word-break: break-all;
}

.sync-bar {
  width: 100%;
  margin-bottom: 6px;
}

.sync-meta {
  font-size: 11.5px;
  color: var(--gray-11);
  margin-bottom: 16px;
}

.sync-detail {
  font-size: 13px;
  color: var(--gray-11);
  line-height: 1.6;
  margin-bottom: 18px;
}

.sync-warning-text {
  font-size: 13px;
  color: var(--gray-11);
  line-height: 1.6;
  margin: 8px 0 16px;
}

.sync-warning-label {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12.5px;
  color: var(--gray-11);
  margin-bottom: 16px;
  user-select: none;
}

.sync-warning-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
