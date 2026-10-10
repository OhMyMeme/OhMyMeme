/* Backup */
let backupPollTimer = null;
let backupRunning = false;

async function loadBackupInfo() {
  const info = await api('backup_get_info');
  if (!info?.ok) return;
  document.getElementById('backup-dir').textContent = info.directory;
  document.getElementById('backup-dir-custom').style.display = info.custom ? '' : 'none';
  const list = document.getElementById('backup-list');
  list.replaceChildren();
  for (const file of info.backups || []) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;align-items:center';
    const name = document.createElement('span');
    name.textContent = file.name + ' · ' + formatSize(file.size);
    name.style.cssText = 'flex:1;word-break:break-all;font-size:12px';
    const remove = document.createElement('button');
    remove.className = 'btn btn-danger-outline btn-sm';
    remove.textContent = '删除';
    remove.onclick = async () => {
      if (!await showConfirm('删除备份', '确定删除 ' + file.name + '？')) return;
      const result = await api('backup_delete', file.name);
      if (!result?.ok) { showToast(result?.error || '删除失败'); return; }
      loadBackupInfo();
    };
    row.append(name, remove);
    list.append(row);
  }
  if (!list.children.length) list.textContent = '暂无备份';
}

async function pickBackupDir() {
  const result = await api('backup_pick_dir');
  if (!result?.ok) {
    if (!result?.cancelled) showToast(result?.error || '选择备份目录失败');
    return;
  }
  loadBackupInfo();
}

async function startBackupCreate() {
  const result = await api('backup_create');
  if (!result?.ok) { showToast(result?.error || '无法开始备份'); return; }
  showBackupProgress('备份中…');
}

async function startBackupRestore() {
  const selected = await api('backup_pick_zip');
  if (!selected?.ok) return;
  if (!await showConfirm('恢复备份', '确定从此 ZIP 恢复？仅支持空库，恢复后保留标签、收藏和分组。')) return;
  const result = await api('backup_restore', selected.path);
  if (!result?.ok) { showToast(result?.error || '无法开始恢复'); return; }
  showBackupProgress('恢复中…');
}

function showBackupProgress(title) {
  const overlay = document.getElementById('backup-progress-overlay');
  rememberSettingsFocus();
  backupRunning = true;
  document.getElementById('backup-progress-title').textContent = title;
  document.getElementById('btn-backup-progress-close').style.display = 'none';
  document.getElementById('backup-progress-text').textContent = '准备中';
  document.getElementById('backup-progress-bar').style.width = '0%';
  document.getElementById('backup-progress-pct').textContent = '0%';
  overlay.style.display = 'flex';
  overlay.querySelector('[role="dialog"]').focus();
  if (backupPollTimer) clearInterval(backupPollTimer);
  backupPollTimer = setInterval(async () => {
    const state = await api('backup_progress');
    if (!state) return;
    document.getElementById('backup-progress-bar').style.width = (state.progress || 0) + '%';
    document.getElementById('backup-progress-pct').textContent = (state.progress || 0) + '%';
    if (!['done', 'error', 'cancelled'].includes(state.status)) return;
    clearInterval(backupPollTimer);
    backupPollTimer = null;
    backupRunning = false;
    document.getElementById('backup-progress-text').textContent = state.status === 'done' ? '操作完成' : (state.error || '操作已取消');
    const close = document.getElementById('btn-backup-progress-close');
    close.style.display = '';
    close.focus();
    loadBackupInfo();
    if (state.status === 'done') {
      api('refresh_memes'); api('refresh_tags'); api('refresh_collections');
    }
  }, 300);
}

function closeBackupProgress() {
  if (backupRunning) return;
  document.getElementById('backup-progress-overlay').style.display = 'none';
  restoreSettingsFocus();
}
