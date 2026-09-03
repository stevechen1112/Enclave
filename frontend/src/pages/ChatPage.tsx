import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { chatApi, parseApiError, formatErrorWithTrace } from '../api'
import { useAuth } from '../auth'
import RiskBanner from '../components/RiskBanner'
import type { Conversation, Message, ChatSource, SSEEvent, SearchResult, RetrievalInfo, KnowledgeDecision } from '../types'
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
import DecisionSummary from '../components/chat/DecisionSummary'
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
  const [streamingDecision, setStreamingDecision] = useState<KnowledgeDecision | null>(null)
  // A 款使用覆蓋式證據抽屜，所有裝置皆由使用者主動開啟。
  const [evidenceOpen, setEvidenceOpen] = useState(false)
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
    let latestUserIndex = -1
    let latestAssistantIndex = -1
    for (let i = messages.length - 1; i >= 0; i--) {
      if (latestUserIndex < 0 && messages[i].role === 'user') latestUserIndex = i
      if (latestAssistantIndex < 0 && messages[i].role === 'assistant') latestAssistantIndex = i
      if (latestUserIndex >= 0 && latestAssistantIndex >= 0) break
    }
    if (latestAssistantIndex > latestUserIndex && messages[latestAssistantIndex].sources?.length) {
      return messages[latestAssistantIndex].sources!
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
    setStreamingDecision(null)
    setStreamStatus(null)
    setRetrieval(null)

    const abortController = new AbortController()
    abortRef.current = abortController

    let finalConvId = activeConvId
    let finalMessageId = ''
    let accumulatedContent = ''
    let suggestions: string[] = []
    let sources: ChatSource[] = []
    let decision: KnowledgeDecision | undefined
    let hadStreamError = false
    let lastRetrieval: RetrievalInfo | null = null
    const legacyModule = searchParams.get('module') || undefined
    const knowledgeMode = searchParams.get('mode') || (legacyModule === 'spec_sop' ? 'spec_sop' : undefined)

    try {
      await chatApi.stream(
        {
          question,
          conversation_id: activeConvId,
          scene_context: sceneContext || undefined,
          knowledge_mode: knowledgeMode === 'spec_sop' ? knowledgeMode : undefined,
          module_key: legacyModule === 'spec_sop' ? undefined : legacyModule,
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
            case 'decision':
              decision = event.decision
              setStreamingDecision(event.decision || null)
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
        decision,
      }

      setMessages(prev => [
        ...prev.filter(m => m.id !== tempUserMsg.id),
        { ...tempUserMsg, id: 'user-' + Date.now(), conversation_id: finalConvId || '' },
        assistantMsg,
      ])
      setStreamingContent('')
      setStreamingSources([])
      setStreamingDecision(null)
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
    setStreamingDecision(null)
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

  const latestQuestionIndex = messages.map(message => message.role).lastIndexOf('user')
  const latestAnswerIndex = messages.map(message => message.role).lastIndexOf('assistant')
  const latestQuestionMessage = latestQuestionIndex >= 0 ? messages[latestQuestionIndex] : undefined
  const latestQuestion = latestQuestionMessage?.content
  const latestAnswer = latestAnswerIndex > latestQuestionIndex ? messages[latestAnswerIndex] : undefined

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

  // 對話記錄改為所有裝置共用的抽屜，主畫面保留給答案決策頁。
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
            className="icon-btn"
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
    <div className="relative flex h-full overflow-hidden bg-wash">
      <h1 className="sr-only">企業知識問答</h1>
      {/* Conversation history is intentionally secondary to the decision workspace. */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="對話記錄">
          <button
            type="button"
            className="absolute inset-0 h-full w-full cursor-default bg-ink/40"
            onClick={() => setSidebarOpen(false)}
            aria-label="關閉對話記錄"
            tabIndex={-1}
          />
          <div className="absolute inset-y-0 left-0 w-80 max-w-[88vw] animate-fade-in bg-surface shadow-lift">
            {sidebarBody}
          </div>
        </div>
      )}

      {/* ──── Chat area ──── */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* A concept: compact product bar, with history and evidence as secondary tools. */}
        <div className="border-b border-line bg-surface">
          <div className="mx-auto flex min-h-16 w-full max-w-6xl items-center gap-2 px-3 md:px-6">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="icon-btn shrink-0"
              aria-label="開啟對話記錄"
            >
              <Menu className="h-5 w-5" aria-hidden />
            </button>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">企業知識 · 答案決策頁</p>
              <h2 className="truncate text-sm font-semibold text-ink">
                {latestQuestion || '今天想確認什麼？'}
              </h2>
            </div>
            {testKnowledge && canTestKnowledge && (
              <span className="chip-highlight hidden shrink-0 sm:inline-flex">
                <FlaskConical className="h-3 w-3" aria-hidden /> 測試知識
              </span>
            )}
            {canTestKnowledge && (
              <button
                type="button"
                role="switch"
                aria-checked={testKnowledge}
                onClick={toggleTestKnowledge}
                className={clsx(
                  'btn-outline hidden min-h-11 px-3 text-xs lg:inline-flex',
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
              className={clsx('btn-outline min-h-11 shrink-0 px-3 text-xs', evidenceOpen && 'border-accent/40 bg-accent-soft text-accent-ink')}
              aria-label={evidenceOpen ? '關閉證據' : '開啟證據'}
            >
              {evidenceOpen
                ? <PanelRightClose className="h-4 w-4" aria-hidden />
                : <PanelRightOpen className="h-4 w-4" aria-hidden />}
              <span className="hidden sm:inline">證據 {drawerSources.length || ''}</span>
            </button>
            <button type="button" onClick={handleNewChat} className="icon-btn shrink-0" aria-label="新對話">
              <Plus className="h-5 w-5" aria-hidden />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-3 py-5 md:px-6 md:py-7">
          {messages.length === 0 && !streamingContent ? (
            <EmptyState
              userName={user?.full_name}
              testMode={testKnowledge && canTestKnowledge}
              onPick={setInput}
            />
          ) : (
            <div className="mx-auto max-w-5xl space-y-6">
              {latestQuestion && (
                <section className="animate-rise-in" aria-label="目前問題與回答處理狀態">
                  <div className="flex items-start gap-3 md:gap-4">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-accent-soft text-lg font-bold text-accent">?</div>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-muted">目前問題</p>
                      <h3 className="mt-1 whitespace-pre-wrap font-display text-xl font-semibold leading-relaxed text-ink md:text-2xl">
                        {latestQuestion}
                      </h3>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <span className="chip-neutral">僅搜尋可存取知識</span>
                        {sceneContext && Object.entries(sceneContext).slice(0, 3).map(([key, value]) => (
                          <span key={key} className="chip-accent">{value}</span>
                        ))}
                        {latestAnswer?.sources?.length ? (
                          <span className="chip-success">{latestAnswer.sources.length} 份證據</span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                  <div className="mt-5 grid grid-cols-2 gap-2 md:grid-cols-4">
                    {[
                      ['理解問題', true],
                      ['搜尋可存取知識', Boolean(retrieval || drawerSources.length || streamingContent || !sending)],
                      ['過濾權限與版本', Boolean(drawerSources.length || streamingContent || !sending)],
                      ['建立可追溯回答', !sending],
                    ].map(([label, complete], index) => (
                      <div key={String(label)} className="card flex min-h-12 items-center gap-2 px-3 py-2 text-xs text-muted">
                        <span className={clsx(
                          'flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-bold',
                          complete ? 'bg-success-soft text-success' : index === 3 && streamingContent ? 'bg-highlight-soft text-highlight' : 'bg-wash text-muted',
                        )}>
                          {complete ? '✓' : index + 1}
                        </span>
                        <span>{label}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}
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
              {messages.map((msg, index) => {
                if (msg.role === 'user') {
                  const isLatest = msg.id === latestQuestionMessage?.id
                  if (isLatest) return null
                  return (
                    <details key={msg.id} className="card animate-fade-in overflow-hidden">
                      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-muted">較早問題：{msg.content}</summary>
                    </details>
                  )
                }

                const kind = msg.emptyKind ?? (msg.sources == null ? null : classifyEmptyAnswer({ sources: msg.sources }))
                const emptyMeta = kind ? EMPTY_ANSWER_LABEL[kind] : null
                const isLatestAnswer = msg.id === latestAnswer?.id

                if (!isLatestAnswer && index < latestQuestionIndex) {
                  return (
                    <details key={msg.id} className="card animate-fade-in overflow-hidden">
                      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-muted">展開較早回答</summary>
                      <div className="border-t border-line px-4 py-4 text-sm leading-relaxed text-ink">
                        <MarkdownRenderer content={msg.content} />
                      </div>
                    </details>
                  )
                }

                return (
                  <article key={msg.id} className={clsx('panel animate-fade-in', !isLatestAnswer && 'opacity-90')}>
                    <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-4 md:px-6">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-sm font-bold text-white">K</div>
                      <div>
                        <h4 className="text-sm font-semibold text-ink">知識助理</h4>
                        <p className="text-xs text-muted">
                          {msg.sources?.length
                            ? `${msg.sources.length} 份企業證據 · 逐項可核對`
                            : '回答會清楚標示證據狀態'}
                        </p>
                      </div>
                      {msg.sources?.length ? <span className="chip-success ml-auto">● 證據可追溯</span> : null}
                    </header>
                    <div className="p-4 md:p-6">
                      {msg.decision && <DecisionSummary decision={msg.decision} />}
                      {emptyMeta && (
                        <RiskBanner
                          level={kind === 'system_unavailable' ? 'danger' : 'warning'}
                          title={emptyMeta.title}
                          description={emptyMeta.description}
                          className="mb-4"
                        />
                      )}
                      {msg.content ? (
                        <div className="rounded-2xl border-l-4 border-accent bg-accent-soft/35 px-4 py-4 text-[15px] leading-relaxed md:px-5">
                          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-accent">直接回答</p>
                          <MarkdownRenderer content={msg.content} />
                        </div>
                      ) : null}
                      {msg.sources && msg.sources.length > 0 && !evidenceOpen && (
                        <div className="mt-4 rounded-2xl border border-line bg-wash/70 p-3">
                          <SourcePanel sources={msg.sources} defaultOpen={false} />
                        </div>
                      )}
                      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
                        <button type="button" onClick={() => setEvidenceOpen(true)} className="btn-outline min-h-11 px-4 text-xs">
                          <PanelRightOpen className="h-4 w-4" aria-hidden /> 查看答案證據
                        </button>
                        {msg.id && !msg.id.startsWith('ai-err-') && <FeedbackButtons messageId={msg.id} />}
                      </div>
                    </div>
                  </article>
                )
              })}

              {/* ──── Streaming in-progress ──── */}
              {sending && streamingContent && (
                <article className="panel animate-fade-in">
                  <header className="flex items-center gap-3 border-b border-line px-4 py-4 md:px-6">
                    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-sm font-bold text-white">K</div>
                    <div className="min-w-0 flex-1">
                      <h4 className="text-sm font-semibold text-ink">正在建立可追溯回答</h4>
                      <p className="truncate text-xs text-muted">{streamStatus || '已完成檢索，正在整理直接結論與依據'}</p>
                    </div>
                    <Loader2 className="h-5 w-5 animate-spin text-accent" aria-hidden />
                  </header>
                  <div className="p-4 md:p-6">
                    {streamingDecision && <DecisionSummary decision={streamingDecision} />}
                    <div className="rounded-2xl border-l-4 border-accent bg-accent-soft/35 px-4 py-4 text-[15px] leading-relaxed md:px-5">
                      <p className="mb-2 text-xs font-bold uppercase tracking-wide text-accent">回答產生中</p>
                      <MarkdownRenderer content={streamingContent} />
                    </div>
                    {streamingSources.length > 0 && !evidenceOpen && <SourcePanel sources={streamingSources} defaultOpen={false} />}
                  </div>
                </article>
              )}

              {/* T7-14: Typing indicator (before first token arrives) */}
              {sending && !streamingContent && (
                <div className="panel p-5 md:p-7">
                  <TypingIndicator status={streamStatus || '正在搜尋可存取知識、核對權限與版本…'} />
                  <p className="mt-3 text-center text-xs text-muted">系統不會把無權限、已撤銷或不適用的內容直接拿來回答。</p>
                </div>
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
        <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="答案證據">
          <button
            type="button"
            className="absolute inset-0 h-full w-full cursor-default bg-ink/40"
            onClick={() => setEvidenceOpen(false)}
            aria-label="關閉證據"
            tabIndex={-1}
          />
          <aside className="absolute inset-y-0 right-0 w-[34rem] max-w-[94vw] animate-fade-in overflow-y-auto border-l border-line bg-surface p-4 shadow-lift md:p-6">
            <div className="mb-4 flex items-center justify-between border-b border-line pb-4">
              <div>
                <p className="text-xs font-semibold text-accent">答案依據</p>
                <h2 className="mt-1 font-display text-lg font-semibold text-ink">可核對的企業證據</h2>
              </div>
              <button type="button" className="icon-btn" onClick={() => setEvidenceOpen(false)} aria-label="關閉證據">
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
              <p className="mb-3 text-xs text-muted">{retrieval.label}</p>
            )}
            {drawerSources.length === 0 ? (
              <div className="card px-4 py-4">
                <p className="text-sm leading-relaxed text-muted">
                  回答產生後，此處會顯示文件版本、頁碼、工作表或影片時間點。沒有證據時，不應把答案當成確定事實。
                </p>
              </div>
            ) : (
              <SourcePanel sources={drawerSources} defaultOpen />
            )}
          </aside>
        </div>
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
