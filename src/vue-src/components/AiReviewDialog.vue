<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { api, rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'
import type { AiSuggestion } from '../types'

const emit = defineEmits<{ applied: []; toast: [msg: string] }>()

const visible = ref(false)
const items = ref<AiSuggestion[]>([])
const index = ref(0)
const boxEl = ref<HTMLElement>()
const saving = ref(false)
const status = ref('')
const statusError = ref(false)
// 建议标签可编辑（复制一份，避免改动原始数据）；已有标签只读展示
const editTags = ref<string[]>([])
const tagInput = ref('')
const editName = ref('')
const editDesc = ref('')
const editVText = ref('')
// 本次会话是否改动过建议（应用/全部应用/丢弃都会改），用于关闭时决定是否通知刷新
const changed = ref(false)

async function open() {
  const r = await api('ai_review_items')
  if (!r || !r.ok) {
    emit('toast', (r && r.error) || '读取建议失败')
    return
  }
  items.value = r.items || []
  index.value = 0
  status.value = ''
  statusError.value = false
  changed.value = false
  rememberFocus()
  visible.value = true
  await nextTick()
  syncCurrent()
  boxEl.value?.focus()
}

function close() {
  visible.value = false
  restoreFocus()
  // 会话内有改动才通知，避免无谓刷新
  if (changed.value) emit('applied')
}

// 把当前建议的字段同步到编辑区；已有标签只读，不进编辑区
function syncCurrent() {
  const it = items.value[index.value]
  if (!it) return
  editTags.value = (it.tags || []).slice()
  editName.value = it.name || ''
  editDesc.value = it.description || ''
  editVText.value = it.visible_text || ''
  tagInput.value = ''
}

function prev() {
  if (index.value > 0) { index.value--; syncCurrent() }
}

function next() {
  if (index.value < items.value.length - 1) { index.value++; syncCurrent() }
}

// 跳过：不动数据，仅切到下一张
function skip() {
  if (index.value < items.value.length - 1) next()
  else setStatus('已是最后一张；关闭即可保留未处理的建议', false)
}

function addTag() {
  const v = tagInput.value.trim()
  if (!v) return
  if (editTags.value.indexOf(v) === -1) editTags.value.push(v)
  tagInput.value = ''
}

function removeTag(i: number) {
  if (i < 0 || i >= editTags.value.length) return
  editTags.value.splice(i, 1)
}

function setStatus(msg: string, isError: boolean) {
  status.value = msg
  statusError.value = isError
}

// payload 不能为空对象，否则后端判为「未找到该表情的建议」
function payloadOf(it: AiSuggestion) {
  return {
    tags: editTags.value.slice(),
    name: editName.value,
    description: editDesc.value,
    visible_text: editVText.value,
    emotions: (it.emotions || []).slice(),
    intents: (it.intents || []).slice(),
  }
}

async function applyCurrent() {
  const it = items.value[index.value]
  if (!it || saving.value) return
  saving.value = true
  const r = await api('ai_tag_apply', it.meme_id, payloadOf(it))
  saving.value = false
  if (!r || !r.ok) {
    setStatus('应用失败：' + ((r && r.error) || '未知错误'), true)
    return
  }
  items.value.splice(index.value, 1)
  if (index.value >= items.value.length) index.value = Math.max(0, items.value.length - 1)
  syncCurrent()
  setStatus('已应用（标签为追加，原有标签保留）', false)
  changed.value = true
  emit('applied')
}

async function applyAll() {
  if (saving.value) return
  saving.value = true
  const r = await api('ai_tag_apply_all')
  saving.value = false
  if (!r || !r.ok) {
    setStatus('全部应用失败：' + ((r && r.error) || '未知错误'), true)
    return
  }
  const failed = r.failed || 0
  items.value = []
  index.value = 0
  syncCurrent()
  setStatus('已应用 ' + (r.applied || 0) + ' 条' + (failed ? '，失败 ' + failed + ' 条' : ''), failed > 0)
  changed.value = true
  emit('applied')
}

// 丢弃当前建议（不写库）
async function discardCurrent() {
  const it = items.value[index.value]
  if (!it || saving.value) return
  saving.value = true
  const r = await api('ai_tag_discard', [it.meme_id])
  saving.value = false
  if (!r || !r.ok) {
    setStatus('丢弃失败：' + ((r && r.error) || '未知错误'), true)
    return
  }
  items.value.splice(index.value, 1)
  if (index.value >= items.value.length) index.value = Math.max(0, items.value.length - 1)
  syncCurrent()
  setStatus('已丢弃该建议（未写入标签）', false)
  // 丢弃同样改变待审集合，需通知主窗口刷新角标与计数
  changed.value = true
  emit('applied')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.stopPropagation(); close() }
  else if (boxEl.value) trapTabFocus(boxEl.value, e)
}

defineExpose({ open })
</script>

