import { createApp, h, ref } from 'vue'
import App from './App.vue'
import './style.css'
import { showLanDeviceConfirm } from '../features/lan/showLanDeviceConfirm'
import type { JsonObjectModel } from '../shared/generated/bridge'

declare global {
  interface Window {
    focusSearch: () => void
    refreshMemes: () => void
    refreshTags: () => void
    refreshCollections: () => void
    showLanDeviceConfirm: (device: JsonObjectModel) => void
  }
}

// 后端 show() 时 evaluate_js("focusSearch()")：快捷键呼出后聚焦搜索栏
window.focusSearch = () => {
  const el = document.getElementById('search')
  if (el) el.focus()
}

// 供 pywebview evaluate_js 调用（需为 window 全局）
window.showLanDeviceConfirm = showLanDeviceConfirm

const app = createApp(App)
app.mount('#app-mount')
