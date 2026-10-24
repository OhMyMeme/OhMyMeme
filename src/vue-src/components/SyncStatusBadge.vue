<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../utils/api'

interface TransferState {
  active: boolean
  status: string
  direction: string
  files_done: number
  files_total: number
  remaining: number
  bytes_done: number
  bytes_total: number
  progress: number
  speed: number
  current_file: string
}

interface SyncStatus {
  configured: boolean
  manifest_state: 'ok' | 'loading' | 'error' | 'missing'
  refreshing: boolean
  checked: boolean
  error: string
  checked_at: number
  local_count: number
  remote_count: number
  local_missing: number
  cloud_missing: number
  synced: boolean
  transfer: TransferState
}

const EMPTY_TRANSFER: TransferState = {
  active: false,
  status: 'idle',
  direction: '',
  files_done: 0,
  files_total: 0,
  remaining: 0,
  bytes_done: 0,
  bytes_total: 0,
  progress: 0,
  speed: 0,
  current_file: '',
}

const RING_RADIUS = 10.5
const RING_CIRC = 2 * Math.PI * RING_RADIUS

const configured = ref(false)
const manifestState = ref<SyncStatus['manifest_state']>('loading')
const refreshing = ref(false)
const errorText = ref('')
const checkedAt = ref(0)
const localCount = ref(0)
const remoteCount = ref(0)
const localMissing = ref(0)
const cloudMissing = ref(0)
const synced = ref(false)
const transfer = ref<TransferState>({ ...EMPTY_TRANSFER })
const nowTick = ref(Date.now())
const open = ref(false)
const popStyle = ref<Record<string, string>>({})

const rootEl = ref<HTMLElement | null>(null)
const btnEl = ref<HTMLButtonElement | null>(null)

let pollTimer: ReturnType<typeof setTimeout> | null = null
let leaveTimer: ReturnType<typeof setTimeout> | null = null
let endTimer: ReturnType<typeof setTimeout> | null = null
let inFlight = false
let disposed = false
let wasTransferring = false

const visualState = computed(() => {
  if (!configured.value) return 'hidden'
  if (transfer.value.active) return 'transfer'
  if (manifestState.value === 'loading') return 'checking'
  if (manifestState.value === 'ok' && synced.value) return 'synced'
  return 'unsynced'
})

const ringPct = computed<number | null>(() => {
  const t = transfer.value
  if (t.files_total > 0) return Math.min(t.files_done / t.files_total, 0.99)
  if (t.bytes_total > 0) return Math.min(t.bytes_done / t.bytes_total, 0.99)
  return null
})

const ringOffset = computed(() => RING_CIRC * (1 - (ringPct.value ?? 0)))
const ringPctText = computed(() => {
  if (ringPct.value === null) return ''
  return Math.round(ringPct.value * 100) + '%'
})

const transferTitle = computed(() => {
  const t = transfer.value
  if (t.status === 'uploading' || t.direction === 'upload') return '正在上传'
  if (t.status === 'downloading' || t.direction === 'download') return '正在下载'
  if (t.status === 'deleting' || t.direction === 'delete') return '正在清理'
  return '正在传输'
})

const remainingText = computed(() => {
  const t = transfer.value
  if (t.files_total > 0 && t.remaining > 0) return `还有 ${t.remaining} 个文件`
  if (t.files_total > 0) return '正在收尾…'
  return '正在准备传输…'
})

const currentFileName = computed(() => {
  const p = transfer.value.current_file || ''
  const parts = p.split(/[\\/]/)
  return parts[parts.length - 1] || ''
})

const speedText = computed(() => {
  const v = transfer.value.speed
  if (!v || v <= 0) return ''
  if (v >= 1048576) return (v / 1048576).toFixed(1) + ' MB/s'
  if (v >= 1024) return (v / 1024).toFixed(1) + ' KB/s'
  return Math.round(v) + ' B/s'
})

const progressText = computed(() => {
  const t = transfer.value
  if (!t.files_total) return ''
  const pct = Math.min(Math.round((t.files_done / t.files_total) * 100), 99)
  return `${pct}%`
})

