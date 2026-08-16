import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: resolve(__dirname, 'src/webui/dist'),
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/vue-src/main.ts'),
      output: {
        entryFileNames: 'ohmymeme.js',
        inlineDynamicImports: true,
        format: 'iife',
      },
    },
    minify: 'esbuild',
    sourcemap: false,
  },
})
