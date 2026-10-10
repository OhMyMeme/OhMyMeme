<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useDialog, useMessage, NButton } from 'naive-ui'
import { api } from '../shared/bridge'
import { activeGroup, dirty, save, reset, resetSignal, registerMessage } from '../shared/store'
import BaseGroup from '../features/base/BaseGroup.vue'
import LogsGroup from '../features/logs/LogsGroup.vue'
import BackupGroup from '../features/backup/BackupGroup.vue'
import DangerGroup from '../features/danger/DangerGroup.vue'
import AboutGroup from '../features/about/AboutGroup.vue'
import NetworkGroup from '../features/network/NetworkGroup.vue'
import ImportGroup from '../features/import/ImportGroup.vue'
import PluginsGroup from '../features/plugins/PluginsGroup.vue'

const dialog = useDialog()
// 注册应用内消息 API，供 store 的全局提示复用同一 provider 主题
registerMessage(useMessage())

const pluginsRef = ref<InstanceType<typeof PluginsGroup> | null>(null)

function onSave() { save() }
function onReset() { reset() }

// 恢复默认后重拉插件面板（对齐旧 resetSettings 的 initPluginsPanel 调用）
watch(resetSignal, () => { pluginsRef.value?.initPanel?.() })

// 全局快捷键：Esc 先关覆盖层（由各 NModal 自行处理，不冒泡到此），Ctrl+Enter 保存
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (document.querySelector('.n-modal-mask')) return
    closeSettings()
  } else if (e.key === 'Enter' && e.ctrlKey) {
    save()
  }
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

const groups: { id: string; label: string; danger?: boolean }[] = [
  { id: 'base', label: '基础设置' },
  { id: 'import', label: '导入' },
  { id: 'network', label: '联网' },
  { id: 'danger', label: '危险操作', danger: true },
  { id: 'logs', label: '日志' },
  { id: 'backup', label: '备份与恢复' },
  { id: 'plugins', label: '插件' },
  { id: 'about', label: '关于' },
]

function switchGroup(id: string) {
  activeGroup.value = id
  const content = document.getElementById('settings-content')
  if (content) content.scrollTop = 0
}

// 窗口拖动：标题栏按下走原生拖动（Linux 交合成器），回退 JS 增量位移（screenX/screenY）
let dragState: { sx: number; sy: number } | null = null
async function onTitlebarMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  if ((e.target as HTMLElement).closest('.title-btn')) return
  const nativeDrag = await api('start_window_drag', e.button + 1, e.screenX, e.screenY)
  if (nativeDrag) return
  dragState = { sx: e.screenX, sy: e.screenY }
  e.preventDefault()
}
function onMouseMove(e: MouseEvent) {
  if (!dragState) return
  const dx = e.screenX - dragState.sx
  const dy = e.screenY - dragState.sy
  if (dx !== 0 || dy !== 0) {
    api('move_window', dx, dy)
    dragState.sx = e.screenX
    dragState.sy = e.screenY
  }
}
function onMouseUp() { dragState = null }

async function closeSettings() {
  if (dirty.value) {
    const ok = await new Promise<boolean>((resolve) => {
      dialog.warning({
        title: '有未保存的更改',
        content: '当前修改尚未保存，确定放弃并关闭设置窗口吗？',
        positiveText: '放弃并关闭',
        negativeText: '取消',
        onPositiveClick: () => resolve(true),
        onNegativeClick: () => resolve(false),
        onClose: () => resolve(false),
        onMaskClick: () => resolve(false),
      })
    })
    if (!ok) return
  }
  try { api('close_settings') } catch (e) { /* ignore */ }
}

defineExpose({ switchGroup, closeSettings })
</script>

<template>
  <div id="app" @mousemove="onMouseMove" @mouseup="onMouseUp">
    <div id="titlebar" @mousedown="onTitlebarMouseDown">
      <div class="logo">OhMy<span>Meme</span> 设置</div>
      <span class="spacer"></span>
      <NButton quaternary class="title-btn" aria-label="关闭设置" @click="closeSettings">×</NButton>
    </div>

    <div id="body">
      <nav id="settings-nav">
        <NButton
          v-for="g in groups"
          :key="g.id"
          quaternary
          class="nav-item"
          :class="{ active: activeGroup === g.id, danger: g.danger }"
          :data-group="g.id"
          @click="switchGroup(g.id)"
        >{{ g.label }}</NButton>
      </nav>
      <div id="settings-content">
        <div v-show="activeGroup === 'base'"><BaseGroup /></div>
        <div v-show="activeGroup === 'import'"><ImportGroup /></div>
        <div v-show="activeGroup === 'network'"><NetworkGroup /></div>
        <div v-show="activeGroup === 'danger'"><DangerGroup /></div>
        <div v-show="activeGroup === 'logs'"><LogsGroup /></div>
        <div v-show="activeGroup === 'backup'"><BackupGroup /></div>
        <div v-show="activeGroup === 'plugins'"><PluginsGroup ref="pluginsRef" /></div>
        <div v-show="activeGroup === 'about'"><AboutGroup /></div>
      </div>
    </div>

    <div id="bottom">
      <NButton size="small" quaternary @click="onReset">恢复默认</NButton>
      <span class="spacer" style="flex:1"></span>
      <NButton @click="closeSettings">取消</NButton>
      <NButton type="primary" @click="onSave">保存</NButton>
    </div>
  </div>
</template>
