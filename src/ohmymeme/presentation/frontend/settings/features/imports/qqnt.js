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
  rememberSettingsFocus();
  document.getElementById('qqnt-overlay').style.display = 'flex';
  document.getElementById('qqnt-error').style.display = 'none';
}

function qqntClose() {
  document.getElementById('qqnt-overlay').style.display = 'none';
  restoreSettingsFocus();
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
  qqntShow();
  qqntGo(1);
  const st = await api('qqnt_check_env');
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

