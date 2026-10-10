<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { NModal, NButton, NProgress } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'

// 解包桥接返回值（api 可能返回 Promise 或同步值）
async function call(method: string, ...args: unknown[]): Promise<any> {
  return await api(method, ...args)
}

// 覆盖层显隐
const visible = ref(false)
// 标题文案
const title = ref('正在导入...')
// 说明文案
const message = ref('准备中')
// 进度百分比
const pct = ref(0)
// 百分比显示文案
const pctText = ref('0%')
// 进度条显隐
const showBar = ref(true)
// 保存按钮显隐
const showSave = ref(false)
// 保存后区域显隐
const showAfterSave = ref(false)
// 帮助按钮显隐
const showHelp = ref(false)
// 错误文案
const error = ref('')
// 保存按钮忙碌态
const saveBusy = ref(false)
// 导入按钮忙碌态
const importBusy = ref(false)
// 进度轮询定时器
let pollTimer: ReturnType<typeof setInterval> | null = null

// 停止轮询
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

// 关闭覆盖层并取消导入
function close() {
  visible.value = false
  stopPoll()
  call('cancel_qq_import')
}

// 打开覆盖层并开始导入
async function open() {
  visible.value = true
  showSave.value = false
  showAfterSave.value = false
  showHelp.value = false
  error.value = ''
  title.value = '正在导入...'
  message.value = '准备中'
  pct.value = 0
  pctText.value = '0%'
  showBar.value = true

  const r = await call('start_qq_import')
  if (!r || !r.ok) {
    title.value = '启动失败'
    error.value = (r && r.error) || '未知错误'
    return
  }

  pollTimer = setInterval(async () => {
    const s = await call('get_qq_import_progress')
    if (!s) return

    const p = s.progress || 0
    pct.value = p
    pctText.value = p + '%'
    message.value = s.message || ''

    if (s.status === 'downloading_adb') {
      title.value = '正在下载 ADB...'
      showHelp.value = false
      if (s.dl_progress > 0) pctText.value = '下载中 ' + s.dl_progress + '%'
    } else if (s.status === 'starting_adb') {
      title.value = '正在启动 ADB...'
      showHelp.value = false
    } else if (s.status === 'waiting_device') {
      title.value = '等待设备连接'
      showHelp.value = true
    } else if (s.status === 'pulling') {
      showHelp.value = false
      title.value = '正在拉取文件...'
    } else if (s.status === 'processing') {
      title.value = '正在处理文件...'
      showHelp.value = false
    } else if (s.status === 'done') {
      showHelp.value = false
      title.value = '导入完成'
      message.value = '共导出 ' + p + ' 个文件'
      showSave.value = true
      stopPoll()
    } else if (s.status === 'error') {
      showHelp.value = false
      stopPoll()
      title.value = '导入失败'
      error.value = s.error || '未知错误'
    }
  }, 300)
}

// 打开 ADB 帮助
function openADBHelp() {
  call('open_adb_help')
}

// 保存导出 ZIP
async function saveZip() {
  error.value = ''
  saveBusy.value = true
  const r = await call('save_qq_zip')
  saveBusy.value = false
  if (r && r.ok) {
    showSave.value = false
    title.value = '导入完成'
    message.value = 'ZIP 已保存到: ' + (r.path || '')
    pctText.value = ''
    showBar.value = false
    showAfterSave.value = true
  } else {
    error.value = (r && r.error) || '保存失败'
  }
}

// 从 ZIP 选择文件导入
async function importFromZip() {
  importBusy.value = true
  const r = await call('import_memes')
  importBusy.value = false
  if (r && r.ok) {
    close()
    showToast(r.rejected ? '导入完成，跳过 ' + r.rejected + ' 个超限文件' : '导入完成')
  }
}

// 模态层被 Esc 关闭时同步取消
function onUpdateShow(v: boolean) {
  if (!v) close()
}

onUnmounted(stopPoll)

defineExpose({ open })
</script>

<template>
  <NModal :show="visible" :mask-closable="false" :closable="false" @update:show="onUpdateShow">
    <div style="background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:400px;border:1px solid var(--border);box-shadow:var(--shadow-lg);text-align:center">
      <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:4px">{{ title }}</div>
      <div style="font-size:12px;color:var(--fg-secondary);margin-bottom:12px;word-break:break-all">{{ message }}</div>
      <NProgress v-if="showBar" type="line" :percentage="pct" :show-indicator="false" :height="8" />
      <div v-if="pctText !== ''" style="font-size:11.5px;color:var(--muted);margin-top:6px;margin-bottom:16px"><span>{{ pctText }}</span></div>
      <div v-else style="margin-bottom:16px"></div>
      <NButton v-if="showSave" type="primary" :loading="saveBusy" @click="saveZip">选择保存位置</NButton>
      <div v-if="showAfterSave" style="margin-top:8px">
        <p style="font-size:12px;color:var(--fg-secondary);margin-bottom:12px;line-height:1.6">请从 ZIP 中筛选需要的表情包，然后点击下方按钮导入</p>
        <NButton type="primary" style="width:100%" :loading="importBusy" @click="importFromZip">选择文件导入</NButton>
      </div>
      <NButton v-if="showHelp" quaternary size="small" @click="openADBHelp">不知道怎么办？</NButton>
      <NButton size="small" @click="close">关闭</NButton>
      <div v-if="error" style="font-size:12px;color:var(--danger);margin-top:8px">{{ error }}</div>
    </div>
  </NModal>
</template>
