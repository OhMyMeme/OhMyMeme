import { api, esc } from '../../shared/bridge'

export function showLanDeviceConfirm(device: any) {
  if (document.getElementById('lan-confirm-overlay')) return
  const overlay = document.createElement('div')
  overlay.id = 'lan-confirm-overlay'
  overlay.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:500;animation:fadeIn .15s'
  const box = document.createElement('div')
  box.setAttribute('role', 'dialog')
  box.setAttribute('aria-modal', 'true')
  box.style.cssText =
    'background:var(--surface);border-radius:var(--radius-lg);padding:24px 28px;width:400px;border:1px solid var(--border);box-shadow:var(--shadow-lg)'
  box.innerHTML =
    '<div style="margin-bottom:14px"><h2 style="font-size:15px;font-weight:600;color:var(--fg);margin-bottom:8px">设备连接请求</h2>'
    + '<p style="font-size:13px;color:var(--fg-secondary);line-height:1.6">以下设备请求连接本机 OhMyMeme：</p>'
    + '<div style="background:var(--card);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px 14px;margin:12px 0;font-size:13px;line-height:1.8">'
    + '<div><span style="color:var(--muted)">设备：</span><b style="color:var(--fg)">' + esc(device?.name || '未知设备') + '</b></div>'
    + '<div><span style="color:var(--muted)">型号：</span><span style="color:var(--fg)">' + esc(device?.model || '-') + '</span></div>'
    + '<div><span style="color:var(--muted)">系统：</span><span style="color:var(--fg)">' + esc(device?.os || '-') + '</span></div>'
    + '<div><span style="color:var(--muted)">版本：</span><span style="color:var(--fg)">' + esc(device?.ver || '-') + '</span></div>'
    + '</div>'
    + '<p style="font-size:12px;color:var(--muted);line-height:1.6">允许后该设备可同步表情包与配置。请确认是你信任的设备。</p></div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end">'
    + '<button id="lan-confirm-deny" class="btn btn-secondary">拒绝</button>'
    + '<button id="lan-confirm-allow" class="btn btn-primary">允许连接</button></div>'
  overlay.appendChild(box)
  document.body.appendChild(overlay)
  const finish = (approved: boolean) => {
    overlay.remove()
    api('lan_confirm_device', approved, device?._confirm_id || '')
  }
  overlay.onclick = (event) => { if (event.target === overlay) finish(false) }
  box.querySelector('#lan-confirm-deny')?.addEventListener('click', () => finish(false))
  box.querySelector('#lan-confirm-allow')?.addEventListener('click', () => finish(true))
}
