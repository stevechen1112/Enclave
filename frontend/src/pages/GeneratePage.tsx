import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Wand2, Download, StopCircle, FolderOpen, Eye, Pencil, Copy, Check, FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import toast from 'react-hot-toast'
import api from '../api'

// P11-7: Convert [來源 N] markers to backtick code spans so ReactMarkdown can intercept them
function preprocessCitations(text: string): string {
  return text
    .replace(/\[來源\s*(\d+)\]/g, '`[來源 $1]`')
    // Add anchor IDs to source lines: "1. 文件名" → add HTML span with id
    .replace(/^(\d+)\.\s+(.+?[（(]相似度.+?[）)])/gm, '<span id="citation-source-$1" class="transition-colors duration-500 rounded px-1">$1. $2</span>')
}

// Custom code component: render [來源 N] spans as orange citation badges with tooltip
function CitationCode({ children, className }: { children?: React.ReactNode; className?: string }) {
  const text = String(children).trim()
  const match = text.match(/^\[來源\s*(\d+)\]$/)
  if (match) {
    return (
      <span
        className="inline-block mx-0.5 rounded px-1.5 py-0 text-xs font-medium bg-orange-100 text-orange-700 border border-orange-200 align-middle cursor-pointer hover:bg-orange-200 transition-colors"
        title={`點擊跳至引用來源 ${match[1]}`}
        onClick={() => {
          const el = document.getElementById(`citation-source-${match[1]}`)
          el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
          el?.classList.add('bg-orange-100')
          setTimeout(() => el?.classList.remove('bg-orange-100'), 2000)
        }}
      >
        {text}
      </span>
    )
  }
  return <code className={className}>{children}</code>
}

/**
 * Phase 11 — 內容生成頁（隨行秘書）
 *
 * 串接：
 *   POST /api/v1/generate/stream  — fetch SSE 串流
 *   POST /api/v1/generate/export/docx
 *   POST /api/v1/generate/export/pdf
 *
 * P11-2: 串流結束後後端自動存入 DB，前端收到 report_id 顯示跳轉提示。
 *        支援 ?from=:id 從已有報告預填 prompt + 模板。
 */

const TEMPLATES = [
  { id: 'draft_response', label: '函件草稿', desc: '公文格式：主旨→說明→辦法→結語', icon: '✉️' },
  { id: 'case_summary', label: '案件摘要', desc: '背景·當事人·時間線·待辦 結構化整理', icon: '📋' },
  { id: 'meeting_minutes', label: '會議記錄', desc: '議題→決議→行動追蹤表 含負責人/期限', icon: '📝' },
  { id: 'analysis_report', label: '分析報告', desc: '跨文件趨勢·風險機會矩陣·策略建議', icon: '📊' },
  { id: 'faq_draft', label: 'FAQ 草稿', desc: 'Q&A 對照格式 自動提取 5-10 個常見問題', icon: '❓' },
]

