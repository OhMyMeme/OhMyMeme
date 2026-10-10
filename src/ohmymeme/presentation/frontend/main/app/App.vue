<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme, zhCN, dateZhCN } from 'naive-ui'
import MainWindow from './MainWindow.vue'
import { naiveThemeOverrides } from '../../shared/naive-theme'
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="naiveThemeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <NMessageProvider>
      <NDialogProvider>
        <MainWindow />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
