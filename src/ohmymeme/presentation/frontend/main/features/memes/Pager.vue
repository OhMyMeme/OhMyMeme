<script setup lang="ts">
import { NPagination } from 'naive-ui'

const props = defineProps<{
  page: number
  pageCount: number
}>()

const emit = defineEmits<{
  'go': [page: number]
}>()

// 页码变化时向父组件派发目标页，越界或未变化不派发
function onUpdatePage(p: number) {
  if (p < 1 || p > props.pageCount || p === props.page) return
  emit('go', p)
}
</script>

<template>
  <div v-if="pageCount > 1" class="pager">
    <NPagination
      :page="page"
      :page-count="pageCount"
      :page-slot="7"
      @update:page="onUpdatePage"
    />
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
</style>
