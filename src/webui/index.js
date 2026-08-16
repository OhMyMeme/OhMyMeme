let allTags = [], activeTags = new Set(), memes = [], pending = false, copyPending = false;
let collections = [], activeCollection = null;
let batchMode = false, selectedMemeIds = new Set();
let dragSrcId = null;
const MEME_PAGE = 200;
let memeOffset = 0, memeHasMore = true, memeLoadingMore = false;
let memeGen = 0, cbGen = 0;
let gridRenderToken = 0;
let tagbarCollapsed = false;

function applyGridScale(value) {
  const raw = Number(value);
  const scale = Number.isFinite(raw) ? Math.min(120, Math.max(48, raw)) : 72;
  document.documentElement.style.setProperty('--grid-card-size', scale + 'px');
}

async function loadGridScale() {
  const settings = await api('get_settings');
  applyGridScale(settings && settings.grid_scale);
}

async function api(method, ...args) {
  try {
    if (typeof pywebview === 'undefined' || !pywebview.api) return null;
    return await pywebview.api[method](...args);
  }
  catch(e) { console.error('API error:', method, e); return null; }
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderMarkdown(md) {
  if (!md) return '';
  let s = esc(md);
  // 代码块 ```lang ... ```（先处理，避免内部被后续规则破坏）
  s = s.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (m, lang, code) => {
    return '<pre class="md-pre"><code>' + code + '</code></pre>';
  });
  // 行内代码
  s = s.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>');
  // 标题
  s = s.replace(/^##### (.*)$/gm, '<h5 class="md-h">$1</h5>');
  s = s.replace(/^#### (.*)$/gm, '<h4 class="md-h">$1</h4>');
  s = s.replace(/^### (.*)$/gm, '<h3 class="md-h">$1</h3>');
  s = s.replace(/^## (.*)$/gm, '<h2 class="md-h">$1</h2>');
  s = s.replace(/^# (.*)$/gm, '<h1 class="md-h">$1</h1>');
  // 引用
  s = s.replace(/^&gt; (.*)$/gm, '<blockquote class="md-quote">$1</blockquote>');
  // 无序列表
  s = s.replace(/^[-*] (.*)$/gm, '<li class="md-li">$1</li>');
  // 有序列表
  s = s.replace(/^\d+\. (.*)$/gm, '<li class="md-li">$1</li>');
  // 粗体 / 斜体
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  // 链接
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="md-link">$1</span>');
  // 分割线
  s = s.replace(/^-{3,}$/gm, '<hr class="md-hr">');
  // 其余换行
  s = s.replace(/\n/g, '<br>');
  // 移除块级元素相邻的多余 <br>，避免文字之间空行
  s = s.replace(/(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)\s*<br>/g, '$1');
  s = s.replace(/<br>\s*(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)/g, '$1');
  return s;
}

let searchTimer;
function onSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => refreshMemes(), 300);
}

async function refreshMemes() {
  const q = document.getElementById('search').value.trim();
  const gen = ++memeGen;
  memeOffset = 0; memeHasMore = true;
  try { memes = await api('search_memes', q, [...activeTags], activeCollection, 0, MEME_PAGE) || []; }
  catch(e) { memes = []; }
  if (gen !== memeGen) return;   // 期间查询条件已变，丢弃过期结果
  memeOffset = memes.length;
  memeHasMore = memes.length === MEME_PAGE;
  renderGrid();
}

async function loadMoreMemes() {
  if (memeLoadingMore || !memeHasMore) return;
  memeLoadingMore = true;
  const gen = memeGen;
  const q = document.getElementById('search').value.trim();
  try {
    const more = await api('search_memes', q, [...activeTags], activeCollection, memeOffset, MEME_PAGE) || [];
    if (gen !== memeGen) return;   // 过期响应丢弃
    if (more.length === 0) {
      memeHasMore = false;
    } else {
      memes = memes.concat(more);
      memeOffset += more.length;
      memeHasMore = more.length === MEME_PAGE;
      const grid = document.getElementById('meme-grid');
      const sortEnabled = canReorderMemes();
      const cards = more.map(renderMemeCard);
      if (sortEnabled) cards.forEach(card => card.classList.add('sort-enter'));
      cards.forEach(card => grid.appendChild(card));
      if (sortEnabled) {
        void cards[0].offsetWidth;
        requestAnimationFrame(() => {
          cards.forEach(card => card.classList.remove('sort-enter'));
        });
      }
    }
  } catch(e) {
    memeHasMore = false;
  } finally {
    memeLoadingMore = false;
  }
}

async function refreshTags() {
  try { allTags = await api('get_tags') || []; } catch(e) { allTags = []; }
  renderTags();
}

function renderTags() {
  const bar = document.getElementById('tagbar');
  bar.innerHTML = '';
  allTags.slice(0, 40).forEach(tag => {
    const el = document.createElement('span');
    el.className = 'tag' + (activeTags.has(tag) ? ' active' : '');
    el.textContent = tag;
    el.onclick = () => { toggleTag(tag); };
    bar.appendChild(el);
  });
  renderTagbarState();
}

function renderTagbarState() {
  const panel = document.getElementById('tagbar-panel');
  const button = document.getElementById('tagbar-toggle');
  if (!panel || !button) return;
  panel.classList.toggle('collapsed', tagbarCollapsed);
  button.setAttribute('aria-expanded', String(!tagbarCollapsed));
  button.title = tagbarCollapsed ? '展开标签' : '收起标签';
  button.innerHTML = '标签 <span aria-hidden="true">⌃</span>';
}

async function toggleTagbar() {
  tagbarCollapsed = !tagbarCollapsed;
  renderTagbarState();
  await api('set_tagbar_collapsed', tagbarCollapsed);
}

function toggleTag(tag) {
  if (activeTags.has(tag)) activeTags.delete(tag); else activeTags.add(tag);
  renderTags();
  refreshMemes();
}

async function refreshCollections() {
  try { collections = await api('get_collections') || []; } catch(e) { collections = []; }
  renderTree();
  updateViewContext();
  renderGrid();
}

function renderTree() {
  const tree = document.getElementById('tree');
  tree.innerHTML = '';
  collections.filter(folder => folder.id < 0).forEach(folder => {
    const row = document.createElement('div');
    row.className = 'tree-row' + (activeCollection === folder.id ? ' active' : '');
    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = folder.name;
    row.appendChild(label);
    const count = document.createElement('span');
    count.className = 'tree-count';
    count.textContent = folder.count || 0;
    row.appendChild(count);
    row.onclick = () => openCollection(folder.id);
    tree.appendChild(row);
  });
}

function updateViewContext() {
  const bar = document.getElementById('view-context');
  const name = document.getElementById('view-context-name');
  const folder = collections.find(item => item.id === activeCollection);
  const isFolder = activeCollection > 0 && folder;
  bar.style.display = isFolder ? 'flex' : 'none';
  name.textContent = isFolder ? folder.name : '';
}

function openCollection(cid) {
  activeCollection = cid;
  renderTree();
  updateViewContext();
  refreshMemes();
}

function openAllMemes() {
  activeCollection = null;
  renderTree();
  updateViewContext();
  refreshMemes();
}

async function createFolder() {
  const name = await showPrompt('新建文件夹', '');
  if (!name || !name.trim()) return;
  const r = await api('create_folder', name.trim());
  if (!r?.ok) return showToast((r && r.error) || '创建文件夹失败');
  showToast('文件夹已创建');
  await refreshCollections();
  renderGrid();
}

/* Context Menu State */
let ctxMeme = null;
let ctxFolder = null;
let lastCtxX = 0, lastCtxY = 0;
let folderPickerResolve = null;

function setupHoverPlay(card, img, memeId, filename) {
  const animUrl = '/api/original/' + memeId + '/' + encodeURIComponent(filename);
  const thumbUrl = img.src;
  let hoverTimer = null;
  card.addEventListener('mouseenter', () => { clearTimeout(hoverTimer); hoverTimer = setTimeout(() => { img.src = animUrl; }, 150); });
  card.addEventListener('mouseleave', () => { clearTimeout(hoverTimer); img.src = thumbUrl; });
}

function renderGrid() {
  const grid = document.getElementById('meme-grid');
  const empty = document.getElementById('empty');
  const folderHome = activeCollection === null && !batchMode &&
    !document.getElementById('search').value.trim() && activeTags.size === 0;
  const sortEnabled = canReorderMemes();
  const renderToken = ++gridRenderToken;
  grid.classList.remove('sort-enabled');
  grid.innerHTML = '';

  if (folderHome) {
    grid.style.display = 'grid';
    empty.style.display = 'none';
    collections.filter(folder => folder.id > 0).forEach(folder => {
      grid.appendChild(renderFolderCard(folder));
    });
    memes.forEach(m => grid.appendChild(renderMemeCard(m)));
  } else if (!memes || memes.length === 0) {
    grid.style.display = 'none';
    empty.style.display = 'flex';
  } else {
    grid.style.display = 'grid';
    empty.style.display = 'none';
    memes.forEach(m => grid.appendChild(renderMemeCard(m)));
  }

  if (sortEnabled) void grid.offsetWidth;
  requestAnimationFrame(() => {
    if (renderToken !== gridRenderToken) return;
    grid.classList.toggle('sort-enabled', sortEnabled);
  });
}

function renderFolderCard(folder) {
  const card = document.createElement('div');
  card.className = 'folder-card';
  card.dataset.folderId = folder.id;
  card.title = '打开文件夹：' + folder.name;
  const icon = document.createElement('div');
  icon.className = 'folder-icon';
  icon.innerHTML = '<span></span>';
  card.appendChild(icon);
  const name = document.createElement('div');
  name.className = 'folder-name';
  name.textContent = folder.name;
  card.appendChild(name);
  const count = document.createElement('div');
  count.className = 'folder-count';
  count.textContent = (folder.count || 0) + ' 个表情';
  card.appendChild(count);
  card.onclick = () => openCollection(folder.id);
  card.oncontextmenu = (e) => {
    e.preventDefault();
    showColTagMenu(e, folder);
  };
  return card;
}

function renderMemeCard(m) {
  const card = document.createElement('div');
  card.className = 'meme-card';
  card.title = m.name;
  card.style.background = 'var(--surface)';
  card.dataset.memeId = m.id;
  const img = document.createElement('img');
  img.alt = m.name;
  img.loading = 'lazy';
  img.draggable = false;
  const animateInGrid = m.is_animated && m.auto_play_gif && !m.hover_to_play;
  if (animateInGrid) {
    img.src = '/api/original/' + m.id + '/' + encodeURIComponent(m.filename);
  } else {
    img.src = '/api/thumb/' + m.id + '/' + encodeURIComponent(m.filename);
  }
  if (m.is_animated && m.hover_to_play) {
    setupHoverPlay(card, img, m.id, m.filename);
  }
  card.appendChild(img);

  const dn = m.name.length > 16 ? m.name.slice(0, 13) + '..' : m.name;
  const name = document.createElement('div');
  name.className = 'name';
  name.textContent = dn;
  card.appendChild(name);

  if (m.from_stego) {
    const badge = document.createElement('span');
    badge.className = 'gif-badge stego-badge';
    badge.textContent = '隐写导入';
    card.appendChild(badge);
  } else if (m.is_animated) {
    const badge = document.createElement('span');
    badge.className = 'gif-badge';
    badge.textContent = m.is_gif ? 'GIF' : 'WebP';
    card.appendChild(badge);
  }

  if (batchMode) {
    const selected = selectedMemeIds.has(m.id);
    card.classList.toggle('selected', selected);
    card.setAttribute('aria-pressed', String(selected));
    const selectionMark = document.createElement('span');
    selectionMark.className = 'selection-mark';
    selectionMark.setAttribute('aria-hidden', 'true');
    selectionMark.textContent = selected ? '✓' : '';
    card.appendChild(selectionMark);
    card.onclick = () => toggleBatchSelection(m.id);
  } else {
    card.onclick = () => copyMeme(m.id, m.name);
  }
  card.oncontextmenu = (e) => { e.preventDefault(); showCtxMenu(e, m); };
  card.draggable = false;
  return card;
}

/* Drag-to-reorder (only enabled in the unfiltered "all memes" view)
 * 模型驱动：memes 数组为唯一真源，拖拽跨槽实时同步 DOM，落点持久化；
 * Pointer Events + 指针捕获，网格感知插入点，FLIP 让位动画 */
let memeDrag = null;
let ignoreClick = false;
let dragSortEnabled = false;

function renderDragSortToggle() {
  const btn = document.getElementById('drag-sort-toggle');
  if (!btn) return;
  btn.classList.toggle('sort-on', dragSortEnabled);
  btn.classList.toggle('sort-off', !dragSortEnabled);
}

function toggleDragSort() {
  dragSortEnabled = !dragSortEnabled;
  renderDragSortToggle();
  if (dragSortEnabled) {
    refreshMemes();
  } else {
    const renderToken = ++gridRenderToken;
    const grid = document.getElementById('meme-grid');
    requestAnimationFrame(() => {
      if (renderToken !== gridRenderToken || dragSortEnabled) return;
      grid.classList.remove('sort-enabled');
    });
  }
}

function canReorderMemes() {
  const q = document.getElementById('search').value.trim();
  if (q || activeTags.size > 0) return false;
  if (batchMode) return false;
  if (!dragSortEnabled) return false;
  return activeCollection === null || activeCollection > 0;
}

function memeCardsInGrid() {
  return Array.from(document.querySelectorAll('#meme-grid .meme-card:not(.folder-card)'));
}

function gridMetrics() {
  const grid = document.getElementById('meme-grid');
  const gRect = grid.getBoundingClientRect();
  const cards = memeCardsInGrid();
  if (!cards.length) return null;
  const style = getComputedStyle(grid);
  const finiteStyleValue = (value) => {
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };
  const paddingLeft = finiteStyleValue(style.paddingLeft);
  const paddingRight = finiteStyleValue(style.paddingRight);
  const paddingTop = finiteStyleValue(style.paddingTop);
  const columnGap = finiteStyleValue(style.columnGap);
  const rowGap = finiteStyleValue(style.rowGap);
  const cardWidth = cards[0].offsetWidth;
  const cardHeight = cards[0].offsetHeight;
  const contentWidth = grid.clientWidth - paddingLeft - paddingRight;
  return {
    originX: gRect.left + grid.clientLeft + paddingLeft,
    originY: gRect.top + grid.clientTop + paddingTop,
    pitchX: cardWidth + columnGap,
    pitchY: cardHeight + rowGap,
    cols: Math.max(1, Math.round((contentWidth + columnGap) / (cardWidth + columnGap))),
  };
}

function gridSlotIndex(x, y) {
  const m = gridMetrics();
  if (!m) return 0;
  const { originX, originY, pitchX, pitchY, cols } = m;
  const col = Math.max(0, Math.min(Math.floor((x - originX) / pitchX), cols - 1));
  const row = Math.max(0, Math.floor((y - originY) / pitchY));
  const all = memeCardsInGrid();
  const slot = Math.min(row * cols + col, all.length - 1);
  return Math.max(0, Math.min(slot, all.length - 1));
}

function moveInArray(arr, from, to) {
  const [item] = arr.splice(from, 1);
  arr.splice(to, 0, item);
}

function cleanupMemeDrag() {
  const d = memeDrag;
  if (!d) return null;
  memeDrag = null;
  const grid = document.getElementById('meme-grid');
  d.card.classList.remove('dragging');
  d.card.style.transform = '';
  grid.classList.remove('drag-active');
  memeCardsInGrid().forEach(c => {
    c.style.transform = '';
    c.style.transition = '';
    c.style.borderTop = '';
    c.style.borderBottom = '';
  });
  return d;
}

function cancelMemeDrag() {
  const d = cleanupMemeDrag();
  if (!d || !d.active) return;
  if (d.natDrag) return; // 原生拖拽路径不重置排序
  memes = d.originalOrder;
  renderGrid();
}

function initDragReorder() {
  const grid = document.getElementById('meme-grid');
  const POINTER = window.PointerEvent != null;
  const pointerId = (e) => (POINTER ? e.pointerId : null);

  const onDown = (e) => {
    ignoreClick = false;
    if ((e.pointerType || 'mouse') === 'mouse' && e.button !== 0) return;
      const card = e.target.closest('.meme-card');
    if (!card || batchMode) return;
    const q = document.getElementById('search').value.trim();
    const filtering = !!(q || activeTags.size > 0);
    // 搜索/筛选时只允许原生拖出到外部应用，不参与内部排序。
    if (!filtering && dragSortEnabled && !canReorderMemes()) return;
    const rect = card.getBoundingClientRect();
    memeDrag = {
      card,
      offX: e.clientX - rect.left,
      offY: e.clientY - rect.top,
      active: false,
      originalOrder: memes.slice(),
      base: rect,
      // 搜索/筛选或关闭排序时用于原生拖拽（拖出到外部应用）的起点
      startX: e.clientX,
      startY: e.clientY,
      natDrag: filtering || !dragSortEnabled,
    };
  };

  let dropTargetFolder = null;

  function clearFolderHighlight() {
    if (dropTargetFolder) {
      dropTargetFolder.classList.remove('drop-target');
      dropTargetFolder = null;
    }
  }

  function findFolderDropTarget(x, y) {
    const elem = document.elementFromPoint(x, y);
    return elem && elem.closest && elem.closest('.folder-card[data-folder-id]');
  }

  const onMove = (e) => {
    const d = memeDrag;
    if (!d) return;
    const movedEnough = Math.hypot(e.clientX - d.startX, e.clientY - d.startY) > 8;
    const folderCard = findFolderDropTarget(e.clientX, e.clientY);
    if (folderCard && Number(folderCard.dataset.folderId) > 0 && movedEnough) {
      clearFolderHighlight();
      dropTargetFolder = folderCard;
      folderCard.classList.add('drop-target');
      d.active = true;
      if (POINTER && pointerId(e) != null) {
        try { grid.setPointerCapture(pointerId(e)); } catch (_) {}
      }
      return;
    }
    clearFolderHighlight();
    // 排序关闭时，窗口内拖动优先用于投放到文件夹；只有拖出窗口才启动原生文件拖拽。
    if (d.natDrag) {
      if (!movedEnough) return;
      if (!d.active) {
        d.active = true;
        if (POINTER && pointerId(e) != null) {
          try { grid.setPointerCapture(pointerId(e)); } catch (_) {}
        }
      }
      const outsideWindow = e.clientX < 0 || e.clientY < 0 ||
        e.clientX > window.innerWidth || e.clientY > window.innerHeight;
      if (!outsideWindow) return;
      const id = Number(d.card.dataset.memeId);
      api('start_native_drag', id).then((ok) => {
        ignoreClick = true;
        if (!ok && memeDrag === d) { d.active = false; showToast('拖拽失败：本地文件不存在'); }
        if (memeDrag === d) cleanupMemeDrag();
      }).catch(() => { if (memeDrag === d) cleanupMemeDrag(); });
      return;
    }
    if (!d.active) {
      const rect = d.card.getBoundingClientRect();
      if (Math.hypot(e.clientX - d.offX - rect.left, e.clientY - d.offY - rect.top) <= 8) return;
      d.active = true;
      d.card.classList.add('dragging');
      grid.classList.add('drag-active');
      if (POINTER && pointerId(e) != null) {
        try { grid.setPointerCapture(pointerId(e)); } catch (_) {}
      }
    }
    const dragX = e.clientX - d.offX - d.base.left;
    const dragY = e.clientY - d.offY - d.base.top;
    d.card.style.transform = 'translate(' + dragX + 'px,' + dragY + 'px) scale(0.90)';
    const all = memeCardsInGrid();
    const cur = all.indexOf(d.card);
    const target = gridSlotIndex(e.clientX, e.clientY);
    if (target === cur) return;
    const lo = Math.min(cur, target), hi = Math.max(cur, target);
    const affected = all.slice(lo, hi + 1).filter(c => c !== d.card);
    const firstRects = affected.map(c => c.getBoundingClientRect());
    moveInArray(memes, cur, target);
    if (target < cur) grid.insertBefore(d.card, all[target]);
    else grid.insertBefore(d.card, all[target].nextSibling);
    const lastRects = affected.map(c => c.getBoundingClientRect());
    affected.forEach((c, i) => {
      c.style.transition = 'none';
      c.style.transform = 'translate(' + (firstRects[i].left - lastRects[i].left) + 'px,' + (firstRects[i].top - lastRects[i].top) + 'px) scale(0.95)';
    });
    requestAnimationFrame(() => {
      affected.forEach(c => { c.style.transition = ''; c.style.transform = ''; });
    });
    const prevTf = d.card.style.transform;
    d.card.style.transform = '';
    d.base = d.card.getBoundingClientRect();
    d.card.style.transform = prevTf;
    const updatedDragX = e.clientX - d.offX - d.base.left;
    const updatedDragY = e.clientY - d.offY - d.base.top;
    d.card.style.transform = 'translate(' + updatedDragX + 'px,' + updatedDragY + 'px) scale(0.90)';
  };

  const onUp = async (e) => {
    const d = memeDrag;
    if (!d) return;
    if (POINTER && pointerId(e) != null) {
      try { grid.releasePointerCapture(pointerId(e)); } catch (_) {}
    }
    const wasActive = d.active;
    const folderDrop = dropTargetFolder;
    cleanupMemeDrag();
    clearFolderHighlight();
    if (folderDrop) {
      ignoreClick = true;
      const fid = Number(folderDrop.dataset.folderId);
      const mid = Number(d.card.dataset.memeId);
      const mode = await chooseFolderDropMode();
      if (!mode) return;
      const r = await api('add_to_folder', mid, fid, mode);
      if (r?.ok) {
        showToast(mode === 'move' ? '已移动到文件夹并自动加标签' : '已复制到文件夹并自动加标签');
        refreshTags();
        refreshCollections();
        refreshMemes();
      } else {
        showToast((r && r.error) || '放入文件夹失败');
      }
      return;
    }
    if (!wasActive) return;
    ignoreClick = true;
    if (d.natDrag) return; // 原生拖拽路径不持久化排序
    const ordered = memes.map(x => x.id).join(',');
    if (ordered !== d.originalOrder.map(x => x.id).join(',')) {
      let ok;
      if (activeCollection > 0) {
        ok = await api('reorder_collection_members', activeCollection, memes.map(x => x.id));
      } else {
        ok = await api('reorder_memes', memes.map(x => x.id));
      }
      if (!ok) {
        memes = d.originalOrder;
        renderGrid();
        showToast('排序保存失败');
      }
    }
  };

  if (POINTER) {
    grid.addEventListener('pointerdown', onDown);
    grid.addEventListener('pointermove', onMove);
    grid.addEventListener('pointerup', onUp);
    grid.addEventListener('pointercancel', () => cancelMemeDrag());
  } else {
    grid.addEventListener('mousedown', onDown);
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
  window.addEventListener('blur', () => cancelMemeDrag());
}

async function copyMeme(id, filename) {
  if (ignoreClick) { ignoreClick = false; return; }
  if (copyPending) return;
  copyPending = true;
  let result;
  try {
    result = await api('copy_meme', id);
  } finally {
    copyPending = false;
  }
  if (result?.ok) {
    showToast(filename + ' 已复制');
    if (activeCollection === -3) refreshMemes();
    refreshCollections();
  }
  else { showToast('复制失败'); }
}

async function pasteMemeToChat(meme) {
  if (!meme || copyPending) return;
  const confirmed = await showConfirm(
    '复制并粘贴',
    '将复制「' + meme.name + '」并尝试粘贴到你按全局快捷键前处于前台的 QQ 或微信窗口。不会按 Enter，也不会发送消息。'
  );
  if (!confirmed) return;
  copyPending = true;
  let result;
  try {
    result = await api('paste_meme_to_chat', meme.id);
  } finally {
    copyPending = false;
  }
  if (!result || !result.ok) {
    showToast('复制失败');
    return;
  }
  if (result.status === 'paste_attempted') {
    showToast('已粘贴到聊天输入框，未发送');
  } else {
    showToast('表情已复制，请切回目标群聊后按 Ctrl+V');
  }
  if (activeCollection === -3) refreshMemes();
  refreshCollections();
}

function toggleFloatingWindow() {
  api('toggle_floating_window');
}

function updateBatchUi() {
  const bar = document.getElementById('batch-bar');
  const toggle = document.getElementById('batch-toggle');
  const count = document.getElementById('batch-count');
  if (bar) bar.style.display = batchMode ? 'flex' : 'none';
  if (toggle) toggle.textContent = batchMode ? '退出批量' : '批量管理';
  if (count) count.textContent = '已选 ' + selectedMemeIds.size + ' 项';
}

function toggleBatchMode() {
  batchMode = !batchMode;
  selectedMemeIds.clear();
  updateBatchUi();
  renderGrid();
}

function toggleBatchSelection(memeId) {
  if (selectedMemeIds.has(memeId)) selectedMemeIds.delete(memeId);
  else selectedMemeIds.add(memeId);
  updateBatchUi();
  renderGrid();
}

function batchSelectAll() {
  memes.forEach(m => selectedMemeIds.add(m.id));
  updateBatchUi();
  renderGrid();
}

function batchClearSelection() {
  selectedMemeIds.clear();
  updateBatchUi();
  renderGrid();
}

function selectedBatchIds() {
  return [...selectedMemeIds];
}

async function batchTags() {
  const ids = selectedBatchIds();
  if (!ids.length) return showToast('请先选择表情');
  const text = await showPrompt('批量标签（以逗号分隔）', '');
  if (text === null) return;
  const mode = await showConfirm('标签方式', '确定为“覆盖”标签；取消则追加标签。');
  const tags = text.split(/[,，]/).map(x => x.trim()).filter(Boolean);
  const r = await api('batch_set_tags', ids, tags, mode ? 'replace' : 'append');
  if (r?.ok) { showToast('已更新 ' + r.count + ' 项标签'); refreshTags(); refreshMemes(); }
  else showToast((r && r.error) || '标签保存失败');
}

async function chooseFolder() {
  const options = (await api('search_collections') || []).map(c => [c.name, c.id]);
  if (!options.length) {
    showToast('请先新建文件夹');
    return null;
  }
  return showFolderPicker(options);
}

async function batchFolder(mode) {
  const ids = selectedBatchIds();
  if (!ids.length) return showToast('请先选择表情');
  const folderId = await chooseFolder();
  if (!folderId || folderId <= 0) return;
  let success = 0;
  for (const memeId of ids) {
    const r = await api('add_to_folder', memeId, folderId, mode);
    if (r?.ok) success++;
  }
  if (!success) return showToast('放入文件夹失败');
  selectedMemeIds.clear();
  updateBatchUi();
  showToast((mode === 'move' ? '已移动 ' : '已复制 ') + success + ' 项并自动加标签');
  await refreshTags();
  await refreshCollections();
  refreshMemes();
}

async function batchDelete() {
  const ids = selectedBatchIds();
  if (!ids.length) return showToast('请先选择表情');
  const preview = await api('batch_delete_preview', ids);
  if (!preview?.ok) return showToast('无法获取删除预览');
  const mb = (preview.total_size / 1048576).toFixed(2);
  if (!await showConfirm('批量删除确认', '将删除 ' + preview.count + ' 项，约 ' + mb + ' MB。此操作不可恢复。')) return;
  const r = await api('batch_delete_memes', ids);
  if (r?.ok) {
    selectedMemeIds.clear();
    showToast('已删除 ' + r.count + ' 项');
    updateBatchUi(); refreshMemes(); refreshTags(); refreshCollections();
  } else showToast((r && r.error) || '删除失败');
}

async function exportPack() {
  const ids = selectedBatchIds();
  if (!ids.length) return showToast('请先选择表情');
  const r = await api('export_pack', ids);
  if (r?.ok) showToast('已导出 ' + r.count + ' 项分享包');
  else if (!r?.cancelled) showToast((r && r.error) || '导出失败');
}

async function importPack() {
  closeImportMenu();
  if (pending) return;
  pending = true;
  const r = await api('import_pack');
  pending = false;
  if (!r || r.cancelled) return;
  if (r.ok) {
    showToast(appendRejectedMsg('已导入 ' + r.imported + ' 项分享包内容', r.rejected));
    refreshMemes(); refreshTags(); refreshCollections();
  } else showToast(r.error || '导入失败');
}

function showImportMenu() {
  document.getElementById('import-overlay').style.display = 'flex';
}

function closeImportMenu() {
  document.getElementById('import-overlay').style.display = 'none';
}

function appendRejectedMsg(msg, count) {
  return count ? msg + '，跳过 ' + count + ' 个超限文件' : msg;
}

async function importLocal() {
  closeImportMenu();
  if (pending) return;
  pending = true;
  const result = await api('import_memes');
  pending = false;
  if (result && result.ok) {
    const msg = result.imported > 0 ? '导入完成' : '未导入文件';
    showToast(appendRejectedMsg(msg, result.rejected));
    refreshMemes(); refreshTags(); refreshCollections();
  }
}

async function importFolder() {
  closeImportMenu();
  if (pending) return;
  const makeGroup = document.getElementById('import-folder-group')?.checked !== false;
  pending = true;
  const r = await api('import_folder', makeGroup);
  pending = false;
  if (!r) return;
  if (!r.ok) { if (r.cancelled) return; showToast(r.error || '导入失败'); return; }
  let msg = r.imported > 0
    ? appendRejectedMsg('导入完成，共 ' + r.imported + ' 个表情', r.rejected)
    : appendRejectedMsg('未导入文件', r.rejected);
  if (r.folder_name) msg += '，已放入文件夹「' + r.folder_name + '」并自动加标签';
  showToast(msg);
  refreshMemes(); refreshTags(); refreshCollections();
}

async function importClipboard() {
  closeImportMenu();
  if (pending) return;
  pending = true;
  const result = await api('import_from_clipboard');
  pending = false;
  if (!result) { showToast('导入失败'); return; }
  if (!result.ok) { showToast(result.error || '导入失败'); return; }
  if (result.id > 0) {
    const newName = await showPrompt('重命名', result.name || '');
    if (newName && newName !== result.name) {
      await api('rename_meme', result.id, newName);
    }
    showToast(appendRejectedMsg('导入完成', result.rejected));
    refreshMemes(); refreshTags(); refreshCollections();
  } else {
    showToast(appendRejectedMsg('未导入文件', result.rejected));
  }
}

function importQQ() {
  closeImportMenu();
  openSettings();  // opens settings.html which has the QQ import button
}

async function rescanCache() {
  await api('rescan_cache');
  showToast('缓存扫描完成');
  refreshMemes();
  refreshTags();
  refreshCollections();
}

/* Context Menu */
function showMenuAt(menu, x, y) {
  menu.classList.add('show');
  const rect = menu.getBoundingClientRect();
  const left = Math.max(4, Math.min(x, window.innerWidth - rect.width - 4));
  const top = Math.max(4, Math.min(y, window.innerHeight - rect.height - 4));
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
}

function showCtxMenu(e, meme) {
  hideFolderPicker();
  ctxMeme = meme;
  ctxFolder = null;
  lastCtxX = e.clientX;
  lastCtxY = e.clientY;
  const menu = document.getElementById('ctx-menu');
  menu.querySelectorAll('.ctx-item, .ctx-divider').forEach(el => {
    el.style.display = '';
  });
  menu.querySelector('[data-action="rename-folder"]').style.display = 'none';
  menu.querySelector('[data-action="delete-folder"]').style.display = 'none';
  const favorite = menu.querySelector('[data-action="favorite"]');
  favorite.textContent = meme.favorited ? '取消收藏' : '收藏';
  menu.querySelector('[data-action="remove-from-folder"]').style.display =
    activeCollection > 0 ? 'flex' : 'none';
  menu.querySelector('[data-action="remove-recent"]').style.display =
    activeCollection === -3 ? 'flex' : 'none';
  showMenuAt(menu, e.clientX, e.clientY);
}

function showColTagMenu(e, folder) {
  hideCtxMenu();
  lastCtxX = e.clientX;
  lastCtxY = e.clientY;
  const menu = document.getElementById('ctx-menu');
  menu.querySelectorAll('.ctx-item, .ctx-divider').forEach(el => {
    el.style.display = 'none';
  });
  if (folder.id > 0) {
    ctxFolder = { id: folder.id, name: folder.name };
    menu.querySelector('[data-action="rename-folder"]').style.display = 'flex';
    menu.querySelector('[data-action="delete-folder"]').style.display = 'flex';
    showMenuAt(menu, e.clientX, e.clientY);
  } else if (folder.id === -3) {
    ctxFolder = null;
    menu.querySelector('[data-action="clear-recent"]').style.display = 'flex';
    showMenuAt(menu, e.clientX, e.clientY);
  }
}

function hideCtxMenu() {
  if (folderPickerResolve) {
    const resolve = folderPickerResolve;
    folderPickerResolve = null;
    resolve(null);
  }
  document.getElementById('ctx-menu').classList.remove('show');
  document.getElementById('ctx-folder-menu').classList.remove('show');
  ctxMeme = null;
  ctxFolder = null;
}

function showFolderPicker(items) {
  return new Promise(resolve => {
    folderPickerResolve = resolve;
    const menu = document.getElementById('ctx-folder-menu');
    menu.innerHTML = '';
    items.forEach(([label, value]) => {
      const button = document.createElement('button');
      button.className = 'ctx-item';
      button.textContent = label;
      button.onclick = () => {
        folderPickerResolve = null;
        menu.classList.remove('show');
        resolve(value);
      };
      menu.appendChild(button);
    });
    menu.classList.add('show');
    const rect = menu.getBoundingClientRect();
    menu.style.left = Math.max(4, Math.min(lastCtxX, window.innerWidth - rect.width - 4)) + 'px';
    menu.style.top = Math.max(4, Math.min(lastCtxY, window.innerHeight - rect.height - 4)) + 'px';
  });
}

function hideFolderPicker() {
  if (folderPickerResolve) {
    const resolve = folderPickerResolve;
    folderPickerResolve = null;
    resolve(null);
  }
  document.getElementById('ctx-folder-menu').classList.remove('show');
}

document.addEventListener('click', (e) => {
  if (e.button === 0 && !e.target.closest('#ctx-menu') && !e.target.closest('#ctx-folder-menu')) hideCtxMenu();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const menu = document.getElementById('ctx-menu');
    const sub = document.getElementById('ctx-folder-menu');
    if ((menu && menu.classList.contains('show')) || (sub && sub.classList.contains('show'))) {
      hideCtxMenu();
    } else {
      hide();
    }
  }
});

document.getElementById('ctx-menu').addEventListener('click', async (e) => {
  const item = e.target.closest('.ctx-item');
  if (!item || item.classList.contains('disabled')) return;
  const action = item.dataset.action;
  const folder = ctxFolder;
  const meme = ctxMeme;
  const folderAction = ['rename-folder', 'delete-folder', 'clear-recent'].includes(action);
  if (!meme && !folderAction) return;
  hideCtxMenu();

  if (action === 'rename-folder') {
    if (!folder) return;
    const name = await showPrompt('重命名文件夹', folder.name);
    if (!name || name.trim() === folder.name) return;
    const ok = await api('rename_folder', folder.id, name.trim());
    showToast(ok ? '文件夹已重命名' : '重命名失败');
    if (ok) await refreshCollections();
    return;
  }

  if (action === 'delete-folder') {
    if (!folder) return;
    const ok = await showConfirm(
      '删除文件夹',
      '确定删除文件夹「' + folder.name + '」？表情文件和文件夹同名标签都会保留。'
    );
    if (!ok) return;
    const deleted = await api('delete_folder', folder.id);
    if (!deleted) return showToast('删除文件夹失败');
    if (activeCollection === folder.id) activeCollection = null;
    showToast('文件夹已删除，表情和标签已保留');
    await refreshCollections();
    refreshMemes();
    return;
  }

  switch (action) {
    case 'rename': {
      const name = await showPrompt('重命名', meme.name);
      if (!name || name === meme.name) return;
      const ok = await api('rename_meme', meme.id, name);
      showToast(ok ? '重命名成功' : '重命名失败');
      if (ok) refreshMemes();
      break;
    }
    case 'favorite': {
      const ok = await api('toggle_favorite', meme.id);
      if (ok === null) break;
      await refreshCollections();
      if (!ok && activeCollection === -2 && !(collections.find(x => x.id === -2)?.count)) {
        activeCollection = null;
      }
      refreshMemes();
      showToast(ok ? '已收藏' : '已取消收藏');
      break;
    }
    case 'tag': {
      const tags = await showTagEditor(meme.id);
      if (tags === null) break;
      const ok = await api('set_meme_tags', meme.id, tags);
      if (!ok) return showToast('标签保存失败');
      showToast(tags.length ? '标签已更新' : '已清除标签');
      const fresh = await api('get_tags') || [];
      [...activeTags].forEach(tag => { if (!fresh.includes(tag)) activeTags.delete(tag); });
      refreshTags();
      refreshMemes();
      break;
    }
    case 'paste-chat':
      await pasteMemeToChat(meme);
      break;
    case 'ai-edit': {
      const prompt = await showPrompt('AI 编辑副本', '');
      if (!prompt || !prompt.trim()) break;
      const started = await api('ai_edit', meme.id, prompt.trim());
      if (!started?.ok) return showToast((started && started.error) || '无法启动 AI 编辑');
      showToast('AI 编辑已开始，原图会保留');
      pollAiEditProgress();
      break;
    }
    case 'put-in-folder': {
      const folderId = await chooseFolder();
      if (!folderId) break;
      const mode = await chooseFolderDropMode();
      if (!mode) break;
      const result = await api('add_to_folder', meme.id, folderId, mode);
      if (!result?.ok) return showToast((result && result.error) || '放入文件夹失败');
      showToast(mode === 'move' ? '已移动到文件夹并自动加标签' : '已复制到文件夹并自动加标签');
      await refreshTags();
      await refreshCollections();
      refreshMemes();
      break;
    }
    case 'remove-from-folder': {
      if (activeCollection <= 0) break;
      const ok = await api('remove_from_folder', meme.id, activeCollection);
      if (!ok) return showToast('移出文件夹失败');
      showToast('已从当前文件夹移出，标签已保留');
      await refreshCollections();
      refreshMemes();
      break;
    }
    case 'delete': {
      const confirmed = await showConfirm('删除确认', '确定删除「' + meme.name + '」？');
      if (!confirmed) return;
      const ok = await api('delete_meme', meme.id);
      if (!ok) return showToast('删除失败');
      showToast('已删除');
      refreshMemes();
      refreshTags();
      refreshCollections();
      break;
    }
    case 'remove-recent': {
      const ok = await api('remove_from_recent', meme.id);
      if (!ok) return showToast('操作失败');
      showToast('已从最近使用中删除');
      await refreshCollections();
      if (!(collections.find(x => x.id === -3)?.count) && activeCollection === -3) activeCollection = null;
      refreshMemes();
      break;
    }
    case 'clear-recent': {
      const confirmed = await showConfirm('清空最近使用', '确定清空最近使用列表？');
      if (!confirmed) return;
      const ok = await api('clear_recent');
      if (!ok) return showToast('操作失败');
      showToast('已清空最近使用');
      await refreshCollections();
      if (activeCollection === -3) activeCollection = null;
      refreshMemes();
      break;
    }
  }
});

/* Tag Editor Modal */
function showTagEditor(memeId) {
  return new Promise(async resolve => {
    let all = [];
    let cur = [];
    try {
      all = await api('get_tags') || [];
      cur = await api('get_meme_tags', memeId) || [];
    } catch(e) {
      showToast('标签加载失败');
      resolve(null);
      return;
    }
    const selected = cur.slice();

    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
    overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(null); } };

    const box = document.createElement('div');
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:20px 24px;width:420px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:14px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:4px">编辑标签</h2></div>'
      + '<input id="tag-editor-input" placeholder="搜索已有标签或输入新标签，回车添加" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);color:var(--fg);font-size:13px;outline:none;font-family:inherit;box-sizing:border-box;margin-bottom:10px">'
      + '<div id="tag-editor-list" style="max-height:200px;overflow-y:auto;display:flex;flex-wrap:wrap;gap:6px;padding:4px 0;margin-bottom:10px"></div>'
      + '<div id="tag-editor-selected" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;min-height:0"></div>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end">'
      + '<button id="tag-editor-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="tag-editor-confirm" class="btn btn-primary">确定</button>'
      + '</div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    const input = document.getElementById('tag-editor-input');
    const listEl = document.getElementById('tag-editor-list');
    const selEl = document.getElementById('tag-editor-selected');

    function renderSelected() {
      selEl.innerHTML = '';
      selected.forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'tag active';
        chip.textContent = tag + ' ×';
        chip.onclick = () => { selected.splice(selected.indexOf(tag), 1); renderList(); renderSelected(); };
        selEl.appendChild(chip);
      });
      if (selected.length === 0) selEl.style.display = 'none';
      else selEl.style.display = '';
    }

    function renderList() {
      listEl.innerHTML = '';
      const q = input.value.trim().toLowerCase();
      const fresh = all.filter(t => q ? t.toLowerCase().includes(q) : true);
      fresh.forEach(tag => {
        const el = document.createElement('span');
        el.className = 'tag' + (selected.includes(tag) ? ' active' : '');
        el.textContent = tag;
        el.onclick = () => {
          const i = selected.indexOf(tag);
          if (i >= 0) selected.splice(i, 1); else selected.push(tag);
          renderList(); renderSelected();
        };
        listEl.appendChild(el);
      });
      if (fresh.length === 0) {
        const empty = document.createElement('div');
        empty.style.cssText = 'font-size:12px;color:var(--muted);width:100%;text-align:center;padding:8px 0';
        empty.textContent = q ? '无匹配标签，回车创建"' + input.value.trim() + '"' : '暂无标签';
        listEl.appendChild(empty);
      }
    }

    function addFromInput() {
      const v = input.value.trim();
      if (!v) return;
      if (!selected.includes(v)) selected.push(v);
      input.value = '';
      renderList(); renderSelected();
    }

    input.addEventListener('input', renderList);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); addFromInput(); }
    });
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        overlay.remove();
        resolve(null);
      }
    });

    document.getElementById('tag-editor-confirm').onclick = () => {
      const v = input.value.trim();
      if (v && !selected.includes(v)) selected.push(v);
      overlay.remove();
      resolve(selected);
    };
    document.getElementById('tag-editor-cancel').onclick = () => { overlay.remove(); resolve(null); };

    renderList();
    renderSelected();
    input.focus();
  });
}

