<script setup lang="ts">
import { onMounted } from 'vue'
import bodyHtml from './settings-body.html?raw'
import cssText from './settings.css?inline'
import legacyCode from './legacy.js?raw'

function injectStyle() {
  const id = 'ohmm-settings-style'
  if (document.getElementById(id)) return
  const style = document.createElement('style')
  style.id = id
  style.textContent = cssText
  document.head.appendChild(style)
}

function runLegacy() {
  const script = document.createElement('script')
  script.id = 'ohmm-settings-legacy'
  script.textContent = legacyCode
  document.body.appendChild(script)
}

function movePluginSections() {
  const source = document.getElementById('plugin-sections-source')
  const content = document.getElementById('settings-content')
  if (!source || !content) return
  while (source.firstChild) content.appendChild(source.firstChild)
}

injectStyle()

onMounted(() => {
  runLegacy()
  movePluginSections()
  const w = window as any
  try {
    w.initSettings?.()
    setTimeout(() => w.initVersion?.(), 500)
    w.initDirtyTracking?.()
    w.initPlugins?.()
  } catch (e) {
    console.error('settings init failed', e)
  }
})
</script>

<template>
  <div id="settings-vue-root" v-html="bodyHtml"></div>
</template>
