/* Update check */
async function checkUpdate() {
  const btn = document.getElementById('btn-check-update');
  const status = document.getElementById('s-update-status');
  btn.disabled = true; btn.textContent = '检查中...'; status.textContent = '';
  // 首次发起强制检查；后台未完成时用非 force 持续轮询直到拿到结果
  let r = await api('check_update', false, true);
  while (r && r.pending) {
    await new Promise(res => setTimeout(res, 1500));
    r = await api('check_update', false, false);
  }
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
  overlay.onclick = (e) => { if (e.target === overlay) { e.stopPropagation(); updCleanup(); } };
  const box = document.createElement('div');
  box.className = 'upd-dialog';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
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
  rememberSettingsFocus();
  document.body.appendChild(overlay);
  document.getElementById('upd-update').focus();
  const updCleanup = () => { overlay.remove(); restoreSettingsFocus(); };

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
        updCleanup();
        if (r) {
          showToast('安装程序已启动，安装完成后将自动更新');
        } else {
          showToast('启动安装程序失败');
        }
      } else if (s.status === 'error') {
        clearInterval(poll);
        document.getElementById('upd-progress-text').textContent = '下载失败: ' + (s.error || '未知错误');
        container.innerHTML += '<button id="upd-retry" class="btn btn-primary" style="width:100%;margin-top:8px">重试</button>';
        document.getElementById('upd-retry').onclick = () => { updCleanup(); showUpdateDialog(current, latest, url); };
      }
    }, 500);
  };
  document.getElementById('upd-later').onclick = () => { updCleanup(); };
  overlay.onkeydown = (e) => { if (e.key === 'Escape') { e.stopPropagation(); updCleanup(); } else trapSettingsFocus(box, e); };
}

async function checkUpdateBackground() {
  const r = await api('check_update');
  if (!r || !r.has_update) return;
  const ignored = localStorage.getItem('update_ignored_' + r.latest);
  if (ignored) return;
  showUpdateDialog(r.current, r.latest, r.download_url, r.notes);
}
