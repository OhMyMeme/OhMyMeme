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

/* Close settings window */
function closeSettings() {
  try { pywebview.api.close_settings(); } catch(e) {}
}

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

async function checkConnectivity() {  // DeepSeek V4 Flash
  const el = document.getElementById('s-net-status');
  if (!el) return;
  el.textContent = '正在检查网络...';
  el.style.color = 'var(--muted)';
  try {
    const r = await api('check_connectivity');
    if (r && r.ok) {
      el.innerHTML = '● 已连接 <span style="opacity:.6">(' + esc(r.latency || '') + ')</span>';
      el.style.color = '#4caf50';
    } else {
      el.textContent = '● 无网络连接';
      el.style.color = '#f44336';
    }
  } catch(_) {
    el.textContent = '● 检查失败';
    el.style.color = '#f44336';
  }
}

/* 局域网互联 */
let lanPollTimer = null;

async function toggleLanSecretConfig() {
  const cb = document.getElementById('s-lan-secret-config');
  if (cb.checked) {
    const ok = confirm('请勿在公共网络或不信任的网络进行此操作！\n\n开启后配置同步将包含 FTP/S3/R2/WebDAV 等密钥字段，密钥将明文传输给局域网内配对设备。\n仅本次会话有效，不写入配置。是否继续？');
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
    el.style.color = 'var(--muted)';
    if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null; }
    return;
  }
  if (r.status === 'error') {
    el.innerHTML = '● 启动失败 <span style="color:#ef4444">' + esc(r.last_error || '') + '</span>';
    el.style.color = 'var(--muted)';
    if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null; }
    return;
  }
  let html = '● 运行中 <span style="opacity:.6">(端口 ' + r.port + '，IP ' + esc(ip) + ')</span>';
  if (r.clients && r.clients.length) {
    html += '<br>已连接设备：' + r.clients.map(c => '<code>' + esc(c.addr) + '</code>').join('、');
  }
  el.innerHTML = html;
  el.style.color = '#4caf50';
  if (lanPollTimer) { clearInterval(lanPollTimer); }
  lanPollTimer = setInterval(async () => {
    const r2 = await api('lan_get_status');
    if (!r2 || r2.status !== 'running') {
      if (lanPollTimer) { clearInterval(lanPollTimer); lanPollTimer = null; }
      refreshLanStatus();
    }
  }, 5000);
}

/* Load settings */
async function getSettings() {
  const s = await api('get_settings');
  if (!s) return false;
  const hk = document.getElementById('s-hotkey');
  const gif = document.getElementById('s-gif');
  const as = document.getElementById('s-auto-start');
  const ss = document.getElementById('s-silent-start');
  if (hk && s.hotkey) hk.value = s.hotkey;
  const hsam = document.getElementById('s-hotkey-show-at-mouse');
  if (hsam) hsam.checked = s.hotkey_show_at_mouse === true;
  if (gif) gif.checked = s.auto_play_gif !== false;
  const hp = document.getElementById('s-hover-play');
  if (hp) hp.checked = s.hover_to_play === true;
  const to = document.getElementById('s-try-original');
  if (to) to.checked = s.try_original_image === true;  // DeepSeek V4 Flash
  const cm = document.getElementById('s-copy-mode');
  if (cm) cm.value = String(s.copy_resize_mode ?? 1);
  if (as) as.checked = s.auto_start === true;
  if (ss) ss.checked = s.silent_start === true;
  const unc = document.getElementById('s-show-uncategorized');
  if (unc) unc.checked = s.show_uncategorized !== false;
  const rec = document.getElementById('s-record-recent');
  if (rec) rec.checked = s.record_recent_use !== false;
  const ssa = document.getElementById('s-show-startup-anim');
  if (ssa) ssa.checked = s.show_startup_animation !== false;
  toggleSilentStart();
  const ff = document.getElementById('s-sync-fetch');
  const sa = document.getElementById('s-sync-auto');
  const st = document.getElementById('s-sync-type');
  if (ff) ff.checked = s.sync_auto_fetch_index === true;
  if (sa) sa.checked = s.sync_auto_sync === true;
  if (st) { st.value = s.sync_type || ''; toggleSyncType(); }
  document.getElementById('s-ftp-host').value = s.ftp_host || '';
  document.getElementById('s-ftp-port').value = s.ftp_port || 21;
  document.getElementById('s-ftp-user').value = s.ftp_user || '';
  document.getElementById('s-ftp-pass').value = s.ftp_password || '';
  document.getElementById('s-ftp-path').value = s.ftp_path || '/';
  document.getElementById('s3-endpoint').value = s.s3_endpoint || '';
  const s3Addr = document.getElementById('s3-addressing-style');
  if (s3Addr) s3Addr.value = s.s3_addressing_style || 'virtual';
  const s3Sig = document.getElementById('s3-signature-version');
  if (s3Sig) s3Sig.value = s.s3_signature_version || 's3';
  document.getElementById('s3-region').value = s.s3_region || '';
  document.getElementById('s3-bucket').value = s.s3_bucket || '';
  document.getElementById('s3-access-key').value = s.s3_access_key || '';
  document.getElementById('s3-secret-key').value = s.s3_secret_key || '';
  document.getElementById('s3-path').value = s.s3_path || '';
  document.getElementById('r2-account-id').value = s.r2_account_id || '';
  document.getElementById('r2-access-key-id').value = s.r2_access_key_id || '';
  document.getElementById('r2-secret-access-key').value = s.r2_secret_access_key || '';
  document.getElementById('r2-bucket').value = s.r2_bucket || '';
  document.getElementById('r2-path').value = s.r2_path || '';
  document.getElementById('wd-url').value = s.webdav_url || '';
  document.getElementById('wd-user').value = s.webdav_user || '';
  document.getElementById('wd-pass').value = s.webdav_password || '';
  document.getElementById('wd-path').value = s.webdav_path || '';
  const kr = document.getElementById('s-delete-remote');
  const rl = document.getElementById('s-remove-local');
  const hw = document.getElementById('s-hide-upload-warn');
  if (kr) kr.checked = s.sync_delete_remote === true;
  if (rl) rl.checked = s.sync_remove_local === true;
  if (hw) hw.checked = s.sync_hide_upload_warning === true;
  const up = document.getElementById('s-show-up-progress');
  const ud = document.getElementById('s-show-up-done');
  const dp = document.getElementById('s-show-dl-progress');
  const dd = document.getElementById('s-show-dl-done');
  if (up) up.checked = s.show_upload_progress !== false;
  if (ud) ud.checked = s.show_upload_done !== false;
  if (dp) dp.checked = s.show_download_progress !== false;
  if (dd) dd.checked = s.show_download_done !== false;
  const lport = document.getElementById('s-lan-port');
  if (lport) lport.value = s.lan_port || 17852;
  const lsec = document.getElementById('s-lan-secret');
  if (lsec) lsec.value = s.lan_secret || '';
  const tgtd = document.getElementById('s-tg-tdata');
  if (tgtd && s.tg_tdata_path) tgtd.value = s.tg_tdata_path;
  checkConnectivity();  // DeepSeek V4 Flash
  loadStorageInfo();
  refreshLanStatus();
  return true;
}

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