/* Custom Modal */
function showPrompt(title, defaultValue) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
    overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(null); } };
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:360px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:16px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:4px">' + esc(title) + '</h2></div>'
      + '<input id="modal-input" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);color:var(--fg);font-size:13px;outline:none;font-family:inherit;box-sizing:border-box" value="' + esc(defaultValue) + '">'
      + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">'
      + '<button id="modal-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="modal-confirm" class="btn btn-primary">确定</button>'
      + '</div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    const input = document.getElementById('modal-input');
    input.focus();
    input.select();
    const cleanup = () => { overlay.remove(); };
    document.getElementById('modal-confirm').onclick = () => { const v = input.value; cleanup(); resolve(v); };
    document.getElementById('modal-cancel').onclick = () => { cleanup(); resolve(null); };
    input.onkeydown = (e) => {
      if (e.key === 'Enter') { const v = input.value; cleanup(); resolve(v); }
      if (e.key === 'Escape') { cleanup(); resolve(null); }
    };
  });
}

function showUpdateDialogFromMain(current, latest, url, notes) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:300;animation:fadeIn .15s';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  const box = document.createElement('div');
  box.className = 'upd-dialog';
  box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:440px;max-height:80vh;overflow-y:auto;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
  box.innerHTML = '<div style="margin-bottom:16px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">发现新版本</h2>'
    + '<p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">当前版本: ' + esc(current) + '<br>最新版本: ' + esc(latest) + '</p></div>'
    + (notes ? '<div style="margin-bottom:16px"><div style="font-size:13px;font-weight:600;color:var(--fg);margin-bottom:6px">更新内容</div><div class="upd-notes" style="font-size:12px;color:var(--fg-secondary);line-height:1.7;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;max-height:220px;overflow-y:auto;overflow-x:hidden">' + renderMarkdown(notes) + '</div></div>' : '')
    + '<div style="display:flex;flex-direction:column;gap:8px">'
    + '<button id="upd-update" class="btn btn-primary" style="width:100%">更新</button>'
    + '<div style="display:flex;gap:8px">'
    + '<button id="upd-later" class="btn btn-secondary btn-flex">稍后提示</button>'
    + '</div></div>';
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.getElementById('upd-update').focus();

  document.getElementById('upd-update').onclick = async () => {
    const btn = document.getElementById('upd-update');
    btn.disabled = true;
    btn.textContent = '准备下载...';
    const ok = await api('start_download', url);
    if (!ok) { btn.disabled = false; btn.textContent = '更新'; return; }

    const container = btn.parentNode;
    container.innerHTML = '<div style="width:100%">'
      + '<div style="font-size:12px;color:var(--fg-secondary);margin-bottom:4px;text-align:center" id="upd-progress-text">下载中 0%</div>'
      + '<div style="width:100%;height:8px;background:var(--bg-secondary);border-radius:4px;overflow:hidden">'
      + '<div id="upd-progress-bar" style="width:0%;height:100%;background:var(--accent);border-radius:4px;transition:width .3s"></div></div></div>';

    const poll = setInterval(async () => {
      const s = await api('get_download_progress');
      if (!s) return;
      const pct = s.progress || 0;
      document.getElementById('upd-progress-bar').style.width = pct + '%';
      if (s.status === 'downloading') {
        document.getElementById('upd-progress-text').textContent = '下载中 ' + pct + '%';
      } else if (s.status === 'done') {
        clearInterval(poll);
        document.getElementById('upd-progress-text').textContent = '下载完成，启动安装...';
        const r = await api('run_downloaded_installer');
        overlay.remove();
        if (r) {
          showToast('安装程序已启动，安装完成后将自动更新');
        } else {
          showToast('启动安装程序失败');
        }
      } else if (s.status === 'error') {
        clearInterval(poll);
        document.getElementById('upd-progress-text').textContent = '下载失败: ' + (s.error || '未知错误');
        container.innerHTML += '<button id="upd-retry" class="btn btn-primary" style="width:100%;margin-top:8px">重试</button>';
        document.getElementById('upd-retry').onclick = () => { overlay.remove(); showUpdateDialogFromMain(current, latest, url); };
      }
    }, 500);
  };
  document.getElementById('upd-later').onclick = () => { overlay.remove(); };
  overlay.onkeydown = (e) => { if (e.key === 'Escape') overlay.remove(); };
}

