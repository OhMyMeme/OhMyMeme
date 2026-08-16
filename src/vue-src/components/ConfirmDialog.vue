<script setup lang="ts">
import { ref, nextTick } from 'vue'

const visible = ref(false)
const title = ref('')
const message = ref('')
const confirmEl = ref<HTMLButtonElement>()

let resolveFn: ((v: boolean) => void) | null = null

async function open(t: string, msg: string): Promise<boolean> {
  if (resolveFn) { resolveFn(false); resolveFn = null }
  title.value = t
  message.value = msg
  visible.value = true
  await nextTick()
  confirmEl.value?.focus()
  return new Promise(resolve => { resolveFn = resolve })
}

function close(v: boolean) {
  visible.value = false
  if (resolveFn) { resolveFn(v); resolveFn = null }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') { e.preventDefault(); close(true) }
  else if (e.key === 'Escape') { e.stopPropagation(); close(false) }
}

defineExpose({ open })
</script>

<template>
  <div v-if="visible" class="confirm-dialog-overlay" @click.self="close(false)">
    <div class="confirm-dialog-box" @keydown="onKeydown">
      <div class="confirm-dialog-title">{{ title }}</div>
      <div class="confirm-dialog-message">{{ message }}</div>
      <div class="confirm-dialog-actions">
        <button ref="confirmEl" class="btn btn-danger" @click="close(true)">确定</button>
        <button class="btn btn-secondary" @click="close(false)">取消</button>
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
