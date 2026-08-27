import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { chatApi, parseApiError, formatErrorWithTrace } from '../api'
import { useAuth } from '../auth'
import RiskBanner from '../components/RiskBanner'
import type { Conversation, Message, ChatSource, SSEEvent, SearchResult, RetrievalInfo } from '../types'
import {
  Send, Plus, Loader2, Trash2, Download, Search, X, Menu,
  PanelRightOpen, PanelRightClose, FlaskConical, MessageSquare,
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
import { useHasCapability } from '../navigation/useCapabilities'
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
  // MKA 語音確認後帶入的查詢（/ask?q=...）
  const [input, setInput] = useState(() => searchParams.get('q') ?? '')
  const [sending, setSending] = useState(false)
  const [loadingConvs, setLoadingConvs] = useState(true)
  const [streamStatus, setStreamStatus] = useState<string | null>(null)
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingSources, setStreamingSources] = useState<ChatSource[]>([])
  // 手機上證據抽屜預設關閉（bottom sheet 會蓋住半個螢幕）；桌機預設開啟
  const [evidenceOpen, setEvidenceOpen] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(min-width: 768px)').matches,
  )
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [deleteConvId, setDeleteConvId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [retrieval, setRetrieval] = useState<RetrievalInfo | null>(null)
  const [messagesError, setMessagesError] = useState<string | null>(null)
  const [sceneContext, setSceneContext] = useState<Record<string, string> | null>(null)
  const canTestKnowledge = useHasCapability('admin_home')
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

  // 離開頁面時中止進行中的 SSE 串流，避免幽靈請求與 setState on unmounted
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

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

  // Deep-link: /ask?q=...&scene=...
  useEffect(() => {
    const q = searchParams.get('q')
    const sceneRaw = searchParams.get('scene')
    if (sceneRaw) {
      try {
        const parsed = JSON.parse(sceneRaw) as Record<string, string>
        setSceneContext(parsed)
      } catch {
        /* ignore bad scene */
      }
    }
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
        {
          question,
          conversation_id: activeConvId,
          scene_context: sceneContext || undefined,
          module_key: searchParams.get('module') || undefined,
        },
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
    setSidebarOpen(false)
  }

  const handleSelectConv = (convId: string) => {
    setActiveConvId(convId)
    setSidebarOpen(false)
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

  const retryLoadMessages = () => {
    if (!activeConvId) return
    setMessagesError(null)
    chatApi.messages(activeConvId)
      .then(msgs => setMessages(msgs))
      .catch((err) => setMessagesError(formatErrorWithTrace(parseApiError(err))))
  }

  const clearSearch = () => {
    setSearchQuery('')
    setSearchResults(null)
  }

  // ──── 對話側欄內容（桌機靜態欄＋手機 drawer 共用）────
  const sidebarBody = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="font-display text-sm font-semibold text-ink">對話記錄</h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleNewChat}
            className="icon-btn"
            aria-label="新對話"
          >
            <Plus className="h-5 w-5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            className="icon-btn md:hidden"
            aria-label="關閉對話記錄"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>
      </div>

      {/* T7-13: search bar */}
      <div className="border-b border-line px-3 py-2.5">
        <div className="flex items-center gap-2">
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="搜尋對話…"
            aria-label="搜尋對話"
            className="input flex-1 text-sm"
          />
          {searchQuery ? (
            <button
              type="button"
              onClick={clearSearch}
              className="icon-btn shrink-0"
              aria-label="清除搜尋"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSearch}
              className="icon-btn shrink-0"
              aria-label="搜尋"
            >
              <Search className="h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
      </div>

      {/* Search results or conversation list */}
      <div className="flex-1 space-y-1 overflow-y-auto px-3 py-3">
        {searchResults !== null ? (
          searchResults.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted">找不到符合的對話</p>
          ) : (
            searchResults.map((r, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  handleSelectConv(r.conversation_id)
                  clearSearch()
                }}
                className="card-interactive block w-full px-4 py-3 text-left"
              >
                <p className="truncate text-sm font-semibold text-ink">{r.conversation_title || '對話'}</p>
                <p className="mt-0.5 truncate text-xs text-muted">{r.snippet}</p>
              </button>
            ))
          )
        ) : loadingConvs ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted" aria-hidden />
          </div>
        ) : conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <MessageSquare className="h-6 w-6 text-muted/60" aria-hidden />
            <p className="text-sm text-muted">尚無對話，從右邊輸入問題開始</p>
          </div>
        ) : (
          conversations.map(conv => (
            <div
              key={conv.id}
              className={clsx(
                'flex items-stretch gap-1 rounded-2xl border transition-colors',
                activeConvId === conv.id
                  ? 'border-accent/40 bg-accent-soft'
                  : 'border-transparent hover:border-line hover:bg-wash',
              )}
            >
              <button
                type="button"
                onClick={() => handleSelectConv(conv.id)}
                className="min-h-11 min-w-0 flex-1 rounded-2xl px-3 py-2 text-left"
                aria-current={activeConvId === conv.id ? 'true' : undefined}
              >
                <p className={clsx(
                  'truncate text-sm font-semibold',
                  activeConvId === conv.id ? 'text-accent-ink' : 'text-ink',
                )}>
                  {conv.title || '新對話'}
                </p>
                <p className="mt-0.5 text-xs text-muted">
                  {format(new Date(conv.created_at), 'MM/dd HH:mm')}
                </p>
              </button>
              <div className="flex shrink-0 items-center">
                <button
                  type="button"
                  onClick={e => handleExport(conv.id, e)}
                  className="icon-btn"
                  aria-label={`匯出對話「${conv.title || '新對話'}」`}
                >
                  <Download className="h-4 w-4" aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={e => handleDeleteConv(conv.id, e)}
                  className="icon-btn hover:bg-danger-soft hover:text-danger"
                  aria-label={`刪除對話「${conv.title || '新對話'}」`}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )

  return (
    <div className="flex h-full">
      <h1 className="sr-only">企業知識問答</h1>
      {/* ──── Conversation sidebar（桌機）──── */}
      <div className="hidden w-72 flex-col border-r border-line bg-surface md:flex">
        {sidebarBody}
      </div>

      {/* ──── Conversation drawer（手機）──── */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="對話記錄">
          <button
            type="button"
            className="absolute inset-0 h-full w-full cursor-default bg-ink/40"
            onClick={() => setSidebarOpen(false)}
            aria-label="關閉對話記錄"
            tabIndex={-1}
          />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] animate-fade-in bg-surface shadow-lift">
            {sidebarBody}
          </div>
        </div>
      )}

      {/* ──── Chat area ──── */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-line bg-surface px-3 py-2 md:px-4">
          <div className="flex min-w-0 items-center gap-1">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="icon-btn md:hidden"
              aria-label="開啟對話記錄"
            >
              <Menu className="h-5 w-5" aria-hidden />
            </button>
            <h2 className="truncate font-display text-sm font-semibold text-ink md:hidden">問答</h2>
            {testKnowledge && canTestKnowledge && (
              <span className="chip-highlight shrink-0">
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
                  'btn-outline hidden min-h-11 px-3 text-xs sm:inline-flex',
                  testKnowledge && 'border-accent/40 bg-accent-soft text-accent-ink',
                )}
              >
                <FlaskConical className="h-3.5 w-3.5" aria-hidden />
                測試知識
              </button>
            )}
            <button
              type="button"
              onClick={() => setEvidenceOpen(v => !v)}
              className="icon-btn"
              aria-label={evidenceOpen ? '關閉證據' : '開啟證據'}
            >
              {evidenceOpen
                ? <PanelRightClose className="h-5 w-5" aria-hidden />
                : <PanelRightOpen className="h-5 w-5" aria-hidden />}
            </button>
            <button
              type="button"
              onClick={handleNewChat}
              className="icon-btn md:hidden"
              aria-label="新對話"
            >
              <Plus className="h-5 w-5" aria-hidden />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-5 md:px-6">
          {messages.length === 0 && !streamingContent ? (
            <EmptyState
              userName={user?.full_name}
              testMode={testKnowledge && canTestKnowledge}
              onPick={setInput}
            />
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              {messagesError && (
                <div className="card flex items-center justify-between gap-3 border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
                  <span className="min-w-0 flex-1">{messagesError}</span>
                  <button
                    type="button"
                    className="btn-outline min-h-11 shrink-0 px-4 text-sm"
                    onClick={retryLoadMessages}
                  >
                    重試
                  </button>
                </div>
              )}
              {messages.map(msg => (
                <div key={msg.id} className={clsx('animate-fade-in flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div
                    className={clsx(
                      'max-w-[92%] rounded-2xl px-4 py-3 text-base leading-relaxed md:max-w-[80%] md:px-5 md:text-sm',
                      msg.role === 'user'
                        ? 'rounded-br-md bg-accent text-white shadow-card'
                        : 'card rounded-bl-md text-ink',
                    )}
                  >
                    {msg.role === 'assistant' ? (
                      <div>
                        <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 border-b border-line pb-2 text-xs text-muted">
                          <span>根據 {msg.sources?.length ?? 0} 份公司文件回答</span>
                          <span>
                            資料更新至{' '}
                            {msg.sources?.find(s => s.updated_at)?.updated_at
                              ? new Date(msg.sources.find(s => s.updated_at)!.updated_at!).toLocaleDateString()
                              : '未知'}
                          </span>
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
                      <span className="whitespace-pre-wrap">{msg.content}</span>
                    )}
                  </div>
                </div>
              ))}

              {/* ──── Streaming in-progress ──── */}
              {sending && streamingContent && (
                <div className="flex animate-fade-in justify-start">
                  <div className="card max-w-[92%] rounded-bl-md px-4 py-3 text-base leading-relaxed text-ink md:max-w-[80%] md:px-5 md:text-sm">
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

        {/* Input：浮起的大卡片（手機加大字體與觸控目標） */}
        <div className="bg-gradient-to-t from-wash via-wash to-transparent px-3 pb-3 pt-2 md:px-6 md:pb-5">
          <div className="card mx-auto flex max-w-3xl items-end gap-2 p-2 shadow-lift md:gap-3 md:p-3">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="輸入你的問題…"
              rows={1}
              aria-label="問題輸入"
              className="max-h-32 min-h-12 flex-1 resize-none rounded-xl border border-transparent bg-transparent px-3 py-2.5 text-base text-ink placeholder:text-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 md:text-[15px]"
              onInput={e => {
                const target = e.target as HTMLTextAreaElement
                target.style.height = 'auto'
                target.style.height = Math.min(target.scrollHeight, 128) + 'px'
              }}
            />
            <button
              type="button"
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="btn-primary min-h-12 min-w-12 shrink-0 px-3"
              aria-label="送出"
            >
              {sending
                ? <Loader2 className="h-6 w-6 animate-spin" aria-hidden />
                : <Send className="h-6 w-6" aria-hidden />}
            </button>
          </div>
        </div>
      </div>

      {/* Evidence drawer — desktop right / mobile bottom sheet */}
      {evidenceOpen && (
        <aside
          className={clsx(
            'border-line bg-surface',
            'fixed inset-x-0 bottom-0 z-30 max-h-[45vh] overflow-y-auto rounded-t-2xl border-t p-4 shadow-lift md:static md:z-0 md:max-h-none md:w-80 md:rounded-none md:border-l md:border-t-0 md:shadow-none',
          )}
          aria-label="證據抽屜"
        >
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-display text-sm font-semibold text-ink">證據</h2>
            <button
              type="button"
              className="icon-btn md:hidden"
              onClick={() => setEvidenceOpen(false)}
              aria-label="關閉證據"
            >
              <X className="h-5 w-5" aria-hidden />
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
            <p className="mb-2 text-xs text-muted">{retrieval.label}</p>
          )}
          {drawerSources.length === 0 ? (
            <div className="card px-4 py-4">
              <p className="text-sm leading-relaxed text-muted">
                回答產生後，此處會顯示可核對的文件證據。沒有證據時不應把答案當成確定事實。
              </p>
            </div>
          ) : (
            <SourcePanel sources={drawerSources} defaultOpen />
          )}
        </aside>
      )}

      {!evidenceOpen && (
        <button
          type="button"
          onClick={() => setEvidenceOpen(true)}
          className="hidden w-12 flex-col items-center justify-start border-l border-line bg-surface pt-4 text-muted transition-colors hover:text-accent md:flex"
          aria-label="開啟證據抽屜"
        >
          <PanelRightOpen className="h-5 w-5" aria-hidden />
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
