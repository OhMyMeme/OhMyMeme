<script setup lang="ts">
import { computed } from 'vue'
import { useCollectionBuilder } from '../composables/useCollectionBuilder'
import { trapTabFocus } from '../utils/api'

const cb = useCollectionBuilder()

const isPick = computed(() => cb.pickMode.value !== '')
const pickTitle = computed(() =>
  cb.pickMode.value === 'move' ? '移动到分组' : '加入分组'
)
const confirmLabel = computed(() => {
  if (!isPick.value) return cb.selectedId.value !== null ? '保存到该分组' : '创建分组'
  const verb = cb.pickMode.value === 'move' ? '移动到' : '加入'
  const target = cb.selectedId.value !== null ? '该分组' : '新分组'
  return verb + target
})

function onBoxKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.stopPropagation(); cb.close() }
  else if (e.key === 'Tab') {
    const box = document.getElementById('cb-box')
    if (box) trapTabFocus(box, e)
  }
}
</script>

<template>
  <div v-if="cb.visible.value" id="cb-overlay">
    <div id="cb-box" :class="{ 'cb-box-pick': isPick }" role="dialog" aria-modal="true" aria-labelledby="cb-title" @keydown="onBoxKeydown">
      <div class="cb-header">
        <h2 id="cb-title">{{ isPick ? pickTitle : '添加分组' }}</h2>
        <div v-if="isPick" class="cb-pick-hint">将{{ cb.pickMode.value === 'move' ? '移动' : '加入' }}已选的 {{ cb.selectedIds.value.size }} 个表情包</div>
        <div class="cb-name-wrap">
          <input
            id="cb-name"
            v-model="cb.collectionName.value"
            type="text"
            placeholder="搜索分组或输入新分组名..."
            autocomplete="off"
            spellcheck="false"
            @focus="cb.showDropdown.value = true"
          />
          <div
            v-if="!cb.loading.value && (isPick || cb.showDropdown.value)"
            id="cb-dropdown"
            class="cb-dropdown show"
            :class="{ 'cb-dropdown-inline': isPick }"
          >
            <div class="cb-dd-section" v-if="cb.collectionName.value.trim() || (!isPick && cb.selectedId.value == null)">新建分组</div>
            <div v-if="cb.collectionName.value.trim()" class="cb-dd-item cb-dd-new-item" @click="cb.createNew()">
              <span class="cb-dd-new">「{{ cb.collectionName.value }}」</span>
              <span class="cb-dd-hint">创建新分组</span>
            </div>
            <div class="cb-dd-section">加入已有分组</div>
            <div
              v-for="opt in cb.filteredCollectionOptions.value"
              :key="opt.id"
              class="cb-dd-item"
              :class="{ 'cb-dd-selected': cb.selectedId.value === opt.id }"
              @click="cb.selectCollection(opt)"
            >
              {{ opt.depth || opt.name }}
            </div>
            <div v-if="!cb.filteredCollectionOptions.value.length" class="cb-dd-item cb-dd-hint">无匹配分组</div>
          </div>
        </div>
      </div>

      <div v-if="!isPick" class="cb-search">
        <input
          v-model="cb.searchQuery.value"
          type="text"
          placeholder="搜索表情包添加到分组..."
          autocomplete="off"
          spellcheck="false"
        />
      </div>

      <div v-if="cb.loading.value" class="cb-loading">加载中...</div>

      <div v-else-if="!isPick" id="cb-cols">
        <div class="cb-col">
          <div class="cb-col-title">表情库 ({{ cb.filteredMemes.value.length }})</div>
          <div class="cb-col-list">
            <div
              v-for="meme in cb.filteredMemes.value"
              :key="meme.id"
              class="cb-meme"
              :class="{ selected: cb.selectedIds.value.has(meme.id) }"
              role="button"
              tabindex="0"
              :aria-pressed="cb.selectedIds.value.has(meme.id)"
              :aria-label="meme.name || meme.original_name || meme.filename"
              @click="cb.toggleMeme(meme.id)"
              @keydown.enter.prevent="cb.toggleMeme(meme.id)"
              @keydown.space.prevent="cb.toggleMeme(meme.id)"
            >
              <img :src="`/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`" :alt="meme.name || meme.original_name || meme.filename" loading="lazy">
              <div v-if="cb.selectedIds.value.has(meme.id)" class="cb-check">✓</div>
            </div>
            <div v-if="cb.filteredMemes.value.length === 0" class="cb-empty">没有表情包</div>
          </div>
        </div>

        <div class="cb-col">
          <div class="cb-col-title">已添加 ({{ cb.selectedIds.value.size }})</div>
          <div class="cb-col-list">
            <div
              v-for="meme in cb.allMemes.value.filter(m => cb.selectedIds.value.has(m.id))"
              :key="meme.id"
              class="cb-meme selected"
              role="button"
              tabindex="0"
              :aria-label="meme.name || meme.original_name || meme.filename"
              @click="cb.toggleMeme(meme.id)"
              @keydown.enter.prevent="cb.toggleMeme(meme.id)"
              @keydown.space.prevent="cb.toggleMeme(meme.id)"
            >
              <img :src="`/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`" :alt="meme.name || meme.original_name || meme.filename" loading="lazy">
              <div class="cb-check">✓</div>
            </div>
            <div v-if="cb.selectedIds.value.size === 0" class="cb-empty">点击左侧表情添加到分组</div>
          </div>
        </div>
      </div>

      <div v-if="!isPick && cb.memberLoadError.value" class="cb-error">
        <span>分组信息加载失败，请重试</span>
        <button class="btn btn-sm btn-secondary" @click="cb.retryLoadMembers()">重试</button>
      </div>

      <div class="cb-footer">
        <button class="btn btn-secondary" @click="cb.close()">取消</button>
        <button class="btn btn-primary" :disabled="cb.loading.value || cb.memberLoading.value || cb.memberLoadError.value || !cb.collectionName.value.trim()" @click="cb.confirm()">{{ confirmLabel }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
#cb-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 450;
  animation: fadeIn 0.15s ease;
}

