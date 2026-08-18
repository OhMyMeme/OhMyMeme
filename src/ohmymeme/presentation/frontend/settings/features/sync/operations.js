async function testSync() {
  const sync = collectSyncSettings();
  if (!validateSync(sync)) return;
  const btn = document.getElementById('btn-ftp-test');
  const status = document.getElementById('s-sync-status');
  btn.disabled = true; btn.textContent = '连接中...'; status.textContent = '';
  await api('save_settings', sync);
  const r = await api('sync_test');
  btn.disabled = false; btn.textContent = '测试连接';
  status.textContent = r === 'ok' ? '连接成功' : '连接失败: ' + r;
}

async function checkSyncStatus() {
  const status = document.getElementById('s-sync-status');
  status.textContent = '检查中...';
  const r = await api('check_sync_status');
  if (!r || !r.ok) {
    status.textContent = '检查失败: ' + ((r && r.error) || '未知错误');
    return;
  }
  if (r.synced) {
    status.textContent = '本地云端已同步（本地 ' + r.local_count + ' 个，云端 ' + r.remote_count + ' 个）';
    showToast('本地云端已同步');
    return;
  }
  let msg = '本地共 ' + r.local_count + ' 个，云端共 ' + r.remote_count + ' 个';
  if (r.local_extra > 0) msg += '，本地多余 ' + r.local_extra + ' 个';
  if (r.local_missing > 0) msg += '，本地缺少 ' + r.local_missing + ' 个';
  status.textContent = msg;
  showToast('同步状态：' + msg);
}

let _orphanFiles = [];

async function scanOrphans() {
  const status = document.getElementById('s-orphan-status');
  const del = document.getElementById('btn-orphan-delete');
  status.textContent = '扫描中...';
  const r = await api('get_remote_orphans', false);
  if (!r || !r.ok) {
    status.textContent = '扫描失败: ' + ((r && r.error) || '未知错误');
    return;
  }
  _orphanFiles = r.orphans || [];
  status.textContent = _orphanFiles.length
    ? '发现 ' + _orphanFiles.length + ' 个孤儿文件'
    : '无孤儿文件';
  del.disabled = _orphanFiles.length === 0;
}

async function deleteOrphans() {
  if (!_orphanFiles.length) return;
  const status = document.getElementById('s-orphan-status');
  const r = await api('get_remote_orphans', true);
  if (!r || !r.ok) {
    status.textContent = '删除失败: ' + ((r && r.error) || '未知错误');
    return;
  }
  status.textContent = '已删除 ' + r.removed + ' 个孤儿文件';
  _orphanFiles = [];
  document.getElementById('btn-orphan-delete').disabled = true;
}

async function showUploadWarning() {
  const sync = collectSyncSettings();
  if (!sync.sync_delete_remote) return true;
  if (sync.sync_hide_upload_warning) return true;
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
    overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    const box = document.createElement('div');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:380px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:14px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">上传确认</h2>'
      + '<p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">上传会将本地的完整状态同步到远端，包括新增、更新和删除操作。远程文件将被覆盖，建议先下载备份。</p></div>'
      + '<label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12.5px;color:var(--muted);margin-bottom:16px;user-select:none">'
      + '<input id="supload-warn-hide" type="checkbox" style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer">不再提醒</label>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end">'
      + '<button id="supload-modal-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="supload-modal-confirm" class="btn btn-primary">继续上传</button></div>';
    overlay.appendChild(box);
    rememberSettingsFocus();
    document.body.appendChild(overlay);
    document.getElementById('supload-modal-confirm').focus();
    const cleanup = () => { overlay.remove(); restoreSettingsFocus(); };
    document.getElementById('supload-modal-confirm').onclick = async () => {
      const hide = document.getElementById('supload-warn-hide').checked;
      if (hide) await api('save_settings', { sync_hide_upload_warning: true });
      cleanup(); resolve(true);
    };
    document.getElementById('supload-modal-cancel').onclick = () => { cleanup(); resolve(false); };
    overlay.onkeydown = (e) => { if (e.key === 'Escape') { e.stopPropagation(); cleanup(); resolve(false); } else trapSettingsFocus(box, e); };
  });
}

let syncPollTimer = null;
let syncBg = false;

function hideSyncProgress() {
  syncBg = true;
  document.getElementById('sync-progress-overlay').style.display = 'none';
  restoreSettingsFocus();
  if (syncPollTimer) { clearInterval(syncPollTimer); syncPollTimer = null; }
}