function chooseFolderDropMode() {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:360px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:16px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">放入文件夹</h2><p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">复制会保留原文件夹归属；移动会从其他文件夹移出。两种方式都会自动添加目标文件夹同名标签。</p></div>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end">'
      + '<button id="folder-drop-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="folder-drop-copy" class="btn btn-secondary">复制</button>'
      + '<button id="folder-drop-move" class="btn btn-primary">移动</button>'
      + '</div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    const done = value => { overlay.remove(); resolve(value); };
    overlay.onclick = e => { if (e.target === overlay) done(null); };
    document.getElementById('folder-drop-cancel').onclick = () => done(null);
    document.getElementById('folder-drop-copy').onclick = () => done('copy');
    document.getElementById('folder-drop-move').onclick = () => done('move');
    document.getElementById('folder-drop-move').focus();
  });
}

function showConfirm(title, message) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
    overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:360px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:16px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:4px">' + esc(title) + '</h2><p style="font-size:13px;color:var(--fg-secondary)">' + esc(message) + '</p></div>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end">'
      + '<button id="modal-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="modal-confirm" class="btn btn-danger">确定</button>'
      + '</div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    document.getElementById('modal-confirm').focus();
    const cleanup = () => { overlay.remove(); };
    document.getElementById('modal-confirm').onclick = () => { cleanup(); resolve(true); };
    document.getElementById('modal-cancel').onclick = () => { cleanup(); resolve(false); };
    overlay.onkeydown = (e) => { if (e.key === 'Escape') { cleanup(); resolve(false); } };
  });
}