function toggleSyncType() {
  const t = document.getElementById('s-sync-type')?.value;
  const f = document.getElementById('s-sync-ftp');
  const s3 = document.getElementById('s-sync-s3');
  const r2 = document.getElementById('s-sync-r2');
  const wd = document.getElementById('s-sync-webdav');
  const o = document.getElementById('s-sync-options');
  const b = document.getElementById('s-sync-buttons');
  if (f) f.style.display = t === 'ftp' ? 'block' : 'none';
  if (s3) s3.style.display = t === 's3' ? 'block' : 'none';
  if (r2) r2.style.display = t === 'r2' ? 'block' : 'none';
  if (wd) wd.style.display = t === 'webdav' ? 'block' : 'none';
  if (o) o.style.display = t ? 'block' : 'none';
  if (b) b.style.display = t ? 'block' : 'none';
}

function collectSyncSettings() {
  return {
    sync_auto_fetch_index: document.getElementById('s-sync-fetch')?.checked === true,
    sync_auto_sync: document.getElementById('s-sync-auto')?.checked === true,
    sync_type: document.getElementById('s-sync-type')?.value || '',
    sync_delete_remote: document.getElementById('s-delete-remote')?.checked === true,
    sync_remove_local: document.getElementById('s-remove-local')?.checked === true,
    sync_hide_upload_warning: document.getElementById('s-hide-upload-warn')?.checked === true,
    ftp_host: document.getElementById('s-ftp-host')?.value || '',
    ftp_port: parseInt(document.getElementById('s-ftp-port')?.value) || 21,
    ftp_user: document.getElementById('s-ftp-user')?.value || '',
    ftp_password: document.getElementById('s-ftp-pass')?.value || '',
    ftp_path: document.getElementById('s-ftp-path')?.value || '/',
    s3_endpoint: document.getElementById('s3-endpoint')?.value || '',
    s3_region: document.getElementById('s3-region')?.value || '',
    s3_bucket: document.getElementById('s3-bucket')?.value || '',
    s3_access_key: document.getElementById('s3-access-key')?.value || '',
    s3_secret_key: document.getElementById('s3-secret-key')?.value || '',
    s3_path: document.getElementById('s3-path')?.value || '',
    s3_addressing_style: document.getElementById('s3-addressing-style')?.value || 'virtual',
    s3_signature_version: document.getElementById('s3-signature-version')?.value || 's3',
    r2_account_id: document.getElementById('r2-account-id')?.value || '',
    r2_access_key_id: document.getElementById('r2-access-key-id')?.value || '',
    r2_secret_access_key: document.getElementById('r2-secret-access-key')?.value || '',
    r2_bucket: document.getElementById('r2-bucket')?.value || '',
    r2_path: document.getElementById('r2-path')?.value || '',
    webdav_url: document.getElementById('wd-url')?.value || '',
    webdav_user: document.getElementById('wd-user')?.value || '',
    webdav_password: document.getElementById('wd-pass')?.value || '',
    webdav_path: document.getElementById('wd-path')?.value || '',
  };
}

