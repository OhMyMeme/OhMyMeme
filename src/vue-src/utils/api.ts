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

// 轻量 Markdown 渲染（与原始实现一致），用于更新日志等富文本
export function renderMarkdown(md: string): string {
  if (!md) return ''
  let s = esc(md)
  s = s.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (m, lang, code) => '<pre class="md-pre"><code>' + code + '</code></pre>')
  s = s.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>')
  s = s.replace(/^##### (.*)$/gm, '<h5 class="md-h">$1</h5>')
  s = s.replace(/^#### (.*)$/gm, '<h4 class="md-h">$1</h4>')
  s = s.replace(/^### (.*)$/gm, '<h3 class="md-h">$1</h3>')
  s = s.replace(/^## (.*)$/gm, '<h2 class="md-h">$1</h2>')
  s = s.replace(/^# (.*)$/gm, '<h1 class="md-h">$1</h1>')
  s = s.replace(/^&gt; (.*)$/gm, '<blockquote class="md-quote">$1</blockquote>')
  s = s.replace(/^[-*] (.*)$/gm, '<li class="md-li">$1</li>')
  s = s.replace(/^\d+\. (.*)$/gm, '<li class="md-li">$1</li>')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="md-link">$1</span>')
  s = s.replace(/^-{3,}$/gm, '<hr class="md-hr">')
  s = s.replace(/\n/g, '<br>')
  s = s.replace(/(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)\s*<br>/g, '$1')
  s = s.replace(/<br>\s*(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)/g, '$1')
  return s
}
