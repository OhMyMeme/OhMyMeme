<script setup lang="ts">
import { ref } from 'vue'
import { NModal, NButton, NCheckbox, useMessage } from 'naive-ui'
import { api } from '../../shared/bridge'

const emit = defineEmits<{
  imported: []
  error: [msg: string]
}>()

const message = useMessage()

const visible = ref(false)
const pending = ref(false)
const makeGroup = ref(true)

function open() {
  visible.value = true
}

function close() {
  visible.value = false
}

// 遮罩点击等关闭统一走 close
function onShowChange(show: boolean) {
  if (!show) close()
}

function appendRejected(msg: string, count?: number) {
  return count ? msg + '，跳过 ' + count + ' 个超限文件' : msg
}

async function importLocal() {
  close()
  if (pending.value) return
  pending.value = true
  try {
    const result = await api('import_memes')
    if (result?.ok) {
      emit('imported')
      showToast(appendRejected(result.imported > 0 ? '导入完成' : '未导入文件', result.rejected))
    } else if (!result?.cancelled) {
      showToast('导入失败')
    }
  } finally {
    pending.value = false
  }
}

async function importFolder() {
  close()
  if (pending.value) return
  const makeGroupValue = makeGroup.value
  pending.value = true
  try {
    const r = await api('import_folder', makeGroupValue)
    if (!r) return
    if (!r.ok) {
      if (r.cancelled) return
      showToast(r.error || '导入失败')
      return
    }
    let msg = appendRejected(r.imported > 0 ? '导入完成，共 ' + r.imported + ' 个表情' : '未导入文件', r.rejected)
    if (r.collection_name) msg += '，已加入分组「' + r.collection_name + '」'
    emit('imported')
    showToast(msg)
  } finally {
    pending.value = false
  }
}

async function importClipboard() {
  close()
  if (pending.value) return
  pending.value = true
  try {
    const result = await api('import_from_clipboard')
    if (!result) { showToast('导入失败'); return }
    if (!result.ok) { showToast(result.error || '导入失败'); return }
    if (result.id > 0) {
      emit('imported')
      showToast(appendRejected('导入完成', result.rejected))
    } else {
      showToast(appendRejected('未导入文件', result.rejected))
    }
  } finally {
    pending.value = false
  }
}

function importQQ() {
  close()
  emit('imported')
  // 打开设置窗口（QQ 导入在设置页）
  api('open_settings')
}

function showToast(msg: string) {
  message.info(msg, { duration: 1600 })
}

defineExpose({ open, close })
</script>

<template>
  <NModal
    :show="visible"
    :close-on-esc="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
    @update:show="onShowChange"
  >
    <div
      class="import-box"
      role="dialog"
      aria-modal="true"
      aria-label="选择导入方式"
      @keydown.esc.stop="close"
    >
      <div class="import-title">选择导入方式</div>
      <NButton type="primary" block :disabled="pending" @click="importLocal">本地导入</NButton>
      <NButton type="primary" block :disabled="pending" @click="importFolder">导入文件夹</NButton>
      <NButton type="primary" block :disabled="pending" @click="importClipboard">从剪贴板导入</NButton>
      <NButton block @click="importQQ">从手机版 QQ 缓存获取</NButton>
      <div class="import-group-label">
        <NCheckbox v-model:checked="makeGroup">导入文件夹时自动创建分组</NCheckbox>
      </div>
      <NButton quaternary size="small" @click="close">取消</NButton>
    </div>
  </NModal>
</template>

<style scoped>
.import-box {
  background: var(--gray-2);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 280px;
  border: 1px solid var(--gray-6);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.import-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-12);
  margin-bottom: 6px;
}

.import-group-label {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 4px;
  font-size: 12px;
  color: var(--gray-11);
  user-select: none;
}
</style>
