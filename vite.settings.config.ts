import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// 设置窗口独立 Vite 入口：产物 settings-vue.js（IIFE 单文件，与主窗口 ohmymeme.js 并列）
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: resolve(__dirname, 'src/webui/dist'),
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/ohmymeme/presentation/frontend/settings-vue/app/main.ts'),
      output: {
        entryFileNames: 'settings-vue.js',
        inlineDynamicImports: true,
        format: 'iife',
      },
    },
    minify: 'esbuild',
    sourcemap: false,
  },
})