<template>
  <div v-if="visible" class="ai-review-overlay" @click.self="close">
    <div
      class="ai-review-box"
      ref="boxEl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-review-title"
      tabindex="-1"
      @keydown="onKeydown"
    >
      <div class="ai-review-head">
        <div id="ai-review-title" class="ai-review-title">审核 AI 建议</div>
        <div v-if="items.length" class="ai-review-counter">{{ index + 1 }} / {{ items.length }}</div>
      </div>

      <div v-if="!items.length" class="ai-review-empty">没有待审核的建议</div>

      <div v-else class="ai-review-body">
        <div class="ai-review-left">
          <div class="ai-review-thumb">
            <img :src="'/api/thumb/' + items[index].meme_id + '/' + encodeURIComponent(items[index].filename)" :alt="items[index].name">
          </div>
          <div class="ai-review-filename">{{ items[index].filename }}</div>
        </div>

        <div class="ai-review-right">
          <div class="ai-review-field">
            <label>建议名称</label>
            <input v-model="editName" placeholder="（无）">
          </div>
          <div class="ai-review-field">
            <label>描述</label>
            <input v-model="editDesc" placeholder="（无）">
          </div>
          <div class="ai-review-field">
            <label>可见文字</label>
            <input v-model="editVText" placeholder="（无）">
          </div>
          <div class="ai-review-field">
            <label>建议标签</label>
            <div class="ai-tag-list ai-review-tags">
              <span v-for="(t, i) in editTags" :key="t" class="ai-tag-chip">
                {{ t }}
                <button class="ai-chip-x" title="移除" @click="removeTag(i)">×</button>
              </span>
              <span v-if="!editTags.length" class="ai-review-none">暂无建议标签</span>
            </div>
            <div class="ai-review-tagadd">
              <input v-model="tagInput" placeholder="输入后回车添加" @keydown.enter.prevent="addTag">
              <button class="btn btn-secondary btn-sm" @click="addTag">添加</button>
            </div>
          </div>
          <div class="ai-review-field">
            <label>已有标签（只读，不会被覆盖）</label>
            <div class="ai-tag-list">
              <span v-for="t in items[index].existing_tags" :key="t" class="ai-tag-chip human">{{ t }}</span>
              <span v-if="!items[index].existing_tags.length" class="ai-review-none">无</span>
            </div>
          </div>
          <div class="ai-review-field" v-if="items[index].emotions.length">
            <label>情绪</label>
            <div class="ai-tag-list">
              <span v-for="t in items[index].emotions" :key="t" class="ai-tag-chip human">{{ t }}</span>
            </div>
          </div>
          <div class="ai-review-field" v-if="items[index].intents.length">
            <label>意图</label>
            <div class="ai-tag-list">
              <span v-for="t in items[index].intents" :key="t" class="ai-tag-chip human">{{ t }}</span>
            </div>
          </div>
          <div class="ai-review-detail">
            <span v-if="items[index].provider">模型：{{ items[index].provider }}</span>
            <span v-if="items[index].created_at">　生成于 {{ items[index].created_at }}</span>
          </div>
        </div>
      </div>

      <div class="ai-review-status" :class="{ error: statusError }">{{ status }}</div>

      <div class="ai-review-actions">
        <button class="btn btn-secondary btn-sm" :disabled="index <= 0" @click="prev">上一张</button>
        <button class="btn btn-secondary btn-sm" :disabled="index >= items.length - 1" @click="next">下一张</button>
        <button class="btn btn-ghost btn-sm" :disabled="!items.length" @click="skip">跳过</button>
        <button class="btn btn-ghost btn-sm" :disabled="!items.length" @click="discardCurrent">丢弃</button>
        <span class="spacer"></span>
        <button class="btn btn-primary btn-sm" :disabled="!items.length || saving" @click="applyCurrent">应用此条</button>
        <button class="btn btn-secondary btn-sm" :disabled="!items.length || saving" @click="applyAll">全部应用</button>
        <button class="btn btn-ghost btn-sm" @click="close">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ai-review-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 270;
}

.ai-review-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px 22px;
  width: 720px;
  max-width: calc(100vw - 40px);
  box-shadow: var(--shadow-lg);
  outline: none;
}

.ai-review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.ai-review-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
}

.ai-review-counter {
  font-size: 12px;
  color: var(--muted);
}

.ai-review-empty {
  text-align: center;
  padding: 28px 0;
  font-size: 13px;
  color: var(--muted);
}

.ai-review-body {
  display: flex;
  gap: 16px;
}

.ai-review-left {
  width: 190px;
  flex-shrink: 0;
}

.ai-review-thumb {
  width: 190px;
  height: 190px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.ai-review-thumb img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.ai-review-filename {
  font-size: 11px;
  color: var(--muted);
  margin-top: 6px;
  word-break: break-all;
  line-height: 1.5;
}

.ai-review-right {
  flex: 1;
  min-width: 0;
  max-height: 360px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.ai-review-field {
  margin-bottom: 10px;
}

.ai-review-field label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--fg-secondary);
  margin-bottom: 4px;
}

.ai-review-field input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--card);
  color: var(--fg);
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
}

.ai-review-field input:focus {
  border-color: var(--primary-strong);
}

.ai-review-tags {
  min-height: 26px;
}

.ai-review-tagadd {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}

.ai-review-tagadd input {
  flex: 1;
}

.ai-review-none {
  font-size: 11.5px;
  color: var(--muted);
}

.ai-review-detail {
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.6;
}

.ai-review-status {
  font-size: 12px;
  color: var(--muted);
  margin-top: 10px;
  min-height: 18px;
}

.ai-review-status.error {
  color: var(--danger);
}

.ai-review-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.ai-chip-x {
  background: none;
  border: none;
  padding: 0;
  margin-left: 4px;
  cursor: pointer;
  color: inherit;
  opacity: 0.6;
  font-size: 13px;
  line-height: 1;
  font-family: inherit;
}

.ai-chip-x:hover {
  opacity: 1;
  color: var(--danger);
}

.spacer {
  flex: 1;
}
</style>
