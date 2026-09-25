<script setup lang="ts">
import { ref, nextTick, onUnmounted } from 'vue'
import { api, rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'

const emit = defineEmits<{ openImportMenu: [] }>()

const visible = ref(false)
const step = ref(0)
const boxEl = ref<HTMLElement>()
const firstBtnEl = ref<HTMLButtonElement>()
const hkInputEl = ref<HTMLInputElement>()

const stepKeys = ['welcome', 'hotkey', 'autostart', 'gif', 'sync', 'import', 'done'] as const
type StepKey = (typeof stepKeys)[number]

const hotkey = ref('Ctrl+Alt+N')
const capturing = ref(false)
const autoStart = ref(false)
const autoPlayGif = ref(true)
const syncType = ref('')
const syncDirty = ref(false)
const saving = ref(false)

const syncOptions = [
  { value: '', label: '暂不使用' },
  { value: 'ftp', label: 'FTP' },
  { value: 's3', label: 'S3 / 阿里云 OSS' },
  { value: 'r2', label: 'Cloudflare R2' },
  { value: 'webdav', label: 'WebDAV' },
]

async function show() {
  step.value = 0
  syncDirty.value = false
  stopCapture()
  rememberFocus()
  visible.value = true
  await nextTick()
  firstBtnEl.value?.focus()
  try {
    const s = await api('get_settings')
    if (s) {
      hotkey.value = s.hotkey || 'Ctrl+Alt+N'
      autoStart.value = s.auto_start === true
      autoPlayGif.value = s.auto_play_gif !== false
      syncType.value = s.sync_type || ''
    }
  } catch (_) {}
}

// 关闭即视为完成（ESC/遮罩/×/完成按钮均写入 manifest 标记，下次启动不再弹出）
async function close() {
  stopCapture()
  visible.value = false
  restoreFocus()
  try {
    await api('complete_guide')
  } catch (_) {}
}

function finish() {
  close()
}

// 快捷键录制（与设置页 startHotkeyCapture 一致）
let captureHandler: ((e: KeyboardEvent) => void) | null = null

function startCapture() {
  if (captureHandler) return
  capturing.value = true
  hkInputEl.value?.focus()
  captureHandler = (e: KeyboardEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const parts: string[] = []
    if (e.ctrlKey) parts.push('Ctrl')
    if (e.altKey) parts.push('Alt')
    if (e.shiftKey) parts.push('Shift')
    if (e.metaKey) parts.push('Win')
    const k = e.key
    if (['Control', 'Alt', 'Shift', 'Meta'].includes(k)) return
    let mk = k
    if (mk === ' ') mk = 'Space'
    else if (mk.length === 1) mk = mk.toUpperCase()
    parts.push(mk)
    hotkey.value = parts.join('+')
    stopCapture()
  }
  document.addEventListener('keydown', captureHandler, true)
}

function stopCapture() {
  if (captureHandler) document.removeEventListener('keydown', captureHandler, true)
  captureHandler = null
  capturing.value = false
}

function onSyncChange() {
  syncDirty.value = true
}

async function saveCurrentStep() {
  const key: StepKey = stepKeys[step.value]
  if (key === 'hotkey' && hotkey.value) await api('save_settings', { hotkey: hotkey.value })
  else if (key === 'autostart') await api('save_settings', { auto_start: autoStart.value })
  else if (key === 'gif') await api('save_settings', { auto_play_gif: autoPlayGif.value })
  else if (key === 'sync' && syncDirty.value) await api('save_settings', { sync_type: syncType.value })
}

async function next() {
  stopCapture()
  if (step.value >= stepKeys.length - 1) return
  saving.value = true
  try {
    await saveCurrentStep()
  } finally {
    saving.value = false
  }
  if (stepKeys[step.value] === 'sync') syncDirty.value = false
  step.value++
  await nextTick()
}

function prev() {
  stopCapture()
  if (step.value > 0) step.value--
}

async function skipSync() {
  syncDirty.value = false
  await next()
}

function openImportMenu() {
  emit('openImportMenu')
}

async function openSettingsImport() {
  try {
    await window.pywebview?.api?.open_settings()
  } catch (_) {}
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    close()
  } else if (boxEl.value) {
    trapTabFocus(boxEl.value, e)
  }
}

onUnmounted(() => stopCapture())

defineExpose({ show, close })
</script>

