/**
 * 總覽 — 給老闆／管理員看的「今天公司知識庫狀況」。
 *
 * 設計原則：不用任何技術術語。不說「來源監控」「生命週期」「控制面」，
 * 只回答三個問題：
 *   1. 有沒有事情需要我處理？
 *   2. 員工問問題，系統答得出來嗎？
 *   3. 公司的資料有沒有順利進來？
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CheckCircle2, RefreshCw, Loader2, ArrowRight,
  FileWarning, Inbox, FolderInput, MessageCircleQuestion,
} from 'lucide-react'
import api, { docApi, parseApiError, type ApiErrorInfo } from '../api'
import clsx from 'clsx'
import AsyncState from '../components/AsyncState'

type AgentStatus = {
  watcher_running?: boolean
  scheduler_running?: boolean
  active_folders?: number
  pending_review_count?: number
}

type DocRow = { status: string; tombstoned_at?: string | null; updated_at?: string | null }

type TodoCard = {
  id: string
  icon: typeof Inbox
  title: string
  description: string
  to: string
  actionLabel: string
  tone: 'warning' | 'danger'
}

function StatCard({
  label,
  value,
  hint,
  warn,
}: {
  label: string
  value: string | number
  hint: string
  warn?: boolean
}) {
  return (
    <div
      className={clsx(
        'flex-1 min-w-[10rem] rounded-2xl border-2 p-5',
        warn ? 'border-amber-300 bg-amber-50' : 'border-line bg-surface',
      )}
    >
      <p className="text-base font-semibold text-muted">{label}</p>
      <p
        className={clsx(
          'mt-1 text-3xl font-bold tabular-nums',
          warn ? 'text-amber-800' : 'text-ink',
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-sm text-muted">{hint}</p>
    </div>
  )
}

export default function OverviewPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [agent, setAgent] = useState<AgentStatus | null>(null)
  const [docStats, setDocStats] = useState<{
    failed: number
    pending: number
    total: number
  } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      let allDocs: DocRow[] = []
      let docsFailed = false
      let docsError: unknown = null

      const agentPromise = api.get<AgentStatus>('/agent/status')

      try {
        allDocs = await docApi.listAll()
      } catch (err) {
        docsFailed = true
        docsError = err
        allDocs = []
      }

      let agentData: AgentStatus | null = null
      let agentFailed = false
      try {
        agentData = (await agentPromise).data
      } catch {
        agentFailed = true
        agentData = null
      }
      setAgent(agentData)

      if (!docsFailed) {
        setDocStats({
          total: allDocs.length,
          failed: allDocs.filter(d => d.status === 'failed').length,
          pending: allDocs.filter(d =>
            ['pending_review', 'pending', 'uploading', 'parsing', 'embedding', 'processing'].includes(d.status),
          ).length,
        })
      } else {
        setDocStats(null)
      }

      if (agentFailed && docsFailed) {
        setError(parseApiError(docsError, '無法載入總覽資料，請稍後重試。'))
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const todos: TodoCard[] = []
  const pendingReview = agent?.pending_review_count ?? 0

  if (docStats && docStats.total === 0) {
    todos.push({
      id: 'empty-kb',
      icon: FolderInput,
      title: '知識庫還是空的',
      description: '還沒有任何公司資料。上傳文件，或設定自動收取資料夾，員工才問得到答案。',
      tone: 'warning',
      to: '/knowledge/sources',
      actionLabel: '去放資料',
    })
  }
  if (pendingReview > 0) {
    todos.push({
      id: 'review',
      icon: Inbox,
      title: `${pendingReview} 份新文件等您確認`,
      description: '確認過的文件才會開放給員工查詢，避免錯誤資料被引用。',
      tone: 'warning',
      to: '/knowledge/review',
      actionLabel: '去確認',
    })
  }
  if (docStats && docStats.failed > 0) {
    todos.push({
      id: 'failed',
      icon: FileWarning,
      title: `${docStats.failed} 份文件讀取失敗`,
      description: '這些文件目前問不到。可能是檔案損壞或格式不支援，請查看後重新上傳。',
      tone: 'danger',
      to: '/knowledge/documents',
      actionLabel: '看是哪幾份',
    })
  }
  if (agent && !agent.watcher_running && (agent.active_folders ?? 0) > 0) {
    todos.push({
      id: 'watcher',
      icon: FolderInput,
      title: '自動收檔案的功能沒有啟動',
      description: '您設定過要自動收取的資料夾，但目前沒在跑。啟動後新檔案才會自動進來。',
      tone: 'warning',
      to: '/knowledge/sources',
      actionLabel: '去啟動',
    })
  }

  const healthy = !loading && !error && todos.length === 0 && docStats != null

  return (
    <div className="h-full overflow-y-auto">
      <div className="border-b border-line/70 bg-wash/50">
        <div className="mx-auto flex max-w-4xl flex-wrap items-end justify-between gap-4 px-4 py-8 md:px-8">
          <div>
            <h1 className="text-3xl font-bold text-ink">公司知識庫狀況</h1>
            <p className="mt-2 text-lg text-muted">
              有沒有需要您處理的事、資料健不健康，一眼看清楚。
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex min-h-12 items-center gap-2 rounded-xl border-2 border-line bg-surface px-4 text-base font-semibold text-muted hover:text-ink disabled:opacity-50"
            aria-label="重新整理總覽"
          >
            <RefreshCw className={clsx('h-5 w-5', loading && 'animate-spin')} aria-hidden />
            重新整理
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-4xl space-y-6 px-4 py-6 md:px-8 md:py-8">
        <div className="flex flex-wrap gap-4" aria-label="知識庫數字">
          <StatCard
            label="員工可查的文件"
            value={loading ? '—' : (docStats?.total ?? '—')}
            hint="這些文件，員工提問時系統找得到"
          />
          <StatCard
            label="等您確認"
            value={loading || agent == null ? '—' : pendingReview}
            hint="新進來的文件，確認後才開放查詢"
            warn={!loading && agent != null && pendingReview > 0}
          />
          <StatCard
            label="讀取失敗"
            value={loading ? '—' : (docStats?.failed ?? '—')}
            hint="這些文件目前問不到，需要處理"
            warn={!loading && (docStats?.failed ?? 0) > 0}
          />
        </div>

        <AsyncState loading={loading} error={error} onRetry={load}>
          {healthy ? (
            <div className="animate-fade-in rounded-2xl border-2 border-emerald-300 bg-emerald-50 p-7">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-emerald-700">
                  <CheckCircle2 className="h-7 w-7" aria-hidden />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-xl font-bold text-emerald-950">目前一切正常</h2>
                  <p className="mt-1.5 text-base leading-relaxed text-emerald-900/80">
                    沒有需要您處理的事。員工問問題時，系統都能從公司資料找到答案。
                  </p>
                  <div className="mt-5 flex flex-wrap gap-3">
                    <Link
                      to="/ask"
                      className="inline-flex min-h-12 items-center gap-2 rounded-xl bg-accent px-5 text-base font-bold text-white hover:bg-accent-hover"
                    >
                      <MessageCircleQuestion className="h-5 w-5" aria-hidden />
                      試著問一個問題
                    </Link>
                    <Link
                      to="/knowledge/sources"
                      className="inline-flex min-h-12 items-center gap-2 rounded-xl border-2 border-line bg-surface px-5 text-base font-semibold text-ink hover:bg-wash"
                    >
                      繼續放資料 <ArrowRight className="h-5 w-5" aria-hidden />
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <section className="animate-fade-in space-y-3" aria-label="需要您處理的事">
              <h2 className="text-xl font-bold text-ink">需要您處理</h2>
              <ul className="space-y-3">
                {todos.map(t => (
                  <li
                    key={t.id}
                    className={clsx(
                      'flex flex-wrap items-center gap-4 rounded-2xl border-2 p-5',
                      t.tone === 'danger'
                        ? 'border-red-300 bg-red-50'
                        : 'border-amber-300 bg-amber-50',
                    )}
                  >
                    <t.icon
                      className={clsx(
                        'h-8 w-8 shrink-0',
                        t.tone === 'danger' ? 'text-red-700' : 'text-amber-700',
                      )}
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <p
                        className={clsx(
                          'text-lg font-bold',
                          t.tone === 'danger' ? 'text-red-900' : 'text-amber-900',
                        )}
                      >
                        {t.title}
                      </p>
                      <p className="mt-0.5 text-base text-ink/80">{t.description}</p>
                    </div>
                    <Link
                      to={t.to}
                      className={clsx(
                        'inline-flex min-h-12 shrink-0 items-center gap-1.5 rounded-xl px-5 text-base font-bold text-white',
                        t.tone === 'danger'
                          ? 'bg-red-700 hover:bg-red-800'
                          : 'bg-amber-600 hover:bg-amber-700',
                      )}
                    >
                      {t.actionLabel} <ArrowRight className="h-5 w-5" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </AsyncState>

        <section className="rounded-2xl border-2 border-line bg-surface p-6">
          <h2 className="text-xl font-bold text-ink">資料是怎麼進來的？</h2>
          <p className="mt-2 text-base leading-relaxed text-muted">
            公司文件從放進來到員工問得到，會經過這幾個步驟。每一步都在「知識」區完成：
          </p>
          <ol className="mt-5 grid gap-3 sm:grid-cols-4">
            {[
              { step: '放進來', desc: '上傳或自動收取' },
              { step: '您確認', desc: '檢查內容沒問題' },
              { step: '開放查詢', desc: '員工問得到' },
              { step: '過期下架', desc: '舊資料可撤銷' },
            ].map(({ step, desc }, i) => (
              <li key={step} className="rounded-xl border-2 border-line bg-wash/60 px-4 py-4">
                <span className="block text-sm font-semibold text-muted">第 {i + 1} 步</span>
                <span className="mt-1 block text-lg font-bold text-ink">{step}</span>
                <span className="mt-0.5 block text-sm text-muted">{desc}</span>
              </li>
            ))}
          </ol>
          {loading && (
            <div className="mt-4 flex justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted" aria-hidden />
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
