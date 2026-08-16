<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../utils/api'

const emit = defineEmits<{
  imported: []
  error: [msg: string]
}>()

const visible = ref(false)
const pending = ref(false)

function open() {
  visible.value = true
}

function close() {
  visible.value = false
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
  const makeGroup = document.getElementById('import-folder-group')?.checked !== false
  pending.value = true
  try {
    const r = await api('import_folder', makeGroup)
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
  try {
    window.pywebview?.api?.open_settings()
  } catch (_) {}
}

function showToast(msg: string) {
  const el = document.getElementById('toast')
  if (!el) return
  el.textContent = msg
  el.classList.add('show')
  setTimeout(() => el.classList.remove('show'), 1600)
}

defineExpose({ open, close })
</script>

<template>
  <div v-if="visible" class="import-overlay" @click.self="close">
    <div class="import-box">
      <div class="import-title">选择导入方式</div>
      <button class="btn btn-primary btn-block" :disabled="pending" @click="importLocal">本地导入</button>
      <button class="btn btn-primary btn-block" :disabled="pending" @click="importFolder">导入文件夹</button>
      <button class="btn btn-primary btn-block" :disabled="pending" @click="importClipboard">从剪贴板导入</button>
      <button class="btn btn-secondary btn-block" @click="importQQ">从手机版 QQ 缓存获取</button>
      <label class="import-group-label">
        <input id="import-folder-group" type="checkbox" checked> 导入文件夹时自动创建分组
      </label>
      <button class="btn btn-ghost btn-sm" @click="close">取消</button>
    </div>
  </div>
</template>

<style scoped>
.import-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 400;
  animation: fadeIn 0.15s ease;
}

.import-box {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 280px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.import-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 6px;
}

.btn-block {
  width: 100%;
}

.import-group-label {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  margin-top: 4px;
  font-size: 12px;
  color: var(--fg-secondary);
  cursor: pointer;
  user-select: none;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
