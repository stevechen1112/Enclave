import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { chatApi, parseApiError, formatErrorWithTrace } from '../api'
import { useAuth } from '../auth'
import RiskBanner from '../components/RiskBanner'
import type { Conversation, Message, ChatSource, SSEEvent, SearchResult, RetrievalInfo } from '../types'
import {
  Send, Plus, Loader2, Trash2,
  Download, Search, X, PanelRightOpen, PanelRightClose, FlaskConical,
} from 'lucide-react'
import clsx from 'clsx'
import { format } from 'date-fns'
import toast from 'react-hot-toast'
import MarkdownRenderer from '../components/chat/MarkdownRenderer'
import SourcePanel from '../components/chat/SourcePanel'
import FeedbackButtons from '../components/chat/FeedbackButtons'
import FollowUpSuggestions from '../components/chat/FollowUpSuggestions'
import TypingIndicator from '../components/chat/TypingIndicator'
import ConfirmDialog from '../components/ConfirmDialog'
import EmptyState from './ask/EmptyState'
import { classifyEmptyAnswer, EMPTY_ANSWER_LABEL, type EmptyAnswerKind } from './ask/emptyAnswer'
import { hasCapability } from '../navigation/capabilities'
import { markTestAskDone } from '../lib/readiness'

const TEST_KNOWLEDGE_KEY = 'enclave_test_knowledge'

/** 擴展 Message 在前端增加附帶資料 */
interface ChatMessage extends Message {
  sources?: ChatSource[]
  suggestions?: string[]
  emptyKind?: EmptyAnswerKind | null
}

