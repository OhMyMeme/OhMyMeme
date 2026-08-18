import { createApp, h, ref } from 'vue'
import VueDragSelect from '@coleqiu/vue-drag-select'
import App from './App.vue'
import './style.css'
import { showLanDeviceConfirm } from '../features/lan/showLanDeviceConfirm'

declare global {
  interface Window {
    pywebview: any
    focusSearch: () => void
    refreshMemes: () => void
    refreshTags: () => void
    refreshCollections: () => void
    showLanDeviceConfirm: (device: any) => void
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
app.use(VueDragSelect) // 注册 <drag-select> / <drag-select-option>
app.mount('#app-mount')