<template>
  <div v-if="visible" class="guide-overlay" @click.self="close">
    <div
      ref="boxEl" class="guide-box" role="dialog" aria-modal="true" aria-label="设置向导"
      @keydown="onKeydown"
    >
      <div class="guide-header">
        <div class="guide-title">设置向导</div>
        <div class="guide-dots" aria-hidden="true">
          <span
            v-for="(k, i) in stepKeys" :key="k" class="guide-dot"
            :class="{ active: i === step, done: i < step }"
          ></span>
        </div>
        <span class="guide-step-no">{{ step + 1 }}/{{ stepKeys.length }}</span>
        <button class="guide-close" aria-label="关闭向导" @click="close">×</button>
      </div>

      <div class="guide-body">
        <!-- 欢迎 -->
        <template v-if="stepKeys[step] === 'welcome'">
          <h3 class="guide-h">欢迎使用 OhMyMeme</h3>
          <p class="guide-p">花一分钟完成基础设置，所有选项之后都可在设置页随时修改。</p>
          <ul class="guide-list">
            <li>设置全局快捷键，随时呼出窗口</li>
            <li>选择是否开机自启</li>
            <li>设置动图是否自动播放</li>
            <li>配置云端同步（可跳过）</li>
            <li>导入第一批表情包（可跳过）</li>
          </ul>
        </template>

        <!-- 快捷键 -->
        <template v-else-if="stepKeys[step] === 'hotkey'">
          <h3 class="guide-h">全局快捷键</h3>
          <p class="guide-p">按下快捷键即可呼出 / 隐藏 OhMyMeme。点击输入框后按下新的组合键即可修改。</p>
          <div class="guide-row">
            <input
              ref="hkInputEl" class="guide-hk" readonly
              :value="capturing ? '' : hotkey"
              :placeholder="capturing ? '按下快捷键…' : ''"
              aria-label="全局快捷键"
              @click="startCapture"
            >
            <button class="btn btn-secondary btn-sm" @click="startCapture">重新录制</button>
          </div>
        </template>

        <!-- 开机自启 -->
        <template v-else-if="stepKeys[step] === 'autostart'">
          <h3 class="guide-h">开机自启</h3>
          <p class="guide-p">是否在开机时自动启动 OhMyMeme（可随时在设置页修改）。</p>
          <label class="guide-check">
            <input v-model="autoStart" type="checkbox">开机自动启动 OhMyMeme
          </label>
        </template>

        <!-- 动图播放 -->
        <template v-else-if="stepKeys[step] === 'gif'">
          <h3 class="guide-h">动图自动播放</h3>
          <p class="guide-p">网格中的动图（GIF / 动画 WebP）是否自动播放。性能不足时可关闭，改为悬停播放。</p>
          <label class="guide-check">
            <input v-model="autoPlayGif" type="checkbox">动图自动播放
          </label>
        </template>

        <!-- 云端同步 -->
        <template v-else-if="stepKeys[step] === 'sync'">
          <h3 class="guide-h">云端同步</h3>
          <p class="guide-p">选择同步后端可在多设备间同步表情包。连接信息（地址 / 账号 / 密钥）可在设置页「联网」中详细配置，本步可跳过。</p>
          <div class="guide-radios">
            <label v-for="opt in syncOptions" :key="opt.value" class="guide-check">
              <input v-model="syncType" type="radio" name="guide-sync" :value="opt.value" @change="onSyncChange">
              {{ opt.label }}
            </label>
          </div>
        </template>

        <!-- 导入 -->
        <template v-else-if="stepKeys[step] === 'import'">
          <h3 class="guide-h">导入表情包</h3>
          <p class="guide-p">现在导入第一批表情包，之后也可随时通过标题栏「导入」按钮添加。</p>
          <div class="guide-actions-col">
            <button class="btn btn-primary btn-block" @click="openImportMenu">本地导入 / 文件夹 / QQ</button>
            <button class="btn btn-secondary btn-block" @click="openSettingsImport">QQ、微信、抖音等更多方式</button>
          </div>
        </template>

        <!-- 完成 -->
        <template v-else>
          <h3 class="guide-h">设置完成</h3>
          <p class="guide-p">一切就绪！点击「完成」开始使用。之后可随时在设置页找到「设置向导」重新运行。</p>
        </template>
      </div>

      <div class="guide-footer">
        <template v-if="stepKeys[step] === 'welcome'">
          <span class="guide-spacer"></span>
          <button ref="firstBtnEl" class="btn btn-primary" @click="next">开始设置</button>
        </template>
        <template v-else-if="stepKeys[step] === 'done'">
          <span class="guide-spacer"></span>
          <button ref="firstBtnEl" class="btn btn-primary" @click="finish">完成</button>
        </template>
        <template v-else-if="stepKeys[step] === 'import'">
          <button class="btn btn-ghost" @click="prev">上一步</button>
          <span class="guide-spacer"></span>
          <button class="btn btn-primary" :disabled="saving" @click="next">下一步</button>
        </template>
        <template v-else>
          <button class="btn btn-ghost" @click="prev">上一步</button>
          <span class="guide-spacer"></span>
          <button v-if="stepKeys[step] === 'sync'" class="btn btn-secondary" :disabled="saving" @click="skipSync">跳过</button>
          <button class="btn btn-primary" :disabled="saving" @click="next">下一步</button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.guide-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 350;
  animation: fadeIn 0.15s ease;
}

.guide-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 440px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
}

.guide-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 20px 0;
}

.guide-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
}

.guide-dots {
  display: flex;
  gap: 5px;
  margin-left: auto;
}

.guide-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border-light);
  transition: background 0.15s;
}

.guide-dot.active {
  background: var(--primary);
}

.guide-dot.done {
  background: var(--primary-light);
}

.guide-step-no {
  font-size: 12px;
  color: var(--muted);
}

.guide-close {
  border: none;
  background: transparent;
  color: var(--fg-secondary);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}

.guide-close:hover {
  background: var(--surface-2);
  color: var(--fg);
}

.guide-body {
  padding: 14px 20px 4px;
  overflow-y: auto;
}

.guide-h {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 8px;
}

.guide-p {
  font-size: 13px;
  color: var(--fg-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
}

.guide-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--fg-secondary);
  line-height: 1.9;
}

.guide-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.guide-hk {
  flex: 1;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--fg);
  font-size: 13px;
  padding: 8px 10px;
  text-align: center;
  cursor: pointer;
}

.guide-hk:focus {
  outline: none;
  border-color: var(--primary);
}

.guide-check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--fg);
  cursor: pointer;
  user-select: none;
  padding: 4px 0;
}

.guide-radios {
  display: flex;
  flex-direction: column;
}

.guide-actions-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.btn-block {
  width: 100%;
}

.guide-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px 18px;
  margin-top: 10px;
  border-top: 1px solid var(--border);
}

.guide-spacer {
  flex: 1;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
