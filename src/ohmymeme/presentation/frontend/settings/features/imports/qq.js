/* QQ Import */
let qqPollTimer = null;

function showQQOverlay() {
  rememberSettingsFocus();
  document.getElementById('qq-import-overlay').style.display = 'flex';
  document.getElementById('btn-qq-save').style.display = 'none';
  document.getElementById('qq-import-error').style.display = 'none';
  document.getElementById('qq-import-title').textContent = '正在导入...';
}

function closeQQOverlay() {
  document.getElementById('qq-import-overlay').style.display = 'none';
  restoreSettingsFocus();
  if (qqPollTimer) { clearInterval(qqPollTimer); qqPollTimer = null; }
  api('cancel_qq_import');
}

async function startQQImport() {
  showQQOverlay();
  document.getElementById('qq-status').style.display = 'none';
  document.getElementById('qq-import-error').style.display = 'none';
  document.getElementById('qq-import-title').textContent = '正在导入...';

  const r = await api('start_qq_import');
  if (!r || !r.ok) {
    document.getElementById('qq-import-title').textContent = '启动失败';
    document.getElementById('qq-import-error').style.display = '';
    document.getElementById('qq-import-error').textContent = (r && r.error) || '未知错误';
    return;
  }

  qqPollTimer = setInterval(async () => {
    const s = await api('get_qq_import_progress');
    if (!s) return;

    const pct = s.progress || 0;
    document.getElementById('qq-import-bar').style.width = pct + '%';
    document.getElementById('qq-import-pct').textContent = pct + '%';
    document.getElementById('qq-import-msg').textContent = s.message || '';

    if (s.status === 'downloading_adb') {
      document.getElementById('qq-import-title').textContent = '正在下载 ADB...';
      document.getElementById('btn-qq-help').style.display = 'none';
      if (s.dl_progress > 0) {
        document.getElementById('qq-import-pct').textContent = '下载中 ' + s.dl_progress + '%';
      }
    } else if (s.status === 'starting_adb') {
      document.getElementById('qq-import-title').textContent = '正在启动 ADB...';
      document.getElementById('btn-qq-help').style.display = 'none';
    } else if (s.status === 'waiting_device') {
      document.getElementById('qq-import-title').textContent = '等待设备连接';
      document.getElementById('btn-qq-help').style.display = '';
    } else if (s.status === 'pulling') {
      document.getElementById('btn-qq-help').style.display = 'none';
      document.getElementById('qq-import-title').textContent = '正在拉取文件...';
    } else if (s.status === 'processing') {
      document.getElementById('qq-import-title').textContent = '正在处理文件...';
      document.getElementById('btn-qq-help').style.display = 'none';
    } else if (s.status === 'done') {
      document.getElementById('btn-qq-help').style.display = 'none';
      document.getElementById('qq-import-title').textContent = '导入完成';
      const fileCount = Number.isFinite(Number(s.total)) ? Number(s.total) : 0;
      document.getElementById('qq-import-msg').textContent = '共导出 ' + fileCount + ' 个文件';
      document.getElementById('btn-qq-save').style.display = '';
      if (qqPollTimer) { clearInterval(qqPollTimer); qqPollTimer = null; }
    } else if (s.status === 'cancelled') {
      document.getElementById('btn-qq-help').style.display = 'none';
      document.getElementById('btn-qq-save').style.display = 'none';
      if (qqPollTimer) { clearInterval(qqPollTimer); qqPollTimer = null; }
      document.getElementById('qq-import-title').textContent = '已取消';
      document.getElementById('qq-import-msg').textContent = s.message || '导入已取消';
    } else if (s.status === 'error') {
      document.getElementById('btn-qq-help').style.display = 'none';
      if (qqPollTimer) { clearInterval(qqPollTimer); qqPollTimer = null; }
      document.getElementById('qq-import-title').textContent = '导入失败';
      document.getElementById('qq-import-error').style.display = '';
      document.getElementById('qq-import-error').textContent = s.error || s.error_code || '未知错误';
    }
  }, 300);
}

function openADBHelp() {
  api('open_adb_help');
}

async function saveQQZip() {
  const btn = document.getElementById('btn-qq-save');
  const errDiv = document.getElementById('qq-import-error');
  errDiv.style.display = 'none';
  btn.disabled = true;
  btn.textContent = '保存中...';
  const r = await api('save_qq_zip');
  btn.disabled = false;
  btn.textContent = '选择保存位置';
  if (r && r.ok) {
    document.getElementById('btn-qq-save').style.display = 'none';
    document.getElementById('qq-import-title').textContent = '导入完成';
    document.getElementById('qq-import-msg').textContent = 'ZIP 已保存到: ' + (r.path || '');
    document.getElementById('qq-import-pct').textContent = '';
    document.getElementById('qq-import-bar').style.display = 'none';
    document.getElementById('qq-after-save').style.display = '';
  } else {
    errDiv.style.display = '';
    errDiv.textContent = (r && r.error) || '保存失败';
  }
}

async function startImportFromZip() {
  const btn = document.getElementById('btn-qq-import-files');
  btn.disabled = true;
  btn.textContent = '导入中...';
  const r = await api('import_memes');
  btn.disabled = false;
  btn.textContent = '选择文件导入';
  if (r && r.ok) {
    closeQQOverlay();
    showToast(r.rejected ? '导入完成，跳过 ' + r.rejected + ' 个超限文件' : '导入完成');
  }
}

/* 抖音表情包下载导入 */