/* Toast */
let toastTimer;
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1600);
}

/* LAN device connect confirm */
function showLanDeviceConfirm(device) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:400;animation:fadeIn .15s';
  overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); api('lan_confirm_device', false); } };
  const box = document.createElement('div');
  box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:400px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
  box.innerHTML = '<div style="margin-bottom:14px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">设备连接请求</h2>'
    + '<p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">以下设备请求连接本机 OhMyMeme：</p>'
    + '<div style="background:var(--card);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px 14px;margin:12px 0;font-size:13px;line-height:1.8">'
    + '<div><span style="color:var(--muted)">设备：</span><b style="color:var(--fg)">' + esc(device.name || '未知设备') + '</b></div>'
    + '<div><span style="color:var(--muted)">型号：</span><span style="color:var(--fg)">' + esc(device.model || '-') + '</span></div>'
    + '<div><span style="color:var(--muted)">系统：</span><span style="color:var(--fg)">' + esc(device.os || '-') + '</span></div>'
    + '<div><span style="color:var(--muted)">版本：</span><span style="color:var(--fg)">' + esc(device.ver || '-') + '</span></div>'
    + '</div>'
    + '<p style="font-size:12px;color:var(--muted);line-height:1.6">允许后该设备可同步表情包与配置。请确认是你信任的设备。</p></div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end">'
    + '<button id="lan-deny" class="btn btn-secondary">拒绝</button>'
    + '<button id="lan-allow" class="btn btn-primary">允许连接</button></div>';
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.getElementById('lan-deny').onclick = () => { overlay.remove(); api('lan_confirm_device', false); };
  document.getElementById('lan-allow').onclick = () => { overlay.remove(); api('lan_confirm_device', true); };
}