function validateSync(sync) {
  if (sync.sync_type === 'ftp') {
    if (!sync.ftp_host.trim()) {
      showToast('请输入 FTP 服务器地址');
      return false;
    }
    const port = parseInt(sync.ftp_port);
    if (!port || port < 1 || port > 65535) {
      showToast('端口号无效（1-65535）');
      return false;
    }
  }
  if (sync.sync_type === 's3') {
    if (!sync.s3_endpoint.trim()) {
      showToast('请输入 Endpoint URL');
      return false;
    }
    if (!sync.s3_bucket.trim()) {
      showToast('请输入 Bucket 名称');
      return false;
    }
  }
  if (sync.sync_type === 'r2') {
    if (!sync.r2_account_id.trim()) {
      showToast('请输入 Cloudflare Account ID');
      return false;
    }
    if (!sync.r2_bucket.trim()) {
      showToast('请输入 Bucket 名称');
      return false;
    }
  }
  if (sync.sync_type === 'webdav') {
    if (!sync.webdav_url.trim()) {
      showToast('请输入 WebDAV URL');
      return false;
    }
  }
  return true;
}

async function saveSettings() {
  const hotkey = document.getElementById('s-hotkey')?.value || 'Ctrl+Alt+N';
  const gif = document.getElementById('s-gif')?.checked !== false;
  const try_original = document.getElementById('s-try-original')?.checked === true;  // DeepSeek V4 Flash
  const copy_mode = parseInt(document.getElementById('s-copy-mode')?.value || '1', 10);
  const hotkey_show_at_mouse = document.getElementById('s-hotkey-show-at-mouse')?.checked === true;
  const auto_start = document.getElementById('s-auto-start')?.checked === true;
  const silent_start = document.getElementById('s-silent-start')?.checked === true;
  const show_uncategorized = document.getElementById('s-show-uncategorized')?.checked !== false;
  const record_recent_use = document.getElementById('s-record-recent')?.checked !== false;
  const show_startup_animation = document.getElementById('s-show-startup-anim')?.checked !== false;
  const sync = collectSyncSettings();
  if (!validateSync(sync)) return;
  const lan_port = parseInt(document.getElementById('s-lan-port')?.value) || 17852;
  const lan_secret = document.getElementById('s-lan-secret')?.value || '';
  const hover_play = document.getElementById('s-hover-play')?.checked === true;
  await api('save_settings', {
    hotkey, hotkey_show_at_mouse, auto_play_gif: gif, hover_to_play: hover_play,
    try_original_image: try_original,  // DeepSeek V4 Flash
    copy_resize_mode: copy_mode,
    auto_start, silent_start, show_uncategorized, record_recent_use,
    show_startup_animation,
    lan_port, lan_secret,
    ...sync
  });
  showToast('设置已保存');
}

async function resetSettings() {
  const s = await api('reset_settings');
  if (s) {
    const hk = document.getElementById('s-hotkey');
    const gif = document.getElementById('s-gif');
    const as = document.getElementById('s-auto-start');
    const ss = document.getElementById('s-silent-start');
    if (hk) hk.value = s.hotkey;
    const hsam = document.getElementById('s-hotkey-show-at-mouse');
    if (hsam) hsam.checked = s.hotkey_show_at_mouse === true;
    if (gif) gif.checked = s.auto_play_gif !== false;
    const hp = document.getElementById('s-hover-play');
    if (hp) hp.checked = s.hover_to_play === true;
    const tgtd = document.getElementById('s-tg-tdata');
    if (tgtd) tgtd.value = s.tg_tdata_path || '';
    const to = document.getElementById('s-try-original');  // DeepSeek V4 Flash
    if (to) to.checked = false;
    const cm = document.getElementById('s-copy-mode');
    if (cm) cm.value = String(s.copy_resize_mode ?? 1);
    if (as) as.checked = s.auto_start === true;
    if (ss) ss.checked = s.silent_start === true;
    toggleSilentStart();
    checkConnectivity();  // DeepSeek V4 Flash
    const ff = document.getElementById('s-sync-fetch');
    const sa = document.getElementById('s-sync-auto');
    const st = document.getElementById('s-sync-type');
    if (ff) ff.checked = false;
    if (sa) sa.checked = false;
    if (st) { st.value = ''; toggleSyncType(); }
    document.getElementById('s-ftp-host').value = '';
    document.getElementById('s-ftp-port').value = '21';
    document.getElementById('s-ftp-user').value = '';
    document.getElementById('s-ftp-pass').value = '';
    document.getElementById('s-ftp-path').value = '/';
    document.getElementById('s3-endpoint').value = '';
    document.getElementById('s3-region').value = '';
    document.getElementById('s3-bucket').value = '';
    document.getElementById('s3-access-key').value = '';
    document.getElementById('s3-secret-key').value = '';
    document.getElementById('s3-path').value = '';
    document.getElementById('r2-account-id').value = '';
    document.getElementById('r2-access-key-id').value = '';
    document.getElementById('r2-secret-access-key').value = '';
    document.getElementById('r2-bucket').value = '';
    document.getElementById('r2-path').value = '';
    document.getElementById('wd-url').value = '';
    document.getElementById('wd-user').value = '';
    document.getElementById('wd-pass').value = '';
    document.getElementById('wd-path').value = '';
    const kr = document.getElementById('s-delete-remote');
    const rl = document.getElementById('s-remove-local');
    const hw = document.getElementById('s-hide-upload-warn');
    if (kr) kr.checked = false;
    if (rl) rl.checked = false;
    if (hw) hw.checked = false;
    const up = document.getElementById('s-show-up-progress');
    const ud = document.getElementById('s-show-up-done');
    const dp = document.getElementById('s-show-dl-progress');
    const dd = document.getElementById('s-show-dl-done');
    if (up) up.checked = true;
    if (ud) ud.checked = true;
    if (dp) dp.checked = true;
    if (dd) dd.checked = true;
    const rec = document.getElementById('s-record-recent');
    if (rec) rec.checked = true;
    const ssa = document.getElementById('s-show-startup-anim');
    if (ssa) ssa.checked = true;
    const lport = document.getElementById('s-lan-port');
    if (lport) lport.value = '17852';
    const lsec = document.getElementById('s-lan-secret');
    if (lsec) lsec.value = '';
    const le = document.getElementById('s-lan-enable');
    if (le) le.checked = false;
    const lcc = document.getElementById('s-lan-secret-config');
    if (lcc) lcc.checked = false;
    await api('lan_stop');
    await api('lan_set_allow_secret_config', false);
    refreshLanStatus();
    showToast('已恢复默认设置');
  }
}

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
    box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:380px;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
    box.innerHTML = '<div style="margin-bottom:14px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">上传确认</h2>'
      + '<p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">上传会将本地的完整状态同步到远端，包括新增、更新和删除操作。远程文件将被覆盖，建议先下载备份。</p></div>'
      + '<label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12.5px;color:var(--muted);margin-bottom:16px;user-select:none">'
      + '<input id="supload-warn-hide" type="checkbox" style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer">不再提醒</label>'
      + '<div style="display:flex;gap:8px;justify-content:flex-end">'
      + '<button id="supload-modal-cancel" class="btn btn-secondary">取消</button>'
      + '<button id="supload-modal-confirm" class="btn btn-primary">继续上传</button></div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    document.getElementById('supload-modal-confirm').focus();
    const cleanup = () => { overlay.remove(); };
    document.getElementById('supload-modal-confirm').onclick = async () => {
      const hide = document.getElementById('supload-warn-hide').checked;
      if (hide) await api('save_settings', { sync_hide_upload_warning: true });
      cleanup(); resolve(true);
    };
    document.getElementById('supload-modal-cancel').onclick = () => { cleanup(); resolve(false); };
    overlay.onkeydown = (e) => { if (e.key === 'Escape') { e.stopPropagation(); cleanup(); resolve(false); } };
  });
}

