<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme, zhCN, dateZhCN } from 'naive-ui'
import { naiveThemeOverrides } from '../../shared/naive-theme'
import SettingsShell from './SettingsShell.vue'
import { loadProjection, loadSettings } from '../shared/store'

// 初始化状态：仅当宿主投影完整校验且设置拉取成功后才挂载 SettingsShell，
// 避免后端未就绪时注册 DOM 交互或触发子组件的 mounted 桥接调用
const ready = ref(false)
const failure = ref('')
let retries = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false

// 先验证宿主投影，再加载设置并挂载交互外壳。
async function init() {
  if (disposed) return
  try {
    await loadProjection()
  } catch (error) {
    console.error(error)
    scheduleRetry('界面配置校验失败')
    return
  }
  if (disposed) return
  let ok = false
  try {
    ok = await loadSettings()
  } catch (error) {
    console.error(error)
    ok = false
  }
  if (ok) {
    if (disposed) return
    failure.value = ''
    ready.value = true
    return
  }
  scheduleRetry('无法连接应用后端')
}

// 原 20 次 / 200ms 重试；超限给出可读失败文案，不再注册任何交互
function scheduleRetry(reason: string) {
  if (disposed || ready.value) return
  retries++
  if (retries < 20) {
    retryTimer = setTimeout(init, 200)
    return
  }
  failure.value = reason + '，请重启应用后重试'
}

onMounted(init)
onUnmounted(() => {
  disposed = true
  if (retryTimer) clearTimeout(retryTimer)
})

defineExpose({ ready, failure, init })
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="naiveThemeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <NMessageProvider placement="bottom">
      <NDialogProvider>
        <SettingsShell v-if="ready" />
        <div v-else-if="failure" class="settings-load-failed" role="alert">{{ failure }}</div>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