/* Sync: upload / download */
async function showUploadWarning() {
  const s = await api('get_settings');
  if (!s) return true;
  if (!s.sync_delete_remote) return true;
  if (s.sync_hide_upload_warning) return true;

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
    overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:380px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:14px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">上传确认</h2>'
      + '<p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">上传会将本地的完整状态同步到远端，包括新增、更新和删除操作。远程文件将被覆盖，建议先下载备份。</p></div>'
      + '<label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12.5px;color:var(--muted);margin-bottom:16px;user-select:none">'
      + '<input id="upload-warn-hide" type="checkbox" style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer">不再提醒</label>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end">'
      + '<button id="modal-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="modal-confirm" class="btn btn-primary">继续上传</button></div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    document.getElementById('modal-confirm').focus();
    const cleanup = () => { overlay.remove(); };
    document.getElementById('modal-confirm').onclick = async () => {
      const hide = document.getElementById('upload-warn-hide').checked;
      if (hide) await api('save_settings', { sync_hide_upload_warning: true });
      cleanup(); resolve(true);
    };
    document.getElementById('modal-cancel').onclick = () => { cleanup(); resolve(false); };
    overlay.onkeydown = (e) => { if (e.key === 'Escape') { cleanup(); resolve(false); } };
  });
}

/* Sync progress */
let syncPollTimer = null;
let syncBg = false;

