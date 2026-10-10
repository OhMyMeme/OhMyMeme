<script setup lang="ts">
import { ref } from 'vue'
import { NButton } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'

// 日志导出状态文案
const status = ref('')

// 导出本次运行至今的日志
async function exportLogs() {
  status.value = '正在导出...'
  const r = await api('export_logs')
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
      <NButton size="small" style="flex:1" @click="exportLogs">导出日志</NButton>
    </div>
    <div id="log-export-status" style="font-size:11.5px;color:var(--muted);margin-top:6px">{{ status }}</div>
  </div>
</template>
