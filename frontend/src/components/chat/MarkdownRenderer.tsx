import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'

interface Props {
  content: string
}

/**
 * T7-3: Markdown 渲染元件
 * 支援 GFM 表格、程式碼高亮、清單等
 */
export default function MarkdownRenderer({ content }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        // 段落
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        // 標題
        h1: ({ children }) => <h1 className="mb-2 mt-3 font-display text-lg font-semibold text-ink">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-3 font-display text-base font-semibold text-ink">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold text-ink">{children}</h3>,
        // 清單
        ul: ({ children }) => <ul className="mb-2 list-disc space-y-0.5 pl-5">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 list-decimal space-y-0.5 pl-5">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        // 表格
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto rounded-xl border border-line">
            <table className="min-w-full border-collapse text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-wash">{children}</thead>,
        th: ({ children }) => (
          <th className="border-b border-line px-3 py-2 text-left font-semibold text-ink">{children}</th>
        ),
        td: ({ children }) => (
          <td className="border-b border-line/60 px-3 py-2 text-muted">{children}</td>
        ),
        // 程式碼
        code: ({ className, children, ...props }) => {
          const isBlock = className?.startsWith('language-')
          if (isBlock) {
            return (
              <code className={`${className} block overflow-x-auto rounded-xl bg-sidebar p-3 text-xs text-sidebar-fg`} {...props}>
                {children}
              </code>
            )
          }
          return (
            <code className="rounded-md bg-highlight-soft px-1.5 py-0.5 font-mono text-xs text-highlight" {...props}>
              {children}
            </code>
          )
        },
        pre: ({ children }) => <pre className="my-2">{children}</pre>,
        // 引言
        blockquote: ({ children }) => (
          <blockquote className="my-2 rounded-r-xl border-l-4 border-accent/40 bg-accent-soft/40 py-1 pl-3 pr-2 text-muted">
            {children}
          </blockquote>
        ),
        // 粗體
        strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
        // 連結
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent underline decoration-accent/40 underline-offset-2 hover:text-accent-hover">
            {children}
          </a>
        ),
        // 分隔線
        hr: () => <hr className="my-3 border-line" />,
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