function hideSyncProgress() {
  syncBg = true;
  const el = document.getElementById('sync-progress-overlay');
  if (el) el.style.display = 'none';
  if (syncPollTimer) { clearInterval(syncPollTimer); syncPollTimer = null; }
}

function hideSyncDone() {
  const el = document.getElementById('sync-done-overlay');
  if (el) el.style.display = 'none';
}

function formatSpeed(bytesPerSec) {
  if (bytesPerSec >= 1048576) return (bytesPerSec / 1048576).toFixed(1) + ' MB/s';
  if (bytesPerSec >= 1024) return (bytesPerSec / 1024).toFixed(1) + ' KB/s';
  return bytesPerSec.toFixed(0) + ' B/s';
}

async function doSyncWithProgress(method, title, progressSetting, doneSetting) {
  const s = await api('get_settings');
  const showProgress = s ? s[progressSetting] !== false : true;
  const showDone = s ? s[doneSetting] !== false : true;

  const warnOk = await showUploadWarning();
  if (!warnOk) return;

  syncBg = false;

  if (showProgress) {
    const po = document.getElementById('sync-progress-overlay');
    if (po) {
      document.getElementById('sync-progress-title').textContent = title;
      document.getElementById('sync-progress-file').textContent = '准备中...';
      document.getElementById('sync-progress-bar').style.width = '0%';
      document.getElementById('sync-progress-pct').textContent = '0%';
      document.getElementById('sync-progress-speed').textContent = '';
      po.style.display = 'flex';
      syncPollTimer = setInterval(async () => {
        const p = await api('get_sync_progress');
        if (!p || p.status === 'idle') return;
        document.getElementById('sync-progress-file').textContent = p.current_file || '';
        document.getElementById('sync-progress-bar').style.width = (p.progress || 0) + '%';
        document.getElementById('sync-progress-pct').textContent = (p.progress || 0) + '%';
        if (p.speed) {
          document.getElementById('sync-progress-speed').textContent = formatSpeed(p.speed);
        }
      }, 300);
    }
  }

  const r = await api(method);
  if (syncPollTimer) { clearInterval(syncPollTimer); syncPollTimer = null; }

  if (showProgress && !syncBg) {
    const po = document.getElementById('sync-progress-overlay');
    if (po) po.style.display = 'none';
  }

  if (r && r.ok) {
    const cnt = r.uploaded || r.downloaded || 0;
    showToast('完成: ' + cnt + ' 个');
    if (showDone) {
      document.getElementById('sync-done-title').textContent = title + '完成';
      document.getElementById('sync-done-detail').textContent = '成功 ' + cnt + ' 个';
      const doo = document.getElementById('sync-done-overlay');
      if (doo) doo.style.display = 'flex';
    }
  } else {
    showToast('失败: ' + ((r && r.error) || '未知错误'));
  }
}

async function syncUpload() {
  await doSyncWithProgress('sync_push', '上传中', 'show_upload_progress', 'show_upload_done');
}

async function syncDownload() {
  await doSyncWithProgress('sync_pull', '下载中', 'show_download_progress', 'show_download_done');
  refreshMemes(); refreshTags(); refreshCollections();
}

function hide() { try { pywebview.api.hide_window(); } catch(e) {} }
function openSettings() { try { pywebview.api.open_settings(); } catch(e) {} }
function focusSearch() { document.getElementById('search')?.focus(); }
let sidebarCollapsed = true;

function renderSidebarState() {
  const sb = document.getElementById('sidebar');
  const btn = document.getElementById('sidebar-toggle');
  if (!sb || !btn) return;
  sb.classList.toggle('collapsed', sidebarCollapsed);
  btn.classList.toggle('collapsed', sidebarCollapsed);
  btn.textContent = sidebarCollapsed ? '▶' : '◀';
}

function toggleSidebar() {
  sidebarCollapsed = !sidebarCollapsed;
  renderSidebarState();
}

