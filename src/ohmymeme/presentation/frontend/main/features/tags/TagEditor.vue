<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { NModal, NInput, NButton, NTag } from 'naive-ui'
import { api } from '../../shared/bridge'

const emit = defineEmits<{
  confirm: [tags: string[] | null, memeId: number]
}>()

const visible = ref(false)
const memeId = ref(0)
const allTags = ref<string[]>([])
const selected = ref<string[]>([])
const query = ref('')
const loading = ref(false)
const inputRef = ref<InstanceType<typeof NInput> | null>(null)

let resolveFn: ((tags: string[] | null) => void) | null = null

async function open(id: number): Promise<string[] | null> {
  memeId.value = id
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
  nextTick(focusInput)
  return new Promise(resolve => { resolveFn = resolve })
}

function close(tags: string[] | null) {
  visible.value = false
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

function focusInput() {
  inputRef.value?.focus()
}

// NModal 出现后聚焦输入框（已在可见状态重复打开时 after-enter 不再触发，open 里另补一次）
function onAfterEnter() {
  focusInput()
}

// 遮罩点击等关闭统一按取消处理
function onShowChange(show: boolean) {
  if (!show) close(null)
}

function confirm() {
  // 只保存明确添加的标签（回车/点击）；输入框残留文字不自动提交
  close(selected.value.slice())
}

defineExpose({ open })
</script>

<template>
  <NModal
    :show="visible"
    :close-on-esc="false"
    :theme-overrides="{ boxShadow: 'none' }"
    transform-origin="center"
    @update:show="onShowChange"
    @after-enter="onAfterEnter"
  >
    <div
      class="tag-editor-box"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tag-editor-title"
      @keydown.esc.stop="close(null)"
    >
      <div id="tag-editor-title" class="tag-editor-title">编辑标签</div>

      <div class="tag-editor-input-wrap" @keydown.enter.prevent="addFromInput">
        <NInput
          ref="inputRef"
          v-model:value="query"
          class="tag-editor-input"
          type="text"
          placeholder="搜索已有标签或输入新标签，回车添加"
          :input-props="{ autocomplete: 'off', spellcheck: 'false' }"
        />
      </div>

      <div class="tag-editor-list">
        <NTag
          v-for="tag in filtered"
          :key="tag"
          size="small"
          checkable
          :checked="selected.includes(tag)"
          @update:checked="toggleTag(tag)"
        >{{ tag }}</NTag>
        <div v-if="!loading && filtered.length === 0" class="tag-editor-empty">
          {{ query.trim() ? `无匹配标签，回车创建"${query.trim()}"` : '暂无标签' }}
        </div>
      </div>

      <div v-if="selected.length" class="tag-editor-selected">
        <NTag
          v-for="tag in selected"
          :key="'sel-' + tag"
          size="small"
          type="primary"
          closable
          @close="toggleTag(tag)"
        >{{ tag }}</NTag>
      </div>

      <div class="tag-editor-actions">
        <NButton @click="close(null)">取消</NButton>
        <NButton type="primary" @click="confirm">确定</NButton>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
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

.tag-editor-input-wrap {
  margin-bottom: 10px;
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
</style>