export default function GeneratePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [selectedTemplate, setSelectedTemplate] = useState(TEMPLATES[0].id)
  const [prompt, setPrompt] = useState('')
  const [contextQuery, setContextQuery] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedContent, setGeneratedContent] = useState('')
  const [exportTitle, setExportTitle] = useState('生成文件')
  const abortRef = useRef<AbortController | null>(null)
  const resultEndRef = useRef<HTMLDivElement | null>(null)

  // P11-5: preview/edit toggle — default to live Markdown preview
  const [previewMode, setPreviewMode] = useState(true)

  // Copy state
  const [justCopied, setJustCopied] = useState(false)

  // Saved report ID (received from SSE after auto-save)
  const [savedReportId, setSavedReportId] = useState<string | null>(null)

  // P11-3: cross-case document selection
  const [availableDocs, setAvailableDocs] = useState<{ id: string; title: string }[]>([])
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) return
    fetch('/api/v1/documents', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!data) return
        const docs: Array<{ id: string; title?: string; filename?: string }> =
          Array.isArray(data) ? data : (data.documents ?? [])
        setAvailableDocs(docs.map(d => ({ id: d.id, title: d.title || d.filename || d.id })))
      })
      .catch(() => {})
  }, [])

  // Prefill from existing report (?from=:id)
  useEffect(() => {
    const fromId = searchParams.get('from')
    if (!fromId) return
    const token = localStorage.getItem('token')
    if (!token) return
    fetch(`/api/v1/generate/reports/${fromId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!data) return
        setSelectedTemplate(data.template || TEMPLATES[0].id)
        setPrompt(data.prompt || '')
        setContextQuery(data.context_query || '')
        if (data.document_ids?.length) {
          setSelectedDocIds(new Set(data.document_ids))
        }
        toast.success('已載入報告設定，可修改後重新生成')
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleDoc = (id: string) => {
    setSelectedDocIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const selectedTemplateMeta = TEMPLATES.find(t => t.id === selectedTemplate)!

  const handleGenerate = async () => {
    if (!prompt.trim()) return
    setIsGenerating(true)
    setGeneratedContent('')
    setSavedReportId(null)

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const token = localStorage.getItem('token') || ''
      const resp = await fetch('/api/v1/generate/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          template: selectedTemplate,
          user_prompt: prompt,
          context_query: contextQuery || prompt,
          max_tokens: 3000,
          document_ids: Array.from(selectedDocIds),
        }),
        signal: ctrl.signal,
      })

      if (!resp.ok || !resp.body) {
        setGeneratedContent('⚠️ 生成失敗，請稍後再試。')
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6).trim()
          if (payload === '[DONE]') break
          try {
            const parsed = JSON.parse(payload)
            if (parsed.error) {
              setGeneratedContent(prev => prev + `\n⚠️ ${parsed.error}`)
            } else if (parsed.report_id) {
              // Auto-saved report ID from backend
              setSavedReportId(parsed.report_id)
            } else if (parsed.content) {
              setGeneratedContent(prev => prev + parsed.content)
            }
          } catch {
            // ignore malformed chunk
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error)?.name !== 'AbortError') {
        setGeneratedContent('⚠️ 連線中斷，請重試。')
      }
    } finally {
      setIsGenerating(false)
      abortRef.current = null
    }
  }

  const handleStop = () => {
    abortRef.current?.abort()
  }

  const handleCopy = useCallback(async () => {
    if (!generatedContent) return
    try {
      await navigator.clipboard.writeText(generatedContent)
      setJustCopied(true)
      toast.success('已複製到剪貼簿')
      setTimeout(() => setJustCopied(false), 2000)
    } catch {
      toast.error('複製失敗')
    }
  }, [generatedContent])

  const handleExport = async (format: 'docx' | 'pdf') => {
    if (!generatedContent) return
    try {
      const resp = await api.post(
        `/generate/export/${format}`,
        { content: generatedContent, title: exportTitle, sources: [] },
        { responseType: 'blob' },
      )
      const blob = new Blob([resp.data], {
        type: format === 'docx'
          ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
          : 'application/pdf',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${exportTitle}.${format}`
      a.click()
      URL.revokeObjectURL(url)
      toast.success(`${format.toUpperCase()} 匯出成功`)
    } catch {
      toast.error(`匯出 ${format.toUpperCase()} 失敗`)
    }
  }

  // Auto-scroll during streaming
  useEffect(() => {
    if (isGenerating && previewMode && resultEndRef.current) {
      resultEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [generatedContent, isGenerating, previewMode])

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">AI 內容生成</h1>
        <p className="text-gray-500 mt-1">基於知識庫文件，生成各種文稿草稿</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* 左側：設定區 */}
        <div className="col-span-4 space-y-4">
          {/* 模板選擇 */}
          <div className="bg-white border rounded-xl p-4">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">選擇生成模板</h2>
            <div className="space-y-2">
              {TEMPLATES.map(t => (
                <button
                  key={t.id}
                  onClick={() => setSelectedTemplate(t.id)}
                  className={`w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                    selectedTemplate === t.id
                      ? 'bg-blue-50 border border-blue-200'
                      : 'hover:bg-gray-50 border border-transparent'
                  }`}
                >
                  <span className="text-lg">{t.icon}</span>
                  <div>
                    <div className="font-medium text-sm text-gray-900">{t.label}</div>
                    <div className="text-xs text-gray-500">{t.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* 知識庫查詢詞（選填） */}
          <div className="bg-white border rounded-xl p-4">
            <h2 className="text-sm font-semibold text-gray-700 mb-2">知識庫搜尋關鍵字（選填）</h2>
            <input
              type="text"
              value={contextQuery}
              onChange={e => setContextQuery(e.target.value)}
              placeholder="留空則使用需求描述"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
            <p className="text-xs text-gray-400 mt-1">系統會以此關鍵字從知識庫檢索相關文件</p>
          </div>

          {/* P11-3: 跨案件文件選擇器 */}
          {availableDocs.length > 0 && (
            <div className="bg-white border rounded-xl p-4">
              <h2 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
                <FolderOpen className="w-4 h-4 text-blue-500" />
                跨案件文件（選填）
              </h2>
              <p className="text-xs text-gray-400 mb-2">勾選的文件內容將直接帶入生成上下文</p>
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {availableDocs.map(doc => (
                  <label key={doc.id} className="flex items-center gap-2 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={selectedDocIds.has(doc.id)}
                      onChange={() => toggleDoc(doc.id)}
                      className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600"
                    />
                    <span className={`text-xs truncate ${selectedDocIds.has(doc.id) ? 'text-blue-700 font-medium' : 'text-gray-600 group-hover:text-gray-900'}`}>
                      {doc.title}
                    </span>
                  </label>
                ))}
              </div>
              {selectedDocIds.size > 0 && (
                <p className="mt-2 text-xs text-blue-600">已選 {selectedDocIds.size} 份文件</p>
              )}
            </div>
          )}

          {/* 匯出標題 */}
          <div className="bg-white border rounded-xl p-4">
            <h2 className="text-sm font-semibold text-gray-700 mb-2">匯出檔案標題</h2>
            <input
              type="text"
              value={exportTitle}
              onChange={e => setExportTitle(e.target.value)}
              placeholder="生成文件"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
        </div>

        {/* 右側：輸入 + 輸出 */}
        <div className="col-span-8 space-y-4">
          {/* 需求輸入 */}
          <div className="bg-white border rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-gray-700">
                {selectedTemplateMeta.icon} {selectedTemplateMeta.label}
              </h2>
              <button
                onClick={() => navigate('/reports')}
                className="flex items-center gap-1 text-xs text-gray-500 border rounded-lg px-2 py-1 hover:bg-gray-50"
              >
                <FileText className="w-3.5 h-3.5" /> 我的報告
              </button>
            </div>

            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder={`描述你的需求，例如：\n「根據王小明的離婚案件文件，起草一份給對方律師的和解提案函件」`}
              className="w-full h-32 text-sm border border-gray-200 rounded-lg p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
            <div className="flex justify-end gap-2 mt-2">
              {isGenerating && (
                <button
                  onClick={handleStop}
                  className="flex items-center gap-2 px-4 py-2 bg-red-100 text-red-600 text-sm rounded-lg hover:bg-red-200"
                >
                  <StopCircle className="w-4 h-4" /> 停止生成
                </button>
              )}
              <button
                onClick={handleGenerate}
                disabled={!prompt.trim() || isGenerating}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Wand2 className="w-4 h-4" />
                {isGenerating ? '生成中...' : '開始生成'}
              </button>
            </div>
          </div>

          {/* 生成結果 */}
          <div className="bg-white border rounded-xl p-4 min-h-[50vh]">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-gray-700">生成結果</h2>
                {savedReportId && !isGenerating && (
                  <button
                    onClick={() => navigate(`/reports/${savedReportId}`)}
                    className="flex items-center gap-1 text-xs text-green-600 bg-green-50 border border-green-200 rounded-lg px-2 py-0.5 hover:bg-green-100 transition"
                  >
                    <Check className="w-3 h-3" /> 已自動儲存 · 查看報告
                  </button>
                )}
              </div>
              {generatedContent && (
                <div className="flex items-center gap-2">
                  {!isGenerating && (
                    <button
                      onClick={() => setPreviewMode(m => !m)}
                      className="flex items-center gap-1 text-xs text-gray-500 border rounded-lg px-2 py-1 hover:bg-gray-50"
                    >
                      {previewMode ? <Pencil className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                      {previewMode ? '編輯模式' : '預覽 Markdown'}
                    </button>
                  )}
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 text-xs text-gray-500 border rounded-lg px-2 py-1 hover:bg-gray-50"
                  >
                    {justCopied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
                    {justCopied ? '已複製' : '複製'}
                  </button>
                  {!isGenerating && (
                    <>
                      <button
                        onClick={() => handleExport('docx')}
                        className="flex items-center gap-1 text-xs text-gray-500 border rounded-lg px-2 py-1 hover:bg-gray-50"
                      >
                        <Download className="w-3.5 h-3.5" /> Word
                      </button>
                      <button
                        onClick={() => handleExport('pdf')}
                        className="flex items-center gap-1 text-xs text-gray-500 border rounded-lg px-2 py-1 hover:bg-gray-50"
                      >
                        <Download className="w-3.5 h-3.5" /> PDF
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>

            {!generatedContent && !isGenerating ? (
              <div className="flex flex-col items-center justify-center h-48 text-gray-300">
                <Wand2 className="w-10 h-10 mb-2 opacity-40" />
                <p className="text-sm">輸入需求描述後點擊生成</p>
              </div>
            ) : !previewMode && !isGenerating ? (
              <div>
                <textarea
                  value={generatedContent}
                  onChange={e => setGeneratedContent(e.target.value)}
                  className="w-full min-h-[45vh] text-sm text-gray-800 font-mono bg-gray-50 border border-gray-100 rounded-lg p-3 resize-y focus:outline-none focus:ring-1 focus:ring-blue-200"
                />
              </div>
            ) : (
              <div className="prose prose-sm max-w-none text-gray-800 max-h-[60vh] overflow-y-auto">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{ code: CitationCode }}
                >
                  {preprocessCitations(generatedContent)}
                </ReactMarkdown>
                {isGenerating && (
                  <span className="inline-block w-2 h-4 bg-blue-500 animate-pulse ml-0.5" />
                )}
                <div ref={resultEndRef} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

