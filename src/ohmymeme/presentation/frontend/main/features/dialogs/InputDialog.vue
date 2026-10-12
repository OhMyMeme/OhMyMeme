<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { NModal, NInput, NButton } from 'naive-ui'

const visible = ref(false)
const title = ref('')
const value = ref('')
const placeholder = ref('')
const inputRef = ref<InstanceType<typeof NInput> | null>(null)

let resolveFn: ((v: string | null) => void) | null = null

// 打开对话框：记录初值后显示，返回 Promise 供调用方 await
function open(t: string, initial: string = '', ph: string = ''): Promise<string | null> {
  // 若上一个对话框尚未关闭，先结算其 Promise，避免旧调用方永久阻塞
  if (resolveFn) { resolveFn(null); resolveFn = null }
  title.value = t
  value.value = initial
  placeholder.value = ph
  visible.value = true
  // 已在可见状态重复打开时 after-enter 不再触发，这里补一次聚焦
  nextTick(focusInput)
  return new Promise(resolve => { resolveFn = resolve })
}

// 关闭并结算 Promise：确定传 trim 后的值，取消/Esc/遮罩传 null
function close(v: string | null) {
  visible.value = false
  if (resolveFn) { resolveFn(v); resolveFn = null }
}

function confirm() {
  close(value.value.trim())
}

function focusInput() {
  inputRef.value?.focus()
  inputRef.value?.select()
}

// NModal 出现后聚焦并选中输入框
function onAfterEnter() {
  focusInput()
}

// NModal 遮罩点击等关闭统一按取消处理
function onShowChange(show: boolean) {
  if (!show) close(null)
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
      class="input-dialog-box"
      role="dialog"
      aria-modal="true"
      aria-labelledby="input-dialog-title"
      @keydown.enter.prevent="confirm"
      @keydown.esc.stop="close(null)"
    >
      <div id="input-dialog-title" class="input-dialog-title">{{ title }}</div>
      <NInput
        ref="inputRef"
        v-model:value="value"
        class="input-dialog-input"
        type="text"
        :placeholder="placeholder"
        :input-props="{ autocomplete: 'off', spellcheck: 'false' }"
      />
      <div class="input-dialog-actions">
        <NButton @click="close(null)">取消</NButton>
        <NButton type="primary" :disabled="!value.trim()" @click="confirm">确定</NButton>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.input-dialog-box {
  background: var(--gray-2);
  border: 1px solid var(--gray-6);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 360px;
  box-shadow: var(--shadow-lg);
}

.input-dialog-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-12);
  margin-bottom: 14px;
}

.input-dialog-input {
  margin-bottom: 16px;
}

.input-dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
