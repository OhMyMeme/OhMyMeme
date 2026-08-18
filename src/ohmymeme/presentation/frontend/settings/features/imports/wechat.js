/* 微信缓存导入 */
let wechatPollTimer = null;

function isWechatAccountUsable(a) {
  return a.status === 'supported' || a.status === 'encrypted_index';
}

function wechatRootInput() {
  const el = document.getElementById('s-wechat-root');
  return (el && el.value) || null;
}

function wechatSetCloseLabel(label) {
  const el = document.getElementById('btn-wechat-close');
  if (el) el.textContent = label;
}

function openWechatImportDialog() {
  rememberSettingsFocus();
  document.getElementById('wechat-import-overlay').style.display = 'flex';
  document.getElementById('wechat-config').style.display = 'block';
  document.getElementById('wechat-progress').style.display = 'none';
  document.getElementById('wechat-import-error').style.display = 'none';
  const status = document.getElementById('wechat-status');
  if (status) { status.textContent = ''; status.className = ''; }
  const btn = document.getElementById('btn-wechat-start');
  if (btn) btn.disabled = false;
  wechatSetCloseLabel('取消导入');
  const pick = document.getElementById('btn-wechat-pick');
  if (pick) pick.focus();
}

function showWechatOverlay() {
  document.getElementById('wechat-config').style.display = 'none';
  document.getElementById('wechat-progress').style.display = 'block';
  document.getElementById('wechat-import-overlay').style.display = 'flex';
  document.getElementById('wechat-import-error').style.display = 'none';
  document.getElementById('wechat-import-title').textContent = '正在导入...';
  document.getElementById('wechat-import-msg').textContent = '准备中';
  document.getElementById('wechat-import-bar').style.width = '0%';
  document.getElementById('wechat-import-pct').textContent = '0%';
  wechatSetCloseLabel('取消导入');
  const closeBtn = document.getElementById('btn-wechat-close');
  if (closeBtn) closeBtn.focus();
}

function closeWechatOverlay() {
  document.getElementById('wechat-import-overlay').style.display = 'none';
  restoreSettingsFocus();
  const btn = document.getElementById('btn-wechat-start');
  if (btn) btn.disabled = false;
  if (wechatPollTimer) {
    clearInterval(wechatPollTimer); wechatPollTimer = null;
    api('cancel_wechat_import');
  }
}

async function pickWechatRoot() {
  const r = await api('pick_wechat_root');
  if (!r || r.cancelled) return;
  const inp = document.getElementById('s-wechat-root');
  if (r.ok && inp) {
    inp.value = r.path;
    showToast('微信目录已设置');
  } else {
    showToast((r && r.error) || '选择失败');
  }
}

function wechatRenderAccounts(r) {
  const group = document.getElementById('s-wechat-account-group');
  const sel = document.getElementById('s-wechat-account');
  const accounts = (r && r.accounts || []).filter(isWechatAccountUsable);
  if (!group || !sel) return;
  if (accounts.length > 1) {
    group.hidden = false;
    sel.innerHTML = '<option value="">请选择账号</option>';
    accounts.forEach(a => {
      const opt = document.createElement('option');
      opt.value = a.path;
      opt.textContent = a.id;
      sel.appendChild(opt);
    });
  } else {
    group.hidden = true;
    sel.innerHTML = '<option value="">自动选择（仅一个账号时）</option>';
  }
}

function wechatSelectedAccount() {
  const group = document.getElementById('s-wechat-account-group');
  const sel = document.getElementById('s-wechat-account');
  if (group && group.hidden) return null;
  return sel && sel.value ? sel.value : null;
}

async function inspectWechat() {
  const btn = document.getElementById('btn-wechat-inspect');
  const status = document.getElementById('wechat-status');
  if (!btn || !status) return;
  btn.disabled = true; status.textContent = ''; status.className = '';
  try {
    const root = wechatRootInput();
    const r = await api('inspect_wechat_environment', root);
    if (!r) { status.textContent = '检测失败'; status.className = 'error'; return; }
    if (r.status === 'supported' || r.status === 'encrypted_index') {
      const accounts = (r.accounts || []).filter(isWechatAccountUsable);
      status.textContent = '已检测到 ' + r.account_directory_count + ' 个账号，其中 ' + accounts.length + ' 个可用';
      status.className = '';
    } else {
      status.textContent = r.reason || r.status || '未检测到';
      status.className = 'error';
    }
    wechatRenderAccounts(r);
  } catch (e) {
    status.textContent = '检测失败: ' + (e.message || e);
    status.className = 'error';
  } finally {
    btn.disabled = false;
  }
}