let syncPollTimer = null;
let syncBg = false;

function hideSyncProgress() {
  syncBg = true;
  document.getElementById('sync-progress-overlay').style.display = 'none';
  if (syncPollTimer) { clearInterval(syncPollTimer); syncPollTimer = null; }
}

function hideSyncDone() {
  document.getElementById('sync-done-overlay').style.display = 'none';
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
  }

  if (r && r.ok) {
    const uploaded = r.uploaded || r.downloaded || 0;
    const skipped = r.skipped || 0;
    const errors = r.errors || 0;
    status.textContent = '完成: 成功 ' + uploaded + ', 跳过 ' + skipped + ', 错误 ' + errors;

    if (showDone) {
      document.getElementById('sync-done-title').textContent = title + '完成';
      document.getElementById('sync-done-detail').textContent = '成功 ' + uploaded + ' 个';
      document.getElementById('sync-done-overlay').style.display = 'flex';
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

/* QQ Import */
let qqPollTimer = null;

function showQQOverlay() {
  document.getElementById('qq-import-overlay').style.display = 'flex';
  document.getElementById('btn-qq-save').style.display = 'none';
  document.getElementById('qq-import-error').style.display = 'none';
  document.getElementById('qq-import-title').textContent = '正在导入...';
}

function closeQQOverlay() {
  document.getElementById('qq-import-overlay').style.display = 'none';
  if (qqPollTimer) { clearInterval(qqPollTimer); qqPollTimer = null; }
  api('cancel_qq_import');
}

async function startQQImport() {
  const btn = document.getElementById('btn-qq-import');
  const status = document.getElementById('qq-status');
  btn.disabled = true; status.textContent = ''; status.className = '';

  const r = await api('start_qq_import');
  if (!r || !r.ok) {
    btn.disabled = false;
    status.textContent = '启动失败';
    status.className = 'error';
    return;
  }

  showQQOverlay();

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
      document.getElementById('qq-import-msg').textContent = '共导出 ' + pct + ' 个文件';
      document.getElementById('btn-qq-save').style.display = '';
      if (qqPollTimer) { clearInterval(qqPollTimer); qqPollTimer = null; }
    } else if (s.status === 'error') {
      document.getElementById('btn-qq-help').style.display = 'none';
      if (qqPollTimer) { clearInterval(qqPollTimer); qqPollTimer = null; }
      document.getElementById('qq-import-title').textContent = '导入失败';
      document.getElementById('qq-import-error').style.display = '';
      document.getElementById('qq-import-error').textContent = s.error || '未知错误';
      const el = document.getElementById('qq-status');
      el.textContent = '导入失败: ' + (s.error || '');
      el.className = 'error';
    }
  }, 300);

  btn.disabled = false;
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
    const el = document.getElementById('qq-status');
    el.textContent = '已保存到: ' + (r.path || '');
    el.className = '';
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
let dyPollTimer = null;

function showDYOverlay() {
  document.getElementById('dy-import-overlay').style.display = 'flex';
  document.getElementById('dy-import-error').style.display = 'none';
  document.getElementById('dy-import-title').textContent = '正在下载...';
  document.getElementById('dy-import-msg').textContent = '准备中';
  document.getElementById('dy-import-bar').style.width = '0%';
  document.getElementById('dy-import-pct').textContent = '0%';
}

