<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NInput, NButton } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'

// 危险操作确认弹窗状态
const show = ref(false)
const target = ref<'local' | 'cloud' | ''>('')
const input1 = ref('')
const input2 = ref('')
const executing = ref(false)

// 弹窗标题（按目标区分本地/云端）
const title = computed(() => target.value === 'local' ? '删除本地所有表情包' : '删除云端所有表情包')

// 弹窗描述（按目标区分本地/云端）
const desc = computed(() => target.value === 'local'
  ? '将永久删除全部表情包文件、缩略图及元数据，此操作不可撤销。'
  : '将永久删除远端服务器上的全部表情包文件，本地文件不受影响。')

// 两个输入框都等于 confirm 才允许确认
const matched = computed(() => input1.value === 'confirm' && input2.value === 'confirm')

// 打开指定目标的确认弹窗
function showConfirm(t: 'local' | 'cloud') {
  target.value = t
  input1.value = ''
  input2.value = ''
  executing.value = false
  show.value = true
}

// 关闭弹窗并重置目标
function cancel() {
  show.value = false
  target.value = ''
}

// 执行删除操作并提示结果
async function exec() {
  if (!target.value) return
  executing.value = true
  const p = api('delete_all_' + target.value)
  const r = p && typeof p.then === 'function' ? await p : p
  executing.value = false
  cancel()
  if (r && r.ok) {
    showToast('操作已完成')
  } else {
    showToast('操作失败: ' + ((r && r.error) || '未知错误'))
  }
}
</script>

<template>
  <div class="section" style="border-color:var(--accent-muted)">
    <div class="section-title" style="color:var(--danger)">危险操作</div>
    <p style="font-size:11.5px;color:var(--muted);margin-bottom:12px;line-height:1.6">以下操作不可撤销，请谨慎使用</p>
    <div style="display:flex;gap:8px">
      <button class="btn btn-flex" style="border-color:var(--danger);color:var(--danger)" @click="showConfirm('local')">删除本地所有表情包</button>
      <button class="btn btn-flex" style="border-color:var(--danger);color:var(--danger)" @click="showConfirm('cloud')">删除云端所有表情包</button>
    </div>

    <NModal
      v-model:show="show"
      preset="card"
      :title="title"
      style="width:420px"
      :mask-closable="false"
    >
      <p style="font-size:13px;color:var(--fg-secondary);line-height:1.6;margin-bottom:12px">{{ desc }}</p>
      <p style="font-size:11.5px;color:var(--muted);margin-bottom:8px;line-height:1.6">请在下方两个输入框中输入 confirm 以确认</p>
      <div style="display:flex;flex-direction:column;gap:8px">
        <NInput v-model:value="input1" placeholder="输入 confirm" />
        <NInput v-model:value="input2" placeholder="再次输入 confirm" />
      </div>
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <NButton @click="cancel">取消</NButton>
          <NButton type="error" :disabled="!matched || executing" @click="exec">{{ executing ? '执行中...' : '确认执行' }}</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>
