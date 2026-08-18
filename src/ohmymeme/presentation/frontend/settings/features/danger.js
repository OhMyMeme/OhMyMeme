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
  rememberSettingsFocus();
  document.getElementById('danger-overlay').style.display = 'flex';
  document.getElementById('danger-input-1').value = '';
  document.getElementById('danger-input-2').value = '';
  checkDangerMatch();
  document.getElementById('danger-input-1').focus();
}

function dangerCancel() {
  document.getElementById('danger-overlay').style.display = 'none';
  dangerTarget = null;
  restoreSettingsFocus();
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
  restoreSettingsFocus();
  if (r && r.ok) {
    showToast('操作已完成');
  } else {
    showToast('操作失败: ' + ((r && r.error) || '未知错误'));
  }
}