function closeDYOverlay() {
  document.getElementById('dy-import-overlay').style.display = 'none';
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
        const el = document.getElementById('dy-status');
        el.textContent = '导入失败: ' + (s.error || '');
        el.className = 'error';
        document.getElementById('dy-import-error').style.display = '';
        document.getElementById('dy-import-error').textContent = s.error || '未知错误';
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

/* Telegram 缓存导入 */
let tgPollTimer = null;

function showTGOverlay() {
  document.getElementById('tg-import-overlay').style.display = 'flex';
  document.getElementById('tg-import-error').style.display = 'none';
  document.getElementById('btn-tg-retry').style.display = 'none';
  document.getElementById('tg-import-title').textContent = '正在导入...';
  document.getElementById('tg-import-msg').textContent = '准备中';
  document.getElementById('tg-import-bar').style.width = '0%';
  document.getElementById('tg-import-pct').textContent = '0%';
}

function closeTGOverlay() {
  document.getElementById('tg-import-overlay').style.display = 'none';
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
        el.textContent = '导入失败: ' + (s.error || '');
        el.className = 'error';
        document.getElementById('tg-import-error').style.display = '';
        document.getElementById('tg-import-error').textContent = s.error || '未知错误';
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

function showWechatOverlay() {
  document.getElementById('wechat-import-overlay').style.display = 'flex';
  document.getElementById('wechat-import-error').style.display = 'none';
  document.getElementById('wechat-import-title').textContent = '正在导入...';
  document.getElementById('wechat-import-msg').textContent = '准备中';
  document.getElementById('wechat-import-bar').style.width = '0%';
  document.getElementById('wechat-import-pct').textContent = '0%';
  wechatSetCloseLabel('取消导入');
}

function closeWechatOverlay() {
  document.getElementById('wechat-import-overlay').style.display = 'none';
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
        el.textContent = '导入失败: ' + (s.error || '未知错误') + errCode;
        el.className = 'error';
        document.getElementById('wechat-import-error').style.display = '';
        document.getElementById('wechat-import-error').textContent = (s.error || '未知错误') + errCode;
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

/* QQNT 提取向导 */
let qqntPollTimer = null;
let qqnt = { step: 1, env: null, accounts: [], qq: '', base: '', output_dir: '' };

function qqntGo(step) {
  qqnt.step = step;
  for (let i = 1; i <= 4; i++) {
    document.getElementById('qqnt-step-' + i).style.display = (i === step) ? '' : 'none';
  }
  document.getElementById('qqnt-prev').style.display = (step === 2) ? '' : 'none';
  const nextBtn = document.getElementById('qqnt-next');
  if (step === 1) { nextBtn.style.display = ''; nextBtn.textContent = '下一步'; }
  else if (step === 2) { nextBtn.style.display = ''; nextBtn.textContent = '开始提取'; }
  else nextBtn.style.display = 'none';
}

function qqntShow() {
  document.getElementById('qqnt-overlay').style.display = 'flex';
  document.getElementById('qqnt-error').style.display = 'none';
}

function qqntClose() {
  document.getElementById('qqnt-overlay').style.display = 'none';
  if (qqntPollTimer) { clearInterval(qqntPollTimer); qqntPollTimer = null; }
  api('qqnt_cancel');
}

function qqntPrev() {
  if (qqnt.step === 2) qqntGo(1);
}

async function qqntNext() {
  if (qqnt.step === 1) {
    if (!qqnt.qq) { showToast('请先选择一个账号'); return; }
    qqnt.base = ''; qqnt.output_dir = '';
    document.getElementById('qqnt-out-base').value = '';
    document.getElementById('qqnt-out-dir').value = '';
    qqntGo(2);
  } else if (qqnt.step === 2) {
    if (!qqnt.output_dir) { showToast('请先选择保存文件夹'); return; }
    qqntStartExtract();
  }
}

async function startQQNTWizard() {
  const btn = document.getElementById('btn-qqnt-start');
  btn.disabled = true;
  qqntShow();
  qqntGo(1);
  const st = await api('qqnt_check_env');
  btn.disabled = false;
  qqntRenderEnv(st);
}

function qqntRenderEnv(st) {
  qqnt.env = st;
  qqnt.accounts = (st && st.accounts) ? st.accounts : [];
  qqnt.qq = '';
  const msg = document.getElementById('qqnt-env-msg');
  const accBox = document.getElementById('qqnt-accounts');
  const actions = document.getElementById('qqnt-env-actions');
  const actionsMsg = document.getElementById('qqnt-env-actions-msg');
  accBox.innerHTML = '';
  actions.style.display = 'block';
  document.getElementById('qqnt-next').disabled = true;

  if (!st || !st.ok) {
    msg.textContent = '未能定位 QQ 用户数据';
    const err = st && st.error;
    if (err === 'config') actionsMsg.textContent = '未找到配置文件或无法读取，请手动选择：';
    else if (err === 'path_missing') actionsMsg.textContent = '用户数据目录不存在（可能已迁移或更换路径），请手动选择：';
    else actionsMsg.textContent = '无法检测 QQ 环境，请手动选择：';
    return;
  }
  if (qqnt.accounts.length === 0) {
    msg.textContent = '未找到已加载表情的账号';
    actionsMsg.textContent = '若你知道用户数据目录（含 QQ 号子目录的 UserDataSavePath 根目录），可手动选择：';
    accBox.innerHTML = '<div style="font-size:12px;color:var(--muted);line-height:1.6">请先在电脑版 QQ 中打开「收藏表情」，将表情全部加载（滑到底），再返回此处重试。</div>';
    return;
  }
  msg.textContent = '请选择要提取的账号：';
  actionsMsg.textContent = '若当前 Windows 用户不在列表中，请手动选择其用户数据目录（含 QQ 号子目录的根目录）：';
  document.getElementById('qqnt-next').disabled = false;
  qqnt.accounts.forEach((a, idx) => {
    const label = document.createElement('label');
    label.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:6px;cursor:pointer;background:var(--card)';
    const name = a.nickname ? a.nickname + '（' + a.qq + '）' : a.qq;
    label.innerHTML = '<input type="radio" name="qqnt-account" style="width:15px;height:15px;accent-color:var(--accent)">'
      + '<span style="font-size:13px;color:var(--fg)">' + esc(name) + '</span>'
      + '<span style="margin-left:auto;font-size:11px;color:var(--muted)">' + a.count + ' 个</span>';
    const radio = label.querySelector('input');
    radio.checked = (idx === 0);
    radio.onchange = () => { qqnt.qq = a.qq; };
    accBox.appendChild(label);
  });
  qqnt.qq = qqnt.accounts[0].qq;
}

async function qqntPickIni() {
  const r = await api('qqnt_pick_ini');
  if (r && !r.cancelled) qqntRenderEnv(r);
}

async function qqntPickUserdata() {
  const r = await api('qqnt_pick_userdata');
  if (r && !r.cancelled) qqntRenderEnv(r);
}

async function qqntPickBase() {
  const r = await api('qqnt_pick_base');
  if (!r || !r.ok) { showToast('选择失败'); return; }
  qqnt.base = r.base;
  document.getElementById('qqnt-out-base').value = r.base;
  await qqntRecomputeDir();
}

async function qqntRecomputeDir() {
  if (!qqnt.base || !qqnt.qq) return;
  const r = await api('qqnt_default_dir', qqnt.base, qqnt.qq);
  if (r && r.ok) {
    qqnt.output_dir = r.dir;
    document.getElementById('qqnt-out-dir').value = r.dir;
  }
}

async function qqntStartExtract() {
  const imageOnly = document.getElementById('qqnt-image-only').checked;
  const overwrite = document.getElementById('qqnt-overwrite').checked;
  document.getElementById('qqnt-progress-bar').style.width = '0%';
  document.getElementById('qqnt-progress-pct').textContent = '0%';
  document.getElementById('qqnt-progress-title').textContent = '正在提取...';
  document.getElementById('qqnt-progress-msg').textContent = '准备中';
  document.getElementById('qqnt-progress-log').textContent = '';
  document.getElementById('qqnt-error').style.display = 'none';
  qqntGo(3);
  const r = await api('qqnt_start', qqnt.qq, qqnt.output_dir, imageOnly, overwrite);
  if (!r || !r.ok) {
    document.getElementById('qqnt-error').style.display = '';
    document.getElementById('qqnt-error').textContent = '启动失败';
    return;
  }
  qqntPollTimer = setInterval(async () => {
    const s = await api('qqnt_get_progress');
    if (!s) return;
    document.getElementById('qqnt-progress-bar').style.width = (s.progress || 0) + '%';
    document.getElementById('qqnt-progress-pct').textContent = (s.progress || 0) + '%';
    document.getElementById('qqnt-progress-msg').textContent = s.message || '';
    if (s.log) {
      const logEl = document.getElementById('qqnt-progress-log');
      logEl.textContent = s.log.join('\n');
      logEl.scrollTop = logEl.scrollHeight;
    }
    if (s.status === 'done') {
      if (qqntPollTimer) { clearInterval(qqntPollTimer); qqntPollTimer = null; }
      qqntRenderDone(s.result);
    } else if (s.status === 'cancelled') {
      if (qqntPollTimer) { clearInterval(qqntPollTimer); qqntPollTimer = null; }
      qqntRenderDone(s.result, true);
    } else if (s.status === 'error') {
      if (qqntPollTimer) { clearInterval(qqntPollTimer); qqntPollTimer = null; }
      document.getElementById('qqnt-progress-title').textContent = '提取失败';
      document.getElementById('qqnt-error').style.display = '';
      document.getElementById('qqnt-error').textContent = s.error || '未知错误';
    }
  }, 300);
}

function qqntRenderDone(res, cancelled) {
  qqntGo(4);
  document.getElementById('qqnt-done-title').textContent = cancelled ? '已取消' : '提取完成';
  const detail = document.getElementById('qqnt-done-detail');
  if (!res) { detail.textContent = '已取消或无结果'; return; }
  let txt = '成功复制 ' + res.copied + ' / ' + res.total + ' 个';
  if (res.failed > 0) txt += '，失败 ' + res.failed + ' 个';
  if (res.skipped > 0) txt += '，跳过 ' + res.skipped + ' 个';
  if (res.renamed > 0) txt += '，修正扩展名 ' + res.renamed + ' 个';
  if (res.unrecognized > 0) txt += '，未识别 ' + res.unrecognized + ' 个';
  detail.innerHTML = txt + '<br>' + esc(res.output_dir || '');
}

async function qqntOpenDir() {
  await api('qqnt_open_dir', qqnt.output_dir);
}

/* Toast */
let toastTimer;
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1600);
}

/* Window Drag */
let dragState = null;
const titlebar = document.getElementById('titlebar');
titlebar.addEventListener('mousedown', async (e) => {
  if (e.button !== 0) return;
  if (e.target.closest('.title-btn')) return;
  const nativeDrag = await api('start_window_drag', e.button + 1, e.screenX, e.screenY);
  if (nativeDrag) return;   // Linux：交给合成器拖动
  dragState = { sx: e.screenX, sy: e.screenY };
  e.preventDefault();
});
document.addEventListener('mousemove', (e) => {
  if (!dragState) return;
  const dx = e.screenX - dragState.sx, dy = e.screenY - dragState.sy;
  if (dx !== 0 || dy !== 0) {
    api('move_window', dx, dy);
    dragState.sx = e.screenX; dragState.sy = e.screenY;
  }
});
document.addEventListener('mouseup', () => { dragState = null; });

/* Keyboard shortcuts */
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const dangerOverlay = document.getElementById('danger-overlay');
    if (dangerOverlay && dangerOverlay.style.display === 'flex') {
      dangerCancel();
      return;
    }
    const dyOverlay = document.getElementById('dy-import-overlay');
    if (dyOverlay && dyOverlay.style.display === 'flex') {
      closeDYOverlay();
      return;
    }
    const tgOverlay = document.getElementById('tg-import-overlay');
    if (tgOverlay && tgOverlay.style.display === 'flex') {
      closeTGOverlay();
      return;
    }
    const wechatOverlay = document.getElementById('wechat-import-overlay');
    if (wechatOverlay && wechatOverlay.style.display === 'flex') {
      closeWechatOverlay();
      return;
    }
    const qqOverlay = document.getElementById('qq-import-overlay');
    if (qqOverlay && qqOverlay.style.display === 'flex') {
      closeQQOverlay();
      return;
    }
    const qqntOverlay = document.getElementById('qqnt-overlay');
    if (qqntOverlay && qqntOverlay.style.display === 'flex') {
      qqntOverlay.style.display = 'none';
      return;
    }
    const syncOverlay = document.getElementById('sync-progress-overlay');
    if (syncOverlay && syncOverlay.style.display === 'flex') {
      hideSyncProgress();
      return;
    }
    const syncDoneOverlay = document.getElementById('sync-done-overlay');
    if (syncDoneOverlay && syncDoneOverlay.style.display === 'flex') {
      syncDoneOverlay.style.display = 'none';
      return;
    }
    closeSettings();
  }
  if (e.key === 'Enter' && e.ctrlKey) saveSettings();
});

