let allTags = [], activeTags = new Set(), memes = [], pending = false;
let collections = [], activeCollection = null;
let dragSrcId = null;

async function api(method, ...args) {
  try { return await pywebview.api[method](...args); }
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
  try { memes = await api('search_memes', q, [...activeTags], activeCollection) || []; }
  catch(e) { memes = []; }
  renderGrid();
}

async function refreshTags() {
  try { allTags = await api('get_tags') || []; } catch(e) { allTags = []; }
  renderTags();
}

function renderTags() {
  const bar = document.getElementById('tagbar');
  bar.innerHTML = '';
  if (allTags.length === 0) return;
  allTags.slice(0, 40).forEach(tag => {
    const el = document.createElement('span');
    el.className = 'tag' + (activeTags.has(tag) ? ' active' : '');
    el.textContent = tag;
    el.onclick = () => { toggleTag(tag); };
    bar.appendChild(el);
  });
}

function toggleTag(tag) {
  if (activeTags.has(tag)) activeTags.delete(tag); else activeTags.add(tag);
  renderTags();
  refreshMemes();
}

let activePath = new Set();

function computeActivePath() {
  activePath.clear();
  if (activeCollection == null || activeCollection <= 0) return;
  function search(items, target) {
    for (const c of items) {
      if (c.id === target) {
        activePath.add(c.id);
        return true;
      }
      if (c.children) {
        if (search(c.children, target)) {
          activePath.add(c.id);
          return true;
        }
      }
    }
    return false;
  }
  search(collections, activeCollection);
}

async function refreshCollections() {
  try { collections = await api('get_collections') || []; } catch(e) { collections = []; }
  computeActivePath();
  renderCollections();
}

function renderCollections() {
  const bar = document.getElementById('colbar');
  bar.innerHTML = '';
  if (collections.length === 0) return;
  const flat = [];
  function flatten(items, parentActive) {
    items.forEach(c => {
      if (c.count === 0 && !c.children) return;
      flat.push(c);
      if (parentActive || activeCollection === c.id || activePath.has(c.id)) {
        if (c.children) flatten(c.children, activeCollection === c.id);
      }
    });
  }
  flatten(collections, false);
  flat.forEach(c => {
    const el = document.createElement('span');
    const isActive = activeCollection === c.id || activePath.has(c.id);
    el.className = 'col-tag' + (isActive ? ' active' : '');
    let label = c.name;
    if (c.count > 0) label += ' (' + c.count + ')';
    if (c.children && c.children.length > 0) label += ' \u25BC';
    el.textContent = label;
    el.onclick = () => { toggleCollection(c.id); };
    el.oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); showColTagMenu(e, c); };
    bar.appendChild(el);
  });
}

function toggleCollection(cid) {
  if (activeCollection === cid) activeCollection = null;
  else activeCollection = cid;
  computeActivePath();
  renderCollections();
  refreshMemes();
}

document.getElementById('colbar').addEventListener('contextmenu', async (e) => {
  const targetCol = activeCollection && activeCollection > 0 ? activeCollection : null;
  if (!targetCol) return;
  e.preventDefault();
  const name = await showPrompt('新建子分组', '');
  if (!name) return;
  const r = await api('create_subcollection', name, targetCol);
  if (r && r.ok) { showToast('已创建子分组'); refreshCollections(); }
  else showToast('创建失败');
});

document.getElementById('grid-wrap').addEventListener('contextmenu', async (e) => {
  if (e.target.closest('.meme-card')) return;
  const targetCol = activeCollection && activeCollection > 0 ? activeCollection : null;
  if (!targetCol) return;
  e.preventDefault();
  const name = await showPrompt('新建子分组', '');
  if (!name) return;
  const r = await api('create_subcollection', name, targetCol);
  if (r && r.ok) { showToast('已创建子分组'); refreshCollections(); refreshMemes(); }
  else showToast('创建失败');
});

