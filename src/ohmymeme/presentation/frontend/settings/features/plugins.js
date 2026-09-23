/* Plugins */
async function initPluginsPanel() {
  const root = document.getElementById('plugin-list');
  if (!root) return;
  try {
    const [pluginsResp, uiResp] = await Promise.all([
      fetch('/api/plugins'),
      fetch('/api/plugins/ui'),
    ]);
    if (!pluginsResp.ok) throw new Error(String(pluginsResp.status));
    const data = await pluginsResp.json();
    const contributions = uiResp.ok
      ? ((await uiResp.json()).contributions || [])
      : [];
    renderPluginList(root, data.plugins || []);
    renderPluginDetails(root, contributions);
  } catch (error) {
    root.textContent = '插件列表加载失败';
  }
}

function renderPluginList(root, plugins) {
  if (!plugins.length) {
    root.textContent = '暂无插件';
    return;
  }
  const kinds = { source: '导入来源', sync: '同步', transport: '传输' };
  root.innerHTML = plugins.map((plugin) => {
    const kind = kinds[plugin.kind] || plugin.kind;
    const origin = plugin.origin === 'bundled' ? '官方' : '第三方';
    const meta = [kind, origin, plugin.version].filter(Boolean).join(' · ');
    const checked = plugin.enabled ? ' checked' : '';
    const versions = plugin.versions || [];
    const rollback = plugin.origin === 'bundled' || versions.length < 2 ? '' :
      '<select class="plugin-version" data-plugin-version="' + esc(plugin.id) + '">' +
      versions.map((v) => '<option value="' + esc(v) + '"' +
        (v === plugin.version ? ' selected' : '') + '>' + esc(v) + '</option>').join('') +
      '</select>' +
      '<button class="btn btn-secondary btn-sm" data-plugin-action="rollback" data-plugin-id="' +
      esc(plugin.id) + '">切换</button>';
    const uninstall = plugin.origin === 'bundled' ? '' :
      '<button class="btn btn-danger-outline btn-sm" data-plugin-action="uninstall" data-plugin-id="' +
      esc(plugin.id) + '">卸载</button>';
    return '<div class="plugin-row" data-plugin-row="' + esc(plugin.id) + '">' +
      '<span class="plugin-info">' +
      '<span class="plugin-name">' + esc(plugin.label) + '</span>' +
      '<span class="plugin-meta">' + esc(plugin.id) + ' · ' + esc(meta) + '</span>' +
      '</span>' +
      '<span class="plugin-actions">' + rollback + uninstall +
      '<button class="btn btn-secondary btn-sm" data-plugin-action="reload" data-plugin-id="' +
      esc(plugin.id) + '">重载</button>' +
      '<input type="checkbox" data-plugin-id="' + esc(plugin.id) + '"' + checked +
      ' aria-label="启用插件">' +
      '</span>' +
      '</div>';
  }).join('');
  root.querySelectorAll('input[data-plugin-id]').forEach((input) => {
    input.addEventListener('change', () => { _settingsDirty = true; });
  });
  root.querySelectorAll('[data-plugin-action]').forEach((button) => {
    button.addEventListener('click', () => {
      const pluginId = button.dataset.pluginId;
      if (button.dataset.pluginAction === 'rollback') rollbackPlugin(pluginId);
      else if (button.dataset.pluginAction === 'uninstall') uninstallPlugin(pluginId);
      else reloadPlugin(pluginId);
    });
  });
}

function collectDisabledPlugins() {
  return Array.from(document.querySelectorAll('#plugin-list input[data-plugin-id]'))
    .filter((input) => !input.checked)
    .map((input) => input.dataset.pluginId);
}

async function installPluginFile(input) {
  const file = input && input.files && input.files[0];
  if (!file) return;
  try {
    const buffer = await file.arrayBuffer();
    const resp = await fetch('/api/plugins/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: buffer,
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || '安装失败');
    showToast('插件已安装：' + data.plugin + ' ' + data.version);
    initPluginsPanel();
  } catch (error) {
    showToast('安装失败：' + (error.message || error));
  } finally {
    input.value = '';
  }
}

