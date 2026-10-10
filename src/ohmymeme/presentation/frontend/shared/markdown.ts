// 转义两窗口中的外部文本。
export function esc(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// 渲染受控 Markdown，先转义且不生成可执行链接。
export function renderMarkdown(markdown: string): string {
  if (!markdown) return ''
  let text = esc(markdown)
  text = text.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (_match, _language, code) => '<pre class="md-pre"><code>' + code + '</code></pre>')
  text = text.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>')
  text = text.replace(/^##### (.*)$/gm, '<h5 class="md-h">$1</h5>')
  text = text.replace(/^#### (.*)$/gm, '<h4 class="md-h">$1</h4>')
  text = text.replace(/^### (.*)$/gm, '<h3 class="md-h">$1</h3>')
  text = text.replace(/^## (.*)$/gm, '<h2 class="md-h">$1</h2>')
  text = text.replace(/^# (.*)$/gm, '<h1 class="md-h">$1</h1>')
  text = text.replace(/^&gt; (.*)$/gm, '<blockquote class="md-quote">$1</blockquote>')
  text = text.replace(/^[-*] (.*)$/gm, '<li class="md-li">$1</li>')
  text = text.replace(/^\d+\. (.*)$/gm, '<li class="md-li">$1</li>')
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="md-link">$1</span>')
  text = text.replace(/^-{3,}$/gm, '<hr class="md-hr">')
  text = text.replace(/\n/g, '<br>')
  text = text.replace(/(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)\s*<br>/g, '$1')
  text = text.replace(/<br>\s*(<\/?(?:h[1-5]|pre|blockquote|li|hr)[^>]*>)/g, '$1')
  return text
}