const idleTitle = computed(() => {
  if (manifestState.value === 'loading') return '正在核对云端清单'
  if (manifestState.value === 'error') return '无法获取云端清单'
  if (manifestState.value === 'missing') return '尚未同步'
  if (synced.value) return '已同步'
  return '存在未同步文件'
})

const popTitle = computed(() => (transfer.value.active ? transferTitle.value : idleTitle.value))

const statusLabel = computed(() => {
  if (!configured.value) return ''
  if (transfer.value.active) return `${transferTitle.value}，${remainingText.value}`
  if (manifestState.value === 'loading') return '正在检查云端同步状态'
  if (manifestState.value === 'error') return '无法获取云端清单'
  if (manifestState.value === 'missing') return '同步状态：尚未同步'
  if (synced.value) return '同步状态：已同步'
  return `同步状态：本地缺失 ${localMissing.value} 个文件，云端缺失 ${cloudMissing.value} 个文件`
})

const statusTitle = computed(() => (statusLabel.value ? statusLabel.value + '（点击查看详情）' : ''))

const checkedText = computed(() => {
  if (!checkedAt.value) return ''
  const sec = Math.max(0, Math.round(nowTick.value / 1000 - checkedAt.value))
  if (sec < 10) return '刚刚检查'
  if (sec < 60) return `${sec} 秒前检查`
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前检查`
  return `${Math.floor(sec / 3600)} 小时前检查`
})

function normalizeTransfer(raw: any): TransferState {
  const t = raw && typeof raw === 'object' ? raw : {}
  const num = (v: any) => {
    const n = Number(v)
    return Number.isFinite(n) && n > 0 ? n : 0
  }
  return {
    active: t.active === true,
    status: typeof t.status === 'string' ? t.status : 'idle',
    direction: typeof t.direction === 'string' ? t.direction : '',
    files_done: num(t.files_done),
    files_total: num(t.files_total),
    remaining: num(t.remaining),
    bytes_done: num(t.bytes_done),
    bytes_total: num(t.bytes_total),
    progress: num(t.progress),
    speed: num(t.speed),
    current_file: typeof t.current_file === 'string' ? t.current_file : '',
  }
}

function applyStatus(r: any) {
  configured.value = r && r.configured === true
  nowTick.value = Date.now()
  if (!configured.value) {
    transfer.value = { ...EMPTY_TRANSFER }
    manifestState.value = 'loading'
    synced.value = false
    wasTransferring = false
    closePopover()
    return
  }
  const state = r.manifest_state
  manifestState.value = state === 'ok' || state === 'error' || state === 'missing' || state === 'loading' ? state : 'loading'
  refreshing.value = r.refreshing === true
  errorText.value = typeof r.error === 'string' ? r.error : ''
  checkedAt.value = Number(r.checked_at) || 0
  localCount.value = Number(r.local_count) || 0
  remoteCount.value = Number(r.remote_count) || 0
  localMissing.value = Number(r.local_missing) || 0
  cloudMissing.value = Number(r.cloud_missing) || 0
  synced.value = r.synced === true
  const prevActive = transfer.value.active
  transfer.value = normalizeTransfer(r.transfer)
  if (prevActive && !transfer.value.active) {
    if (open.value && wasTransferring) {
      if (endTimer) clearTimeout(endTimer)
      endTimer = setTimeout(() => closePopover(), 320)
    }
    wasTransferring = false
    // 同步结束后远端清单可能已变化：补一次普通刷新（后端会按需重拉）
    setTimeout(() => { if (!disposed) refresh() }, 360)
  } else if (!prevActive && transfer.value.active) {
    wasTransferring = true
  }
}

async function refresh(force = false): Promise<boolean> {
  if (disposed || inFlight) return false
  if (typeof window.pywebview === 'undefined' || !window.pywebview?.api?.get_sync_status) return false
  inFlight = true
  let ok = false
  try {
    const r = await api('get_sync_status', force)
    if (r && typeof r === 'object') {
      applyStatus(r)
      ok = true
    }
  } catch (e) {
    console.error('sync status error:', e)
  } finally {
    inFlight = false
  }
  return ok
}

function schedule(delay?: number) {
  if (pollTimer) clearTimeout(pollTimer)
  if (disposed) return
  const ms = delay ?? (transfer.value.active ? 600 : refreshing.value ? 900 : 5000)
  pollTimer = setTimeout(tick, ms)
}

async function tick() {
  if (disposed) return
  const ok = await refresh()
  schedule(ok ? undefined : 700)
}

function positionPopover() {
  const rect = btnEl.value?.getBoundingClientRect()
  if (!rect) return
  const width = 272
  const margin = 8
  const left = Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin))
  const arrow = Math.max(12, Math.min(width - 12, rect.left + rect.width / 2 - left))
  popStyle.value = {
    left: left + 'px',
    top: rect.bottom + 8 + 'px',
    width: width + 'px',
    '--arrow-left': arrow + 'px',
  }
}

function onDocPointerDown(e: PointerEvent) {
  if (!open.value) return
  const target = e.target as Node | null
  if (target && rootEl.value?.contains(target)) return
  closePopover()
}

function addGlobalListeners() {
  document.addEventListener('pointerdown', onDocPointerDown, true)
  window.addEventListener('resize', positionPopover)
}

function removeGlobalListeners() {
  document.removeEventListener('pointerdown', onDocPointerDown, true)
  window.removeEventListener('resize', positionPopover)
}

function openPopover() {
  if (!configured.value) return
  positionPopover()
  open.value = true
  addGlobalListeners()
  nextTick(positionPopover)
}

function closePopover() {
  if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = null }
  if (endTimer) { clearTimeout(endTimer); endTimer = null }
  if (!open.value) return
  open.value = false
  removeGlobalListeners()
}

function toggle() {
  if (open.value) closePopover()
  else openPopover()
}

function onRootEnter() {
  if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = null }
}

function onRootLeave() {
  // 传输中按需求鼠标移离即隐藏；非传输状态保留弹窗便于阅读，点外部/Esc 关闭
  if (!open.value || !transfer.value.active) return
  if (leaveTimer) clearTimeout(leaveTimer)
  leaveTimer = setTimeout(() => { leaveTimer = null; closePopover() }, 220)
}

function onWindowFocus() {
  if (!open.value) refresh()
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible' && !open.value) refresh()
}

onMounted(() => {
  schedule(0)
  window.addEventListener('focus', onWindowFocus)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  disposed = true
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
  if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = null }
  if (endTimer) { clearTimeout(endTimer); endTimer = null }
  removeGlobalListeners()
  window.removeEventListener('focus', onWindowFocus)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

defineExpose({
  refresh,
  close: closePopover,
  isOpen: () => open.value,
})
</script>

<template>
  <div
    v-show="configured"
    ref="rootEl"
    class="sync-status"
    :class="'is-' + visualState"
    @mouseenter="onRootEnter"
    @mouseleave="onRootLeave"
  >
    <button
      ref="btnEl"
      type="button"
      class="icon-btn sync-status__btn"
      :class="{ 'is-open': open }"
      :title="statusTitle"
      :aria-label="statusLabel"
      aria-haspopup="dialog"
      :aria-expanded="open"
      aria-controls="sync-status-popover"
      @click="toggle"
    >
      <span class="sync-status__glyph" aria-hidden="true">
        <template v-if="transfer.active">
          <svg class="sync-status__ring" viewBox="0 0 24 24">
            <circle class="sync-ring__track" cx="12" cy="12" :r="RING_RADIUS" />
            <circle
              v-if="ringPct !== null"
              class="sync-ring__value"
              cx="12"
              cy="12"
              :r="RING_RADIUS"
              :stroke-dasharray="RING_CIRC"
              :stroke-dashoffset="ringOffset"
            />
            <circle
              v-else
              class="sync-ring__value sync-ring__value--indeterminate"
              cx="12"
              cy="12"
              :r="RING_RADIUS"
            />
          </svg>
          <svg class="sync-status__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="7.4" />
            <path d="M9.4 14.8V9.4m0 0L7.6 11.2m1.8-1.8 1.8 1.8" />
            <path d="M14.6 9.2v5.4m0 0 1.8-1.8m-1.8 1.8-1.8-1.8" />
          </svg>
        </template>
        <template v-else>
          <svg class="sync-status__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
          </svg>
          <span v-if="visualState === 'synced'" class="sync-status__badge sync-status__badge--ok">
            <svg viewBox="0 0 12 12" width="7" height="7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.6 6.3 4.8 8.5 9.4 3.5"/></svg>
          </span>
          <span v-else-if="visualState === 'unsynced'" class="sync-status__badge sync-status__badge--warn">!</span>
        </template>
      </span>
    </button>

    <Transition name="sync-pop">
      <div
        v-if="open"
        id="sync-status-popover"
        class="sync-pop"
        :style="popStyle"
        role="dialog"
        :aria-label="popTitle"
        @mousedown.stop
      >
        <template v-if="transfer.active">
          <div class="sync-pop__head">
            <span class="sync-pop__pulse" aria-hidden="true"></span>
            <span class="sync-pop__title">{{ transferTitle }}</span>
            <span v-if="progressText" class="sync-pop__pct">{{ progressText }}</span>
          </div>
          <div class="sync-pop__remaining" aria-live="polite">{{ remainingText }}</div>
          <div class="sync-pop__bar" role="progressbar" :aria-valuemin="0" :aria-valuemax="100" :aria-valuenow="ringPct === null ? undefined : Math.round(ringPct * 100)">
            <i :style="{ width: ringPct === null ? '35%' : Math.round(ringPct * 100) + '%' }"></i>
          </div>
          <div class="sync-pop__meta">
            <span>{{ transfer.files_done }}/{{ transfer.files_total || '?' }} 个文件</span>
            <span v-if="speedText">{{ speedText }}</span>
          </div>
          <div v-if="currentFileName" class="sync-pop__file" :title="transfer.current_file">{{ currentFileName }}</div>
          <div class="sync-pop__hint">传输在后台继续进行</div>
        </template>

        <template v-else>
          <div class="sync-pop__head">
            <span class="sync-pop__title">同步状态</span>
            <button
              type="button"
              class="sync-pop__refresh"
              :class="{ 'is-spinning': refreshing }"
              title="重新检查云端清单"
              aria-label="重新检查云端清单"
              :disabled="refreshing"
              @click="refresh(true)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
            </button>
          </div>

          <div v-if="manifestState === 'loading'" class="sync-pop__state">
            <span class="sync-spinner" aria-hidden="true"></span>
            <span>正在读取云端同步信息…</span>
          </div>

          <div v-else-if="manifestState === 'error'" class="sync-pop__state-block">
            <div class="sync-pop__state-title">无法获取云端清单</div>
            <div class="sync-pop__state-text">请检查网络连接或云端同步配置后重试。</div>
            <div v-if="errorText" class="sync-pop__error" :title="errorText">{{ errorText }}</div>
          </div>

          <div v-else-if="manifestState === 'missing'" class="sync-pop__state-block">
            <div class="sync-pop__state-title">尚未同步</div>
            <div class="sync-pop__state-text">云端还没有同步清单。上传一次即可建立清单，之后这里会显示同步状态。</div>
          </div>

          <div v-else-if="synced" class="sync-pop__ok">
            <span class="sync-pop__ok-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
            </span>
            <div>
              <div class="sync-pop__ok-title">已同步</div>
              <div class="sync-pop__ok-sub">本机与云端一致</div>
            </div>
          </div>

          <div v-else class="sync-pop__rows">
            <div v-if="localMissing" class="sync-row">
              <span class="sync-row__icon sync-row__icon--down" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12m-5-5 5 5 5-5"/><path d="M5 20h14"/></svg>
              </span>
              <div class="sync-row__text">
                <div class="sync-row__title">本地缺失 <b class="is-primary">{{ localMissing }}</b> 个文件</div>
                <div class="sync-row__sub">云端有，本机没有</div>
              </div>
            </div>
            <div v-if="cloudMissing" class="sync-row">
              <span class="sync-row__icon sync-row__icon--up" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V8m-5 5 5-5 5 5"/><path d="M5 4h14"/></svg>
              </span>
              <div class="sync-row__text">
                <div class="sync-row__title">云端缺失 <b class="is-warn">{{ cloudMissing }}</b> 个文件</div>
                <div class="sync-row__sub">本机有，云端没有</div>
              </div>
            </div>
          </div>

          <div v-if="manifestState === 'ok'" class="sync-pop__foot">
            <span>本机 {{ localCount }} · 云端 {{ remoteCount }}</span>
            <span v-if="errorText" class="sync-pop__foot-warn" :title="errorText">检查失败</span>
            <span v-else-if="checkedText">{{ checkedText }}</span>
          </div>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.sync-status {
  display: flex;
  align-items: center;
  -webkit-app-region: no-drag;
}

.sync-status__btn {
  position: relative;
  overflow: visible;
}

.sync-status.is-synced .sync-status__btn,
.sync-status.is-unsynced .sync-status__btn {
  color: var(--fg-secondary);
}

.sync-status.is-synced .sync-status__btn:hover,
.sync-status.is-unsynced .sync-status__btn:hover {
  color: var(--fg);
}

.sync-status.is-checking .sync-status__btn {
  color: var(--muted);
  animation: sync-soft-pulse 1.7s ease-in-out infinite;
}

.sync-status.is-transfer .sync-status__btn {
  color: var(--primary);
}

.sync-status__glyph {
  position: relative;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
}

.sync-status__icon {
  position: relative;
  width: 16px;
  height: 16px;
}

.sync-status__ring {
  position: absolute;
  inset: 0;
  width: 24px;
  height: 24px;
  transform: rotate(-90deg);
  overflow: visible;
}

.sync-ring__track {
  fill: none;
  stroke: var(--border-light);
  stroke-width: 1.6;
  opacity: 0.85;
}

.sync-ring__value {
  fill: none;
  stroke: var(--primary);
  stroke-width: 1.9;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.4s ease;
}

.sync-ring__value--indeterminate {
  stroke-dasharray: 14 52;
  animation: sync-ring-spin 1.15s linear infinite;
  transform-origin: center;
  transform-box: fill-box;
}

.sync-status__badge {
  position: absolute;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1.5px solid var(--surface);
  color: #06210f;
  font-size: 8px;
  font-weight: 800;
  line-height: 1;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
}

.sync-status__badge--ok { background: var(--success); }
.sync-status__badge--warn { background: var(--warning); }

.sync-pop {
  position: fixed;
  z-index: 300;
  width: 272px;
  padding: 12px 14px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  background: var(--surface-2);
  box-shadow: var(--shadow-lg);
  color: var(--fg);
  text-align: left;
  -webkit-app-region: no-drag;
}

.sync-pop::before {
  content: '';
  position: absolute;
  top: -5px;
  left: var(--arrow-left, 50%);
  width: 9px;
  height: 9px;
  margin-left: -4.5px;
  background: var(--surface-2);
  border-left: 1px solid var(--border-light);
  border-top: 1px solid var(--border-light);
  transform: rotate(45deg);
}

.sync-pop__head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 20px;
}

.sync-pop__title {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.3;
}

.sync-pop__refresh {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin: -1px -4px -1px 0;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.sync-pop__refresh:hover:not(:disabled) {
  background: var(--surface);
  color: var(--fg);
}

.sync-pop__refresh:disabled { cursor: default; opacity: 0.7; }

.sync-pop__refresh svg { width: 13px; height: 13px; }

.sync-pop__refresh.is-spinning svg { animation: sync-spin 0.9s linear infinite; }

.sync-pop__pct {
  flex: none;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--primary);
}

.sync-pop__pulse {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary);
  animation: sync-pulse 1.6s ease-out infinite;
}

.sync-pop__remaining {
  margin: 7px 0 10px;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.01em;
  line-height: 1.25;
}

.sync-pop__bar {
  height: 5px;
  border-radius: 3px;
  background: var(--border);
  overflow: hidden;
}

.sync-pop__bar > i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--primary);
  transition: width 0.35s ease;
}

.sync-pop__meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
}

.sync-pop__file {
  margin-top: 6px;
  overflow: hidden;
  font-size: 10.5px;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sync-pop__hint {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border-hair);
  font-size: 10.5px;
  color: var(--muted);
}

.sync-pop__state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0 4px;
  font-size: 11.5px;
  color: var(--fg-secondary);
}

.sync-spinner {
  width: 13px;
  height: 13px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: sync-spin 0.8s linear infinite;
}

.sync-pop__state-block { padding: 8px 0 2px; }

.sync-pop__state-title {
  margin-bottom: 3px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--fg);
}

.sync-pop__state-text {
  font-size: 11px;
  line-height: 1.55;
  color: var(--fg-secondary);
}

.sync-pop__error {
  max-height: 46px;
  margin-top: 6px;
  overflow: auto;
  font-size: 10.5px;
  line-height: 1.45;
  color: var(--muted);
  word-break: break-word;
}

.sync-pop__ok {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 0 2px;
}

.sync-pop__ok-icon {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(34, 197, 94, 0.16);
  color: var(--success);
}

.sync-pop__ok-icon svg { width: 14px; height: 14px; }

.sync-pop__ok-title {
  font-size: 12.5px;
  font-weight: 600;
}

.sync-pop__ok-sub {
  margin-top: 1px;
  font-size: 10.5px;
  color: var(--muted);
}

.sync-pop__rows { padding-top: 2px; }

.sync-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 7px 0;
}

.sync-row + .sync-row { border-top: 1px solid var(--border-hair); }

.sync-row__icon {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
}

.sync-row__icon svg { width: 14px; height: 14px; }

.sync-row__icon--down {
  background: rgba(59, 130, 246, 0.14);
  color: var(--primary);
}

.sync-row__icon--up {
  background: rgba(245, 158, 11, 0.15);
  color: var(--warning);
}

.sync-row__text { min-width: 0; }

.sync-row__title {
  font-size: 12px;
  line-height: 1.4;
  color: var(--fg);
}

.sync-row__title b { font-weight: 700; }
.sync-row__title b.is-primary { color: var(--primary); }
.sync-row__title b.is-warn { color: var(--warning-text); }

.sync-row__sub {
  margin-top: 1px;
  font-size: 10.5px;
  line-height: 1.35;
  color: var(--muted);
}

.sync-pop__foot {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px solid var(--border-hair);
  font-size: 10.5px;
  color: var(--muted);
}

.sync-pop__foot-warn { color: var(--warning-text); }

.sync-pop-enter-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.sync-pop-leave-active {
  transition: opacity 0.1s ease, transform 0.1s ease;
}

.sync-pop-enter-from,
.sync-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}

@keyframes sync-ring-spin {
  to { transform: rotate(360deg); }
}

@keyframes sync-spin {
  to { transform: rotate(360deg); }
}

@keyframes sync-pulse {
  0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.45); }
  70% { box-shadow: 0 0 0 6px rgba(59, 130, 246, 0); }
  100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
}

@keyframes sync-soft-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

@media (prefers-reduced-motion: reduce) {
  .sync-status.is-checking .sync-status__btn,
  .sync-ring__value--indeterminate,
  .sync-pop__pulse,
  .sync-pop__refresh.is-spinning svg,
  .sync-spinner {
    animation: none;
  }

  .sync-pop-enter-active,
  .sync-pop-leave-active,
  .sync-ring__value,
  .sync-pop__bar > i {
    transition: none;
  }
}
</style>
