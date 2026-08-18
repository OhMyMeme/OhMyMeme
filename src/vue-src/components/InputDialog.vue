<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'

const visible = ref(false)
const title = ref('')
const value = ref('')
const placeholder = ref('')
const inputEl = ref<HTMLInputElement>()
const boxEl = ref<HTMLElement>()

let resolveFn: ((v: string | null) => void) | null = null

async function open(t: string, initial: string = '', ph: string = ''): Promise<string | null> {
  // 若上一个对话框尚未关闭，先结算其 Promise，避免旧调用方永久阻塞
  if (resolveFn) { resolveFn(null); resolveFn = null }
  title.value = t
  value.value = initial
  placeholder.value = ph
  rememberFocus()
  visible.value = true
  await nextTick()
  inputEl.value?.focus()
  inputEl.value?.select()
  return new Promise(resolve => { resolveFn = resolve })
}

function close(v: string | null) {
  visible.value = false
  restoreFocus()
  if (resolveFn) { resolveFn(v); resolveFn = null }
}

function confirm() {
  close(value.value.trim())
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') { e.preventDefault(); confirm() }
  else if (e.key === 'Escape') { e.stopPropagation(); close(null) }
  else if (boxEl.value) trapTabFocus(boxEl.value, e)
}

defineExpose({ open })
</script>

<template>
  <div v-if="visible" class="input-dialog-overlay" @click.self="close(null)">
    <div class="input-dialog-box" ref="boxEl" role="dialog" aria-modal="true" aria-labelledby="input-dialog-title" @keydown="onKeydown">
      <div id="input-dialog-title" class="input-dialog-title">{{ title }}</div>
      <input
        id="input-dialog-input"
        ref="inputEl"
        v-model="value"
        class="input-dialog-input"
        type="text"
        :placeholder="placeholder"
        autocomplete="off"
        spellcheck="false"
      >
      <div class="input-dialog-actions">
        <button class="btn btn-secondary" @click="close(null)">取消</button>
        <button class="btn btn-primary" :disabled="!value.trim()" @click="confirm">确定</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.input-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 250;
  animation: fadeIn 0.15s ease;
}

.input-dialog-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 360px;
  box-shadow: var(--shadow-lg);
}

.input-dialog-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 14px;
}

.input-dialog-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--fg);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  margin-bottom: 16px;
  transition: border-color 0.15s;
}

.input-dialog-input:focus {
  border-color: var(--primary);
}

.input-dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
