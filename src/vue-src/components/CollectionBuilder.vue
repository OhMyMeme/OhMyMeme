<script setup lang="ts">
import { useCollectionBuilder } from '../composables/useCollectionBuilder'

const cb = useCollectionBuilder()

function handleConfirm(name: string, ids: number[]) {
  console.log('Create collection:', name, 'with', ids.length, 'memes')
}
</script>

<template>
  <div v-if="cb.visible.value" id="cb-overlay">
    <div id="cb-box">
      <div class="cb-header">
        <h2>添加分组</h2>
        <div class="cb-name-wrap">
          <input
            id="cb-name"
            v-model="cb.collectionName.value"
            type="text"
            placeholder="输入分组名或选择已有分组..."
            autocomplete="off"
            spellcheck="false"
            @focus="cb.showDropdown.value = true"
          />
          <div v-if="cb.showDropdown.value" id="cb-dropdown" class="cb-dropdown show">
            <div v-if="cb.collectionName.value.trim()" class="cb-dd-item cb-dd-new-item" @click="cb.createNew()">
              <span class="cb-dd-new">「{{ cb.collectionName.value }}」</span>
              <span class="cb-dd-hint">新建分组</span>
            </div>
            <div
              v-for="opt in cb.collectionOptions.value"
              :key="opt.id"
              class="cb-dd-item"
              @click="cb.selectCollection(opt)"
            >
              {{ opt.name }}
            </div>
          </div>
        </div>
      </div>

      <div class="cb-search">
        <input
          v-model="cb.searchQuery.value"
          type="text"
          placeholder="搜索表情包添加到分组..."
          autocomplete="off"
          spellcheck="false"
        />
      </div>

      <div v-if="cb.loading.value" class="cb-loading">加载中...</div>

      <div v-else id="cb-cols">
        <div class="cb-col">
          <div class="cb-col-title">表情库 ({{ cb.filteredMemes.value.length }})</div>
          <div class="cb-col-list">
            <div
              v-for="meme in cb.filteredMemes.value"
              :key="meme.id"
              class="cb-meme"
              :class="{ selected: cb.selectedIds.value.has(meme.id) }"
              @click="cb.toggleMeme(meme.id)"
            >
              <img :src="`/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`" :alt="meme.original_name || meme.filename" loading="lazy">
              <div v-if="cb.selectedIds.value.has(meme.id)" class="cb-check">✓</div>
            </div>
            <div v-if="cb.filteredMemes.value.length === 0" class="cb-empty">没有表情包</div>
          </div>
        </div>

        <div class="cb-col">
          <div class="cb-col-title">已添加 ({{ cb.selectedIds.value.size }})</div>
          <div class="cb-col-list">
            <div
              v-for="meme in cb.filteredMemes.value.filter(m => cb.selectedIds.value.has(m.id))"
              :key="meme.id"
              class="cb-meme selected"
              @click="cb.toggleMeme(meme.id)"
            >
              <img :src="`/api/thumb/${meme.id}/${encodeURIComponent(meme.filename)}`" :alt="meme.original_name || meme.filename" loading="lazy">
              <div class="cb-check">✓</div>
            </div>
            <div v-if="cb.selectedIds.value.size === 0" class="cb-empty">点击左侧表情添加到分组</div>
          </div>
        </div>
      </div>

      <div class="cb-footer">
        <button class="btn btn-secondary" @click="cb.close()">取消</button>
        <button class="btn btn-primary" :disabled="!cb.collectionName.value.trim()" @click="cb.confirm()">确定</button>
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

.cb-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.cb-header h2 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
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
  background: var(--primary);
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
