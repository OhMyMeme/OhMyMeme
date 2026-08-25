<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { api, rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'

const emit = defineEmits<{
  confirm: [tags: string[] | null, memeId: number]
}>()

const visible = ref(false)
const memeId = ref(0)
const allTags = ref<string[]>([])
const selected = ref<string[]>([])
const query = ref('')
const loading = ref(false)
const boxEl = ref<HTMLElement>()
const inputEl = ref<HTMLInputElement>()

let resolveFn: ((tags: string[] | null) => void) | null = null

async function open(id: number): Promise<string[] | null> {
  memeId.value = id
  rememberFocus()
  visible.value = true
  loading.value = true
  query.value = ''
  selected.value = []
  try {
    const [all, cur] = await Promise.all([
      api('get_tags'),
      api('get_meme_tags', id),
    ])
    allTags.value = all || []
    selected.value = cur || []
  } catch (_) {
    allTags.value = []
    selected.value = []
  }
  loading.value = false
  await nextTick()
  inputEl.value?.focus()
  return new Promise(resolve => { resolveFn = resolve })
}

function close(tags: string[] | null) {
  visible.value = false
  restoreFocus()
  emit('confirm', tags, memeId.value)
  if (resolveFn) { resolveFn(tags); resolveFn = null }
}

function toggleTag(tag: string) {
  const i = selected.value.indexOf(tag)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(tag)
}

function addFromInput() {
  const v = query.value.trim()
  if (!v) return
  if (!selected.value.includes(v)) selected.value.push(v)
  query.value = ''
}

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return allTags.value.filter(t => (q ? t.toLowerCase().includes(q) : true))
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') { e.preventDefault(); addFromInput() }
}

function onBoxKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null) }
  else if (boxEl.value) trapTabFocus(boxEl.value, e)
}

function confirm() {
  // 只保存明确添加的标签（回车/点击）；输入框残留文字不自动提交
  close(selected.value.slice())
}

defineExpose({ open })
</script>

<template>
  <div v-if="visible" class="tag-editor-overlay" @click.self="close(null)">
    <div class="tag-editor-box" ref="boxEl" role="dialog" aria-modal="true" aria-labelledby="tag-editor-title" @keydown="onBoxKeydown">
      <div id="tag-editor-title" class="tag-editor-title">编辑标签</div>

      <input
        id="tag-editor-input"
        ref="inputEl"
        v-model="query"
        class="tag-editor-input"
        type="text"
        placeholder="搜索已有标签或输入新标签，回车添加"
        autocomplete="off"
        spellcheck="false"
        @keydown="onKeydown"
      >

      <div class="tag-editor-list">
        <span
          v-for="tag in filtered"
          :key="tag"
          class="tag"
          :class="{ active: selected.includes(tag) }"
          role="button"
          tabindex="0"
          :aria-pressed="selected.includes(tag)"
          @click="toggleTag(tag)"
          @keydown.enter.prevent="toggleTag(tag)"
          @keydown.space.prevent="toggleTag(tag)"
        >{{ tag }}</span>
        <div v-if="!loading && filtered.length === 0" class="tag-editor-empty">
          {{ query.trim() ? `无匹配标签，回车创建"${query.trim()}"` : '暂无标签' }}
        </div>
      </div>

      <div v-if="selected.length" class="tag-editor-selected">
        <span
          v-for="tag in selected"
          :key="'sel-' + tag"
          class="tag active"
          role="button"
          tabindex="0"
          aria-pressed="true"
          @click="toggleTag(tag)"
          @keydown.enter.prevent="toggleTag(tag)"
          @keydown.space.prevent="toggleTag(tag)"
        >{{ tag }} ×</span>
      </div>

      <div class="tag-editor-actions">
        <button class="btn btn-secondary" @click="close(null)">取消</button>
        <button class="btn btn-primary" @click="confirm">确定</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tag-editor-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  animation: fadeIn 0.15s ease;
}

.tag-editor-box {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 420px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
}

.tag-editor-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 14px;
}

.tag-editor-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--fg);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  margin-bottom: 10px;
  transition: border-color 0.15s;
}

.tag-editor-input:focus {
  border-color: var(--primary);
}

.tag-editor-list {
  max-height: 200px;
  overflow-y: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 0;
  margin-bottom: 10px;
}

.tag-editor-empty {
  font-size: 12px;
  color: var(--muted);
  width: 100%;
  text-align: center;
  padding: 8px 0;
}

.tag-editor-selected {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.tag-editor-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
