<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { NModal, NInput, NButton, NProgress } from 'naive-ui'
import { api } from '../../shared/bridge'
import { pluginProgressValue } from '../../shared/plugin-ui'

// 解包桥接返回值（api 可能返回 Promise 或同步值）
async function call(method: string, ...args: unknown[]): Promise<any> {
  return await api(method, ...args)
}

// 覆盖层显隐
const visible = ref(false)
// 阶段：config 配置 / progress 进度
const phase = ref<'config' | 'progress'>('config')
// 抖音 Cookie（瞬时操作密钥，仅用于本次下载，不进入设置）
const cookie = ref('')
// 配置阶段状态文案
const status = ref('')
// 配置阶段状态色
const statusMode = ref<'' | 'ok' | 'error'>('')
// 进度标题
const progressTitle = ref('正在下载...')
// 进度说明
const progressMsg = ref('准备中')
// 进度百分比
const pct = ref(0)
// 错误文案
const error = ref('')
// 开始按钮忙碌态
const busy = ref(false)
// 进度轮询定时器
let pollTimer: ReturnType<typeof setInterval> | null = null

// 停止轮询
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// 打开配置阶段
function open() {
  visible.value = true
  phase.value = 'config'
  error.value = ''
  status.value = ''
  statusMode.value = ''
  busy.value = false
}

// 切换到进度阶段
function showProgress() {
  phase.value = 'progress'
  error.value = ''
  progressTitle.value = '正在下载...'
  progressMsg.value = '准备中'
  pct.value = 0
}

// 开始下载并轮询进度
async function startImport() {
  busy.value = true
  status.value = ''
  statusMode.value = ''

  const c = (cookie.value || '').trim()
  if (!c) {
    busy.value = false
    status.value = '请先填写抖音 Cookie'
    statusMode.value = 'error'
    return
  }

  let r: any
  try {
    r = await call('start_douyin_import', c)
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
      const s = await call('get_douyin_import_progress')
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

      pct.value = Number(pluginProgressValue('get_douyin_import_progress', s, 'progress') ?? 0)
      progressMsg.value = String(pluginProgressValue('get_douyin_import_progress', s, 'message') ?? '')

      if (s.status === 'done') {
        progressTitle.value = '导入完成'
        stopPoll()
        status.value = s.message || '导入完成'
        statusMode.value = ''
        cookie.value = ''
        busy.value = false
      } else if (s.status === 'error') {
        progressTitle.value = '导入失败'
        stopPoll()
        let hint = s.error || '未知错误'
        if (s.error_code === 'login_failed') {
          hint += '；请从浏览器抖音网页版重新复制 Cookie 后重试'
        } else if (s.error_code === 'sign_failed') {
          hint += '；请稍后重试，或更新 Cookie 后再试'
        } else if (s.error_code === 'no_stickers') {
          hint += '；请确认抖音收藏的自定义表情包存在'
        }
        status.value = '导入失败: ' + hint
        statusMode.value = 'error'
        error.value = hint
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

// 关闭覆盖层并取消下载
function close() {
  visible.value = false
  stopPoll()
  call('cancel_douyin_import')
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
    <div style="background:var(--gray-2);border-radius:var(--radius-lg);padding:24px 28px;width:440px;border:1px solid var(--gray-6);box-shadow:var(--shadow-lg)">
      <div v-show="phase === 'config'">
        <div style="font-size:14px;font-weight:600;color:var(--gray-12);margin-bottom:4px">从抖音导入</div>
        <div style="font-size:12px;color:var(--gray-11);margin-bottom:12px;line-height:1.6">通过抖音网页版 API 下载自定义表情包（WebP 原格式保存，需登录 Cookie）</div>
        <div class="form-group">
          <label>抖音 Cookie</label>
          <NInput type="password" placeholder="粘贴抖音网页版 Cookie（sessionid=xxx; ...）" :value="cookie" :input-props="{ id: 's-dy-cookie', autocomplete: 'off' }" @update:value="(v) => cookie = v" />
        </div>
        <div class="s-net-status" :class="{ 'status-ok': statusMode === 'ok', 'status-error': statusMode === 'error' }" style="font-size:11.5px;color:var(--gray-11);margin-bottom:10px;word-break:break-all;line-height:1.6">{{ status }}</div>
        <div style="display:flex;gap:8px">
          <NButton size="small" type="primary" style="flex:1" :loading="busy" @click="startImport">开始下载</NButton>
          <NButton size="small" @click="close">取消</NButton>
        </div>
      </div>
      <div v-show="phase === 'progress'" style="text-align:center">
        <div style="font-size:14px;font-weight:600;color:var(--gray-12);margin-bottom:4px">{{ progressTitle }}</div>
        <div style="font-size:12px;color:var(--gray-11);margin-bottom:12px;word-break:break-all">{{ progressMsg }}</div>
        <NProgress type="line" :percentage="pct" :show-indicator="false" :height="8" />
        <div style="font-size:11.5px;color:var(--gray-11);margin-top:6px;margin-bottom:16px">
          <span>{{ pct }}%</span>
        </div>
        <NButton size="small" @click="close">关闭</NButton>
        <div v-if="error" style="font-size:12px;color:var(--red-11);margin-top:8px;word-break:break-all">{{ error }}</div>
      </div>
    </div>
  </NModal>
</template>
