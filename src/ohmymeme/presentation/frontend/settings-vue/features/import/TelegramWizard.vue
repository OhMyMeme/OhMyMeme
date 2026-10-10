<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { NModal, NCheckbox, NInput, NButton, NProgress } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast, settings } from '../../shared/store'
import { pluginProgressValue } from '../../shared/plugin-ui'

// 解包桥接返回值（api 可能返回 Promise 或同步值）
async function call(method: string, ...args: unknown[]): Promise<any> {
  return await api(method, ...args)
}

// 覆盖层显隐
const visible = ref(false)
// 阶段：config 配置 / progress 进度
const phase = ref<'config' | 'progress'>('config')
// tdata 目录
const tdata = ref('')
// 本地密码（瞬时操作密钥，仅用于本次导入，不进入设置）
const passcode = ref('')
// WebM 转 WebP
const convert = ref(true)
// 配置阶段状态文案
const status = ref('')
// 配置阶段状态色
const statusMode = ref<'' | 'ok' | 'error'>('')
// 进度标题
const progressTitle = ref('正在导入...')
// 进度说明
const progressMsg = ref('准备中')
// 进度百分比
const pct = ref(0)
// 剩余时间文案
const eta = ref('')
// 错误文案
const error = ref('')
// 重试选择 tdata 按钮显隐
const showRetry = ref(false)
// 开始按钮忙碌态
const busy = ref(false)
// 进度轮询定时器
let pollTimer: ReturnType<typeof setInterval> | null = null

// 停止轮询
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// 秒数格式化为中文时长
function formatDuration(sec: number): string {
  sec = Math.max(0, Math.round(sec || 0))
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m > 0) return m + '分' + (s > 0 ? s + '秒' : '')
  return s + '秒'
}

// 根据进度与耗时刷新剩余时间
function updateEta(s: any) {
  const prog = s.progress || 0
  const elapsed = s.elapsed_s || 0
  const terminal = ['done', 'error', 'cancelled'].includes(s.status)
  if (prog <= 0 || elapsed <= 0 || terminal) {
    eta.value = elapsed > 0 ? '已用 ' + formatDuration(elapsed) : ''
    return
  }
  const remain = (100 - prog) / prog * elapsed
  eta.value = '已用 ' + formatDuration(elapsed) + ' · 预计剩余 ' + formatDuration(remain)
}

// 打开配置阶段（tdata 目录从持久配置预填）
function open() {
  visible.value = true
  phase.value = 'config'
  error.value = ''
  status.value = ''
  statusMode.value = ''
  busy.value = false
  if (settings.tg_tdata_path) tdata.value = settings.tg_tdata_path
}

// 选择 tdata 目录
async function pickTdata() {
  const r = await call('pick_tg_tdata')
  if (!r || r.cancelled) return
  if (r.ok) { tdata.value = r.path; showToast('tdata 目录已设置') }
  else showToast((r && r.error) || '选择失败')
}

// 重新选择 tdata 目录并重开对话框
function retryPick() {
  close()
  pickTdata()
  open()
}

// 切换到进度阶段
function showProgress() {
  phase.value = 'progress'
  error.value = ''
  showRetry.value = false
  progressTitle.value = '正在导入...'
  progressMsg.value = '准备中'
  pct.value = 0
  eta.value = ''
}

