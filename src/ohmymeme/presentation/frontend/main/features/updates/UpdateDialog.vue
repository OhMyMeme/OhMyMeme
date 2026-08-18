<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { api, renderMarkdown } from '../../shared/bridge'

const visible = ref(false)
const current = ref('')
const latest = ref('')
const url = ref('')
const notesHtml = ref('')

const phase = ref<'idle' | 'downloading' | 'done' | 'error'>('idle')
const progress = ref(0)
const errorMsg = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

function show(cur: string, latestVer: string, dlUrl: string, notes: string) {
  current.value = cur
  latest.value = latestVer
  url.value = dlUrl
  notesHtml.value = renderMarkdown(notes)
  phase.value = 'idle'
  progress.value = 0
  visible.value = true
}

function close() {
  visible.value = false
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function showToast(msg: string) {
  const el = document.getElementById('toast')
  if (!el) return
  el.textContent = msg
  el.classList.add('show')
  setTimeout(() => el.classList.remove('show'), 1600)
}

async function startDownload() {
  phase.value = 'downloading'
  progress.value = 0
  const ok = await api('start_download', url.value)
  if (!ok) { phase.value = 'error'; errorMsg.value = '启动下载失败'; return }

  pollTimer = setInterval(async () => {
    const s = await api('get_download_progress')
    if (!s) return
    progress.value = s.progress || 0
    if (s.status === 'downloading') {
      phase.value = 'downloading'
    } else if (s.status === 'done') {
      clearInterval(pollTimer); pollTimer = null
      phase.value = 'done'
      const r = await api('run_downloaded_installer')
      visible.value = false
      showToast(r ? '安装程序已启动，安装完成后将自动更新' : '启动安装程序失败')
    } else if (s.status === 'error') {
      clearInterval(pollTimer); pollTimer = null
      phase.value = 'error'
      errorMsg.value = s.error || '未知错误'
    }
  }, 500)
}

function retry() {
  phase.value = 'idle'
  startDownload()
}

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

defineExpose({ show })
</script>

<template>
  <div v-if="visible" class="upd-overlay" @click.self="close">
    <div class="upd-box" @keydown.esc.stop="close">
      <div class="upd-header">
        <h2>发现新版本</h2>
        <p class="upd-versions">当前版本: {{ current }}<br>最新版本: {{ latest }}</p>
      </div>

      <div v-if="notesHtml" class="upd-notes-wrap">
        <div class="upd-notes-label">更新内容</div>
        <div class="upd-notes" v-html="notesHtml"></div>
      </div>

      <!-- 下载进度 -->
      <div v-if="phase === 'downloading'" class="upd-progress">
        <div class="upd-progress-text">下载中 {{ progress }}%</div>
        <div class="upd-progress-bar-wrap">
          <div class="upd-progress-bar" :style="{ width: progress + '%' }"></div>
        </div>
      </div>
      <div v-if="phase === 'done'" class="upd-progress-text">下载完成，启动安装...</div>
      <div v-if="phase === 'error'" class="upd-error">
        下载失败: {{ errorMsg }}
        <button class="btn btn-primary" style="width:100%;margin-top:8px" @click="retry">重试</button>
      </div>

      <!-- 操作按钮 -->
      <div v-if="phase === 'idle'" class="upd-actions">
        <button class="btn btn-primary btn-block" @click="startDownload">更新</button>
        <button class="btn btn-secondary btn-block" @click="close">稍后提示</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.upd-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
  animation: fadeIn 0.15s ease;
}

.upd-box {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 24px 28px;
  width: 440px;
  max-height: 80vh;
  overflow-y: auto;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
}

.upd-header {
  margin-bottom: 16px;
}

.upd-header h2 {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 8px;
}

.upd-versions {
  font-size: 13px;
  color: var(--fg-secondary);
  line-height: 1.6;
}

.upd-notes-wrap {
  margin-bottom: 16px;
}

.upd-notes-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 6px;
}

.upd-notes {
  font-size: 12px;
  color: var(--fg-secondary);
  line-height: 1.7;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  max-height: 220px;
  overflow-y: auto;
  overflow-x: hidden;
}

.upd-notes :deep(.md-h) { margin: 8px 0 4px; font-size: 12.5px; font-weight: 600; color: var(--fg); }
.upd-notes :deep(.md-pre) { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 10px; margin: 6px 0; overflow-x: auto; }
.upd-notes :deep(.md-code) { background: var(--surface-2); border-radius: 3px; padding: 0 3px; font-size: 11px; color: var(--primary); }
.upd-notes :deep(.md-pre .md-code), .upd-notes :deep(.md-pre code) { background: transparent; color: var(--fg-secondary); padding: 0; }
.upd-notes :deep(.md-quote) { border-left: 3px solid var(--primary); padding-left: 10px; margin: 6px 0; color: var(--muted); }
.upd-notes :deep(.md-li) { margin-left: 16px; }
.upd-notes :deep(.md-link) { color: var(--primary); }
.upd-notes :deep(.md-hr) { border: none; border-top: 1px solid var(--border); margin: 8px 0; }
.upd-notes :deep(strong) { color: var(--fg); }

.upd-progress-text {
  font-size: 12px;
  color: var(--fg-secondary);
  margin-bottom: 4px;
  text-align: center;
}

.upd-progress-bar-wrap {
  width: 100%;
  height: 8px;
  background: var(--bg-elevated);
  border-radius: 4px;
  overflow: hidden;
}

.upd-progress-bar {
  width: 0%;
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s;
}

.upd-error {
  font-size: 12px;
  color: #ef4444;
  text-align: center;
}

.upd-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.btn-block {
  width: 100%;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
