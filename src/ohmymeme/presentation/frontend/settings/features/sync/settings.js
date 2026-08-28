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
  _settingsDirty = false;
}

async function resetSettings() {
  const s = await api('reset_settings');
  if (s) {
    const hsam = document.getElementById('s-hotkey-show-at-mouse');
    if (hsam) hsam.checked = s.hotkey_show_at_mouse === true;
    await getSettings();
    const le = document.getElementById('s-lan-enable');
    if (le) le.checked = false;
    const lcc = document.getElementById('s-lan-secret-config');
    if (lcc) lcc.checked = false;
    await api('lan_stop');
    await api('lan_set_allow_secret_config', false);
    refreshLanStatus();
    showToast('已恢复默认设置');
    _settingsDirty = false;
  }
}
