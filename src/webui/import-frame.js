/* 宿主 iframe 协议 SDK：不提供来源界面或任意 Bridge。 */
let importFrameInit = null;
let importFrameStart = null;
let importFrameRequest = 0;
const importFramePending = new Map();
const importFrameCompleted = new Set();

function api(method, ...args) {
  if (!importFrameInit || !importFrameInit.actions.some(action => action.name === method)) return Promise.reject(new Error('未注册的导入动作'));
  return new Promise((resolve, reject) => {
    const id = ++importFrameRequest;
    const timeout = setTimeout(() => { importFramePending.delete(id); reject(new Error('导入动作响应超时')); }, 120000);
    importFramePending.set(id, {resolve, reject, timeout, method});
    parent.postMessage({type: 'call', id, name: method, args}, '*');
  });
}

function registerImportFrame(start) {
  importFrameStart = start;
  parent.postMessage({type: 'ready'}, '*');
}

function closeImportFrame() { parent.postMessage({type: 'close'}, '*'); }
function showToast(message) { parent.postMessage({type: 'notice', message: String(message)}, '*'); }
function pluginUILabel(method) { return importFrameInit.actions.find(action => action.name === method)?.label || method; }
function pluginProgressValue(_method, state, field) { return state[field]; }
function rememberSettingsFocus() {}
function restoreSettingsFocus() {}
function esc(value) { return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])); }

window.addEventListener('message', async event => {
  if (event.source !== parent) return;
  const data = event.data;
  if (!data || typeof data !== 'object') return;
  if (data.type === 'init' && !importFrameInit) {
    importFrameInit = data;
    for (const [key, value] of Object.entries(data.theme || {})) {
      if (typeof value === 'string' && value.trim()) document.documentElement.style.setProperty(key, value);
    }
    const tdata = document.getElementById('s-tg-tdata');
    if (tdata && data.values?.tg_tdata_path) tdata.value = data.values.tg_tdata_path;
    try { await importFrameStart?.(); } catch (error) { showToast(error.message || '导入界面初始化失败'); }
    return;
  }
  const request = importFramePending.get(data.id);
  if (!request) return;
  importFramePending.delete(data.id);
  clearTimeout(request.timeout);
  if (data.type === 'error') request.reject(new Error(data.error || '导入动作失败'));
  else if (data.type === 'result') {
    request.resolve(data.result);
    if (/progress$/.test(request.method) && data.result?.status === 'done' && !importFrameCompleted.has(request.method)) {
      importFrameCompleted.add(request.method);
      parent.postMessage({type: 'imported'}, '*');
    }
  }
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); closeImportFrame(); return; }
  if (event.key !== 'Tab') return;
  const items = [...document.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')].filter(element => element.getClientRects().length);
  const first = items[0], last = items[items.length - 1];
  if (!first || !last) return;
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