async function uninstallPlugin(pluginId) {
  if (!(await showConfirm('卸载插件', '确定卸载 ' + pluginId + '？该插件目录会被删除，配置保留。'))) return;
  try {
    const resp = await fetch('/api/plugins/uninstall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: pluginId }),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || '卸载失败');
    showToast('插件已卸载');
    initPluginsPanel();
  } catch (error) {
    showToast('卸载失败：' + (error.message || error));
  }
}

async function reloadPlugin(pluginId) {
  try {
    const resp = await fetch('/api/plugins/reload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: pluginId }),
    });
    if (!resp.ok) throw new Error(String(resp.status));
    showToast('插件已重载，下次使用时按磁盘版本启动');
  } catch (error) {
    showToast('重载失败：' + (error.message || error));
  }
}

async function rollbackPlugin(pluginId) {
  const select = document.querySelector(
    'select[data-plugin-version="' + pluginId + '"]'
  );
  const version = select && select.value;
  if (!version) return;
  try {
    const resp = await fetch('/api/plugins/rollback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: pluginId, version }),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || '切换失败');
    showToast('已切换到 ' + data.version + '，重启后生效');
    initPluginsPanel();
  } catch (error) {
    showToast('切换失败：' + (error.message || error));
  }
}

/* Import injections */
const IMPORT_SOURCE_ROWS = {
  'source.qqnt': '[onclick="startQQNTWizard()"]',
  'source.telegram': '[onclick="openTGImportDialog()"]',
  'source.douyin': '[onclick="openDYImportDialog()"]',
  'source.wechat': '[onclick="openWechatImportDialog()"]',
};

async function initImportSources() {
  const container = document.getElementById('import-injected');
  if (!container) return;
  let sources = [];
  let contributions = [];
  try {
    const [sourceResp, uiResp] = await Promise.all([
      fetch('/api/plugins'),
      fetch('/api/plugins/ui'),
    ]);
    if (sourceResp.ok) sources = (await sourceResp.json()).plugins || [];
    if (uiResp.ok) contributions = (await uiResp.json()).contributions || [];
  } catch (error) {
    return;
  }
  annotateImportSources(sources);
  renderInjectedImports(container, contributions, sources);
}

function annotateImportSources(sources) {
  const byId = {};
  sources.forEach((plugin) => { byId[plugin.id] = plugin; });
  Object.entries(IMPORT_SOURCE_ROWS).forEach(([id, selector]) => {
    const row = document.querySelector(selector);
    const source = byId[id];
    if (!row || !source) return;
    row.querySelectorAll('.import-status').forEach((node) => node.remove());
    row.classList.remove('import-row-disabled', 'import-row-missing');
    row.disabled = false;
    if (!source.available) {
      row.classList.add('import-row-missing');
      row.disabled = true;
      addImportStatus(row, '不可用：缺少插件包');
    } else if (!source.enabled) {
      row.classList.add('import-row-disabled');
      row.disabled = true;
      addImportStatus(row, '已禁用（重启生效）');
    }
  });
}

function addImportStatus(row, text) {
  const span = document.createElement('span');
  span.className = 'import-status';
  span.textContent = text;
  row.appendChild(span);
}

function renderInjectedImports(container, contributions, sources) {
  const enabled = {};
  sources.forEach((plugin) => { enabled[plugin.id] = plugin.enabled; });
  container.innerHTML = '';
  contributions
    .filter((item) => item.injection.point === 'imports.row')
    .forEach((item) => {
      const injection = item.injection;
      const wrapper = document.createElement('div');
      wrapper.className = 'import-row import-injected-row' +
        (item.enabled ? '' : ' import-row-disabled');
      const info = document.createElement('span');
      info.className = 'plugin-info';
      const name = document.createElement('span');
      name.className = 'import-name';
      name.textContent = injection.label;
      info.appendChild(name);
      if (injection.description) {
        const meta = document.createElement('span');
        meta.className = 'plugin-meta';
        meta.textContent = injection.description;
        info.appendChild(meta);
      }
      if (!item.enabled) {
        const status = document.createElement('span');
        status.className = 'import-status';
        status.textContent = '已禁用（重启生效）';
        info.appendChild(status);
      }
      wrapper.appendChild(info);
      const fields = document.createElement('div');
      fields.className = 'import-injected-fields';
      injection.fields.forEach((field) => {
        fields.appendChild(renderInjectedField(field));
      });
      wrapper.appendChild(fields);
      const actions = document.createElement('div');
      actions.className = 'plugin-actions';
      injection.actions.forEach((action) => {
        const button = document.createElement('button');
        button.className = 'btn btn-primary btn-sm';
        button.textContent = action.label;
        button.onclick = () => callInjectedAction(item.provider, action, fields);
        actions.appendChild(button);
      });
      wrapper.appendChild(actions);
      container.appendChild(wrapper);
    });
}

function renderInjectedField(field) {
  const wrap = document.createElement('label');
  wrap.className = 'injected-field';
  const label = document.createElement('span');
  label.textContent = field.label + (field.required ? ' *' : '');
  wrap.appendChild(label);
  let input;
  if (field.type === 'enum') {
    input = document.createElement('select');
    (field.options || []).forEach((option) => {
      const item = document.createElement('option');
      item.value = option;
      item.textContent = option;
      input.appendChild(item);
    });
  } else {
    input = document.createElement('input');
    if (field.type === 'secret') input.type = 'password';
    if (field.type === 'bool') input.type = 'checkbox';
    if (field.type === 'int') input.type = 'number';
    if (field.default !== undefined && field.default !== null) {
      if (field.type === 'bool') input.checked = field.default === true;
      else input.value = String(field.default);
    }
    if (field.placeholder) input.placeholder = field.placeholder;
  }
  input.dataset.injectField = field.key;
  input.dataset.injectType = field.type;
  wrap.appendChild(input);
  return wrap;
}

function collectInjectedPayload(fields) {
  const payload = {};
  fields.querySelectorAll('[data-inject-field]').forEach((input) => {
    const type = input.dataset.injectType;
    if (type === 'bool') {
      payload[input.dataset.injectField] = input.checked;
    } else if (type === 'int') {
      const parsed = Number.parseInt(input.value, 10);
      payload[input.dataset.injectField] = Number.isNaN(parsed) ? 0 : parsed;
    } else {
      payload[input.dataset.injectField] = input.value;
    }
  });
  return payload;
}

async function callInjectedAction(provider, action, fields) {
  try {
    const resp = await fetch('/api/plugins/ui/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider,
        name: action.name,
        payload: collectInjectedPayload(fields),
      }),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || '动作失败');
    showToast(action.kind === 'query' ? '查询完成' : '已执行：' + action.label);
  } catch (error) {
    showToast('执行失败：' + (error.message || error));
  }
}

