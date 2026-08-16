import { createApp, h, ref } from 'vue'
import App from './App.vue'
import './style.css'

declare global {
  interface Window {
    pywebview: any
  }
}

// 后端 show() 时 evaluate_js("focusSearch()")：快捷键呼出后聚焦搜索栏
window.focusSearch = () => {
  const el = document.getElementById('search')
  if (el) el.focus()
}

const app = createApp(App)
app.mount('#app-mount')