async function startWechatImport() {
  const btn = document.getElementById('btn-wechat-start');
  const status = document.getElementById('wechat-status');
  if (!btn || !status) return;
  btn.disabled = true; status.textContent = ''; status.className = '';
  const root = wechatRootInput();
  const account = wechatSelectedAccount();
  const accountGroup = document.getElementById('s-wechat-account-group');
  if (accountGroup && !accountGroup.hidden && !account) {
    btn.disabled = false;
    status.textContent = '检测到多个账号，请选择账号';
    status.className = 'error';
    return;
  }
  let r;
  try {
    r = await api('start_wechat_import', root, true, account);
  } catch (e) {
    btn.disabled = false;
    status.textContent = '启动失败: ' + (e.message || e);
    status.className = 'error';
    return;
  }
  if (!r || !r.ok) {
    btn.disabled = false;
    status.textContent = '启动失败: ' + (r && r.error ? r.error : '未知错误');
    status.className = 'error';
    return;
  }
  showWechatOverlay();
  let nullCount = 0;
  let pollInFlight = false;
  wechatPollTimer = setInterval(async () => {
    if (pollInFlight) return;
    pollInFlight = true;
    try {
      const s = await api('get_wechat_import_progress');
      if (!s) {
        nullCount++;
        if (nullCount > 20) {
          if (wechatPollTimer) { clearInterval(wechatPollTimer); wechatPollTimer = null; }
          document.getElementById('wechat-import-title').textContent = '导入失败';
          document.getElementById('wechat-import-error').style.display = '';
          document.getElementById('wechat-import-error').textContent = '连接中断';
          status.textContent = '导入失败: 连接中断';
          status.className = 'error';
          wechatSetCloseLabel('关闭');
          btn.disabled = false;
        }
        return;
      }
      nullCount = 0;
      document.getElementById('wechat-import-bar').style.width = (s.progress || 0) + '%';
      document.getElementById('wechat-import-pct').textContent = (s.progress || 0) + '%';
      document.getElementById('wechat-import-msg').textContent = s.message || '';
      if (s.status === 'done') {
        document.getElementById('wechat-import-title').textContent = '导入完成';
        if (wechatPollTimer) { clearInterval(wechatPollTimer); wechatPollTimer = null; }
        const el = document.getElementById('wechat-status');
        el.textContent = s.message || '导入完成';
        el.className = '';
        wechatSetCloseLabel('关闭');
        btn.disabled = false;
      } else if (s.status === 'error') {
        document.getElementById('wechat-import-title').textContent = '导入失败';
        if (wechatPollTimer) { clearInterval(wechatPollTimer); wechatPollTimer = null; }
        const el = document.getElementById('wechat-status');
        const errCode = s.error_code ? ' [' + s.error_code + ']' : '';
        let errMsg = s.error || '未知错误';
        if (s.error_code === 'no_binary') {
          errMsg += '；请检查网络后重试（需从 GitHub 下载辅助工具）';
        } else if (s.error_code === 'no_key') {
          errMsg += '；请确认微信已登录且为支持的版本';
        }
        el.textContent = '导入失败: ' + errMsg + errCode;
        el.className = 'error';
        document.getElementById('wechat-import-error').style.display = '';
        document.getElementById('wechat-import-error').textContent = errMsg + errCode;
        wechatSetCloseLabel('关闭');
        btn.disabled = false;
      } else if (s.status === 'cancelled') {
        document.getElementById('wechat-import-title').textContent = '已取消';
        if (wechatPollTimer) { clearInterval(wechatPollTimer); wechatPollTimer = null; }
        wechatSetCloseLabel('关闭');
        btn.disabled = false;
      }
    } catch (e) {
      if (wechatPollTimer) { clearInterval(wechatPollTimer); wechatPollTimer = null; }
      document.getElementById('wechat-import-title').textContent = '导入失败';
      document.getElementById('wechat-import-error').style.display = '';
      document.getElementById('wechat-import-error').textContent = e.message || '连接异常';
      wechatSetCloseLabel('关闭');
      btn.disabled = false;
    } finally {
      pollInFlight = false;
    }
  }, 300);
}

