import { reactive, ref } from 'vue'
import { api } from './bridge'
import { loadPluginUI } from './plugin-ui'

// 设置窗口共享状态：原始 settings dict、脏标记、当前导航分组
export const settings = reactive<Record<string, any>>({})
export const activeGroup = ref('base')
export const dirty = ref(false)
export const pluginUILabels = reactive<Record<string, string>>({})

export function markDirty() {
  dirty.value = true
}

// 拉取后端设置并填充共享状态
export async function loadSettings(): Promise<boolean> {
  const s = api('get_settings')
  const resolved = s && typeof s.then === 'function' ? await s : s
  if (!resolved) return false
  Object.keys(settings).forEach((k) => delete settings[k])
  Object.assign(settings, resolved)
  dirty.value = false
  return true
}

// 加载宿主 UI 投影并提取数据驱动标签（导入行/同步后端下拉/LAN 区标题）
export async function loadProjection(): Promise<void> {
  const snapshot = await loadPluginUI()
  for (const contribution of snapshot.contributions) {
    pluginUILabels[(contribution as any).screen] = (contribution as any).label
  }
}
