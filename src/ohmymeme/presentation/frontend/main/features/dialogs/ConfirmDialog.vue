<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { NModal, NButton } from 'naive-ui'

const visible = ref(false)
const title = ref('')
const message = ref('')
const boxEl = ref<HTMLElement | null>(null)

let resolveFn: ((v: boolean) => void) | null = null

// 打开确认框并返回用户选择
function open(t: string, msg: string): Promise<boolean> {
  if (resolveFn) { resolveFn(false); resolveFn = null }
  title.value = t
  message.value = msg
  visible.value = true
  // 已在可见状态重复打开时 after-enter 不再触发，这里补一次聚焦
  nextTick(focusCancel)
  return new Promise(resolve => { resolveFn = resolve })
}

// 关闭并结算 Promise：确定 true，取消/Esc/遮罩 false
function close(v: boolean) {
  visible.value = false
  if (resolveFn) { resolveFn(v); resolveFn = null }
}

function focusCancel() {
  boxEl.value?.querySelector<HTMLButtonElement>('.confirm-dialog-cancel')?.focus()
}

// NModal 出现后默认聚焦「取消」，危险操作需显式点「确定」（不响应 Enter 自动确认）
function onAfterEnter() {
  focusCancel()
}

// NModal 遮罩点击等关闭统一按取消处理
function onShowChange(show: boolean) {
  if (!show) close(false)
}

defineExpose({ open })
</script>

<template>
  <NModal
    :show="visible"
    :close-on-esc="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
    @update:show="onShowChange"
    @after-enter="onAfterEnter"
  >
    <div
      ref="boxEl"
      class="confirm-dialog-box"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-message"
      @keydown.esc.stop="close(false)"
    >
      <div id="confirm-dialog-title" class="confirm-dialog-title">{{ title }}</div>
      <div id="confirm-dialog-message" class="confirm-dialog-message">{{ message }}</div>
      <div class="confirm-dialog-actions">
        <NButton type="error" @click="close(true)">确定</NButton>
        <NButton class="confirm-dialog-cancel" @click="close(false)">取消</NButton>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.confirm-dialog-box {
  background: var(--gray-2);
  border: 1px solid var(--gray-6);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 360px;
  box-shadow: var(--shadow-lg);
}

.confirm-dialog-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-12);
  margin-bottom: 8px;
}

.confirm-dialog-message {
  font-size: 13px;
  color: var(--gray-11);
  line-height: 1.6;
  margin-bottom: 16px;
}

.confirm-dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