/* Drag-and-drop import */
(function() {
  const overlay = document.getElementById('drop-overlay');
  if (!overlay) return;
  let dragCounter = 0;
  document.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragCounter++;
    overlay.classList.add('drag-over');
  });
  document.addEventListener('dragover', (e) => {
    e.preventDefault();
  });
  document.addEventListener('dragleave', () => {
    dragCounter--;
    if (dragCounter <= 0) { dragCounter = 0; overlay.classList.remove('drag-over'); }
  });
  document.addEventListener('drop', async (e) => {
    e.preventDefault();
    dragCounter = 0;
    overlay.classList.remove('drag-over');
    const dt = e.dataTransfer;
    // 从 dataTransfer 提取文件路径
    let uri = '';
    let file = null;

    // 方式1: getData('text/uri-list') — 浏览器拖入（HTTP URL）
    if (!uri) { try { uri = dt.getData('text/uri-list') || ''; } catch(_) {} }
    // 方式2: getData('text/plain') — 回退
    if (!uri) { try { uri = dt.getData('text/plain') || ''; } catch(_) {} }
    uri = uri.trim();
    // 方式3: items text/html → 提取 file://（GNOME 文件管理器）
    if (!uri) {
      try {
        if (dt.items && dt.items.length) {
          for (let i = 0; i < dt.items.length; i++) {
            const item = dt.items[i];
            if (item.kind === 'string' && item.type === 'text/html') {
              const html = await new Promise(res => item.getAsString(res));
              if (!html) continue;
              const text = html.replace(/<[^>]+>/g, '').trim();
              if (text.startsWith('file://')) { uri = text; break; }
            }
          }
        }
      } catch(_) {}
    }
    // 方式3: files
    if (!uri) { try { if (dt.files && dt.files.length) file = dt.files[0]; } catch(_) {} }
    // 方式4: items → getAsFile
    if (!uri && !file) {
      try {
        if (dt.items && dt.items.length) {
          for (let i = 0; i < dt.items.length; i++) {
            const it = dt.items[i];
            if (it.kind === 'file') { file = it.getAsFile(); if (file) break; }
          }
        }
      } catch(_) {}
    }

    if (uri) {
      try {
        const r = await api('download_original_image', uri);
        if (r && r.ok) { location.reload(); return; }
      } catch(_) {}
    }
    if (file) {
      try {
        const b64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result.split(',')[1]);
          reader.onerror = () => reject(reader.error);
          reader.readAsDataURL(file);
        });
        const res = await fetch('/api/upload/', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: [{ name: file.name, data: b64 }] }),
        });
        if (res.ok) { location.reload(); }
      } catch(_) {}
    }
  });
})();

/* Window Drag */
let dragState = null;
const titlebar = document.getElementById('titlebar');
titlebar.addEventListener('mousedown', async (e) => {
  if (e.button !== 0) return;
  if (e.target.closest('.title-btn') || e.target.closest('.icon-btn')) return;
  const nativeDrag = await api('start_window_drag', e.button + 1, e.screenX, e.screenY);
  if (nativeDrag) return;   // Linux：交给合成器拖动
  dragState = { sx: e.screenX, sy: e.screenY };
  e.preventDefault();
});
document.addEventListener('mousemove', (e) => {
  if (!dragState) return;
  const dx = e.screenX - dragState.sx, dy = e.screenY - dragState.sy;
  if (dx !== 0 || dy !== 0) {
    api('move_window', dx, dy);
    dragState.sx = e.screenX; dragState.sy = e.screenY;
  }
});
document.addEventListener('mouseup', () => { dragState = null; });

async function checkUpdateAndPrompt() {
  try {
    const upd = await api('check_update');
    if (upd && upd.has_update) {
      showUpdateDialogFromMain(upd.current, upd.latest, upd.download_url, upd.notes);
    }
  } catch(e) {}
}

/* Init */
document.addEventListener('DOMContentLoaded', async () => {
  renderDragSortToggle();
  renderSidebarState();
  initDragReorder();
  const dragSortBtn = document.getElementById('drag-sort-toggle');
  if (dragSortBtn) {
    dragSortBtn.addEventListener('click', toggleDragSort);
    dragSortBtn.addEventListener('mousedown', function(e) { e.stopPropagation(); });
  }
  const sidebarBtn = document.getElementById('sidebar-toggle');
  if (sidebarBtn) sidebarBtn.addEventListener('click', toggleSidebar);
  const tagbarBtn = document.getElementById('tagbar-toggle');
  if (tagbarBtn) tagbarBtn.addEventListener('click', toggleTagbar);
  const gridWrap = document.getElementById('grid-wrap');
  gridWrap.addEventListener('scroll', () => {
    if (gridWrap.scrollTop + gridWrap.clientHeight >= gridWrap.scrollHeight - 300) {
      loadMoreMemes();
    }
  });
  document.getElementById('loading').classList.remove('hidden');
  // 等待 pywebview 桥接就绪
  while (typeof pywebview === 'undefined' || !pywebview.api) {
    await new Promise(r => setTimeout(r, 100));
  }
  await loadGridScale();
  const data = await api('get_init_data');
  if (data) {
    memes = data.memes || [];
    memeOffset = memes.length;
    memeHasMore = memes.length === MEME_PAGE;
    allTags = data.tags || [];
    tagbarCollapsed = !!data.tagbar_collapsed;
    renderTags();
    collections = data.collections || [];
    renderTree();
    updateViewContext();
    renderGrid();
  }
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('search').focus();
  setTimeout(async () => {
    await api('rescan_cache');
    await api('run_auto_sync');
    memes = await api('search_memes', '', [], activeCollection, 0, MEME_PAGE) || [];
    memeOffset = memes.length;
    memeHasMore = memes.length === MEME_PAGE;
    renderGrid();
    allTags = await api('get_tags') || [];
    renderTags();
    collections = await api('get_collections') || [];
    renderTree();
    await checkUpdateAndPrompt();
  }, 300);
  // 每日检测更新（复用启动时的检测与弹窗逻辑）
  setInterval(checkUpdateAndPrompt, 24 * 60 * 60 * 1000);
});

/* AI 面板 */
function pollAiEditProgress() {
  const timer = setInterval(async () => {
    const state = await api('get_ai_progress');
    if (!state || state.task_type !== 'edit') return;
    if (state.status === 'done' || state.status === 'error' || state.status === 'cancelled') {
      clearInterval(timer);
      showToast(state.message || (state.status === 'done' ? '编辑完成' : '编辑失败'));
      if (state.status === 'done') refreshMemes();
    }
  }, 350);
}

