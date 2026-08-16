function api(method, ...args) {
  return window.pywebview.api[method](...args);
}

let searchTimer = null;

function esc(value) {
  return String(value || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[c]);
}

async function refreshFloatingResults() {
  const input = document.getElementById('floating-search');
  const grid = document.getElementById('floating-grid');
  const empty = document.getElementById('floating-empty');
  const items = await api('floating_search_memes', input.value.trim(), 48) || [];
  grid.innerHTML = '';
  items.forEach(item => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'floating-card';
    card.title = item.name;
    card.innerHTML = '<img alt="' + esc(item.name) + '" src="/api/thumb/' + item.id + '/' + encodeURIComponent(item.filename) + '"><span class="floating-name">' + esc(item.name) + '</span>';
    card.onclick = async () => {
      const result = await api('copy_meme_from_floating', item.id);
      if (result && result.ok) {
        window.pywebview.api.hide_floating_window();
      }
    };
    grid.appendChild(card);
  });
  empty.style.display = items.length ? 'none' : 'block';
}

function focusFloatingSearch() {
  const input = document.getElementById('floating-search');
  input.focus();
  input.select();
}

window.focusFloatingSearch = focusFloatingSearch;

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('floating-search');
  const titlebar = document.getElementById('floating-titlebar');
  let dragState = null;
  let dragFrame = 0;
  let dragTarget = null;
  titlebar.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button')) return;
    dragState = {
      offsetX: e.screenX - window.screenX,
      offsetY: e.screenY - window.screenY,
    };
    titlebar.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  titlebar.addEventListener('pointermove', e => {
    if (!dragState) return;
    dragTarget = {
      x: e.screenX - dragState.offsetX,
      y: e.screenY - dragState.offsetY,
    };
    if (dragFrame) return;
    dragFrame = requestAnimationFrame(() => {
      dragFrame = 0;
      if (dragTarget) window.pywebview.api.move_floating_window(dragTarget.x, dragTarget.y);
    });
  });
  const stopFloatingDrag = e => {
    if (!dragState) return;
    if (titlebar.hasPointerCapture(e.pointerId)) titlebar.releasePointerCapture(e.pointerId);
    dragState = null;
    dragTarget = null;
  };
  titlebar.addEventListener('pointerup', stopFloatingDrag);
  titlebar.addEventListener('pointercancel', stopFloatingDrag);
  input.oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(refreshFloatingResults, 120);
  };
  input.onkeydown = e => {
    if (e.key === 'Escape') window.pywebview.api.hide_floating_window();
  };
  document.getElementById('floating-close').onclick = () => window.pywebview.api.hide_floating_window();
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') window.pywebview.api.hide_floating_window();
  });
  refreshFloatingResults();
  focusFloatingSearch();
});