function hideSyncDone() {
  document.getElementById('sync-done-overlay').style.display = 'none';
  restoreSettingsFocus();
  location.reload();
}

function formatSpeed(bytesPerSec) {
  if (bytesPerSec >= 1048576) return (bytesPerSec / 1048576).toFixed(1) + ' MB/s';
  if (bytesPerSec >= 1024) return (bytesPerSec / 1024).toFixed(1) + ' KB/s';
  return bytesPerSec.toFixed(0) + ' B/s';
}

async function doSyncWithProgress(method, title, progressSetting, doneSetting, btnId, statusId) {
  const sync = collectSyncSettings();
  if (!validateSync(sync)) return;
  const warnOk = await showUploadWarning();
  if (!warnOk) return;
  await api('save_settings', sync);

  // 检查设置
  const showProgress = document.getElementById(progressSetting)?.checked !== false;
  const showDone = document.getElementById(doneSetting)?.checked !== false;

  const btn = document.getElementById(btnId);
  const status = document.getElementById(statusId);
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = '同步中...';
  status.textContent = '';

  syncBg = false;

  if (showProgress) {
    rememberSettingsFocus();
    document.getElementById('sync-progress-title').textContent = title;
    document.getElementById('sync-progress-file').textContent = '准备中...';
    document.getElementById('sync-progress-bar').style.width = '0%';
    document.getElementById('sync-progress-pct').textContent = '0%';
    document.getElementById('sync-progress-speed').textContent = '';
    document.getElementById('sync-progress-overlay').style.display = 'flex';

    syncPollTimer = setInterval(async () => {
      const s = await api('get_sync_progress');
      if (!s || s.status === 'idle') return;
      document.getElementById('sync-progress-file').textContent = s.current_file || '';
      document.getElementById('sync-progress-bar').style.width = (s.progress || 0) + '%';
      document.getElementById('sync-progress-pct').textContent = (s.progress || 0) + '%';
      if (s.speed) {
        document.getElementById('sync-progress-speed').textContent = formatSpeed(s.speed);
      }
    }, 300);
  }

  const r = await api(method);
  btn.disabled = false;
  btn.textContent = origText;

  if (syncPollTimer) { clearInterval(syncPollTimer); syncPollTimer = null; }

  if (showProgress && !syncBg) {
    document.getElementById('sync-progress-overlay').style.display = 'none';
    restoreSettingsFocus();
  }

  if (r && r.ok) {
    const uploaded = r.uploaded || r.downloaded || 0;
    const skipped = r.skipped || 0;
    const errors = r.errors || 0;
    status.textContent = '完成: 成功 ' + uploaded + ', 跳过 ' + skipped + ', 错误 ' + errors;

    if (showDone) {
      rememberSettingsFocus();
      document.getElementById('sync-done-title').textContent = title + '完成';
      document.getElementById('sync-done-detail').textContent = '成功 ' + uploaded + ' 个';
      document.getElementById('sync-done-overlay').style.display = 'flex';
      const closeBtn = document.querySelector('#sync-done-overlay .btn');
      if (closeBtn) closeBtn.focus();
    }
  } else {
    let msg = '失败: ' + ((r && r.error) || '未知错误');
    const ff = (r && r.failed_files) || [];
    if (ff.length) {
      const errors = ff.filter(f => f.status !== 'unknown');
      const unknowns = ff.filter(f => f.status === 'unknown');
      const parts = [];
      if (errors.length) {
        const names = errors.slice(0, 5).map(f => f.filename || '?').join(', ');
        parts.push('失败 ' + errors.length + ' 个: ' + names);
      }
      if (unknowns.length) {
        parts.push(unknowns.length + ' 个删除结果不确定，将在下次同步时复核');
      }
      msg += '（' + parts.join('；') + '）';
    }
    status.textContent = msg;
  }

  // 刷新主窗口
  try { pywebview.api.refresh_memes?.(); } catch(_) {}
  try { pywebview.api.refresh_tags?.(); } catch(_) {}
  try { pywebview.api.refresh_collections?.(); } catch(_) {}
}

async function syncPush() {
  await doSyncWithProgress('sync_push', '上传中...', 's-show-up-progress', 's-show-up-done', 'btn-sync-push', 's-sync-status');
}

async function syncPull() {
  await doSyncWithProgress('sync_pull', '下载中...', 's-show-dl-progress', 's-show-dl-done', 'btn-sync-pull', 's-sync-status');
}


