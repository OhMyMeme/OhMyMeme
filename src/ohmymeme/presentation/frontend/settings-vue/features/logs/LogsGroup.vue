<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'

// 日志导出状态文案
const status = ref('')

// 导出本次运行至今的日志
async function exportLogs() {
  status.value = '正在导出...'
  const p = api('export_logs')
  const r = p && typeof p.then === 'function' ? await p : p
  if (!r || !r.ok) {
    status.value = '导出失败：' + ((r && r.error) || '未知错误')
    return
  }
  status.value = '已导出 ' + r.count + ' 条日志：' + r.path
  showToast('日志已导出')
}
</script>

<template>
  <div class="section">
    <div class="section-title">日志</div>
    <p style="font-size:11.5px;color:var(--muted);margin-bottom:10px;line-height:1.6">导出本次运行至今的 Debug 级日志，便于排查问题</p>
    <div style="display:flex;gap:8px">
      <button class="btn btn-secondary btn-sm btn-flex" @click="exportLogs">导出日志</button>
    </div>
    <div style="font-size:11.5px;color:var(--muted);margin-top:6px">{{ status }}</div>
  </div>
</template>
