/* Hotkey capture */
let hotkeyCapturing = false;
function startHotkeyCapture(input) {
  if (hotkeyCapturing) return;
  hotkeyCapturing = true;
  input.value = '';
  input.placeholder = '按下快捷键...';
  input.style.borderColor = 'var(--accent)';
  const handler = (e) => {
    e.preventDefault(); e.stopPropagation();
    const parts = [];
    if (e.ctrlKey) parts.push('Ctrl');
    if (e.altKey) parts.push('Alt');
    if (e.shiftKey) parts.push('Shift');
    if (e.metaKey) parts.push('Win');
    const key = e.key;
    if (['Control','Alt','Shift','Meta'].includes(key)) return;
    let mk = key;
    if (mk === ' ') mk = 'Space';
    if (mk.length === 1) mk = mk.toUpperCase();
    parts.push(mk);
    input.value = parts.join('+');
    input.placeholder = '';
    input.style.borderColor = 'var(--border)';
    hotkeyCapturing = false;
    document.removeEventListener('keydown', handler, true);
  };
  document.addEventListener('keydown', handler, true);
}

function toggleSilentStart() {
  const autoStart = document.getElementById('s-auto-start')?.checked === true;
  const row = document.getElementById('s-silent-row');
  if (row) row.style.display = autoStart ? '' : 'none';
}

async function exportLogs() {
  const status = document.getElementById('log-export-status');
  status.textContent = '正在导出...';
  const r = await api('export_logs');
  if (!r || !r.ok) {
    status.textContent = '导出失败：' + ((r && r.error) || '未知错误');
    return;
  }
  status.textContent = '已导出 ' + r.count + ' 条日志：' + r.path;
  showToast('日志已导出');
}
