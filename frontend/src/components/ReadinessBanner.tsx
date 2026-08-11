import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, ChevronRight, X } from 'lucide-react'
import { useAuth } from '../auth'
import { useHasCapability } from '../navigation/useCapabilities'
import api from '../api'
import clsx from 'clsx'
import { isTestAskDone, TEST_ASK_DONE_EVENT } from '../lib/readiness'

const STORAGE_KEY = 'enclave_readiness_dismissed_v1'

type Step = {
  id: string
  label: string
  done: boolean
  to: string
}

export default function ReadinessBanner() {
  const { experience } = useAuth()
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(STORAGE_KEY) === '1')
  const [steps, setSteps] = useState<Step[] | null>(null)
  const [testAskTick, setTestAskTick] = useState(0)

  const isAdmin = useHasCapability('admin_home')

  useEffect(() => {
    const onDone = () => setTestAskTick(t => t + 1)
    window.addEventListener(TEST_ASK_DONE_EVENT, onDone)
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'enclave_test_ask_done') onDone()
    }
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(TEST_ASK_DONE_EVENT, onDone)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  useEffect(() => {
    if (!isAdmin || dismissed) return
    let cancelled = false
    ;(async () => {
      try {
        const [docs, connectors, review, agent] = await Promise.allSettled([
          // Only need existence — one row is enough
          api.get<unknown[]>('/documents/', { params: { limit: 1 } }),
          api.get<unknown[]>('/connectors/'),
          api.get<{ total: number }>('/agent/review?limit=1'),
          api.get<{ watcher_running?: boolean; active_folders?: number }>('/agent/status'),
        ])
        if (cancelled) return
        const hasDocs = docs.status === 'fulfilled' && docs.value.data.length > 0
        const hasSource =
          (connectors.status === 'fulfilled' && connectors.value.data.length > 0) ||
          (agent.status === 'fulfilled' && (agent.value.data.active_folders ?? 0) > 0)
        const reviewedOrEmpty =
          review.status === 'fulfilled' && (review.value.data.total ?? 0) === 0
        const testAskDone = isTestAskDone()
        setSteps([
          { id: 'health', label: '確認系統可用', done: true, to: '/overview' },
          { id: 'source', label: '上傳或接 NAS', done: hasDocs || hasSource, to: '/knowledge/sources' },
          { id: 'review', label: '完成第一批審核', done: reviewedOrEmpty && hasDocs, to: '/knowledge/review' },
          { id: 'ask', label: '用測試問題驗證證據', done: testAskDone, to: '/ask' },
        ])
      } catch {
        if (!cancelled) setSteps(null)
      }
    })()
    return () => { cancelled = true }
  }, [isAdmin, dismissed, testAskTick])

  if (!isAdmin || dismissed || !steps) return null

  const doneCount = steps.filter(s => s.done).length
  const allDone = doneCount >= steps.length

  if (allDone) return null

  return (
    <div className="border-b border-accent/15 bg-accent/[0.04] px-4 py-2 md:px-6">
      <div className="mx-auto flex max-w-5xl items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <p className="shrink-0 text-xs font-semibold text-ink">
              首次設定
              <span className="ml-1.5 font-normal text-muted">{doneCount}/{steps.length}</span>
            </p>
            {experience?.product?.maturity_label && (
              <span className="hidden rounded border border-line bg-surface px-1.5 py-0.5 text-[10px] text-muted sm:inline">
                {experience.product.maturity_label}
              </span>
            )}
            <ol className="flex min-w-0 flex-1 flex-wrap gap-1.5">
              {steps.map((s, i) => (
                <li key={s.id}>
                  <Link
                    to={s.to}
                    className={clsx(
                      'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] leading-5',
                      s.done
                        ? 'border-emerald-200/80 bg-emerald-50 text-emerald-800'
                        : 'border-line bg-surface text-ink hover:border-accent/40',
                    )}
                  >
                    {s.done ? <CheckCircle2 className="h-3 w-3" aria-hidden /> : <span className="text-muted">{i + 1}</span>}
                    {s.label}
                    {!s.done && <ChevronRight className="h-3 w-3 text-muted" aria-hidden />}
                  </Link>
                </li>
              ))}
            </ol>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(STORAGE_KEY, '1')
            setDismissed(true)
          }}
          className="shrink-0 rounded-md p-1.5 text-muted hover:bg-surface hover:text-ink"
          aria-label="稍後完成，關閉指引"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