/* Plugin detail panels and sandboxed frames */
function renderPluginDetails(root, contributions) {
  const grouped = {};
  contributions.forEach((item) => {
    (grouped[item.provider] = grouped[item.provider] || []).push(item.injection);
  });
  Object.entries(grouped).forEach(([provider, injections]) => {
    const row = root.querySelector(
      '[data-plugin-row="' + CSS.escape(provider) + '"]'
    );
    if (!row) return;
    const actions = row.querySelector('.plugin-actions');
    if (!actions) return;
    const toggle = document.createElement('button');
    toggle.className = 'btn btn-secondary btn-sm';
    toggle.textContent = '详情';
    const detail = document.createElement('div');
    detail.className = 'plugin-detail';
    detail.style.display = 'none';
    toggle.onclick = () => togglePluginDetail(toggle, detail, provider, injections);
    actions.insertBefore(toggle, actions.firstChild);
    row.parentNode.insertBefore(detail, row.nextSibling);
  });
}

async function togglePluginDetail(toggle, detail, provider, injections) {
  if (detail.style.display !== 'none') {
    detail.querySelectorAll('iframe').forEach((frame) => {
      if (frame._cleanup) frame._cleanup();
    });
    detail.innerHTML = '';
    detail.style.display = 'none';
    toggle.textContent = '详情';
    return;
  }
  detail.innerHTML = '';
  for (const injection of injections) {
    if (injection.point === 'plugin_detail.panel') {
      detail.appendChild(await renderConfigPanel(provider, injection));
    } else if (injection.point === 'plugin_detail.iframe') {
      detail.appendChild(renderIframeSection(provider, injection));
    }
  }
  detail.style.display = 'flex';
  toggle.textContent = '收起';
}

