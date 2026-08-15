import { createApp, h, ref } from 'vue'
import App from './App.vue'
import './style.css'

declare global {
  interface Window {
    pywebview: any
  }
}

const app = createApp(App)
app.mount('#app-mount')
