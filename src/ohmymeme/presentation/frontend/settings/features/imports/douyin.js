let dyPollTimer = null;

function openDYImportDialog() {
  rememberSettingsFocus();
  document.getElementById('dy-import-overlay').style.display = 'flex';
  document.getElementById('dy-config').style.display = 'block';
  document.getElementById('dy-progress').style.display = 'none';
  document.getElementById('dy-import-error').style.display = 'none';
  const status = document.getElementById('dy-status');
  if (status) { status.textContent = ''; status.className = ''; }
  const btn = document.getElementById('btn-dy-start');
  if (btn) btn.disabled = false;
  const firstInput = document.getElementById('s-dy-cookie');
  if (firstInput) firstInput.focus();
}

function showDYOverlay() {
  document.getElementById('dy-config').style.display = 'none';
  document.getElementById('dy-progress').style.display = 'block';
  document.getElementById('dy-import-overlay').style.display = 'flex';
  document.getElementById('dy-import-error').style.display = 'none';
  document.getElementById('dy-import-title').textContent = '正在下载...';
  document.getElementById('dy-import-msg').textContent = '准备中';
  document.getElementById('dy-import-bar').style.width = '0%';
  document.getElementById('dy-import-pct').textContent = '0%';
}

function closeDYOverlay() {
  document.getElementById('dy-import-overlay').style.display = 'none';
  restoreSettingsFocus();
  if (dyPollTimer) { clearInterval(dyPollTimer); dyPollTimer = null; }
  api('cancel_douyin_import');
}

async function startDYImport() {
  const btn = document.getElementById('btn-dy-start');
  const status = document.getElementById('dy-status');
  if (!btn || !status) return;
  btn.disabled = true; status.textContent = ''; status.className = '';

  const cookieEl = document.getElementById('s-dy-cookie');
  const cookie = cookieEl ? cookieEl.value.trim() : '';

  if (!cookie) {
    btn.disabled = false;
    status.textContent = '请先填写抖音 Cookie';
    status.className = 'error';
    return;
  }

  let r;
  try {
    r = await api('start_douyin_import', cookie);
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

  showDYOverlay();

  let nullCount = 0;
  let pollInFlight = false;
  dyPollTimer = setInterval(async () => {
    if (pollInFlight) return;
    pollInFlight = true;
    try {
      const s = await api('get_douyin_import_progress');
      if (!s) {
        nullCount++;
        if (nullCount > 20) {
          if (dyPollTimer) { clearInterval(dyPollTimer); dyPollTimer = null; }
          document.getElementById('dy-import-title').textContent = '导入失败';
          document.getElementById('dy-import-error').style.display = '';
          document.getElementById('dy-import-error').textContent = '连接中断';
          btn.disabled = false;
        }
        return;
      }
      nullCount = 0;

      document.getElementById('dy-import-bar').style.width = (s.progress || 0) + '%';
      document.getElementById('dy-import-pct').textContent = (s.progress || 0) + '%';
      document.getElementById('dy-import-msg').textContent = s.message || '';

      if (s.status === 'done') {
        document.getElementById('dy-import-title').textContent = '导入完成';
        if (dyPollTimer) { clearInterval(dyPollTimer); dyPollTimer = null; }
        const el = document.getElementById('dy-status');
        el.textContent = s.message || '导入完成';
        el.className = '';
        if (cookieEl) cookieEl.value = '';
        btn.disabled = false;
      } else if (s.status === 'error') {
        document.getElementById('dy-import-title').textContent = '导入失败';
        if (dyPollTimer) { clearInterval(dyPollTimer); dyPollTimer = null; }
        let hint = s.error || '未知错误';
        if (s.error_code === 'login_failed') {
          hint += '；请从浏览器抖音网页版重新复制 Cookie 后重试';
        } else if (s.error_code === 'sign_failed') {
          hint += '；请稍后重试，或更新 Cookie 后再试';
        } else if (s.error_code === 'no_stickers') {
          hint += '；请确认抖音收藏的自定义表情包存在';
        }
        const el = document.getElementById('dy-status');
        el.textContent = '导入失败: ' + hint;
        el.className = 'error';
        document.getElementById('dy-import-error').style.display = '';
        document.getElementById('dy-import-error').textContent = hint;
        btn.disabled = false;
      } else if (s.status === 'cancelled') {
        document.getElementById('dy-import-title').textContent = '已取消';
        if (dyPollTimer) { clearInterval(dyPollTimer); dyPollTimer = null; }
        btn.disabled = false;
      }
    } catch (e) {
      if (dyPollTimer) { clearInterval(dyPollTimer); dyPollTimer = null; }
      document.getElementById('dy-import-title').textContent = '导入失败';
      document.getElementById('dy-import-error').style.display = '';
      document.getElementById('dy-import-error').textContent = e.message || '连接异常';
      btn.disabled = false;
    } finally {
      pollInFlight = false;
    }
  }, 300);
}

