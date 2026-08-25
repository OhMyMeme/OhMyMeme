<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { rememberFocus, restoreFocus, trapTabFocus } from '../utils/api'

interface Candidate {
  id: number
  filename: string
  name: string
  distance: number
}

const visible = ref(false)
const candidates = ref<Candidate[]>([])
const truncated = ref(false)
const scanLimit = ref(0)
const boxEl = ref<HTMLElement>()
const skipEl = ref<HTMLButtonElement>()

let resolveFn: ((action: string | null) => void) | null = null

async function open(cands: Candidate[], truncatedFlag: boolean = false, limit: number = 0): Promise<string | null> {
  if (resolveFn) { resolveFn(null); resolveFn = null }
  candidates.value = cands || []
  truncated.value = !!truncatedFlag
  scanLimit.value = limit || 0
  rememberFocus()
  visible.value = true
  await nextTick()
  // 默认聚焦「跳过」，避免误操作导入/删除
  skipEl.value?.focus()
  return new Promise(resolve => { resolveFn = resolve })
}

function choose(action: string) {
  visible.value = false
  restoreFocus()
  if (resolveFn) { resolveFn(action); resolveFn = null }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.stopPropagation(); choose('discard') }
  else if (boxEl.value) trapTabFocus(boxEl.value, e)
}

function thumbUrl(c: Candidate) {
  return `/api/thumb/${c.id}/${encodeURIComponent(c.filename)}`
}

defineExpose({ open })
</script>

<template>
  <div v-if="visible" class="similimp-overlay" @click.self="choose('discard')">
    <div class="similimp-box" ref="boxEl" role="dialog" aria-modal="true" aria-labelledby="similimp-title" @keydown="onKeydown">
      <div id="similimp-title" class="similimp-title">发现内容近似图片</div>
      <div class="similimp-desc">这张图与库中的以下图片内容几乎一致，但属于不同的文件。请选择如何处理这次导入。</div>
      <div v-if="truncated" class="similimp-truncated">注意：表情库较大，本次仅比对了前 {{ scanLimit }} 张，超出上限的图未参与比对。</div>
      <div class="similimp-cands">
        <div v-for="c in candidates" :key="c.id" class="similimp-cand">
          <img :src="thumbUrl(c)" :alt="c.name" class="similimp-thumb" loading="lazy">
          <div class="similimp-meta">
            <div class="similimp-name" :title="c.name">{{ c.name }}</div>
            <div class="similimp-file" :title="c.filename">{{ c.filename }}</div>
          </div>
        </div>
      </div>
      <div class="similimp-actions">
        <button class="btn btn-primary" @click="choose('keep_new')">保留新图</button>
        <button class="btn btn-secondary" @click="choose('keep_old')">保留旧图</button>
        <button class="btn btn-ghost" @click="choose('keep_both')">都保留</button>
        <button ref="skipEl" class="btn btn-danger" @click="choose('discard')">跳过</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.similimp-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 260;
  animation: fadeIn 0.15s ease;
}

.similimp-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  width: 400px;
  max-height: 82vh;
  overflow-y: auto;
  box-shadow: var(--shadow-lg);
}

.similimp-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 6px;
}

.similimp-desc {
  font-size: 12px;
  color: var(--fg-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
}

.similimp-truncated {
  font-size: 11px;
  color: var(--danger, #ef4444);
  line-height: 1.5;
  margin-bottom: 12px;
}

.similimp-cands {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.similimp-cand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
}

.similimp-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
  background: rgba(0, 0, 0, 0.1);
}

.similimp-meta {
  min-width: 0;
}

.similimp-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--fg);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.similimp-file {
  font-size: 11px;
  color: var(--fg-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.similimp-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
