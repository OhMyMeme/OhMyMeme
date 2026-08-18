let pendingStorageDir = null;

function formatSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 100 ? 0 : 1) + ' ' + units[i];
}

async function loadStorageInfo() {
  let st = null;
  try { st = await api('get_storage_info'); } catch (e) { st = null; }
  if (!st) return;
  const el = document.getElementById('s-cache-dir');
  if (el && st.cache_dir) el.value = st.cache_dir;
  const status = document.getElementById('s-storage-status');
  if (status) {
    status.textContent = '共 ' + (st.file_count || 0) + ' 个表情包，约 ' + formatSize(st.total_size || 0)
      + (st.custom ? '' : '（默认位置）');
  }
}

async function pickStorageDir() {
  const status = document.getElementById('s-storage-status');
  let r = null;
  try { r = await api('pick_storage_dir'); } catch (e) { r = null; }
  if (!r || !r.ok) {
    if (status && !(r && r.cancelled)) status.textContent = '无法打开目录选择对话框';
    return;
  }
  pendingStorageDir = r.path;
  const newDir = document.getElementById('s-cache-dir-new');
  const pending = document.getElementById('s-storage-pending');
  if (newDir) newDir.value = r.path;
  if (pending) pending.style.display = 'block';
  if (status) status.textContent = '';
}

function cancelStoragePick() {
  pendingStorageDir = null;
  const pending = document.getElementById('s-storage-pending');
  if (pending) pending.style.display = 'none';
  loadStorageInfo();
}

async function applyStorageDir() {
  if (!pendingStorageDir) return;
  const moveEl = document.getElementById('s-move-files');
  const move = moveEl ? moveEl.checked === true : true;
  const btn = document.getElementById('btn-storage-apply');
  const status = document.getElementById('s-storage-status');
  const pending = document.getElementById('s-storage-pending');
  if (btn) btn.disabled = true;
  try {
    const r = await api('apply_storage_dir', pendingStorageDir, move);
    if (!r || !r.ok) {
      if (status) status.textContent = '应用失败：' + (r && r.error ? r.error : '未知错误');
      return;
    }
    pendingStorageDir = null;
    if (pending) pending.style.display = 'none';
    const el = document.getElementById('s-cache-dir');
    if (el && r.cache_dir) el.value = r.cache_dir;
    let msg = '已应用新存储目录';
    if (r.moved > 0) msg += '，已移动 ' + r.moved + ' 个文件';
    if (r.failed && r.failed.length) msg += '，失败 ' + r.failed.length + ' 个：' + r.failed.map(f => f.path || f.name).join('、');
    if (status) status.textContent = msg;
    showToast('存储位置已更新');
  } catch (e) {
    if (status) status.textContent = '应用失败：' + (e && e.message ? e.message : '未知错误');
  } finally {
    if (btn) btn.disabled = false;
  }
}
