<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { NModal, NButton, NProgress, useDialog } from 'naive-ui'
import { api } from '../../shared/bridge'
import { showToast } from '../../shared/store'

const dialog = useDialog()

// 备份目录显示路径
const directory = ref('')
// 备份目录是否为自定义
const custom = ref(false)
// 备份文件列表
const backups = ref<any[]>([])
// 恢复提示文案
const restoreStatus = ref('')
// 进度弹窗显隐
const showProgress = ref(false)
// 进度弹窗标题
const progressTitle = ref('')
// 进度说明文案
const progressText = ref('')
// 进度百分比
const progress = ref(0)
// 备份/恢复任务是否进行中
const backupRunning = ref(false)
// 进度轮询定时器
let pollTimer: ReturnType<typeof setInterval> | null = null

// 格式化文件大小
function formatSize(v: number): string {
  if (!v) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(v >= 100 ? 0 : 1) + ' ' + units[i]
}

// 弹出确认框并返回用户是否确定
async function showConfirm(title: string, content: string): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    dialog.warning({
      title,
      content,
      positiveText: '确定',
      negativeText: '取消',
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false),
      onMaskClick: () => resolve(false),
    })
  })
}

// 拉取备份目录与列表
async function loadBackupInfo() {
  const info = await api('backup_get_info')
  if (!info || !info.ok) return
  directory.value = info.directory
  custom.value = !!info.custom
  backups.value = info.backups || []
}

// 删除指定备份文件
async function delBackup(file: any) {
  if (!await showConfirm('删除备份', '确定删除 ' + file.name + '？')) return
  const r = await api('backup_delete', file.name)
  if (!r || !r.ok) { showToast((r && r.error) || '删除失败'); return }
  loadBackupInfo()
}

// 选择备份目录
async function pickBackupDir() {
  const r = await api('backup_pick_dir')
  if (!r || !r.ok) {
    if (!(r && r.cancelled)) showToast((r && r.error) || '选择备份目录失败')
    return
  }
  loadBackupInfo()
}

// 开始备份
async function startBackupCreate() {
  const r = await api('backup_create')
  if (!r || !r.ok) { showToast((r && r.error) || '无法开始备份'); return }
  showBackupProgress('备份中…')
}

// 从备份 ZIP 恢复（仅空库，后端落库前复核）
async function startBackupRestore() {
  const selected = await api('backup_pick_zip')
  if (!selected || !selected.ok) return
  if (!await showConfirm('恢复备份', '确定从此 ZIP 恢复？仅支持空库，恢复后保留标签、收藏和分组。')) return
  const r = await api('backup_restore', selected.path)
  if (!r || !r.ok) { showToast((r && r.error) || '无法开始恢复'); return }
  showBackupProgress('恢复中…')
}

// 显示进度弹窗并轮询进度
function showBackupProgress(title: string) {
  backupRunning.value = true
  progressTitle.value = title
  progressText.value = '准备中'
  progress.value = 0
  showProgress.value = true
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    const state = await api('backup_progress')
    if (!state) return
    progress.value = state.progress || 0
    if (!['done', 'error', 'cancelled'].includes(state.status)) return
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    backupRunning.value = false
    progressText.value = state.status === 'done' ? '操作完成' : (state.error || '操作已取消')
    loadBackupInfo()
    if (state.status === 'done') {
      api('refresh_memes'); api('refresh_tags'); api('refresh_collections')
    }
  }, 300)
}

// 关闭进度弹窗（运行中不可关闭）
function closeBackupProgress() {
  if (backupRunning.value) return
  showProgress.value = false
}

onMounted(() => {
  loadBackupInfo()
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="section">
    <div class="section-title">备份</div>
    <p style="font-size:11.5px;color:var(--gray-11);margin-bottom:10px;line-height:1.6">备份包含全部表情原图与数据库（标签、收藏、分组、排序随库保留），用于 PC 间迁移。不包含缩略图（恢复后自动重建）与应用设置。</p>
    <div style="font-size:11.5px;color:var(--gray-11);margin-bottom:8px;word-break:break-all">备份目录：<span id="backup-dir">{{ directory }}</span><span v-if="custom" class="immediate-hint" style="margin-left:6px">自定义</span></div>
    <div style="display:flex;gap:8px;margin-bottom:8px">
      <NButton size="small" style="flex:1" @click="pickBackupDir">选择备份目录</NButton>
      <NButton size="small" type="primary" style="flex:1" @click="startBackupCreate">立即备份</NButton>
    </div>
    <div class="section-title" style="margin-top:6px">备份列表</div>
    <div id="backup-list" style="display:flex;flex-direction:column;gap:6px">
      <div v-for="file in backups" :key="file.name" style="display:flex;gap:8px;align-items:center">
        <span style="flex:1;word-break:break-all;font-size:12px">{{ file.name }} · {{ formatSize(file.size) }}</span>
        <NButton size="small" type="error" tertiary @click="delBackup(file)">删除</NButton>
      </div>
      <span v-if="!backups.length">暂无备份</span>
    </div>
  </div>
  <div class="section">
    <div class="section-title">恢复</div>
    <p style="font-size:11.5px;color:var(--gray-11);margin-bottom:10px;line-height:1.6">从备份 ZIP 恢复到本机。<b style="color:var(--red-11)">仅允许在数据库为空时进行</b>（例如新设备首次使用），已有数据的库会被拒绝、不会覆盖。恢复完成后请重启应用。</p>
    <NButton size="small" style="flex:1" @click="startBackupRestore">从备份 ZIP 恢复…</NButton>
    <div id="backup-restore-status" style="font-size:11.5px;color:var(--gray-11);margin-top:6px">{{ restoreStatus }}</div>
  </div>

  <NModal
    v-model:show="showProgress"
    preset="card"
    :title="progressTitle"
    style="width:420px"
    :mask-closable="false"
    :closable="!backupRunning"
    :close-on-esc="!backupRunning"
  >
    <div style="text-align:center">
      <div style="font-size:12px;color:var(--gray-11);margin-bottom:12px;word-break:break-all">{{ progressText }}</div>
      <NProgress type="line" :percentage="progress" :show-indicator="false" :height="8" />
      <div style="font-size:11.5px;color:var(--gray-11);margin-top:6px;margin-bottom:16px">{{ progress + '%' }}</div>
    </div>
    <template #footer>
      <div v-if="!backupRunning" style="text-align:center">
        <NButton size="small" @click="closeBackupProgress">关闭</NButton>
      </div>
    </template>
  </NModal>
</template>