async function renderConfigPanel(provider, panel) {
  const box = document.createElement('div');
  box.className = 'plugin-config';
  const title = document.createElement('div');
  title.className = 'section-title';
  title.textContent = panel.label;
  box.appendChild(title);
  let values = {};
  try {
    const resp = await fetch(
      '/api/plugins/ui/config?provider=' + encodeURIComponent(provider)
    );
    if (resp.ok) values = (await resp.json()).values || {};
  } catch (error) {
    values = {};
  }
  const fields = document.createElement('div');
  fields.className = 'import-injected-fields';
  panel.fields.forEach((field) => {
    const wrap = renderInjectedField(field);
    const input = wrap.querySelector('[data-inject-field]');
    const value = values[field.key];
    if (input && field.type === 'bool') input.checked = value === true;
    else if (input && field.type === 'secret') {
      input.placeholder = value && value.configured ? '已配置（留空保持不变）' : '';
    } else if (input && value !== undefined && value !== null) {
      input.value = String(value);
    }
    fields.appendChild(wrap);
  });
  box.appendChild(fields);
  const actions = document.createElement('div');
  actions.className = 'plugin-actions';
  const save = document.createElement('button');
  save.className = 'btn btn-primary btn-sm';
  save.textContent = '保存配置';
  save.onclick = async () => {
    try {
      const resp = await fetch('/api/plugins/ui/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          values: collectInjectedPayload(fields),
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || '保存失败');
      showToast('配置已保存');
    } catch (error) {
      showToast('保存失败：' + (error.message || error));
    }
  };
  actions.appendChild(save);
  (panel.actions || []).forEach((action) => {
    const button = document.createElement('button');
    button.className = 'btn btn-secondary btn-sm';
    button.textContent = action.label;
    button.onclick = () => {
      callDeclaredAction(
        provider,
        action.name,
        collectInjectedPayload(fields)
      ).then(
        () => showToast('已执行：' + action.label),
        (error) => showToast('执行失败：' + ((error && error.message) || error))
      );
    };
    actions.appendChild(button);
  });
  box.appendChild(actions);
  return box;
}

function renderIframeSection(provider, injection) {
  const box = document.createElement('div');
  box.className = 'plugin-config';
  const title = document.createElement('div');
  title.className = 'section-title';
  title.textContent = injection.label || '自定义界面';
  const button = document.createElement('button');
  button.className = 'btn btn-secondary btn-sm';
  button.textContent = '加载自定义界面';
  const holder = document.createElement('div');
  button.onclick = () => {
    if (holder.dataset.loaded) return;
    holder.dataset.loaded = '1';
    holder.appendChild(mountInjectedIframe(provider, injection));
    button.disabled = true;
    button.textContent = '已加载';
  };
  box.appendChild(title);
  box.appendChild(button);
  box.appendChild(holder);
  return box;
}

function mountInjectedIframe(provider, injection) {
  const frame = document.createElement('iframe');
  frame.className = 'plugin-ui-frame';
  frame.setAttribute('sandbox', 'allow-scripts');
  frame.style.height = (injection.height || 360) + 'px';
  const rate = { start: Date.now(), count: 0 };
  const entry = injection.entry
    .split('/')
    .map((part) => encodeURIComponent(part))
    .join('/');
  const onMessage = (event) => {
    if (event.source !== frame.contentWindow) return;
    const data = event.data;
    if (!data || typeof data !== 'object') return;
    if (data.type === 'ready') {
      frame.contentWindow.postMessage({ type: 'init', provider }, '*');
      return;
    }
    if (data.type !== 'call' || typeof data.name !== 'string') return;
    const now = Date.now();
    if (now - rate.start > 1000) {
      rate.start = now;
      rate.count = 0;
    }
    rate.count += 1;
    if (rate.count > 20) return;
    let size = 0;
    try {
      size = JSON.stringify(data).length;
    } catch (error) {
      return;
    }
    if (size > 65536) return;
    callDeclaredAction(provider, data.name, data.payload || {}).then(
      (result) =>
        frame.contentWindow.postMessage(
          { type: 'result', id: data.id, result },
          '*'
        ),
      (error) =>
        frame.contentWindow.postMessage(
          {
            type: 'error',
            id: data.id,
            error: String((error && error.message) || error),
          },
          '*'
        )
    );
  };
  window.addEventListener('message', onMessage);
  frame._cleanup = () => window.removeEventListener('message', onMessage);
  frame.src = '/api/plugins/' + encodeURIComponent(provider) + '/ui/' + entry;
  return frame;
}

async function callDeclaredAction(provider, name, payload) {
  const resp = await fetch('/api/plugins/ui/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, name, payload }),
  });
  const data = await resp.json();
  if (!resp.ok || !data.ok) throw new Error(data.error || '动作失败');
  return data.result;
}
