<script setup lang="ts">
import { onMounted } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme } from 'naive-ui'
import { naiveThemeOverrides } from '../../main/app/naive-theme'
import SettingsShell from './SettingsShell.vue'
import { loadProjection, loadSettings } from '../shared/store'

// 初始化：先校验宿主 UI 投影，再拉取设置（bridge 未就绪时重试）
let retries = 0
async function init() {
  try { await loadProjection() }
  catch (e) { console.error(e); return }
  const ok = await loadSettings()
  if (ok) return
  retries++
  if (retries < 20) setTimeout(init, 200)
}

onMounted(init)
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="naiveThemeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <SettingsShell />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
