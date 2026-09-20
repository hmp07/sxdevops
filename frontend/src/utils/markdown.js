import { marked } from 'marked'
import DOMPurify from 'dompurify'

// Markdown 渲染（安全）：marked 转 HTML 后经 DOMPurify 消毒，防 XSS
export function renderMarkdown(text) {
  if (!text) return ''
  const raw = marked.parse(String(text), { gfm: true, breaks: true })
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
}