/* Update check */
async function checkUpdate() {
  const btn = document.getElementById('btn-check-update');
  const status = document.getElementById('s-update-status');
  btn.disabled = true; btn.textContent = '检查中...'; status.textContent = '';
  const r = await api('check_update');
  btn.disabled = false; btn.textContent = '检查更新';
  if (!r) { status.textContent = '检查失败'; return; }
  document.getElementById('s-ver-current').textContent = '当前版本: ' + (r.current || '--');
  if (r.error) { status.textContent = '检查失败: ' + r.error; return; }
  if (!r.latest) { status.textContent = '暂无版本信息'; return; }
  if (r.has_update) {
    showUpdateDialog(r.current, r.latest, r.download_url, r.notes);
  } else {
    status.textContent = '已是最新版本 (' + r.latest + ')';
  }
}

function showUpdateDialog(current, latest, url, notes) {
  const overlay = document.createElement('div');
  overlay.id = 'update-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:300;animation:fadeIn .15s';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  const box = document.createElement('div');
  box.className = 'upd-dialog';
  box.style.cssText = 'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:440px;max-height:80vh;overflow-y:auto;border:1px solid var(--border);box-shadow:var(--shadow-lg)';
  box.innerHTML = '<div style="margin-bottom:16px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">发现新版本</h2>'
    + '<p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">当前版本: ' + esc(current) + '<br>最新版本: ' + esc(latest) + '</p></div>'
    + (notes ? '<div style="margin-bottom:16px"><div style="font-size:13px;font-weight:600;color:var(--fg);margin-bottom:6px">更新内容</div><div class="upd-notes" style="font-size:12px;color:var(--fg-secondary);line-height:1.7;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;max-height:220px;overflow-y:auto;overflow-x:hidden">' + renderMarkdown(notes) + '</div></div>' : '')
    + '<div style="display:flex;flex-direction:column;gap:8px">'
    + '<button id="upd-update" class="btn btn-primary" style="width:100%">更新</button>'
    + '<div style="display:flex;gap:8px">'
    + '<button id="upd-later" class="btn btn-secondary btn-flex">稍后提示</button>'
    + '</div></div>';
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.getElementById('upd-update').focus();

   document.getElementById('upd-update').onclick = async () => {
    const btn = document.getElementById('upd-update');
    btn.disabled = true;
    btn.textContent = '准备下载...';
    const ok = await api('start_download', url);
    if (!ok) { btn.disabled = false; btn.textContent = '更新'; return; }

    // 替换按钮为进度条
    const container = btn.parentNode;
    container.innerHTML = '<div style="width:100%">'
      + '<div style="font-size:12px;color:var(--fg-secondary);margin-bottom:4px;text-align:center" id="upd-progress-text">下载中 0%</div>'
      + '<div style="width:100%;height:8px;background:var(--bg-secondary);border-radius:4px;overflow:hidden">'
      + '<div id="upd-progress-bar" style="width:0%;height:100%;background:var(--accent);border-radius:4px;transition:width .3s"></div></div></div>';

    const poll = setInterval(async () => {
      const s = await api('get_download_progress');
      if (!s) return;
      const pct = s.progress || 0;
      document.getElementById('upd-progress-bar').style.width = pct + '%';
      if (s.status === 'downloading') {
        document.getElementById('upd-progress-text').textContent = '下载中 ' + pct + '%';
      } else if (s.status === 'done') {
        clearInterval(poll);
        document.getElementById('upd-progress-text').textContent = '下载完成，启动安装...';
        const r = await api('run_downloaded_installer');
        overlay.remove();
        if (r) {
          showToast('安装程序已启动，安装完成后将自动更新');
        } else {
          showToast('启动安装程序失败');
        }
      } else if (s.status === 'error') {
        clearInterval(poll);
        document.getElementById('upd-progress-text').textContent = '下载失败: ' + (s.error || '未知错误');
        container.innerHTML += '<button id="upd-retry" class="btn btn-primary" style="width:100%;margin-top:8px">重试</button>';
        document.getElementById('upd-retry').onclick = () => { overlay.remove(); showUpdateDialog(current, latest, url); };
      }
    }, 500);
  };
  document.getElementById('upd-later').onclick = () => { overlay.remove(); };
  overlay.onkeydown = (e) => { if (e.key === 'Escape') overlay.remove(); };
}

