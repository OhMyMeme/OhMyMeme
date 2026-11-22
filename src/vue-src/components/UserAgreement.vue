<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { api, rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'

const visible = ref(false)
const agreed = ref(false)
const boxEl = ref<HTMLElement>()
const checkboxEl = ref<HTMLInputElement>()

const AGREEMENT_URL = 'https://github.com/OhMyMeme/OhMyMeme/blob/dev/docs/user_agreement.md'
const PRIVACY_URL = 'https://github.com/OhMyMeme/OhMyMeme/blob/dev/docs/privacy.md'

async function show() {
  agreed.value = false
  rememberFocus()
  visible.value = true
  await nextTick()
  checkboxEl.value?.focus()
}

function openDoc(url: string) {
  api('open_url', url)
}

// 阻塞式弹窗：无 ×/ESC/遮罩关闭，勾选后「开始使用」写入同意标记
async function start() {
  if (!agreed.value) return
  try {
    await api('accept_agreement')
  } catch (_) {}
  visible.value = false
  restoreFocus()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Tab' && boxEl.value) {
    trapTabFocus(boxEl.value, e)
  }
}

defineExpose({ show })
</script>

<template>
  <div v-if="visible" class="agreement-overlay">
    <div
      ref="boxEl" class="agreement-box" role="dialog" aria-modal="true" aria-label="用户协议与隐私策略"
      @keydown="onKeydown"
    >
      <div class="agreement-title">欢迎使用 OhMyMeme</div>
      <p class="agreement-p">
        开始使用前，请仔细阅读
        <a href="#" class="agreement-link" @click.prevent="openDoc(AGREEMENT_URL)">《用户协议》</a>与
        <a href="#" class="agreement-link" @click.prevent="openDoc(PRIVACY_URL)">《隐私策略》</a>。
      </p>
      <label class="agreement-check">
        <input ref="checkboxEl" v-model="agreed" type="checkbox">我已阅读
        <a href="#" class="agreement-link" @click.prevent.stop="openDoc(AGREEMENT_URL)">《用户协议》</a>与
        <a href="#" class="agreement-link" @click.prevent.stop="openDoc(PRIVACY_URL)">《隐私策略》</a>
      </label>
      <div class="agreement-footer">
        <button class="btn btn-primary" :disabled="!agreed" @click="start">开始使用</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agreement-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 400;
  animation: fadeIn 0.15s ease;
}

.agreement-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 440px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
  padding: 20px;
}

.agreement-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 12px;
}

.agreement-p {
  font-size: 13px;
  color: var(--fg-secondary);
  line-height: 1.6;
  margin-bottom: 14px;
}

.agreement-link {
  color: var(--primary);
  cursor: pointer;
  text-decoration: none;
}

.agreement-link:hover {
  text-decoration: underline;
}

.agreement-check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--fg);
  cursor: pointer;
  user-select: none;
  padding: 4px 0 14px;
  line-height: 1.6;
}

.agreement-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
