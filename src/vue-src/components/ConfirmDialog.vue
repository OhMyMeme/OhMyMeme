<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'

interface ConfirmOptions {
  confirmText?: string
  cancelText?: string
  variant?: 'danger' | 'primary'
  focusConfirm?: boolean
}

const visible = ref(false)
const title = ref('')
const message = ref('')
const confirmText = ref('确定')
const cancelText = ref('取消')
const confirmClass = ref('btn btn-danger')
const boxEl = ref<HTMLElement>()
const confirmEl = ref<HTMLButtonElement>()
const cancelEl = ref<HTMLButtonElement>()

let resolveFn: ((v: boolean) => void) | null = null

async function open(t: string, msg: string, opts: ConfirmOptions = {}): Promise<boolean> {
  if (resolveFn) { resolveFn(false); resolveFn = null }
  title.value = t
  message.value = msg
  confirmText.value = opts.confirmText || '确定'
  cancelText.value = opts.cancelText || '取消'
  confirmClass.value = opts.variant === 'primary' ? 'btn btn-primary' : 'btn btn-danger'
  rememberFocus()
  visible.value = true
  await nextTick()
  // 默认聚焦「取消」，危险操作需显式点「确定」
  if (opts.focusConfirm) confirmEl.value?.focus()
  else cancelEl.value?.focus()
  return new Promise(resolve => { resolveFn = resolve })
}

function close(v: boolean) {
  visible.value = false
  restoreFocus()
  if (resolveFn) { resolveFn(v); resolveFn = null }
}

function onKeydown(e: KeyboardEvent) {
  // 危险操作不响应 Enter 自动确认，避免误触；Escape 取消；Tab 循环
  if (e.key === 'Escape') { e.stopPropagation(); close(false) }
  else if (boxEl.value) trapTabFocus(boxEl.value, e)
}

defineExpose({ open })
</script>

<template>
  <div v-if="visible" class="confirm-dialog-overlay" @click.self="close(false)">
    <div class="confirm-dialog-box" ref="boxEl" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-message" @keydown="onKeydown">
      <div id="confirm-dialog-title" class="confirm-dialog-title">{{ title }}</div>
      <div id="confirm-dialog-message" class="confirm-dialog-message">{{ message }}</div>
      <div class="confirm-dialog-actions">
        <button ref="confirmEl" :class="confirmClass" @click="close(true)">{{ confirmText }}</button>
        <button ref="cancelEl" class="btn btn-secondary" @click="close(false)">{{ cancelText }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.confirm-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 260;
  animation: fadeIn 0.15s ease;
}

.confirm-dialog-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 360px;
  box-shadow: var(--shadow-lg);
}

.confirm-dialog-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 8px;
}

.confirm-dialog-message {
  font-size: 13px;
  color: var(--fg-secondary);
  line-height: 1.6;
  margin-bottom: 16px;
}

.confirm-dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
