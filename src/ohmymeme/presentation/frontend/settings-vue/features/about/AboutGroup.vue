<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { NModal, NButton, NProgress } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'
import { renderMarkdown } from '../../shared/markdown'

// 当前版本显示文案
const current = ref('--')
// 更新检查状态文案
const updateStatus = ref('')
// 更新检查按钮忙碌态
const checking = ref(false)
// 贡献者头像是否可显示
const contributorsOk = ref(true)

// 更新对话框状态
const showUpdate = ref(false)
const updateCurrent = ref('')
const latest = ref('')
const downloadUrl = ref('')
const notes = ref('')
// 更新流程阶段：idle 待更新 / preparing 准备下载 / downloading 下载中 / error 下载失败
const phase = ref<'idle' | 'preparing' | 'downloading' | 'error'>('idle')
const progress = ref(0)
const progressText = ref('')
let poll: ReturnType<typeof setInterval> | null = null

// 延迟等待轮询间隔
function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms))
}

// 拉取并显示当前版本号
async function loadVersion() {
  const ver = await api('get_current_version')
  current.value = ver || '--'
}

// 检查更新：首发强制检查，pending 时非 force 轮询直到拿到结果
async function checkUpdate() {
  checking.value = true
  updateStatus.value = ''
  let r = await api('check_update', false, true)
  while (r && r.pending) {
    await sleep(1500)
    r = await api('check_update', false, false)
  }
  checking.value = false
  if (!r) { updateStatus.value = '检查失败'; return }
  current.value = r.current || '--'
  if (r.error) { updateStatus.value = '检查失败: ' + r.error; return }
  if (!r.latest) { updateStatus.value = '暂无版本信息'; return }
  if (r.has_update) {
    openUpdate(r.current, r.latest, r.download_url, r.notes)
  } else {
    updateStatus.value = '已是最新版本 (' + r.latest + ')'
  }
}

// 打开更新对话框并重置下载状态
function openUpdate(cur: string, lat: string, url: string, updateNotes: string) {
  updateCurrent.value = cur || ''
  latest.value = lat || ''
  downloadUrl.value = url || ''
  notes.value = updateNotes || ''
  phase.value = 'idle'
  progress.value = 0
  progressText.value = ''
  if (poll) { clearInterval(poll); poll = null }
  showUpdate.value = true
}

// 开始下载并在完成后启动安装程序
async function startDownload() {
  phase.value = 'preparing'
  const ok = await api('start_download', downloadUrl.value)
  if (!ok) { phase.value = 'idle'; return }
  phase.value = 'downloading'
  progress.value = 0
  progressText.value = '下载中 0%'
  poll = setInterval(async () => {
    const s = await api('get_download_progress')
    if (!s) return
    const pct = s.progress || 0
    progress.value = pct
    if (s.status === 'downloading') {
      progressText.value = '下载中 ' + pct + '%'
    } else if (s.status === 'done') {
      if (poll) { clearInterval(poll); poll = null }
      progressText.value = '下载完成，启动安装...'
      const r = await api('run_downloaded_installer')
      showUpdate.value = false
      if (r) {
        showToast('安装程序已启动，安装完成后将自动更新')
      } else {
        showToast('启动安装程序失败')
      }
    } else if (s.status === 'error') {
      if (poll) { clearInterval(poll); poll = null }
      phase.value = 'error'
      progressText.value = '下载失败: ' + (s.error || '未知错误')
    }
  }, 500)
}

// 下载失败后重开对话框
function retry() {
  openUpdate(updateCurrent.value, latest.value, downloadUrl.value, notes.value)
}

onMounted(() => {
  loadVersion()
})
onUnmounted(() => {
  if (poll) { clearInterval(poll); poll = null }
})
</script>

<template>
  <div class="section">
    <div class="about-hero">
      <div class="about-logo">OhMy<span>Meme</span></div>
      <div class="about-desc">轻量跨平台表情包管理系统</div>
    </div>
    <div class="about-version-row">
      <span id="s-ver-current" class="about-version">当前版本: {{ current }}</span>
      <NButton size="small" :loading="checking" @click="checkUpdate">检查更新</NButton>
    </div>
    <div id="s-update-status" class="about-update-status">{{ updateStatus }}</div>
    <div class="section-title">贡献者</div>
    <div class="about-contributors">
      <img v-if="contributorsOk" id="contributors-img" :src="'/api/contributors'" loading="lazy" alt="项目贡献者" @error="contributorsOk = false">
    </div>
    <div v-if="!contributorsOk" id="contributors-fallback" style="font-size:11.5px;color:var(--muted)">贡献者名单加载失败</div>

    <NModal
      v-model:show="showUpdate"
      preset="card"
      title="发现新版本"
      style="width:440px"
      :mask-closable="false"
    >
      <p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">当前版本: {{ updateCurrent }}<br>最新版本: {{ latest }}</p>
      <div v-if="notes" style="margin-top:16px">
        <div style="font-size:13px;font-weight:600;color:var(--fg);margin-bottom:6px">更新内容</div>
        <div class="upd-notes" style="font-size:12px;color:var(--fg-secondary);line-height:1.7;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;max-height:220px;overflow-y:auto;overflow-x:hidden" v-html="renderMarkdown(notes)"></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;margin-top:16px">
        <NButton v-if="phase === 'idle'" type="primary" style="width:100%" @click="startDownload">更新</NButton>
        <NButton v-if="phase === 'preparing'" type="primary" style="width:100%" disabled>准备下载...</NButton>
        <div v-if="phase === 'downloading' || phase === 'error'" style="width:100%">
          <div style="font-size:12px;color:var(--fg-secondary);margin-bottom:4px;text-align:center">{{ progressText }}</div>
          <NProgress type="line" :percentage="progress" :show-indicator="false" :height="8" />
        </div>
        <NButton v-if="phase === 'error'" type="primary" style="width:100%" @click="retry">重试</NButton>
      </div>
      <template #footer>
        <NButton style="width:100%" @click="showUpdate = false">稍后提示</NButton>
      </template>
    </NModal>
  </div>
</template>