export default function ChatPage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingConvs, setLoadingConvs] = useState(true)
  const [streamStatus, setStreamStatus] = useState<string | null>(null)
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingSources, setStreamingSources] = useState<ChatSource[]>([])
  const [evidenceOpen, setEvidenceOpen] = useState(true)
  const [deleteConvId, setDeleteConvId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [retrieval, setRetrieval] = useState<RetrievalInfo | null>(null)
  const [messagesError, setMessagesError] = useState<string | null>(null)
  const canTestKnowledge = hasCapability(user?.role, 'admin_home', user?.is_superuser)
  const [testKnowledge, setTestKnowledge] = useState(() => {
    try {
      return localStorage.getItem(TEST_KNOWLEDGE_KEY) === '1'
    } catch {
      return false
    }
  })

  // T7-13: search
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const retrievalRef = useRef<RetrievalInfo | null>(null)

  useEffect(() => {
    retrievalRef.current = retrieval
  }, [retrieval])

  const toggleTestKnowledge = () => {
    setTestKnowledge(prev => {
      const next = !prev
      try {
        localStorage.setItem(TEST_KNOWLEDGE_KEY, next ? '1' : '0')
      } catch { /* ignore */ }
      return next
    })
  }

  // Load conversations
  const loadConversations = useCallback(async () => {
    try {
      const convs = await chatApi.conversations()
      setConversations(convs)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '無法載入對話列表')))
    } finally {
      setLoadingConvs(false)
    }
  }, [])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  // Deep-link: /ask?q=...
  useEffect(() => {
    const q = searchParams.get('q')
    if (q) {
      setInput(q)
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const drawerSources = useMemo(() => {
    if (sending && streamingSources.length) return streamingSources
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant' && messages[i].sources?.length) {
        return messages[i].sources!
      }
    }
    return [] as ChatSource[]
  }, [messages, sending, streamingSources])

  // Load messages when conversation changes
  useEffect(() => {
    if (!activeConvId) {
      setMessages([])
      return
    }
    setMessagesError(null)
    chatApi.messages(activeConvId)
      .then(msgs => setMessages(msgs))
      .catch((err) => {
        const info = parseApiError(err, '無法載入訊息')
        setMessagesError(formatErrorWithTrace(info))
        toast.error(formatErrorWithTrace(info))
      })
  }, [activeConvId])

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  // ──────── T7-1: SSE Streaming send ────────
  const handleSend = async () => {
    const question = input.trim()
    if (!question || sending) return

    markTestAskDone()

    // Optimistic user message
    const tempUserMsg: ChatMessage = {
      id: 'temp-' + Date.now(),
      conversation_id: activeConvId || '',
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, tempUserMsg])
    setInput('')
    setSending(true)
    setStreamingContent('')
    setStreamingSources([])
    setStreamStatus(null)
    setRetrieval(null)

    const abortController = new AbortController()
    abortRef.current = abortController

    let finalConvId = activeConvId
    let finalMessageId = ''
    let accumulatedContent = ''
    let suggestions: string[] = []
    let sources: ChatSource[] = []
    let hadStreamError = false
    let lastRetrieval: RetrievalInfo | null = null

    try {
      await chatApi.stream(
        { question, conversation_id: activeConvId },
        (event: SSEEvent) => {
          switch (event.type) {
            case 'status':
              setStreamStatus(event.content || null)
              break
            case 'retrieval':
              if (event.retrieval) {
                lastRetrieval = event.retrieval
                setRetrieval(event.retrieval)
              }
              break
            case 'sources':
              sources = event.sources || []
              setStreamingSources(sources)
              break
            case 'token':
              accumulatedContent += event.content || ''
              setStreamingContent(accumulatedContent)
              setStreamStatus(null) // hide status once tokens flow
              break
            case 'suggestions':
              suggestions = event.items || []
              break
            case 'done':
              finalConvId = event.conversation_id || finalConvId
              finalMessageId = event.message_id || ''
              break
            case 'error':
              hadStreamError = true
              toast.error(event.content || '處理失敗')
              break
          }
        },
        abortController.signal,
      )

      if (hadStreamError) {
        setStreamingContent('')
        setStreamingSources([])
        setStreamStatus(null)
        const errKind = classifyEmptyAnswer({
          sources: [],
          retrieval: lastRetrieval,
          hadError: true,
        })
        const errMsg: ChatMessage = {
          id: 'ai-err-' + Date.now(),
          conversation_id: finalConvId || '',
          role: 'assistant',
          content: '',
          created_at: new Date().toISOString(),
          sources: [],
          emptyKind: errKind,
        }
        setMessages(prev => [
          ...prev.filter(m => m.id !== tempUserMsg.id),
          { ...tempUserMsg, id: 'user-' + Date.now(), conversation_id: finalConvId || '' },
          errMsg,
        ])
        return
      }

      // Stream finished — commit assistant message
      const emptyKind = classifyEmptyAnswer({
        sources,
        retrieval: lastRetrieval || retrievalRef.current,
        hadError: false,
      })
      const assistantMsg: ChatMessage = {
        id: finalMessageId || 'ai-' + Date.now(),
        conversation_id: finalConvId || '',
        role: 'assistant',
        content: accumulatedContent,
        created_at: new Date().toISOString(),
        sources,
        suggestions,
        emptyKind,
      }

      setMessages(prev => [
        ...prev.filter(m => m.id !== tempUserMsg.id),
        { ...tempUserMsg, id: 'user-' + Date.now(), conversation_id: finalConvId || '' },
        assistantMsg,
      ])
      setStreamingContent('')
      setStreamingSources([])
      setStreamStatus(null)

      // Update conversation list if new
      if (!activeConvId && finalConvId) {
        setActiveConvId(finalConvId)
        loadConversations()
      }
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') return
      const info = parseApiError(err, '發送失敗，請稍後重試')
      toast.error(formatErrorWithTrace(info))
      if (info.requestId) {
        setRetrieval(prev => prev || { mode: 'error', degraded: true, request_id: info.requestId, label: info.message })
      }
      setMessages(prev => prev.filter(m => m.id !== tempUserMsg.id))
      setInput(question)
    } finally {
      setSending(false)
      setStreamStatus(null)
      abortRef.current = null
    }
  }

  const handleNewChat = () => {
    if (abortRef.current) abortRef.current.abort()
    setActiveConvId(null)
    setMessages([])
    setInput('')
    setStreamingContent('')
    setStreamingSources([])
    setStreamStatus(null)
  }

  const handleDeleteConv = (convId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDeleteConvId(convId)
  }

  const confirmDeleteConv = async () => {
    if (!deleteConvId) return
    setDeleting(true)
    try {
      await chatApi.deleteConversation(deleteConvId)
      if (activeConvId === deleteConvId) handleNewChat()
      setConversations(prev => prev.filter(c => c.id !== deleteConvId))
      toast.success('對話已刪除')
      setDeleteConvId(null)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '刪除失敗')))
    } finally {
      setDeleting(false)
    }
  }

  // T7-11: Export
  const handleExport = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      const blob = await chatApi.exportConversation(convId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `conversation_${convId}.md`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('對話已匯出')
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '匯出失敗')))
    }
  }

  // T7-13: Search
  const handleSearch = async () => {
    const q = searchQuery.trim()
    if (!q) {
      setSearchResults(null)
      return
    }
    try {
      const results = await chatApi.searchConversations(q)
      setSearchResults(results)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '搜尋失敗')))
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // T7-6: Follow-up suggestion click
  const handleSuggestionClick = (question: string) => {
    setInput(question)
  }

  // 最後一條 assistant message 的 suggestions
  const lastSuggestions =
    !sending && messages.length > 0 && messages[messages.length - 1]?.role === 'assistant'
      ? messages[messages.length - 1].suggestions
      : undefined

  return (
    <div className="flex h-full">
      {/* ──── Conversation sidebar ──── */}
      <div className="hidden md:flex w-64 flex-col border-r border-gray-200 bg-white">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-700">對話記錄</h2>
          <button
            onClick={handleNewChat}
            className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 hover:text-blue-600 transition-colors"
            title="新對話"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        {/* T7-13: search bar */}
        <div className="px-3 py-2 border-b border-gray-100">
          <div className="flex items-center gap-1">
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="搜尋對話..."
              className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:border-blue-400 focus:outline-none"
            />
            {searchQuery ? (
              <button
                onClick={() => { setSearchQuery(''); setSearchResults(null) }}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button onClick={handleSearch} className="p-1 text-gray-400 hover:text-gray-600">
                <Search className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Search results or conversation list */}
        <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
          {searchResults !== null ? (
            searchResults.length === 0 ? (
              <p className="py-8 text-center text-xs text-gray-400">無搜尋結果</p>
            ) : (
              searchResults.map((r, i) => (
                <div
                  key={i}
                  onClick={() => {
                    setActiveConvId(r.conversation_id)
                    setSearchResults(null)
                    setSearchQuery('')
                  }}
                  className="rounded-lg px-3 py-2 text-xs cursor-pointer hover:bg-gray-50 text-gray-600"
                >
                  <p className="font-medium truncate">{r.conversation_title || '對話'}</p>
                  <p className="text-gray-400 truncate mt-0.5">{r.snippet}</p>
                </div>
              ))
            )
          ) : loadingConvs ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
            </div>
          ) : conversations.length === 0 ? (
            <p className="py-8 text-center text-xs text-gray-400">尚無對話</p>
          ) : (
            conversations.map(conv => (
              <div
                key={conv.id}
                onClick={() => setActiveConvId(conv.id)}
                className={clsx(
                  'group flex items-center justify-between rounded-lg px-3 py-2 text-sm cursor-pointer transition-colors',
                  activeConvId === conv.id ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50',
                )}
              >
                <div className="flex-1 truncate">
                  <p className="truncate font-medium">{conv.title || '新對話'}</p>
                  <p className="text-xs text-gray-400">{format(new Date(conv.created_at), 'MM/dd HH:mm')}</p>
                </div>
                <div className="ml-2 hidden gap-0.5 group-hover:flex">
                  <button
                    onClick={e => handleExport(conv.id, e)}
                    className="rounded p-1 text-gray-400 hover:bg-blue-50 hover:text-blue-500 transition-colors"
                    title="匯出"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={e => handleDeleteConv(conv.id, e)}
                    className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
                    aria-label="刪除對話"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ──── Chat area ──── */}
      <div className="flex flex-1 flex-col min-w-0">
        {/* Header: mobile + admin test toggle */}
        <div className="flex items-center justify-between border-b border-line bg-surface px-4 py-2">
          <div className="flex items-center gap-2 min-w-0">
            <h2 className="text-sm font-semibold text-ink md:hidden">問答</h2>
            {testKnowledge && canTestKnowledge && (
              <span className="inline-flex items-center gap-1 rounded-md bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">
                <FlaskConical className="h-3 w-3" aria-hidden /> 測試知識
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {canTestKnowledge && (
              <button
                type="button"
                role="switch"
                aria-checked={testKnowledge}
                onClick={toggleTestKnowledge}
                className={clsx(
                  'hidden sm:inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                  testKnowledge
                    ? 'border-accent/40 bg-accent/10 text-accent'
                    : 'border-line text-muted hover:text-ink',
                )}
                title="Admin：切換測試知識語境（僅前端）"
              >
                <FlaskConical className="h-3.5 w-3.5" aria-hidden />
                測試知識
              </button>
            )}
            <button
              type="button"
              onClick={() => setEvidenceOpen(v => !v)}
              className="rounded-lg p-1.5 text-muted hover:bg-wash"
              aria-label={evidenceOpen ? '關閉證據' : '開啟證據'}
            >
              {evidenceOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            </button>
            <button
              onClick={handleNewChat}
              className="rounded-lg p-1.5 text-muted hover:bg-wash hover:text-accent md:hidden"
              aria-label="新對話"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4">
          {messages.length === 0 && !streamingContent ? (
            <EmptyState
              userName={user?.full_name}
              testMode={testKnowledge && canTestKnowledge}
              onPick={setInput}
            />
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              {messagesError && (
                <div className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
                  {messagesError}
                  <button
                    type="button"
                    className="ml-3 underline"
                    onClick={() => {
                      if (!activeConvId) return
                      setMessagesError(null)
                      chatApi.messages(activeConvId)
                        .then(msgs => setMessages(msgs))
                        .catch((err) => setMessagesError(formatErrorWithTrace(parseApiError(err))))
                    }}
                  >
                    重試
                  </button>
                </div>
              )}
              {messages.map(msg => (
                <div key={msg.id} className={clsx('animate-fade-in flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div
                    className={clsx(
                      'max-w-[85%] md:max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white'
                        : 'bg-white text-gray-800 border border-gray-200 shadow-sm',
                    )}
                  >
                    {msg.role === 'assistant' ? (
                      <div>
                        <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 border-b border-line pb-2 text-[11px] text-muted">
                          <span>證據 {msg.sources?.length ?? 0}</span>
                          <span>
                            資料更新{' '}
                            {msg.sources?.find(s => s.updated_at)?.updated_at
                              ? new Date(msg.sources.find(s => s.updated_at)!.updated_at!).toLocaleDateString()
                              : '未知'}
                          </span>
                          <span>回答範圍：可存取知識</span>
                        </div>
                        {(() => {
                          // Historical API messages omit sources — do not invent empty-answer banners
                          const kind =
                            msg.emptyKind ??
                            (msg.sources == null
                              ? null
                              : classifyEmptyAnswer({ sources: msg.sources }))
                          if (!kind) return null
                          const meta = EMPTY_ANSWER_LABEL[kind]
                          return (
                            <RiskBanner
                              level={kind === 'system_unavailable' ? 'danger' : 'warning'}
                              title={meta.title}
                              description={meta.description}
                              className="mb-3"
                            />
                          )
                        })()}
                        {msg.content ? <MarkdownRenderer content={msg.content} /> : null}
                        {msg.sources && msg.sources.length > 0 && (
                          <SourcePanel sources={msg.sources} defaultOpen={!evidenceOpen} />
                        )}
                        {msg.id && !msg.id.startsWith('ai-err-') && (
                          <FeedbackButtons messageId={msg.id} />
                        )}
                      </div>
                    ) : (
                      <span>{msg.content}</span>
                    )}
                  </div>
                </div>
              ))}

              {/* ──── Streaming in-progress ──── */}
              {sending && streamingContent && (
                <div className="flex justify-start animate-fade-in">
                  <div className="max-w-[85%] md:max-w-[80%] rounded-2xl bg-white border border-gray-200 px-4 py-3 shadow-sm text-sm leading-relaxed text-gray-800">
                    <MarkdownRenderer content={streamingContent} />
                    {streamingSources.length > 0 && <SourcePanel sources={streamingSources} />}
                  </div>
                </div>
              )}

              {/* T7-14: Typing indicator (before first token arrives) */}
              {sending && !streamingContent && (
                <TypingIndicator status={streamStatus || '正在搜尋可存取知識…'} />
              )}

              {/* T7-6: Follow-up suggestions (after stream completes) */}
              {lastSuggestions && lastSuggestions.length > 0 && (
                <FollowUpSuggestions suggestions={lastSuggestions} onSelect={handleSuggestionClick} />
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-line bg-surface p-3 md:p-4">
          <div className="mx-auto flex max-w-3xl items-end gap-2 md:gap-3">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="輸入你的問題…"
              rows={1}
              aria-label="問題輸入"
              className="flex-1 resize-none rounded-xl border border-line px-4 py-3 text-sm focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none transition-shadow"
              style={{ maxHeight: '120px' }}
              onInput={e => {
                const target = e.target as HTMLTextAreaElement
                target.style.height = 'auto'
                target.style.height = Math.min(target.scrollHeight, 120) + 'px'
              }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-white hover:bg-accent-hover disabled:opacity-40 transition-colors shrink-0"
              aria-label="送出"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Evidence drawer — desktop right / mobile bottom sheet */}
      {evidenceOpen && (
        <aside
          className={clsx(
            'border-line bg-surface',
            'fixed inset-x-0 bottom-0 z-30 max-h-[45vh] overflow-y-auto rounded-t-2xl border-t shadow-lg p-4 md:static md:z-0 md:max-h-none md:w-80 md:rounded-none md:border-l md:border-t-0 md:shadow-none',
          )}
          aria-label="證據抽屜"
        >
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">證據</h2>
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-wash md:hidden"
              onClick={() => setEvidenceOpen(false)}
              aria-label="關閉"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {retrieval?.degraded && (
            <RiskBanner
              level="warning"
              title={retrieval.label || '目前僅使用本機主索引'}
              description={retrieval.request_id ? `追蹤：${retrieval.request_id}` : undefined}
              className="mb-3"
            />
          )}
          {!retrieval?.degraded && retrieval?.label && drawerSources.length > 0 && (
            <p className="mb-2 text-[11px] text-muted">{retrieval.label}</p>
          )}
          {drawerSources.length === 0 ? (
            <p className="text-xs text-muted leading-relaxed">
              回答產生後，此處會顯示可核對的文件證據。沒有證據時不應把答案當成確定事實。
            </p>
          ) : (
            <SourcePanel sources={drawerSources} defaultOpen />
          )}
        </aside>
      )}

      {!evidenceOpen && (
        <button
          type="button"
          onClick={() => setEvidenceOpen(true)}
          className="hidden md:flex w-10 flex-col items-center justify-start border-l border-line bg-surface pt-4 text-muted hover:text-accent"
          aria-label="開啟證據抽屜"
        >
          <PanelRightOpen className="h-4 w-4" />
        </button>
      )}

      <ConfirmDialog
        open={!!deleteConvId}
        danger
        busy={deleting}
        title="刪除此對話？"
        description="對話記錄將被移除，無法復原。"
        confirmLabel="刪除對話"
        onCancel={() => !deleting && setDeleteConvId(null)}
        onConfirm={confirmDeleteConv}
      />
    </div>
  )
}
