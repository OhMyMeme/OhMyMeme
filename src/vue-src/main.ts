import { createApp, h, ref } from 'vue'
import VueDragSelect from '@coleqiu/vue-drag-select'
import App from './App.vue'
import './style.css'

declare global {
  interface Window {
    pywebview: any
    focusSearch: () => void
    refreshMemes: () => void
    refreshTags: () => void
    refreshCollections: () => void
    showGuide: () => void
    onCloudReady: () => void
    ommPluginRefresh: (pluginId?: string) => void
    ommPluginsReady?: Promise<void>
  }
}

// 后端 show() 时 evaluate_js("focusSearch()")：快捷键呼出后聚焦搜索栏
window.focusSearch = () => {
  const el = document.getElementById('search')
  if (el) el.focus()
}

const app = createApp(App)
app.use(VueDragSelect) // 注册 <drag-select> / <drag-select-option>
app.mount('#app-mount')