#cb-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 640px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}

/* 选择模式（批量加入/移动分组）：窄弹窗固定高度（受 80vh 限制），
   分组列表内联常显并弹性伸缩，保证底部按钮始终可达。
   带 #cb-box/#cb-dropdown 前缀提升优先级，否则被基础规则的 ID/顺序覆盖 */
#cb-box.cb-box-pick {
  width: 460px;
  height: min(520px, 80vh);
}

#cb-box.cb-box-pick .cb-header {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

#cb-box.cb-box-pick .cb-pick-hint {
  flex-shrink: 0;
}

#cb-box.cb-box-pick .cb-name-wrap {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

#cb-dropdown.cb-dropdown-inline {
  position: static;
  flex: 1 1 auto;
  min-height: 0;
  max-height: none;
  margin-top: 8px;
  box-shadow: none;
}

#cb-box.cb-box-pick .cb-footer {
  flex-shrink: 0;
}

.cb-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.cb-header h2 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
}

.cb-pick-hint {
  font-size: 12px;
  color: var(--muted);
  margin: -6px 0 8px;
}

.cb-name-wrap {
  position: relative;
}

.cb-name-wrap input {
  width: 100%;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--fg);
  font-size: 13px;
  outline: none;
}

.cb-name-wrap input:focus {
  border-color: var(--primary);
}

.cb-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  max-height: 200px;
  overflow-y: auto;
  z-index: 10;
  box-shadow: var(--shadow-lg);
  margin-top: 4px;
}

.cb-dd-item {
  padding: 8px 12px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cb-dd-section {
  padding: 5px 12px;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  background: var(--surface-2);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.cb-dd-selected {
  color: var(--primary);
  font-weight: 600;
}

.cb-dd-item:hover {
  background: var(--surface-2);
}

.cb-dd-new {
  color: var(--primary);
}

.cb-dd-hint {
  font-size: 11px;
  color: var(--muted);
}

.cb-search {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
}

.cb-search input {
  width: 100%;
  padding: 7px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--fg);
  font-size: 13px;
  outline: none;
}

.cb-search input:focus {
  border-color: var(--primary);
}

.cb-loading {
  padding: 40px;
  text-align: center;
  color: var(--muted);
}

#cb-cols {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.cb-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--border);
}

.cb-col:last-child {
  border-right: none;
}

.cb-col-title {
  padding: 8px 14px;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.cb-col-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
  grid-auto-rows: 70px;
  gap: 6px;
  align-content: start;
}

.cb-meme {
  position: relative;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 2px solid var(--border);
  cursor: pointer;
  transition: border-color 0.15s;
}

.cb-meme:hover {
  border-color: var(--primary);
}

.cb-meme.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.3);
}

.cb-meme img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cb-check {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--primary-strong);
  color: white;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cb-empty {
  grid-column: 1 / -1;
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
}

.cb-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 20px;
  font-size: 12px;
  color: var(--danger, #dc2626);
  background: rgba(220, 38, 38, 0.08);
  border-top: 1px solid var(--border);
}

.cb-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
