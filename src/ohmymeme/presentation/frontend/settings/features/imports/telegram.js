/* Telegram 缓存导入 */
let tgPollTimer = null;

function openTGImportDialog() {
  rememberSettingsFocus();
  document.getElementById('tg-import-overlay').style.display = 'flex';
  document.getElementById('tg-config').style.display = 'block';
  document.getElementById('tg-progress').style.display = 'none';
  document.getElementById('tg-import-error').style.display = 'none';
  const status = document.getElementById('tg-status');
  if (status) { status.textContent = ''; status.className = ''; }
  const btn = document.getElementById('btn-tg-start');
  if (btn) btn.disabled = false;
  const passcode = document.getElementById('s-tg-passcode');
  if (passcode) passcode.focus();
}

function formatDuration(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m > 0) return m + '分' + (s > 0 ? s + '秒' : '');
  return s + '秒';
}

function updateTgEta(s) {
  const el = document.getElementById('tg-import-eta');
  if (!el || !s) return;
  const prog = s.progress || 0;
  const elapsed = s.elapsed_s || 0;
  const terminal = ['done', 'error', 'cancelled'].includes(s.status);
  if (prog <= 0 || elapsed <= 0 || terminal) {
    el.textContent = elapsed > 0 ? '已用 ' + formatDuration(elapsed) : '';
    return;
  }
  const remain = (100 - prog) / prog * elapsed;
  el.textContent = '已用 ' + formatDuration(elapsed) + ' · 预计剩余 ' + formatDuration(remain);
}

function showTGOverlay() {
  document.getElementById('tg-config').style.display = 'none';
  document.getElementById('tg-progress').style.display = 'block';
  document.getElementById('tg-import-overlay').style.display = 'flex';
  document.getElementById('tg-import-error').style.display = 'none';
  document.getElementById('btn-tg-retry').style.display = 'none';
  document.getElementById('tg-import-title').textContent = '正在导入...';
  document.getElementById('tg-import-msg').textContent = '准备中';
  document.getElementById('tg-import-bar').style.width = '0%';
  document.getElementById('tg-import-pct').textContent = '0%';
  const etaEl = document.getElementById('tg-import-eta');
  if (etaEl) etaEl.textContent = '';
  const closeBtn = document.getElementById('btn-tg-close');
  if (closeBtn) closeBtn.focus();
}

function closeTGOverlay() {
  document.getElementById('tg-import-overlay').style.display = 'none';
  restoreSettingsFocus();
  if (tgPollTimer) { clearInterval(tgPollTimer); tgPollTimer = null; }
  api('cancel_tg_import');
}

async function pickTGTdata() {
  const r = await api('pick_tg_tdata');
  if (!r || r.cancelled) return;
  const inp = document.getElementById('s-tg-tdata');
  if (r.ok && inp) {
    inp.value = r.path;
    showToast('tdata 目录已设置');
  } else {
    showToast((r && r.error) || '选择失败');
  }
}

function tgRetryPick() {
  closeTGOverlay();
  pickTGTdata();
  openTGImportDialog();
}

async function startTGImport() {
  const btn = document.getElementById('btn-tg-start');
  const status = document.getElementById('tg-status');
  if (!btn || !status) return;
  btn.disabled = true; status.textContent = ''; status.className = '';

  const tdataEl = document.getElementById('s-tg-tdata');
  const passcodeEl = document.getElementById('s-tg-passcode');
  const convertEl = document.getElementById('s-tg-convert');
  const tdata = tdataEl ? tdataEl.value : '';
  const passcode = passcodeEl ? passcodeEl.value : '';
  const convert = convertEl ? convertEl.checked !== false : true;

  let r;
  try {
    r = await api('start_tg_import', tdata || null, passcode, convert);
  } catch (e) {
    btn.disabled = false;
    status.textContent = '启动失败: ' + (e.message || e);
    status.className = 'error';
    return;
  }
  if (!r || !r.ok) {
    btn.disabled = false;
    status.textContent = '启动失败';
    status.className = 'error';
    return;
  }

  showTGOverlay();

  let nullCount = 0;
  let pollInFlight = false;
  tgPollTimer = setInterval(async () => {
    if (pollInFlight) return;
    pollInFlight = true;
    try {
      const s = await api('get_tg_import_progress');
      if (!s) {
        nullCount++;
        if (nullCount > 20) {
          if (tgPollTimer) { clearInterval(tgPollTimer); tgPollTimer = null; }
          document.getElementById('tg-import-title').textContent = '导入失败';
          document.getElementById('tg-import-error').style.display = '';
          document.getElementById('tg-import-error').textContent = '连接中断';
          btn.disabled = false;
        }
        return;
      }
      nullCount = 0;

      document.getElementById('tg-import-bar').style.width = (s.progress || 0) + '%';
      document.getElementById('tg-import-pct').textContent = (s.progress || 0) + '%';
      document.getElementById('tg-import-msg').textContent = s.message || '';
      updateTgEta(s);

      if (s.status === 'done') {
        document.getElementById('tg-import-title').textContent = '导入完成';
        if (tgPollTimer) { clearInterval(tgPollTimer); tgPollTimer = null; }
        const el = document.getElementById('tg-status');
        el.textContent = s.message || '导入完成';
        el.className = '';
        if (passcodeEl) passcodeEl.value = '';
        btn.disabled = false;
      } else if (s.status === 'error') {
        document.getElementById('tg-import-title').textContent = '导入失败';
        if (tgPollTimer) { clearInterval(tgPollTimer); tgPollTimer = null; }
        const el = document.getElementById('tg-status');
        let errMsg = s.error || '未知错误';
        if (s.error_code === 'no_ffmpeg') {
          errMsg += '；安装 ffmpeg 后可重试，或取消勾选「WebM 转 WebP」直接导入静态贴纸';
        }
        el.textContent = '导入失败: ' + errMsg;
        el.className = 'error';
        document.getElementById('tg-import-error').style.display = '';
        document.getElementById('tg-import-error').textContent = errMsg;
        if (['no_tdata', 'invalid_tdata', 'no_cache'].includes(s.error_code)) {
          document.getElementById('btn-tg-retry').style.display = '';
        }
        btn.disabled = false;
      } else if (s.status === 'cancelled') {
        document.getElementById('tg-import-title').textContent = '已取消';
        if (tgPollTimer) { clearInterval(tgPollTimer); tgPollTimer = null; }
        btn.disabled = false;
      }
    } catch (e) {
      if (tgPollTimer) { clearInterval(tgPollTimer); tgPollTimer = null; }
      document.getElementById('tg-import-title').textContent = '导入失败';
      document.getElementById('tg-import-error').style.display = '';
      document.getElementById('tg-import-error').textContent = e.message || '连接异常';
      btn.disabled = false;
    } finally {
      pollInFlight = false;
    }
  }, 300);
}

