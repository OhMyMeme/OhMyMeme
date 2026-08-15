export async function api(method: string, ...args: any[]): Promise<any> {
  try {
    if (typeof pywebview === 'undefined' || !pywebview.api) return null
    return await pywebview.api[method](...args)
  } catch (e) {
    console.error('API error:', method, e)
    return null
  }
}

export function esc(s: string): string {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