/* Context Menu State */
let ctxMeme = null;
let ctxFolder = null;
let lastCtxX = 0, lastCtxY = 0;
let subgroupPickerResolve = null;

function renderGrid() {
  const grid = document.getElementById('meme-grid');
  const empty = document.getElementById('empty');
  grid.innerHTML = '';
  const curCol = activeCollection && activeCollection > 0 ? activeCollection : null;
  let hasFolderCards = false;
  if (curCol) {
    const parentCol = collections.find(c => c.id === curCol);
    if (parentCol && parentCol.children) {
      hasFolderCards = parentCol.children.length > 0;
      parentCol.children.forEach(child => {
        const card = document.createElement('div');
        card.className = 'meme-card folder-card';
        card.style.background = 'var(--surface)';
        card.dataset.folderId = child.id;
        const preview = document.createElement('div');
        preview.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:24px;color:var(--muted);flex-direction:column;gap:4px';
        preview.innerHTML = '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="var(--accent)" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><span style="font-size:11px;color:var(--fg-secondary)">' + esc(child.name) + '</span>';
        card.appendChild(preview);
        card.onclick = () => { activeCollection = child.id; computeActivePath(); refreshMemes(); renderCollections(); };
        card.oncontextmenu = (e) => { e.preventDefault(); showFolderMenu(e, child.id, child.name); };
        grid.appendChild(card);
      });
    }
  }

  if (!memes || memes.length === 0) {
    if (!hasFolderCards) {
      grid.style.display = 'none'; empty.style.display = 'flex'; return;
    }
    grid.style.display = 'grid'; empty.style.display = 'none'; return;
  }
  grid.style.display = 'grid'; empty.style.display = 'none';

  memes.forEach(m => {
    const card = document.createElement('div');
    card.className = 'meme-card';
    card.title = m.name;
    card.style.background = 'var(--surface)';
    card.dataset.memeId = m.id;
    const img = document.createElement('img');
    img.alt = m.name;
    img.loading = 'lazy';
    img.draggable = false;
    if (m.is_animated && m.auto_play_gif) {
      img.src = '/api/original/' + m.id + '/' + encodeURIComponent(m.filename);
    } else {
      img.src = '/api/thumb/' + m.id + '/' + encodeURIComponent(m.filename);
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

    card.onclick = () => copyMeme(m.id, m.name);
    card.oncontextmenu = (e) => { e.preventDefault(); showCtxMenu(e, m); };
    card.draggable = false;
    grid.appendChild(card);
  });

}

/* Drag-to-reorder (only enabled in the unfiltered "all memes" view)
 * 模型驱动：memes 数组为唯一真源，拖拽跨槽实时同步 DOM，落点持久化；
 * Pointer Events + 指针捕获，网格感知插入点，FLIP 让位动画 */
let memeDrag = null;
let ignoreClick = false;
let dragSortEnabled = true;

function toggleDragSort() {
  dragSortEnabled = !dragSortEnabled;
  const btn = document.getElementById('drag-sort-toggle');
  if (btn) {
    btn.classList.toggle('sort-on', dragSortEnabled);
    btn.classList.toggle('sort-off', !dragSortEnabled);
  }
  refreshMemes();
}

function canReorderMemes() {
  const q = document.getElementById('search').value.trim();
  if (q || activeTags.size > 0) return false;
  if (!dragSortEnabled) return false;
  return activeCollection == null || activeCollection > 0;
}

function memeCardsInGrid() {
  return Array.from(document.querySelectorAll('#meme-grid .meme-card:not(.folder-card)'));
}

function gridMetrics() {
  const grid = document.getElementById('meme-grid');
  const gRect = grid.getBoundingClientRect();
  const cards = memeCardsInGrid();
  if (!cards.length) return null;
  const gap = parseFloat(getComputedStyle(grid).rowGap) || 10;
  const first = cards[0].getBoundingClientRect();
  return {
    gRect, first,
    pitchX: first.width + gap,
    pitchY: first.height + gap,
    cols: Math.max(1, Math.round((gRect.width + gap) / (first.width + gap))),
  };
}

function gridSlotIndex(x, y) {
  const m = gridMetrics();
  if (!m) return 0;
  const { gRect, pitchX, pitchY, cols } = m;
  const col = Math.max(0, Math.min(Math.floor((x - gRect.left) / pitchX), cols - 1));
  const row = Math.max(0, Math.floor((y - gRect.top) / pitchY));
  // 绝对格子索引（含 folder-card 占位），再映射到非 folder 的 meme 卡数组索引
  const all = Array.from(document.querySelectorAll('#meme-grid .meme-card'));
  const absSlot = Math.min(row * cols + col, all.length - 1);
  let idx = -1;
  for (let i = 0; i <= absSlot; i++) {
    if (!all[i].classList.contains('folder-card')) idx++;
  }
  return Math.max(0, Math.min(idx, memeCardsInGrid().length - 1));
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
    const card = e.target.closest('.meme-card:not(.folder-card)');
    if (!card) return;
    const q = document.getElementById('search').value.trim();
    if (q || activeTags.size > 0) return; // 搜索/筛选时禁止拖拽
    // 排序开启时仅可排序视图记录 memeDrag；排序关闭时允许原生拖出
    if (dragSortEnabled && !canReorderMemes()) return;
    const rect = card.getBoundingClientRect();
    memeDrag = {
      card,
      offX: e.clientX - rect.left,
      offY: e.clientY - rect.top,
      active: false,
      originalOrder: memes.slice(),
      base: rect,
      // 排序关闭时用于原生拖拽（拖出到外部应用）的起点
      startX: e.clientX,
      startY: e.clientY,
      natDrag: !dragSortEnabled,
    };
  };

  const onMove = (e) => {
    const d = memeDrag;
    if (!d) return;
    // 排序关闭：检测移动阈值后启动原生拖拽（QQ/微信真实文件）
    if (d.natDrag && !d.active) {
      const dist = Math.hypot(e.clientX - d.startX, e.clientY - d.startY);
      if (dist <= 8) return;
      d.active = true;
      const id = Number(d.card.dataset.memeId);
      api('start_native_drag', id).then((ok) => {
        ignoreClick = true;
        if (!ok && memeDrag === d) { d.active = false; showToast('拖拽失败：本地文件不存在'); }
        if (memeDrag === d) cleanupMemeDrag();
      }).catch(() => { if (memeDrag === d) cleanupMemeDrag(); });
      return;
    }
    if (d.natDrag) return; // 原生拖拽进行中，跳过排序逻辑
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
    d.card.style.transform = 'translate(' + (e.clientX - d.offX - d.base.left) + 'px,' + (e.clientY - d.offY - d.base.top) + 'px) scale(0.95)';
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
      c.style.transform = 'translate(' + (firstRects[i].left - lastRects[i].left) + 'px,' + (firstRects[i].top - lastRects[i].top) + 'px)';
    });
    requestAnimationFrame(() => {
      affected.forEach(c => { c.style.transition = ''; c.style.transform = ''; });
    });
    const prevTf = d.card.style.transform;
    d.card.style.transform = '';
    d.base = d.card.getBoundingClientRect();
    d.card.style.transform = prevTf;
    d.card.style.transform = 'translate(' + (e.clientX - d.offX - d.base.left) + 'px,' + (e.clientY - d.offY - d.base.top) + 'px) scale(0.95)';
  };

  const onUp = async (e) => {
    const d = memeDrag;
    if (!d) return;
    if (POINTER && pointerId(e) != null) {
      try { grid.releasePointerCapture(pointerId(e)); } catch (_) {}
    }
    const wasActive = d.active;
    cleanupMemeDrag();
    if (!wasActive) return;
    ignoreClick = true;
    if (d.natDrag) return; // 原生拖拽路径不持久化排序
    const ordered = memes.map(x => x.id).join(',');
    if (ordered !== d.originalOrder.map(x => x.id).join(',')) {
      let ok;
      if (activeCollection && activeCollection > 0) {
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
  const ok = await api('copy_meme', id);
  if (ok) {
    showToast(filename + ' 已复制');
    setTimeout(hide, 300);
    if (activeCollection === -3) refreshMemes();
    refreshCollections();
  }
  else { showToast('复制失败'); }
}

function showImportMenu() {
  document.getElementById('import-overlay').style.display = 'flex';
}

function closeImportMenu() {
  document.getElementById('import-overlay').style.display = 'none';
}

async function importLocal() {
  closeImportMenu();
  if (pending) return;
  pending = true;
  const result = await api('import_memes');
  pending = false;
  if (result) { showToast('导入完成'); refreshMemes(); refreshTags(); refreshCollections(); }
}

async function importClipboard() {
  closeImportMenu();
  if (pending) return;
  pending = true;
  const result = await api('import_from_clipboard');
  pending = false;
  if (!result) { showToast('导入失败'); return; }
  if (!result.ok) { showToast(result.error || '导入失败'); return; }
  const newName = await showPrompt('重命名', result.name || '');
  if (newName && newName !== result.name) {
    await api('rename_meme', result.id, newName);
  }
  showToast('导入完成');
  refreshMemes(); refreshTags(); refreshCollections();
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
function showCtxMenu(e, meme) {
  hideSubgroupMenu();
  ctxMeme = meme;
  lastCtxX = e.clientX; lastCtxY = e.clientY;
  const menu = document.getElementById('ctx-menu');
  // 恢复所有项目可见
  menu.querySelectorAll('.ctx-item, .ctx-divider').forEach(el => {
    el.style.display = '';
  });
  const dfBtn = menu.querySelector('[data-action="delete-folder"]');
  if (dfBtn) dfBtn.style.display = 'none';
  const rcBtn = menu.querySelector('[data-action="rename-collection"]');
  if (rcBtn) rcBtn.style.display = 'none';
  const dcBtn = menu.querySelector('[data-action="delete-collection"]');
  if (dcBtn) dcBtn.style.display = 'none';
  const crBtn = menu.querySelector('[data-action="clear-recent"]');
  if (crBtn) crBtn.style.display = 'none';
  const favBtn = menu.querySelector('[data-action="favorite"]');
  if (meme.favorited) {
    favBtn.textContent = '取消收藏';
  } else {
    favBtn.textContent = '收藏';
  }
  const rmBtn = menu.querySelector('[data-action="remove-collection"]');
  if (activeCollection && activeCollection !== -1) {
    rmBtn.style.display = 'flex';
  } else {
    rmBtn.style.display = 'none';
  }
  const sgBtn = menu.querySelector('[data-action="add-to-subgroup"]');
  if (sgBtn) {
    sgBtn.style.display = (activeCollection && activeCollection > 0) ? 'flex' : 'none';
  }
  const rrBtn = menu.querySelector('[data-action="remove-recent"]');
  if (rrBtn) {
    rrBtn.style.display = activeCollection === -3 ? 'flex' : 'none';
  }
  menu.classList.add('show');
  const rect = menu.getBoundingClientRect();
  let left = e.clientX;
  let top = e.clientY;

  if (left + rect.width > window.innerWidth) {
    left = window.innerWidth - rect.width - 4;
  }
  if (top + rect.height > window.innerHeight) {
    top = window.innerHeight - rect.height - 4;
  }
  if (left < 0) left = 4;
  if (top < 0) top = 4;

  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
}

function showFolderMenu(e, folderId, folderName) {
  hideCtxMenu();
  ctxFolder = { id: folderId, name: folderName };
  lastCtxX = e.clientX; lastCtxY = e.clientY;
  const menu = document.getElementById('ctx-menu');
  menu.querySelectorAll('.ctx-item, .ctx-divider').forEach(el => {
    el.style.display = 'none';
  });
  const df = menu.querySelector('[data-action="delete-folder"]');
  if (df) df.style.display = 'flex';
  menu.classList.add('show');
  const rect = menu.getBoundingClientRect();
  let left = e.clientX, top = e.clientY;
  if (left + rect.width > window.innerWidth) left = e.clientX - rect.width;
  if (top + rect.height > window.innerHeight) top = window.innerHeight - rect.height - 4;
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
}

function showColTagMenu(e, col) {
  if (col.id > 0) {
    hideCtxMenu();
    ctxFolder = { id: col.id, name: col.name };
    lastCtxX = e.clientX; lastCtxY = e.clientY;
    const menu = document.getElementById('ctx-menu');
    menu.querySelectorAll('.ctx-item, .ctx-divider').forEach(el => {
      el.style.display = 'none';
    });
    const rc = menu.querySelector('[data-action="rename-collection"]');
    if (rc) rc.style.display = 'flex';
    const dc = menu.querySelector('[data-action="delete-collection"]');
    if (dc) dc.style.display = 'flex';
    menu.classList.add('show');
    const rect = menu.getBoundingClientRect();
    let left = e.clientX, top = e.clientY;
    if (left + rect.width > window.innerWidth) left = e.clientX - rect.width;
    if (top + rect.height > window.innerHeight) top = window.innerHeight - rect.height - 4;
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
    return;
  }
  if (col.id === -3) {
    hideCtxMenu();
    ctxFolder = null;
    lastCtxX = e.clientX; lastCtxY = e.clientY;
    const menu = document.getElementById('ctx-menu');
    menu.querySelectorAll('.ctx-item, .ctx-divider').forEach(el => {
      el.style.display = 'none';
    });
    const cr = menu.querySelector('[data-action="clear-recent"]');
    if (cr) cr.style.display = 'flex';
    menu.classList.add('show');
    const rect = menu.getBoundingClientRect();
    let left = e.clientX, top = e.clientY;
    if (left + rect.width > window.innerWidth) left = e.clientX - rect.width;
    if (top + rect.height > window.innerHeight) top = window.innerHeight - rect.height - 4;
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  }
}

function getColParentId(cols, cid) {
  for (const c of cols) {
    if (c.children && c.children.some(ch => ch.id === cid)) return c.id;
    if (c.children) {
      const r = getColParentId(c.children, cid);
      if (r !== null) return r;
    }
  }
  return null;
}

function hideCtxMenu() {
  if (subgroupPickerResolve) {
    const r = subgroupPickerResolve;
    subgroupPickerResolve = null;
    r(null);
  }
  document.getElementById('ctx-menu').classList.remove('show');
  document.getElementById('ctx-subgroup-menu').classList.remove('show');
  ctxMeme = null;
  ctxFolder = null;
}

async function showSubgroupPicker(items) {
  return new Promise(resolve => {
    subgroupPickerResolve = resolve;
    const menu = document.getElementById('ctx-subgroup-menu');
    menu.innerHTML = '';
    items.forEach(([label, val]) => {
      const btn = document.createElement('button');
      btn.className = 'ctx-item';
      btn.textContent = label;
      btn.onclick = () => {
        subgroupPickerResolve = null;
        menu.classList.remove('show');
        resolve(val);
      };
      menu.appendChild(btn);
    });
    menu.style.left = '';
    menu.style.top = '';
    menu.classList.add('show');
    const mr = menu.getBoundingClientRect();
    let left = lastCtxX;
    let top = lastCtxY;
    if (left + mr.width > window.innerWidth) left = window.innerWidth - mr.width - 4;
    if (top + mr.height > window.innerHeight) top = window.innerHeight - mr.height - 4;
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
  });
}

function hideSubgroupMenu() {
  if (subgroupPickerResolve) {
    const r = subgroupPickerResolve;
    subgroupPickerResolve = null;
    r(null);
  }
  document.getElementById('ctx-subgroup-menu').classList.remove('show');
}

document.addEventListener('click', (e) => {
  if (e.button === 0 && !e.target.closest('#ctx-menu') && !e.target.closest('#ctx-subgroup-menu')) hideCtxMenu();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const menu = document.getElementById('ctx-menu');
    const sub = document.getElementById('ctx-subgroup-menu');
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
  const f = ctxFolder;
  const m = ctxMeme;
  if (!m && action !== 'delete-folder' && action !== 'rename-collection' && action !== 'delete-collection' && action !== 'clear-recent') return;
  hideCtxMenu();

  if (action === 'delete-folder') {
    if (!f) return;
    const confirmed = await showConfirm('删除小分组', '确定删除小分组「' + f.name + '」？分组内表情包将移回上层分组。');
    if (!confirmed) return;
    // 将所有表情包移回上层
    const parentCol = collections.find(c => c.children && c.children.some(ch => ch.id === f.id));
    const parentId = parentCol ? parentCol.id : null;
    const memesInFolder = await api('search_memes', '', [], f.id) || [];
    for (const mm of memesInFolder) {
      if (parentId) await api('add_to_existing_collection', mm.id, parentId);
    }
    await api('delete_collection', f.id);
    showToast('小分组已删除');
    if (activeCollection === f.id) activeCollection = parentId;
    refreshCollections(); refreshMemes(); return;
  }

  if (action === 'rename-collection') {
    if (!f) return;
    const newName = await showPrompt('重命名分组', f.name);
    if (!newName || newName === f.name) return;
    const ok = await api('rename_collection', f.id, newName);
    if (ok) { showToast('已重命名'); refreshCollections(); }
    else showToast('重命名失败');
    return;
  }

  if (action === 'delete-collection') {
    if (!f) return;
    const confirmed = await showConfirm('删除分组', '确定删除分组「' + f.name + '」？分组内表情包将退回到上级分组。');
    if (!confirmed) return;
    // 将所有表情包移回上级分组（顶层分组的上级为全部）
    const parentId = getColParentId(collections, f.id);
    const memesInFolder = await api('search_memes', '', [], f.id) || [];
    for (const mm of memesInFolder) {
      if (parentId) await api('add_to_existing_collection', mm.id, parentId);
    }
    await api('delete_collection', f.id);
    showToast('分组已删除');
    if (activeCollection === f.id) activeCollection = parentId;
    refreshCollections(); refreshMemes(); return;
  }

  switch (action) {
    case 'rename': {
      const newName = await showPrompt('重命名', m.name);
      if (!newName || newName === m.name) return;
      const ok = await api('rename_meme', m.id, newName);
      if (ok) { showToast('重命名成功'); refreshMemes(); }
      else { showToast('重命名失败'); }
      break;
    }
    case 'favorite': {
      const ok = await api('toggle_favorite', m.id);
      if (ok !== null) {
        await refreshCollections();
        if (!ok && activeCollection === -1) {
          const fav = collections.find(x => x.id === -1);
          if (!fav || fav.count === 0) {
            activeCollection = null;
          }
        }
        refreshMemes(); showToast(ok ? '已收藏' : '已取消收藏');
      }
      break;
    }
    case 'collection': {
      const topCols = (collections || []).filter(c => c.id > 0);
      const els = [['新建分组', '__new__']];
      topCols.forEach(c => els.push([c.name, c.id]));
      const picked = await showSubgroupPicker(els);
      if (picked === '__new__') {
        const name = await showPrompt('添加分组', '');
        if (!name) break;
        const ok = await api('add_to_collection', m.id, name);
        if (ok) { showToast('已添加到分组：' + name); refreshCollections(); }
        else showToast('添加分组失败');
      } else if (picked && picked > 0) {
        const ok = await api('add_to_existing_collection', m.id, picked);
        if (ok) { showToast('已添加到分组'); refreshCollections(); }
        else showToast('添加分组失败');
      }
      break;
    }
    case 'add-to-subgroup': {
      const targetCol = activeCollection && activeCollection > 0 ? activeCollection : null;
      const children = targetCol ? (await api('get_child_collections', targetCol) || []) : [];
      const els = [['新建小分组', '__new__']];
      children.forEach(ch => els.push([ch.name, ch.id]));
      if (els.length === 0) {
        const name = await showPrompt('新建小分组', '');
        if (!name) break;
        if (targetCol) {
          const r = await api('create_subcollection', name, targetCol);
          if (r.ok) await api('add_to_existing_collection', m.id, r.id);
        } else {
          await api('add_to_collection', m.id, name);
        }
        showToast('已添加'); refreshCollections(); refreshMemes(); break;
      }
      const picked = await showSubgroupPicker(els);
      if (picked === '__new__') {
        const name = await showPrompt('新建小分组', '');
        if (!name) break;
        if (targetCol) {
          const r = await api('create_subcollection', name, targetCol);
          if (r.ok) await api('add_to_existing_collection', m.id, r.id);
        } else {
          await api('add_to_collection', m.id, name);
        }
        showToast('已添加'); refreshCollections(); refreshMemes();
      } else if (picked && picked > 0) {
        await api('add_to_existing_collection', m.id, picked);
        showToast('已添加'); refreshCollections(); refreshMemes();
      }
      break;
    }
    case 'remove-collection': {
      const removedFrom = activeCollection;
      const ok = await api('remove_from_collection', m.id, removedFrom);
      if (ok) {
        // 如果是从小分组移除，加回上层大分组
        const allCols = collections;
        let parentId = null;
        for (const c of allCols) {
          if (c.children) {
            const found = c.children.find(ch => ch.id === removedFrom);
            if (found) { parentId = c.id; break; }
          }
        }
        if (parentId) await api('add_to_existing_collection', m.id, parentId);
        showToast('已移回上层分组');
        await refreshCollections();
        const c = collections.find(x => x.id === removedFrom);
        if (!c || c.count === 0) {
          if (removedFrom > 0) await api('delete_collection', removedFrom);
          activeCollection = parentId || null;
          renderCollections();
        }
        refreshMemes();
      } else showToast('移除失败');
      break;
    }
    case 'delete': {
      const confirmed = await showConfirm('删除确认', '确定删除「' + m.name + '」？');
      if (!confirmed) return;
      const ok = await api('delete_meme', m.id);
      if (ok) { showToast('已删除'); refreshMemes(); refreshTags(); refreshCollections(); }
      else { showToast('删除失败'); }
      break;
    }
    case 'remove-recent': {
      const ok = await api('remove_from_recent', m.id);
      if (ok) {
        showToast('已从最近使用中删除');
        await refreshCollections();
        const rc = collections.find(x => x.id === -3);
        if (!rc || rc.count === 0) { activeCollection = null; }
        refreshMemes();
      } else { showToast('操作失败'); }
      break;
    }
    case 'clear-recent': {
      const confirmed = await showConfirm('清空最近使用', '确定清空最近使用列表？');
      if (!confirmed) return;
      const ok = await api('clear_recent');
      if (ok) {
        showToast('已清空最近使用');
        await refreshCollections();
        if (activeCollection === -3) activeCollection = null;
        refreshMemes();
      } else { showToast('操作失败'); }
      break;
    }
  }
});

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
  if (e.target.closest('.title-btn')) return;
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
  initDragReorder();
  document.getElementById('loading').classList.remove('hidden');
  const data = await api('get_init_data');
  if (data) {
    memes = data.memes || [];
    renderGrid();
    allTags = data.tags || [];
    renderTags();
    collections = data.collections || [];
    renderCollections();
  }
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('search').focus();
  setTimeout(async () => {
    await api('rescan_cache');
    await api('run_auto_sync');
    memes = await api('search_memes', '', [], null) || [];
    renderGrid();
    allTags = await api('get_tags') || [];
    renderTags();
    collections = await api('get_collections') || [];
    renderCollections();
    await checkUpdateAndPrompt();
  }, 300);
  // 每日检测更新（复用启动时的检测与弹窗逻辑）
  setInterval(checkUpdateAndPrompt, 24 * 60 * 60 * 1000);
});
