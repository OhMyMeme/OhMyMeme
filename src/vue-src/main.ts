import { createApp, h, ref } from 'vue'
import App from './App.vue'
import { VueDraggableNext } from 'vue-draggable-next'
import './style.css'

declare global {
  interface Window {
    pywebview: any
  }
}

const app = createApp(App)
app.component('VueDraggableNext', VueDraggableNext)
app.mount('#app-mount')
