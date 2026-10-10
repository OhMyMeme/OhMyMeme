<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme } from 'naive-ui'
import MainWindow from './MainWindow.vue'
import { naiveThemeOverrides } from './naive-theme'
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="naiveThemeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <MainWindow />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
