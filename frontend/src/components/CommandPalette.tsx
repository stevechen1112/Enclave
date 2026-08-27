import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, X } from 'lucide-react'

import type { NavItem } from '../navigation/capabilities'

export default function CommandPalette({
  open,
  items,
  onClose,
}: {
  open: boolean
  items: NavItem[]
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!open) return
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const frame = window.requestAnimationFrame(() => {
      setQuery('')
      inputRef.current?.focus()
    })
    return () => {
      window.cancelAnimationFrame(frame)
      previousFocus?.focus()
    }
  }, [open])
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return needle
      ? items.filter(item => `${item.label} ${item.to}`.toLocaleLowerCase().includes(needle))
      : items
  }, [items, query])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center bg-ink/50 p-4 pt-[12vh]" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="command-title" className="w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl" onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
        if (event.key !== 'Tab') return
        const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>('input, button, a[href]') || [])].filter(element => !element.hasAttribute('disabled'))
        if (!focusable.length) return
        const first = focusable[0]; const last = focusable[focusable.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }}>
        <h2 id="command-title" className="sr-only">前往功能</h2>
        <div className="flex items-center gap-2 border-b border-line px-4"><Search className="h-5 w-5 text-muted" aria-hidden /><input ref={inputRef} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') onClose() }} className="min-h-14 flex-1 bg-transparent text-base text-ink outline-none" placeholder="搜尋可用功能…" aria-label="搜尋可用功能" /><button type="button" className="icon-btn" onClick={onClose} aria-label="關閉功能搜尋"><X className="h-5 w-5" /></button></div>
        <nav aria-label="功能搜尋結果" className="max-h-80 overflow-y-auto p-2">{filtered.length ? filtered.map(item => <Link key={item.to} to={item.to} onClick={onClose} className="flex min-h-11 items-center justify-between rounded-xl px-3 text-sm text-ink hover:bg-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"><span className="font-medium">{item.label}</span><span className="font-mono text-xs text-muted">{item.to}</span></Link>) : <p className="px-3 py-6 text-center text-sm text-muted">沒有符合的可用功能</p>}</nav>
      </section>
    </div>
  )
}
