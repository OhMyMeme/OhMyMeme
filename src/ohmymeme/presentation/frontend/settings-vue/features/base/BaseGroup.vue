<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { NCheckbox, NSelect, NInput, NButton } from 'naive-ui'
import { api } from '../../shared/bridge'
import { settings, markDirty, showToast, resetSignal } from '../../shared/store'

// 快捷键捕获：点击输入框后在捕获阶段监听下一组组合键（契约对齐原 startHotkeyCapture）
const capturing = ref(false)
let hotkeyHandler: ((e: KeyboardEvent) => void) | null = null
function startHotkeyCapture() {
  if (capturing.value) return
  capturing.value = true
  settings.hotkey = ''
  hotkeyHandler = (e: KeyboardEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const parts: string[] = []
    if (e.ctrlKey) parts.push('Ctrl')
    if (e.altKey) parts.push('Alt')
    if (e.shiftKey) parts.push('Shift')
    if (e.metaKey) parts.push('Win')
    const key = e.key
    if (['Control', 'Alt', 'Shift', 'Meta'].includes(key)) return
    let mk = key
    if (mk === ' ') mk = 'Space'
    if (mk.length === 1) mk = mk.toUpperCase()
    parts.push(mk)
    settings.hotkey = parts.join('+')
    markDirty()
    capturing.value = false
    if (hotkeyHandler) { document.removeEventListener('keydown', hotkeyHandler, true); hotkeyHandler = null }
  }
  document.addEventListener('keydown', hotkeyHandler, true)
}

// 浏览器来源连通性探测（文案与状态色对齐原 checkConnectivity）
const netStatus = ref('')
const netStatusMode = ref<'' | 'ok' | 'error'>('')
async function checkConnectivity() {
  netStatus.value = '正在检查网络...'
  netStatusMode.value = ''
  try {
    const r = await api('check_connectivity')
    if (r && r.ok) {
      netStatus.value = '● 已连接 (' + (r.latency || '') + ')'
      netStatusMode.value = 'ok'
    } else {
      netStatus.value = '● 无网络连接'
      netStatusMode.value = 'error'
    }
  } catch (_) {
    netStatus.value = '● 检查失败'
    netStatusMode.value = 'error'
  }
}

const copyModeOptions = [
  { label: '不处理，直接复制原图', value: 0 },
  { label: '缩放为 WebP', value: 1 },
  { label: '转换为 GIF', value: 2 },
  { label: '转换为 GIF 并隐写原图（可无损还原）', value: 3 },
]

// 存储位置
const storageStatus = ref('')
const cacheDir = ref('')
const pendingDir = ref<string | null>(null)
const moveFiles = ref(true)
const applying = ref(false)

function formatSize(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = bytes, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(v >= 100 ? 0 : 1) + ' ' + units[i]
}

async function loadStorageInfo() {
  let st: any = null
  try { st = await api('get_storage_info') } catch { st = null }
  if (!st) return
  if (st.cache_dir) cacheDir.value = st.cache_dir
  storageStatus.value = '共 ' + (st.file_count || 0) + ' 个表情包，约 ' + formatSize(st.total_size || 0)
    + (st.custom ? '' : '（默认位置）')
}

async function pickStorageDir() {
  let r: any = null
  try { r = await api('pick_storage_dir') } catch { r = null }
  if (!r || !r.ok) {
    if (!(r && r.cancelled)) storageStatus.value = '无法打开目录选择对话框'
    return
  }
  pendingDir.value = r.path
  storageStatus.value = ''
}

function cancelStoragePick() {
  pendingDir.value = null
  loadStorageInfo()
}

async function applyStorageDir() {
  if (!pendingDir.value) return
  applying.value = true
  try {
    const r = await api('apply_storage_dir', pendingDir.value, moveFiles.value)
    if (!r || !r.ok) {
      storageStatus.value = '应用失败：' + (r && r.error ? r.error : '未知错误')
      return
    }
    pendingDir.value = null
    if (r.cache_dir) cacheDir.value = r.cache_dir
    let msg = '已应用新存储目录'
    if (r.moved > 0) msg += '，已移动 ' + r.moved + ' 个文件'
    if (r.failed && r.failed.length) msg += '，失败 ' + r.failed.length + ' 个：' + r.failed.map((f: any) => f.path || f.name).join('、')
    storageStatus.value = msg
    showToast('存储位置已更新')
  } catch (e: any) {
    storageStatus.value = '应用失败：' + (e && e.message ? e.message : '未知错误')
  } finally {
    applying.value = false
  }
}

onMounted(() => {
  loadStorageInfo()
  checkConnectivity()
})
onUnmounted(() => {
  if (hotkeyHandler) document.removeEventListener('keydown', hotkeyHandler, true)
})

// 恢复默认后重跑连通性探测（对齐旧 resetSettings 的 checkConnectivity 调用）
watch(resetSignal, () => { checkConnectivity() })

defineExpose({ loadStorageInfo, checkConnectivity })
</script>