function showAiPanel() {
  let aiTimer = null;

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
  overlay.onclick = (e) => { if (e.target === overlay) { stopPoll(); overlay.remove(); } };

  const box = document.createElement('div');
  box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:20px 24px;width:520px;max-width:90vw;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
  box.innerHTML = ''
    + '<div style="margin-bottom:14px;display:flex;align-items:center;justify-content:space-between">'
    + '<h2 style="font-size:15px;font-weight:600;color:var(--fg)">AI 面板</h2>'
    + '<button id="ai-close" class="btn btn-ghost btn-sm">×</button>'
    + '</div>'
    + '<div style="display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid var(--border)">'
    + '<button class="ai-tab active" data-tab="organize">整理</button>'
    + '<button class="ai-tab" data-tab="search">找图</button>'
    + '<button class="ai-tab" data-tab="generate">生成</button>'
    + '</div>'
    + '<div id="ai-tab-organize" class="ai-tab-content">'
    + '<p style="font-size:12px;color:var(--muted);margin-bottom:10px;line-height:1.6">AI 会优先整理尚未补全标签、描述或图片文字的表情；确认应用前不会修改你的表情库。</p>'
    + '<div style="display:flex;gap:8px;margin-bottom:10px">'
    + '<input id="ai-batch-size" type="number" value="50" min="1" max="200" style="width:80px;padding:6px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);color:var(--fg);font-size:13px">'
    + '<button id="ai-organize-start" class="btn btn-primary">开始整理</button>'
    + '<button id="ai-organize-cancel" class="btn btn-secondary" style="display:none">取消</button>'
    + '</div>'
    + '</div>'
    + '<div id="ai-suggestions" style="display:none;margin-top:12px;max-height:300px;overflow-y:auto;border-top:1px solid var(--border);padding-top:10px"></div>'
    + '<div id="ai-tab-search" class="ai-tab-content" style="display:none">'
    + '<p style="font-size:12px;color:var(--muted);margin-bottom:10px;line-height:1.6">从网络搜索表情包图片并导入</p>'
    + '<div style="display:flex;gap:8px;margin-bottom:10px">'
    + '<input id="ai-search-keyword" placeholder="输入关键词" style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);color:var(--fg);font-size:13px">'
    + '<select id="ai-search-count" style="padding:6px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);color:var(--fg);font-size:13px">'
    + '<option value="5">5张</option><option value="10" selected>10张</option><option value="20">20张</option><option value="30">30张</option>'
    + '</select>'
    + '<button id="ai-search-start" class="btn btn-primary">搜索</button>'
    + '<button id="ai-search-cancel" class="btn btn-secondary" style="display:none">取消</button>'
    + '</div>'
    + '</div>'
    + '<div id="ai-tab-generate" class="ai-tab-content" style="display:none">'
    + '<p style="font-size:12px;color:var(--muted);margin-bottom:10px;line-height:1.6">用 AI 文生图生成表情包</p>'
    + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
    + '<span style="font-size:12px;color:var(--muted)">提示词模板</span>'
    + '<select id="ai-gen-template" style="flex:1;padding:6px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);color:var(--fg);font-size:12px">'
    + '<option value="">不使用模板</option>'
    + '<option value="emoji">聊天表情</option>'
    + '<option value="sticker">贴纸</option>'
    + '<option value="reaction">反应图</option>'
    + '<option value="minimal">极简图标</option>'
    + '</select>'
    + '</div>'
    + '<div style="margin-bottom:10px">'
    + '<textarea id="ai-gen-prompt" placeholder="描述你想要的表情包，如：一只猫吃面条的表情" style="width:100%;height:60px;padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);color:var(--fg);font-size:13px;resize:vertical;font-family:inherit;box-sizing:border-box"></textarea>'
    + '</div>'
    + '<div style="display:flex;gap:8px;margin-bottom:10px">'
    + '<button id="ai-gen-start" class="btn btn-primary">生成</button>'
    + '<button id="ai-gen-cancel" class="btn btn-secondary" style="display:none">取消</button>'
    + '</div>'
    + '</div>'
    + '<div id="ai-progress-wrap" style="display:none;margin-top:6px">'
    + '<div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:4px">'
    + '<span id="ai-progress-text">准备中</span><span id="ai-progress-pct">0%</span>'
    + '</div>'
    + '<div style="height:6px;background:var(--card);border-radius:3px;overflow:hidden">'
    + '<div id="ai-progress-bar" style="height:100%;width:0;background:var(--accent);transition:width .3s"></div>'
    + '</div>'
    + '<div id="ai-log" style="margin-top:8px;max-height:120px;overflow-y:auto;font-size:11px;color:var(--muted);line-height:1.5"></div>'
    + '</div>';

  overlay.appendChild(box);
  document.body.appendChild(overlay);

  function stopPoll() {
    if (aiTimer) { clearInterval(aiTimer); aiTimer = null; }
  }

  function startPoll() {
    stopPoll();
    aiTimer = setInterval(async () => {
      try {
        const s = await api('get_ai_progress');
        if (!s) return;
        const wrap = document.getElementById('ai-progress-wrap');
        if (wrap) wrap.style.display = '';
        const bar = document.getElementById('ai-progress-bar');
        const txt = document.getElementById('ai-progress-text');
        const pct = document.getElementById('ai-progress-pct');
        const log = document.getElementById('ai-log');
        if (bar) bar.style.width = (s.progress || 0) + '%';
        if (pct) pct.textContent = (s.progress || 0) + '%';
        if (txt) txt.textContent = s.message || '';
        if (log && s.log) log.innerHTML = s.log.map(l => '<div>' + esc(l) + '</div>').join('');
        if (s.status === 'done' || s.status === 'error' || s.status === 'cancelled') {
          stopPoll();
          if (s.status === 'error') showToast(s.message || 'AI 操作失败');
          else if (s.status === 'done') showToast(s.message || '完成');
          resetButtons();
          if (s.status === 'done' && s.task_type === 'organize') renderSuggestions(s.task_id);
          if (s.status === 'done' && s.task_type !== 'organize') refreshMemes();
        }
      } catch(e) {}
    }, 300);
  }

  async function renderSuggestions(taskId) {
    const host = document.getElementById('ai-suggestions');
    if (!host || !taskId) return;
    const data = await api('get_ai_suggestions', taskId);
    const items = Object.values(data || {});
    if (!items.length) {
      host.style.display = 'none';
      host.innerHTML = '';
      return;
    }
    host.style.display = '';
    host.innerHTML = '<div style="font-size:13px;font-weight:600;margin-bottom:8px">待审核建议（' + items.length + '）</div>';
    const list = document.createElement('div');
    list.style.cssText = 'display:flex;flex-direction:column;gap:8px';
    items.forEach(item => {
      const row = document.createElement('div');
      row.style.cssText = 'padding:9px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card)';
      row.innerHTML = '<div style="font-size:11px;color:var(--muted);margin-bottom:6px">表情 #' + esc(item.id) + '</div>'
        + '<input data-field="tags" value="' + esc((item.tags || []).join('、')) + '" placeholder="标签，以顿号或逗号分隔" style="width:100%;box-sizing:border-box;padding:5px 7px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);color:var(--fg);font-size:12px;margin-bottom:5px">'
        + '<input data-field="collection" value="' + esc(item.collection || '') + '" placeholder="建议文件夹" style="width:100%;box-sizing:border-box;padding:5px 7px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);color:var(--fg);font-size:12px;margin-bottom:5px">'
        + '<input data-field="description" value="' + esc(item.description || '') + '" placeholder="图片描述（用于搜索）" style="width:100%;box-sizing:border-box;padding:5px 7px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);color:var(--fg);font-size:12px;margin-bottom:5px">'
        + '<input data-field="ocr_text" value="' + esc(item.ocr_text || '') + '" placeholder="图片文字（用于搜索）" style="width:100%;box-sizing:border-box;padding:5px 7px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);color:var(--fg);font-size:12px">';
      row.querySelectorAll('input').forEach(input => {
        input.addEventListener('change', async () => {
          const tags = row.querySelector('[data-field="tags"]').value.split(/[、,，]/).map(x => x.trim()).filter(Boolean);
          const result = await api('adjust_ai_suggestion', taskId, item.id, tags,
            row.querySelector('[data-field="collection"]').value.trim(),
            row.querySelector('[data-field="description"]').value.trim(),
            row.querySelector('[data-field="ocr_text"]').value.trim());
          if (!result || !result.ok) showToast((result && result.error) || '保存建议失败');
        });
      });
      list.appendChild(row);
    });
    host.appendChild(list);
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px';
    const discard = document.createElement('button');
    discard.className = 'btn btn-secondary';
    discard.textContent = '全部丢弃';
    discard.onclick = async () => {
      const ok = await showConfirm('丢弃 AI 建议', '确认丢弃当前 ' + items.length + ' 条建议？不会修改表情库。');
      if (!ok) return;
      const result = await api('discard_ai_suggestions', taskId);
      if (result && result.ok) { showToast('已丢弃 ' + result.discarded + ' 条建议'); renderSuggestions(taskId); }
    };
    const apply = document.createElement('button');
    apply.className = 'btn btn-primary';
    apply.textContent = '确认应用';
    apply.onclick = async () => {
      const ok = await showConfirm('应用 AI 建议', '确认把当前 ' + items.length + ' 条建议写入标签、文件夹和搜索描述？');
      if (!ok) return;
      const result = await api('apply_ai_suggestions', taskId);
      if (!result || !result.ok) { showToast((result && result.error) || '应用失败'); return; }
      showToast('已应用 ' + result.applied + ' 条建议');
      await refreshTags(); await refreshCollections(); await refreshMemes();
      renderSuggestions(taskId);
    };
    actions.appendChild(discard);
    actions.appendChild(apply);
    host.appendChild(actions);
  }

  function resetButtons() {
    ['organize','search','generate'].forEach(t => {
      const start = document.getElementById('ai-' + t + '-start');
      const cancel = document.getElementById('ai-' + t + '-cancel');
      if (start) start.style.display = '';
      if (cancel) cancel.style.display = 'none';
    });
  }

  document.getElementById('ai-close').onclick = () => { stopPoll(); overlay.remove(); };

  document.querySelectorAll('.ai-tab').forEach(btn => {
    btn.style.cssText = 'padding:6px 14px;border:none;background:none;color:var(--muted);font-size:13px;cursor:pointer;border-bottom:2px solid transparent';
    btn.onclick = () => {
      document.querySelectorAll('.ai-tab').forEach(b => { b.classList.remove('active'); b.style.color='var(--muted)'; b.style.borderBottomColor='transparent'; });
      btn.classList.add('active');
      btn.style.color='var(--accent)';
      btn.style.borderBottomColor='var(--accent)';
      document.querySelectorAll('.ai-tab-content').forEach(c => c.style.display='none');
      const tab = document.getElementById('ai-tab-' + btn.dataset.tab);
      if (tab) tab.style.display = '';
    };
  });
  const firstTab = document.querySelector('.ai-tab.active');
  if (firstTab) { firstTab.style.color='var(--accent)'; firstTab.style.borderBottomColor='var(--accent)'; }

  document.getElementById('ai-organize-start').onclick = () => {
    const bs = document.getElementById('ai-batch-size').value || 50;
    document.getElementById('ai-organize-start').style.display='none';
    document.getElementById('ai-organize-cancel').style.display='';
    api('ai_organize', parseInt(bs));
    startPoll();
  };
  document.getElementById('ai-organize-cancel').onclick = () => api('cancel_ai_task');

  document.getElementById('ai-search-start').onclick = () => {
    const kw = document.getElementById('ai-search-keyword').value.trim();
    if (!kw) { showToast('请输入关键词'); return; }
    const cnt = document.getElementById('ai-search-count').value || 10;
    document.getElementById('ai-search-start').style.display='none';
    document.getElementById('ai-search-cancel').style.display='';
    api('ai_search_web', kw, parseInt(cnt));
    startPoll();
  };
  document.getElementById('ai-search-cancel').onclick = () => api('cancel_ai_task');

  const promptTemplates = {
    emoji: '适合作为中文聊天表情包，角色表情夸张、主体居中、干净纯色背景、无文字：',
    sticker: '可爱贴纸风格，轮廓清晰、背景透明或纯色、主体完整、无水印无文字：',
    reaction: '反应图风格，突出强烈情绪、表情清晰、构图简单、无水印无文字：',
    minimal: '极简扁平图标风格，主体居中、高对比、少细节、无文字：'
  };
  document.getElementById('ai-gen-template').onchange = () => {
    const template = promptTemplates[document.getElementById('ai-gen-template').value];
    const input = document.getElementById('ai-gen-prompt');
    if (template && !input.value.trim()) input.value = template;
  };
  document.getElementById('ai-gen-start').onclick = () => {
    const input = document.getElementById('ai-gen-prompt');
    const template = promptTemplates[document.getElementById('ai-gen-template').value] || '';
    let pr = input.value.trim();
    if (!pr) { showToast('请输入描述'); return; }
    if (template && !pr.startsWith(template)) pr = template + pr;
    document.getElementById('ai-gen-start').style.display='none';
    document.getElementById('ai-gen-cancel').style.display='';
    api('ai_generate', pr, 1);
    startPoll();
  };
  document.getElementById('ai-gen-cancel').onclick = () => api('cancel_ai_task');
}
