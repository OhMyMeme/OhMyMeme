/* Toast */
let toastTimer;
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1600);
}

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

/* Keyboard shortcuts */
document.addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    const box = visibleSettingsOverlay();
    if (box) { trapSettingsFocus(box, e); return; }
  }
  if (e.key === 'Escape') {
    const dangerOverlay = document.getElementById('danger-overlay');
    if (dangerOverlay && dangerOverlay.style.display === 'flex') {
      dangerCancel();
      return;
    }
    const dyOverlay = document.getElementById('dy-import-overlay');
    if (dyOverlay && dyOverlay.style.display === 'flex') {
      closeDYOverlay();
      return;
    }
    const tgOverlay = document.getElementById('tg-import-overlay');
    if (tgOverlay && tgOverlay.style.display === 'flex') {
      closeTGOverlay();
      return;
    }
    const wechatOverlay = document.getElementById('wechat-import-overlay');
    if (wechatOverlay && wechatOverlay.style.display === 'flex') {
      closeWechatOverlay();
      return;
    }
    const qqOverlay = document.getElementById('qq-import-overlay');
    if (qqOverlay && qqOverlay.style.display === 'flex') {
      closeQQOverlay();
      return;
    }
    const qqntOverlay = document.getElementById('qqnt-overlay');
    if (qqntOverlay && qqntOverlay.style.display === 'flex') {
      qqntClose();
      return;
    }
    const syncOverlay = document.getElementById('sync-progress-overlay');
    if (syncOverlay && syncOverlay.style.display === 'flex') {
      hideSyncProgress();
      return;
    }
    const syncDoneOverlay = document.getElementById('sync-done-overlay');
    if (syncDoneOverlay && syncDoneOverlay.style.display === 'flex') {
      syncDoneOverlay.style.display = 'none';
      restoreSettingsFocus();
      return;
    }
    closeSettings();
  }
  if (e.key === 'Enter' && e.ctrlKey) saveSettings();
});

