// 网络/LAN 状态色：统一走 CSS token 类，不在 JS 里写死颜色
function setStatusColor(el, mode) {
  if (!el) return;
  el.style.color = '';
  el.classList.remove('status-ok', 'status-error');
  if (mode === 'ok') el.classList.add('status-ok');
  else if (mode === 'error') el.classList.add('status-error');
}

async function checkConnectivity() {
  const el = document.getElementById('s-net-status');
  if (!el) return;
  el.textContent = '正在检查网络...';
  setStatusColor(el, '');
  el.style.color = 'var(--muted)';
  try {
    const r = await api('check_connectivity');
    if (r && r.ok) {
      el.innerHTML = '● 已连接 <span style="opacity:.6">(' + esc(r.latency || '') + ')</span>';
      setStatusColor(el, 'ok');
    } else {
      el.textContent = '● 无网络连接';
      setStatusColor(el, 'error');
    }
  } catch(_) {
    el.textContent = '● 检查失败';
    setStatusColor(el, 'error');
  }
}

/* 局域网互联 */
let lanPollTimer = null;

function showConfirm(title, message) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:200;animation:fadeIn .15s';
    overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    const box = document.createElement('div');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:400px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:16px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">' + esc(title) + '</h2><p style="font-size:13px;color:var(--fg-secondary);line-height:1.7;white-space:pre-line">' + esc(message) + '</p></div>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end">'
      + '<button id="sconfirm-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="sconfirm-ok" class="btn btn-primary">确定</button></div>';
    overlay.appendChild(box);
    rememberSettingsFocus();
    document.body.appendChild(overlay);
    document.getElementById('sconfirm-ok').focus();
    const cleanup = () => { overlay.remove(); restoreSettingsFocus(); };
    document.getElementById('sconfirm-ok').onclick = () => { cleanup(); resolve(true); };
    document.getElementById('sconfirm-cancel').onclick = () => { cleanup(); resolve(false); };
    overlay.onkeydown = (e) => { if (e.key === 'Escape') { e.stopPropagation(); cleanup(); resolve(false); } else trapSettingsFocus(box, e); };
  });
}

async function toggleLanSecretConfig() {
  const cb = document.getElementById('s-lan-secret-config');
  if (cb.checked) {
    const ok = await showConfirm('允许密钥传输', '请勿在公共网络或不信任的网络进行此操作！\n\n开启后配置同步将包含 FTP/S3/R2/WebDAV 等密钥字段，密钥将明文传输给局域网内配对设备。\n仅本次会话有效，不写入配置。是否继续？');
    if (!ok) {
      cb.checked = false;
      return;
    }
  }
  const r = await api('lan_set_allow_secret_config', cb.checked === true);
  if (r && r.allow_secret_config !== undefined) cb.checked = r.allow_secret_config;
}

async function toggleLan() {
  const cb = document.getElementById('s-lan-enable');
  if (cb.checked) {
    const port = parseInt(document.getElementById('s-lan-port')?.value) || 17852;
    const secret = document.getElementById('s-lan-secret')?.value || '';
    const r = await api('lan_start', port, secret);
    if (!r || !r.ok) {
      cb.checked = false;
      const st = r && r.status ? r.status : {};
      showToast('启动局域网服务失败：' + (st.last_error || '未知错误'));
    }
  } else {
    await api('lan_stop');
  }
  refreshLanStatus();
}

async function refreshLanStatus() {
  const el = document.getElementById('lan-status');
  if (!el) return;
  const r = await api('lan_get_status');
  const ip = await api('lan_get_ip');
  const cc = document.getElementById('s-lan-secret-config');
  if (cc && r) cc.checked = r.allow_secret_config === true;
  if (!r || r.status === 'stopped') {
    el.innerHTML = '● 已停止 <span style="opacity:.6">(端口 ' + (r ? r.port : 17852) + ')</span>';
    setStatusColor(el, '');
    el.style.color = 'var(--muted)';
    if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null; }
    return;
  }
  if (r.status === 'error') {
    el.innerHTML = '● 启动失败 <span class="status-error">' + esc(r.last_error || '') + '</span>';
    setStatusColor(el, '');
    el.style.color = 'var(--muted)';
    if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null; }
    return;
  }
  let html = '● 运行中 <span style="opacity:.6">(端口 ' + r.port + '，IP ' + esc(ip) + ')</span>';
  if (r.clients && r.clients.length) {
    html += '<br>已连接设备：' + r.clients.map(c => '<code>' + esc(c.addr) + '</code>').join('、');
  }
  el.innerHTML = html;
  setStatusColor(el, 'ok');
  if (lanPollTimer) { clearInterval(lanPollTimer); }
  lanPollTimer = setInterval(async () => {
    const r2 = await api('lan_get_status');
    if (!r2 || r2.status !== 'running') {
      if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null; }
      refreshLanStatus();
    }
  }, 5000);
}
