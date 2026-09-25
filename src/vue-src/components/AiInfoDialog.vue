<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { api, rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'

interface AiDetail {
  name: string
  description: string
  visible_text: string
  emotions: string[]
  intents: string[]
  status: string | null
  error: string
  provider: string
  analyzed_at: string
  tags: string[]
}

const visible = ref(false)
const loading = ref(false)
const detail = ref<AiDetail | null>(null)
const imgSrc = ref('')
const boxEl = ref<HTMLElement>()

async function open(memeId: number, filename: string, memeName: string) {
  rememberFocus()
  visible.value = true
  loading.value = true
  detail.value = null
  imgSrc.value = '/api/thumb/' + memeId + '/' + encodeURIComponent(filename || '')
  await nextTick()
  boxEl.value?.focus()
  const r = await api('ai_detail', memeId)
  loading.value = false
  if (!r || !r.ok) {
    detail.value = {
      name: memeName || '',
      description: '',
      visible_text: '',
      emotions: [],
      intents: [],
      status: null,
      error: (r && r.error) || '读取失败',
      provider: '',
      analyzed_at: '',
      tags: [],
    }
    return
  }
  detail.value = r.detail as AiDetail
}

function close() {
  visible.value = false
  restoreFocus()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.stopPropagation(); close() }
  else if (boxEl.value) trapTabFocus(boxEl.value, e)
}

defineExpose({ open })
</script>

<template>
  <div v-if="visible" class="ai-info-overlay" @click.self="close">
    <div
      class="ai-info-box"
      ref="boxEl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-info-title"
      tabindex="-1"
      @keydown="onKeydown"
    >
      <div class="ai-info-title" id="ai-info-title">AI 解读</div>

      <div v-if="loading" class="ai-info-loading">加载中...</div>

      <div v-else-if="detail" class="ai-info-body">
        <div class="ai-info-left">
          <div class="ai-review-thumb">
            <img :src="imgSrc" alt="">
          </div>
        </div>
        <div class="ai-info-right">
          <div v-if="detail.status === null || detail.status === undefined" class="ai-info-note">
            这张表情还没有 AI 解读。可在设置页「AI」中 tagging，或在右键菜单里对单张 tagging。
          </div>
          <div v-else-if="detail.status === 'failed'" class="ai-info-note error">
            上次 tagging 失败{{ detail.error ? '：' + detail.error : '' }}
          </div>
          <div v-else-if="detail.status === 'running'" class="ai-info-note">正在 tagging...</div>

          <div v-if="detail.name" class="ai-info-row">
            <span class="ai-info-label">名称</span>
            <span class="ai-info-value">{{ detail.name }}</span>
          </div>
          <div v-if="detail.description" class="ai-info-row">
            <span class="ai-info-label">描述</span>
            <span class="ai-info-value">{{ detail.description }}</span>
          </div>
          <div v-if="detail.visible_text" class="ai-info-row">
            <span class="ai-info-label">可见文字</span>
            <span class="ai-info-value">{{ detail.visible_text }}</span>
          </div>
          <div v-if="detail.emotions.length" class="ai-info-row">
            <span class="ai-info-label">情绪</span>
            <span class="ai-info-value">{{ detail.emotions.join('、') }}</span>
          </div>
          <div v-if="detail.intents.length" class="ai-info-row">
            <span class="ai-info-label">意图</span>
            <span class="ai-info-value">{{ detail.intents.join('、') }}</span>
          </div>
          <div class="ai-info-row">
            <span class="ai-info-label">标签</span>
            <span class="ai-info-value">
              <span class="ai-tag-list">
                <span v-for="t in detail.tags" :key="t" class="ai-tag-chip human">{{ t }}</span>
                <span v-if="!detail.tags.length" class="ai-info-none">无</span>
              </span>
            </span>
          </div>
          <div v-if="detail.provider || detail.analyzed_at" class="ai-info-meta">
            <span v-if="detail.provider">模型：{{ detail.provider }}</span>
            <span v-if="detail.analyzed_at">　分析于 {{ detail.analyzed_at }}</span>
          </div>
        </div>
      </div>

      <div class="ai-info-actions">
        <button class="btn btn-secondary btn-sm" @click="close">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ai-info-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 265;
}

.ai-info-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px 22px;
  width: 560px;
  max-width: calc(100vw - 40px);
  box-shadow: var(--shadow-lg);
  outline: none;
}

.ai-info-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 12px;
}

.ai-info-loading {
  font-size: 12.5px;
  color: var(--muted);
  padding: 20px 0;
  text-align: center;
}

.ai-info-body {
  display: flex;
  gap: 16px;
}

.ai-info-left {
  flex-shrink: 0;
}

.ai-review-thumb {
  width: 150px;
  height: 150px;
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

.ai-info-right {
  flex: 1;
  min-width: 0;
  max-height: 320px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.ai-info-note {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.7;
  margin-bottom: 10px;
}

.ai-info-note.error {
  color: var(--danger);
}

.ai-info-none {
  font-size: 11.5px;
  color: var(--muted);
}

.ai-info-meta {
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.6;
  margin-top: 6px;
}

.ai-info-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