async function checkUpdateBackground() {
  const r = await api('check_update');
  if (!r || !r.has_update) return;
  const ignored = localStorage.getItem('update_ignored_' + r.latest);
  if (ignored) return;
  showUpdateDialog(r.current, r.latest, r.download_url, r.notes);
}

/* Danger zone */
let dangerTarget = null;

function showDangerConfirm(target) {
  dangerTarget = target;
  const title = document.getElementById('danger-title');
  const desc = document.getElementById('danger-desc');
  if (target === 'local') {
    title.textContent = '删除本地所有表情包';
    desc.textContent = '将永久删除全部表情包文件、缩略图及元数据，此操作不可撤销。';
  } else {
    title.textContent = '删除云端所有表情包';
    desc.textContent = '将永久删除远端服务器上的全部表情包文件，本地文件不受影响。';
  }
  document.getElementById('danger-overlay').style.display = 'flex';
  document.getElementById('danger-input-1').value = '';
  document.getElementById('danger-input-2').value = '';
  checkDangerMatch();
  document.getElementById('danger-input-1').focus();
}

function dangerCancel() {
  document.getElementById('danger-overlay').style.display = 'none';
  dangerTarget = null;
}

document.getElementById('danger-input-1').addEventListener('input', checkDangerMatch);
document.getElementById('danger-input-2').addEventListener('input', checkDangerMatch);

