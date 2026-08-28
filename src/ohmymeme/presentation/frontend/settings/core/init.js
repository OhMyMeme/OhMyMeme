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
  initDirtyTracking();
});