<template>
  <div class="section">
    <div class="form-group">
      <label>全局快捷键</label>
      <NInput
        readonly
        :value="capturing ? '按下组合键...' : (settings.hotkey || '')"
        :input-props="{ id: 's-hotkey' }"
        @click="startHotkeyCapture"
      />
    </div>
    <div class="check-row">
      <NCheckbox :checked="settings.hotkey_show_at_mouse === true" @update:checked="(v) => { settings.hotkey_show_at_mouse = v; markDirty() }">
        通过全局快捷键打开时显示在鼠标位置
      </NCheckbox>
    </div>
  </div>

  <div class="section">
    <div class="section-title">启动与开机自启</div>
    <div class="check-row">
      <NCheckbox :checked="settings.auto_start === true" @update:checked="(v) => { settings.auto_start = v; markDirty() }">
        开机自启
      </NCheckbox>
    </div>
    <div v-if="settings.auto_start === true" class="check-row">
      <NCheckbox :checked="settings.silent_start === true" @update:checked="(v) => { settings.silent_start = v; markDirty() }">
        开机自启时静默启动（直接托盘运行）
      </NCheckbox>
    </div>
    <div class="check-row">
      <NCheckbox :checked="settings.show_startup_animation !== false" @update:checked="(v) => { settings.show_startup_animation = v; markDirty() }">
        显示启动动画
      </NCheckbox>
    </div>
  </div>

  <div class="section">
    <div class="section-title">分组显示</div>
    <div class="check-row">
      <NCheckbox :checked="settings.show_uncategorized !== false" @update:checked="(v) => { settings.show_uncategorized = v; markDirty() }">
        显示「未分类」分组
      </NCheckbox>
    </div>
    <div class="check-row">
      <NCheckbox :checked="settings.record_recent_use !== false" @update:checked="(v) => { settings.record_recent_use = v; markDirty() }">
        记录最近使用
      </NCheckbox>
    </div>
  </div>

  <div class="section">
    <div class="section-title">动图</div>
    <div class="check-row">
      <NCheckbox :checked="settings.auto_play_gif !== false" @update:checked="(v) => { settings.auto_play_gif = v; markDirty() }">
        动图自动播放
      </NCheckbox>
    </div>
    <div class="check-row">
      <NCheckbox :checked="settings.hover_to_play === true" @update:checked="(v) => { settings.hover_to_play = v; markDirty() }">
        动图悬停播放（性能不足时启用）
      </NCheckbox>
    </div>
  </div>

  <div class="section">
    <div class="section-title">图片来源</div>
    <div class="check-row">
      <NCheckbox :checked="settings.try_original_image === true" @update:checked="(v) => { settings.try_original_image = v; markDirty(); checkConnectivity() }">
        浏览器来源尝试获取原图
      </NCheckbox>
    </div>
    <div
      v-if="netStatus"
      class="s-net-status"
      :class="{ 'status-ok': netStatusMode === 'ok', 'status-error': netStatusMode === 'error' }"
      style="font-size:12px;margin-top:4px;padding-left:4px"
    >{{ netStatus }}</div>
  </div>

  <div class="section">
    <div class="section-title">复制处理</div>
    <div class="select-row">
      <span class="select-row-label">复制超限静态图时</span>
      <NSelect
        style="flex:1"
        :value="settings.copy_resize_mode ?? 1"
        :options="copyModeOptions"
        @update:value="(v) => { settings.copy_resize_mode = typeof v === 'number' ? v : 1; markDirty() }"
      />
    </div>
    <p style="font-size:11.5px;color:var(--muted);margin-top:4px;line-height:1.6">复制超过尺寸上限的静态图时按此处模式处理；动图不受影响。隐写模式会把原图信息随 GIF 隐藏，接收方可运行解码工具还原，但会显著增大文件体积。</p>
  </div>

  <div class="section">
    <div class="section-title">存储位置</div>
    <p style="font-size:11.5px;color:var(--muted);margin-bottom:10px;line-height:1.6">表情包图片文件存放目录；数据库与缩略图仍保留在系统数据目录</p>
    <div class="form-group">
      <label>当前存储目录</label>
      <NInput readonly placeholder="加载中..." :value="cacheDir" :input-props="{ id: 's-cache-dir' }" />
    </div>
    <div v-if="pendingDir" style="margin-bottom:10px">
      <div class="form-group">
        <label>新存储目录</label>
        <NInput readonly :value="pendingDir" :input-props="{ id: 's-cache-dir-new' }" />
      </div>
      <div class="check-row" style="margin-bottom:8px">
        <NCheckbox :checked="moveFiles" @update:checked="(v) => moveFiles = v">
          同时把现有表情包移动到新目录
        </NCheckbox>
      </div>
      <div style="display:flex;gap:8px">
        <NButton type="primary" size="small" :disabled="applying" @click="applyStorageDir">应用更改</NButton>
        <NButton size="small" quaternary @click="cancelStoragePick">取消</NButton>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:6px">点击「应用更改」立即生效，无需保存</div>
    </div>
    <div style="display:flex;gap:8px">
      <NButton size="small" @click="pickStorageDir">更改位置</NButton>
    </div>
    <div v-if="storageStatus" style="font-size:11.5px;color:var(--muted);margin-top:6px;line-height:1.6">{{ storageStatus }}</div>
  </div>
</template>