function checkDangerMatch() {
  const i1 = document.getElementById('danger-input-1');
  const i2 = document.getElementById('danger-input-2');
  const match = i1.value === 'confirm' && i2.value === 'confirm';
  document.getElementById('danger-confirm-btn').disabled = !match;
  i1.classList.toggle('match', i1.value === 'confirm');
  i2.classList.toggle('match', i2.value === 'confirm');
}

async function dangerExec() {
  if (!dangerTarget) return;
  const btn = document.getElementById('danger-confirm-btn');
  btn.disabled = true;
  btn.textContent = '执行中...';
  const r = await api('delete_all_' + dangerTarget);
  btn.textContent = '确认执行';
  document.getElementById('danger-overlay').style.display = 'none';
  dangerTarget = null;
  if (r && r.ok) {
    showToast('操作已完成');
  } else {
    showToast('操作失败: ' + ((r && r.error) || '未知错误'));
  }
}



/* Init */
let initRetries = 0;
async function initSettings() {
  const s = await getSettings();
  if (s) {
    document.getElementById('s-hotkey')?.focus();
    // 若用户已手动切换分组，则不覆盖；否则默认基础设置
    const active = document.querySelector('#settings-nav .nav-item.active');
    if (!active) switchSettingsGroup('base');
    return;
  }
  // pywebview bridge not ready yet, retry
  initRetries++;
  if (initRetries < 20) {
    setTimeout(initSettings, 200);
  }
}

/* 左栏分组导航：显示对应分组的 section，隐藏其余 */
function switchSettingsGroup(group) {
  document.querySelectorAll('#settings-nav .nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.group === group);
  });
  document.querySelectorAll('#settings-content .section').forEach(sec => {
    sec.style.display = (sec.dataset.group === group) ? 'block' : 'none';
  });
  const content = document.getElementById('settings-content');
  if (content) content.scrollTop = 0;
}

async function initVersion() {
  const ver = await api('get_current_version');
  const el = document.getElementById('s-ver-current');
  if (el) el.textContent = '当前版本: ' + (ver || '--');
}
document.addEventListener('DOMContentLoaded', () => {
  initSettings();
  setTimeout(initVersion, 500);
});
