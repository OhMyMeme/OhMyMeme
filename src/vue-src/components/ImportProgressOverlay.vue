<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../utils/api'

const emit = defineEmits<{
  imported: []
}>()

const visible = ref(false)
const pct = ref('0%')
const msg = ref('准备中...')
const current = ref('')
const done = ref(0)
const total = ref(0)
const finished = ref(false)
const finalMsg = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null

function showToast(msg: string) {
  const el = document.getElementById('toast')
  if (!el) return
  el.textContent = msg
  el.classList.add('show')
  setTimeout(() => el.classList.remove('show'), 1600)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function poll() {
  let s: any = null
  try { s = await api('get_import_progress') } catch (_) { s = null }
  if (!s) return
  pct.value = (s.progress || 0) + '%'
  done.value = s.done || 0
  total.value = s.total || 0
  if (s.current) current.value = '正在导入: ' + s.current
  if (!s.status || s.status === 'idle' || s.status === 'running') return
  // 终态
  stopPolling()
  finished.value = true
  if (s.status === 'done') {
    finalMsg.value = '导入完成，共导入 ' + (s.imported || 0) + ' 个表情'
    if (s.rejected) finalMsg.value += '，跳过 ' + s.rejected + ' 个超限文件'
    if (s.skipped_dup) finalMsg.value += '，' + s.skipped_dup + ' 个已存在（重复）'
    showToast('导入完成')
    emit('imported')
  } else if (s.status === 'cancelled') {
    finalMsg.value = '导入已取消'
    showToast('导入已取消')
  } else {
    finalMsg.value = '导入失败: ' + (s.error || '未知错误')
    showToast('导入失败')
  }
}

function start() {
  visible.value = true
  finished.value = false
  finalMsg.value = ''
  pct.value = '0%'
  msg.value = '准备中...'
  current.value = ''
  done.value = 0
  total.value = 0
  stopPolling()
  pollTimer = setInterval(poll, 300)
}

function cancel() {
  api('cancel_import_job').catch(() => {})
}

function background() {
  // 后台运行：隐藏覆盖层但继续导入（不停止轮询，仅收起 UI）
  if (finished.value) { visible.value = false; return }
  visible.value = false
}

function close() {
  visible.value = false
  stopPolling()
}

defineExpose({ start })
</script>

<template>
  <div v-if="visible" class="imp-overlay" @click.self="background">
    <div class="imp-box">
      <div class="imp-title">导入表情包</div>
      <div class="imp-file">{{ finished ? finalMsg : (current || msg) }}</div>
      <div class="imp-bar-wrap">
        <div class="imp-bar" :style="{ width: pct }"></div>
      </div>
      <div class="imp-meta">
        <span>{{ pct }}</span>
        <span v-if="!finished && total > 0" style="margin-left:12px">{{ done }} / {{ total }}</span>
      </div>
      <div class="imp-actions">
        <button v-if="!finished" class="btn btn-ghost btn-sm" @click="background">后台运行</button>
        <button v-if="!finished" class="btn btn-ghost btn-sm" @click="cancel">取消</button>
        <button v-if="finished" class="btn btn-primary btn-sm" @click="close">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.imp-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 510;
  animation: fadeIn 0.15s ease;
}

.imp-box {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 24px 28px;
  width: 400px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  text-align: center;
}

.imp-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 8px;
}

.imp-file {
  font-size: 12px;
  color: var(--fg-secondary);
  margin-bottom: 12px;
  word-break: break-all;
  min-height: 16px;
}

.imp-bar-wrap {
  width: 100%;
  height: 8px;
  background: var(--bg);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}

.imp-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s;
}

.imp-meta {
  font-size: 11.5px;
  color: var(--muted);
  margin-bottom: 14px;
}

.imp-actions {
  display: flex;
  gap: 8px;
  justify-content: center;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
