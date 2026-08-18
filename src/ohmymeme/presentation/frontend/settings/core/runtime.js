/* API helper */
function api(method, ...args) {
  if (typeof pywebview === 'undefined' || !pywebview.api || typeof pywebview.api[method] !== 'function') {
    return null;
  }
  try { return pywebview.api[method](...args); }
  catch(e) { console.error('api error', method, e); return null; }
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
  s = s.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (m, lang, code) => {
    return '<pre class="md-pre"><code>' + code + '</code></pre>';
  });
  s = s.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>');
  s = s.replace(/^##### (.*)$/gm, '<h5 class="md-h">$1</h5>');
  s = s.replace(/^#### (.*)$/gm, '<h4 class="md-h">$1</h4>');
  s = s.replace(/^### (.*)$/gm, '<h3 class="md-h">$1</h3>');
  s = s.replace(/^## (.*)$/gm, '<h2 class="md-h">$1</h2>');
  s = s.replace(/^# (.*)$/gm, '<h1 class="md-h">$1</h1>');
  s = s.replace(/^&gt; (.*)$/gm, '<blockquote class="md-quote">$1</blockquote>');
  s = s.replace(/^[-*] (.*)$/gm, '<li class="md-li">$1</li>');
  s = s.replace(/^\d+\. (.*)$/gm, '<li class="md-li">$1</li>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="md-link">$1</span>');
  s = s.replace(/^-{3,}$/gm, '<hr class="md-hr">');
  s = s.replace(/\n/g, '<br>');
  s = s.replace(/(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)\s*<br>/g, '$1');
  s = s.replace(/<br>\s*(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)/g, '$1');
  return s;
}

/* 覆盖层焦点管理（无障碍） */
let _settingsFocusTarget = null;
function rememberSettingsFocus() {
  _settingsFocusTarget = document.activeElement instanceof HTMLElement ? document.activeElement : null;
}
function restoreSettingsFocus() {
  const el = _settingsFocusTarget;
  _settingsFocusTarget = null;
  if (el && el.isConnected) el.focus();
}
// Tab 循环：把焦点限制在覆盖层 box 内
function trapSettingsFocus(box, e) {
  if (e.key !== 'Tab') return;
  const items = box.querySelectorAll('button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (e.shiftKey && (active === first || !box.contains(active))) {
    e.preventDefault(); last.focus();
  } else if (!e.shiftKey && (active === last || !box.contains(active))) {
    e.preventDefault(); first.focus();
  }
}
// 找当前可见覆盖层（静态 HTML + 动态创建的 update/confirm 弹窗）
const _SETTINGS_OVERLAY_IDS = ['danger-overlay','sync-progress-overlay','sync-done-overlay','qq-import-overlay','qqnt-overlay','tg-import-overlay','dy-import-overlay','wechat-import-overlay','update-overlay'];
function visibleSettingsOverlay() {
  for (const id of _SETTINGS_OVERLAY_IDS) {
    const el = document.getElementById(id);
    if (el && el.style.display !== 'none') {
      return el.querySelector('[role="dialog"]') || el;
    }
  }
  return null;
}

/* Close settings window */
let _settingsDirty = false;
function markSettingsDirty() { _settingsDirty = true; }

// 收集表单输入，未保存的修改在关闭/按 Esc 时提示
function initDirtyTracking() {
  const root = document.getElementById('settings-content');
  if (!root) return;
  const track = (e) => {
    const t = e.target;
    if (t && t.matches && t.matches('input, select, textarea')) markSettingsDirty();
  };
  root.addEventListener('input', track);
  root.addEventListener('change', track);
}

async function closeSettings() {
  if (_settingsDirty) {
    const ok = await showConfirm('有未保存的更改', '当前修改尚未保存，确定放弃并关闭设置窗口吗？');
    if (!ok) return;
  }
  try { pywebview.api.close_settings(); } catch(e) {}
}

