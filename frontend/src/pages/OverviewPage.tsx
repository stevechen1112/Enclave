/**
 * Admin overview — task-first control surface (UIUX §9.3)
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CheckCircle2, RefreshCw, Loader2, Plug, ArrowRight,
} from 'lucide-react'
import api, { docApi, parseApiError, type ApiErrorInfo } from '../api'
import clsx from 'clsx'
import TaskInbox, { type TaskItem } from '../components/TaskInbox'
import AsyncState from '../components/AsyncState'

type AgentStatus = {
  watcher_running?: boolean
  scheduler_running?: boolean
  active_folders?: number
  pending_review_count?: number
}

type DocRow = { status: string; tombstoned_at?: string | null; updated_at?: string | null }

function StatPill({ label, value, warn }: { label: string; value: string | number; warn?: boolean }) {
  return (
    <div className="min-w-[7rem] flex-1 rounded-xl border border-line/80 bg-surface/80 px-4 py-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={clsx('mt-1 font-display text-2xl font-semibold tabular-nums', warn ? 'text-amber-700' : 'text-ink')}>
        {value}
      </p>
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
      // 列表 API 預設 limit=100 且排除 tombstone；listAll 分頁累加後才可當營運統計。
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
        setError(parseApiError(
          docsError,
          '無法載入總覽資料，請稍後重試。',
        ))
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const tasks: TaskItem[] = []
  const pendingReview = agent?.pending_review_count ?? 0
  if (docStats && docStats.total === 0) {
    tasks.push({
      id: 'empty-kb',
      title: '尚未導入知識',
      description: '上傳文件或接上 NAS／監控資料夾，才能開始審核與提問。',
      tone: 'warning',
      to: '/knowledge/sources',
      actionLabel: '管理來源',
    })
  }
  if (pendingReview > 0) {
    tasks.push({
      id: 'review',
      title: `${pendingReview} 筆待審核`,
      description: '新文件等待確認分類後才會進入可搜尋知識庫。',
      count: pendingReview,
      tone: 'warning',
      to: '/knowledge/review',
      actionLabel: '前往審核',
    })
  }
  if (docStats && docStats.failed > 0) {
    tasks.push({
      id: 'failed',
      title: `${docStats.failed} 份文件處理失敗`,
      description: '失敗文件無法被問到。請查看原因後重試或重新上傳。',
      count: docStats.failed,
      tone: 'danger',
      to: '/knowledge/documents',
      actionLabel: '查看文件',
    })
  }
  if (agent && !agent.watcher_running && (agent.active_folders ?? 0) > 0) {
    tasks.push({
      id: 'watcher',
      title: '監控資料夾已設定但未啟用',
      description: '啟用監控後，NAS／資料夾中的新檔才會自動進入入庫流程。',
      tone: 'warning',
      to: '/knowledge/sources',
      actionLabel: '管理來源',
    })
  }
  const healthy = !loading && !error && tasks.length === 0 && docStats != null

  return (
    <div className="h-full overflow-y-auto">
      <div className="relative overflow-hidden border-b border-line/70">
        <div
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              'linear-gradient(135deg, rgba(15,118,110,0.12) 0%, transparent 42%), linear-gradient(225deg, rgba(15,23,42,0.06) 0%, transparent 40%)',
          }}
          aria-hidden
        />
        <div className="relative mx-auto flex max-w-5xl flex-wrap items-end justify-between gap-4 px-4 py-8 md:px-8 md:py-10">
          <div className="max-w-xl">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-accent">控制面</p>
            <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight text-ink md:text-4xl">
              總覽
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-muted md:text-[15px]">
              先處理需要你出手的事，再確認知識是否健康流轉。
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-line bg-surface/90 px-3 py-2 text-sm text-muted shadow-sm hover:text-ink disabled:opacity-50"
            aria-label="重新整理總覽"
          >
            <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} aria-hidden />
            重新整理
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-5xl space-y-6 px-4 py-6 md:px-8 md:py-8">
        <div className="flex flex-wrap gap-3" aria-label="知識生命週期狀態">
          <StatPill
            label="來源監控"
            value={
              loading
                ? '—'
                : agent == null
                  ? '未知'
                  : agent.watcher_running
                    ? '運行中'
                    : '未啟用'
            }
            warn={!loading && agent != null && !agent.watcher_running}
          />
          <StatPill
            label="待審"
            value={loading || agent == null ? '—' : pendingReview}
            warn={!loading && agent != null && pendingReview > 0}
          />
          <StatPill label="處理中" value={loading ? '—' : (docStats?.pending ?? '—')} />
          <StatPill label="可存取文件" value={loading ? '—' : (docStats?.total ?? '—')} />
        </div>

        <AsyncState loading={loading} error={error} onRetry={load}>
          {healthy ? (
            <div className="animate-fade-in rounded-2xl border border-emerald-200/80 bg-gradient-to-br from-emerald-50/90 to-surface p-7 shadow-sm">
              <div className="flex items-start gap-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-100 text-emerald-700">
                  <CheckCircle2 className="h-6 w-6" aria-hidden />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="font-display text-xl font-semibold text-emerald-950">知識系統正常</h2>
                  <p className="mt-1.5 max-w-lg text-sm leading-relaxed text-emerald-900/75">
                    目前沒有待處理事項。可用問答驗證證據，或到來源繼續擴充知識。
                  </p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    <Link
                      to="/ask"
                      className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
                    >
                      測試提問 <ArrowRight className="h-4 w-4" aria-hidden />
                    </Link>
                    <Link
                      to="/knowledge/sources"
                      className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-line bg-surface px-4 py-2 text-sm text-ink hover:bg-wash"
                    >
                      <Plug className="h-4 w-4" aria-hidden /> 管理來源
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <section className="animate-fade-in space-y-3">
              <h2 className="font-display text-lg font-semibold text-ink">需要處理</h2>
              <TaskInbox tasks={tasks} />
            </section>
          )}
        </AsyncState>

        <section className="rounded-2xl border border-line/80 bg-surface/90 p-6 shadow-sm">
          <h2 className="font-display text-lg font-semibold text-ink">知識生命週期</h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
            來源 → 審核 → 入庫 → 被引用 → 撤銷。這些步驟都在「知識」完成，不必另找設定頁。
          </p>
          <ol className="mt-5 grid gap-2 sm:grid-cols-5">
            {['來源', '審核', '入庫', '被引用', '撤銷'].map((step, i) => (
              <li
                key={step}
                className="rounded-xl border border-line bg-wash/60 px-3 py-3 text-center"
              >
                <span className="block text-[10px] font-medium text-muted">{i + 1}</span>
                <span className="mt-1 block text-sm font-medium text-ink">{step}</span>
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
