<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  pageCount: number
}>()

const emit = defineEmits<{
  'go': [page: number]
}>()

// 页码窗口：首尾 + 当前页前后各 2，间隔处用省略号
const pages = computed<number[]>(() => {
  const cur = props.page
  const total = props.pageCount
  const win = new Set<number>()
  const show = (p: number) => { if (p >= 1 && p <= total) win.add(p) }
  show(1)
  show(cur - 2); show(cur - 1); show(cur); show(cur + 1); show(cur + 2)
  show(total)
  return [...win].sort((a, b) => a - b)
})

// 判断两页之间是否需要省略号
function needDots(idx: number): boolean {
  if (idx === 0) return false
  return pages.value[idx] - pages.value[idx - 1] > 1
}

function go(p: number) {
  if (p < 1 || p > props.pageCount || p === props.page) return
  emit('go', p)
}
</script>

<template>
  <div v-if="pageCount > 1" class="pager">
    <button class="pager-btn" :disabled="page <= 1" title="上一页" @click="go(page - 1)">&lt;</button>
    <template v-for="(p, idx) in pages" :key="p">
      <span v-if="needDots(idx)" class="pager-dots">…</span>
      <button class="pager-btn" :class="{ active: p === page }" @click="go(p)">{{ p }}</button>
    </template>
    <button class="pager-btn" :disabled="page >= pageCount" title="下一页" @click="go(page + 1)">&gt;</button>
    <button class="pager-btn" :disabled="page >= pageCount" title="末页" @click="go(pageCount)">&gt;&gt;</button>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 5px 10px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.pager-btn {
  min-width: 28px;
  height: 28px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--fg-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}

.pager-btn:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--fg);
  border-color: var(--border-light);
}

.pager-btn.active {
  background: var(--primary-strong);
  border-color: var(--primary-strong);
  color: #fff;
}

.pager-btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.pager-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.pager-dots {
  color: var(--muted);
  font-size: 12px;
  padding: 0 2px;
  user-select: none;
}
</style>