// 开始导入并轮询进度
async function startImport() {
  busy.value = true
  status.value = ''
  statusMode.value = ''

  let r: any
  try {
    r = await call('start_tg_import', tdata.value || null, passcode.value, convert.value)
  } catch (e: any) {
    busy.value = false
    status.value = '启动失败: ' + (e.message || e)
    statusMode.value = 'error'
    return
  }
  if (!r || !r.ok) {
    busy.value = false
    status.value = '启动失败'
    statusMode.value = 'error'
    return
  }

  showProgress()

  let nullCount = 0
  let pollInFlight = false
  pollTimer = setInterval(async () => {
    if (pollInFlight) return
    pollInFlight = true
    try {
      const s = await call('get_tg_import_progress')
      if (!s) {
        nullCount++
        if (nullCount > 20) {
          stopPoll()
          progressTitle.value = '导入失败'
          error.value = '连接中断'
          busy.value = false
        }
        return
      }
      nullCount = 0

      pct.value = Number(pluginProgressValue('get_tg_import_progress', s, 'progress') ?? 0)
      progressMsg.value = String(pluginProgressValue('get_tg_import_progress', s, 'message') ?? '')
      updateEta(s)

      if (s.status === 'done') {
        progressTitle.value = '导入完成'
        stopPoll()
        status.value = s.message || '导入完成'
        statusMode.value = ''
        passcode.value = ''
        busy.value = false
      } else if (s.status === 'error') {
        progressTitle.value = '导入失败'
        stopPoll()
        let errMsg = s.error || '未知错误'
        if (s.error_code === 'no_ffmpeg') {
          errMsg += '；安装 ffmpeg 后可重试，或取消勾选「WebM 转 WebP」直接导入静态贴纸'
        }
        status.value = '导入失败: ' + errMsg
        statusMode.value = 'error'
        error.value = errMsg
        if (['no_tdata', 'invalid_tdata', 'no_cache'].includes(s.error_code)) showRetry.value = true
        busy.value = false
      } else if (s.status === 'cancelled') {
        progressTitle.value = '已取消'
        stopPoll()
        busy.value = false
      }
    } catch (e: any) {
      stopPoll()
      progressTitle.value = '导入失败'
      error.value = e.message || '连接异常'
      busy.value = false
    } finally {
      pollInFlight = false
    }
  }, 300)
}

// 关闭覆盖层并取消导入
function close() {
  visible.value = false
  stopPoll()
  call('cancel_tg_import')
}

// 模态层被 Esc 关闭时同步取消
function onUpdateShow(v: boolean) {
  if (!v) close()
}

onUnmounted(stopPoll)

defineExpose({ open })
</script>

<template>
  <NModal :show="visible" :mask-closable="false" :closable="false" @update:show="onUpdateShow">
    <div style="background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:440px;border:1px solid var(--border);box-shadow:var(--shadow-lg)">
      <div v-show="phase === 'config'">
        <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:4px">从 Telegram Desktop 导入</div>
        <div style="font-size:12px;color:var(--muted);margin-bottom:12px;line-height:1.6">从 Telegram Desktop 本地缓存解密提取表情包（WebP 直取，WebM 无损转 WebP 并保留透明通道）</div>
        <div class="form-group">
          <label>tdata 目录</label>
          <NInput readonly placeholder="未设置，将自动检测" :value="tdata" :input-props="{ id: 's-tg-tdata' }" />
        </div>
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <NButton size="small" style="flex:1" @click="pickTdata">手动指定 tdata 目录</NButton>
        </div>
        <div class="form-group" style="margin-bottom:10px">
          <label>本地密码（可选）</label>
          <NInput type="password" placeholder="Telegram Desktop 设置了本地密码时填写" :value="passcode" :input-props="{ id: 's-tg-passcode', autocomplete: 'off' }" @update:value="(v) => passcode = v" />
        </div>
        <div class="check-row" style="margin-bottom:12px">
          <NCheckbox :checked="convert" @update:checked="(v) => convert = v">WebM 转 WebP（保留透明动画，需 ffmpeg）</NCheckbox>
        </div>
        <div class="s-net-status" :class="{ 'status-ok': statusMode === 'ok', 'status-error': statusMode === 'error' }" style="font-size:11.5px;color:var(--muted);margin-bottom:10px;word-break:break-all;line-height:1.6">{{ status }}</div>
        <div style="display:flex;gap:8px">
          <NButton size="small" type="primary" style="flex:1" :loading="busy" @click="startImport">开始导入</NButton>
          <NButton size="small" @click="close">取消</NButton>
        </div>
      </div>
      <div v-show="phase === 'progress'" style="text-align:center">
        <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:4px">{{ progressTitle }}</div>
        <div style="font-size:12px;color:var(--fg-secondary);margin-bottom:12px;word-break:break-all">{{ progressMsg }}</div>
        <NProgress type="line" :percentage="pct" :show-indicator="false" :height="8" />
        <div style="font-size:11.5px;color:var(--muted);margin-top:6px;margin-bottom:16px">
          <span>{{ pct }}%</span>
          <span style="margin-left:8px">{{ eta }}</span>
        </div>
        <NButton v-if="showRetry" size="small" @click="retryPick">手动选择 tdata 目录</NButton>
        <NButton size="small" @click="close">关闭</NButton>
        <div v-if="error" style="font-size:12px;color:var(--danger);margin-top:8px;word-break:break-all">{{ error }}</div>
      </div>
    </div>
  </NModal>
</template>
