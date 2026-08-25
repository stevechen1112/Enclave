import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Database, Layers, Plus, RotateCcw, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { kbApi, knowledgeControlApi, parseApiError, type ApiErrorInfo, type KnowledgeControlOverview } from '../../api'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'

interface KnowledgeGap {
  id: string
  query_text: string
  confidence_score: number
  suggested_topic: string | null
  status: string
  created_at: string | null
}

interface Category {
  id: string
  name: string
  description: string | null
  is_active: boolean
}

export default function QualityPage() {
  const releaseStatus: Record<string, string> = {
    candidate: '候選版本', shadow: '唯讀試跑中', active: '正式使用中', retired: '歷史版本', rejected: '未通過',
  }
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [gaps, setGaps] = useState<KnowledgeGap[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [newName, setNewName] = useState('')
  const [adding, setAdding] = useState(false)
  const [control, setControl] = useState<KnowledgeControlOverview | null>(null)
  const [releaseBusy, setReleaseBusy] = useState(false)
  const [feedback, setFeedback] = useState<Array<{ id: string; category: string | null; comment: string | null; status: string }>>([])
  const [freshness, setFreshness] = useState<Array<{ id: string; document_id: string; state: string; reasons: string[] }>>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [g, c, k, f, s] = await Promise.all([
        kbApi.listGaps('open'),
        kbApi.listCategories(true),
        knowledgeControlApi.overview(),
        knowledgeControlApi.feedback('open'),
        knowledgeControlApi.freshness(),
      ])
      setGaps(g)
      setCategories(c)
      setControl(k)
      setFeedback(f)
      setFreshness(s.filter(row => row.state !== 'current'))
    } catch (err) {
      setError(parseApiError(err, '無法載入知識品質資料'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleScan = async () => {
    try {
      await kbApi.scanGaps(7)
      toast.success('缺口掃描已排程，稍後自動更新')
      setTimeout(load, 2000)
    } catch (err) {
      toast.error(parseApiError(err, '排程失敗').message)
    }
  }

  const runReleaseAction = async (action: () => Promise<unknown>, success: string) => {
    setReleaseBusy(true)
    try {
      await action()
      toast.success(success)
      await load()
    } catch (err) {
      toast.error(parseApiError(err, '版本操作失敗').message)
    } finally {
      setReleaseBusy(false)
    }
  }

  const handleResolve = async (id: string) => {
    try {
      await kbApi.resolveGap(id, { resolve_note: '已標記解決' })
      toast.success('已標記解決')
      load()
    } catch (err) {
      toast.error(parseApiError(err, '操作失敗').message)
    }
  }

  const handleAddCategory = async () => {
    if (!newName.trim()) return
    setAdding(true)
    try {
      await kbApi.createCategory({ name: newName.trim() })
      setNewName('')
      toast.success('分類已新增')
      load()
    } catch (err) {
      toast.error(parseApiError(err, '新增失敗').message)
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8">
      <div className="mx-auto max-w-4xl space-y-8">
        <PageHeader
          variant="section"
          title="品質"
          subtitle="追蹤知識庫還缺哪些內容，並維護文件分類。"
        />

        <AsyncState loading={loading} error={error} onRetry={load}>
          <>
            <section className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-ink">知識保鮮與使用者回饋</h2>
                  <p className="mt-1 text-sm text-muted">過期、撤權或同步異常的資料需要先處理；使用者回饋會留下負責人與處理紀錄，不會直接改寫答案。</p>
                </div>
                <button type="button" className="btn-outline" onClick={async () => {
                  try {
                    await knowledgeControlApi.scanFreshness()
                    toast.success('保鮮檢查已排程')
                  } catch {
                    toast.error('保鮮檢查排程失敗，請稍後再試')
                  }
                }}>重新檢查</button>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="card p-4">
                  <p className="font-medium text-ink">待處理資料 {freshness.length}</p>
                  {freshness.length === 0 ? <p className="mt-2 text-sm text-muted">目前沒有過期或撤權資料</p> : (
                    <ul className="mt-2 space-y-2 text-sm text-muted">{freshness.slice(0, 8).map(row => <li key={row.id}>文件 {row.document_id.slice(0, 8)} · {row.state} · {row.reasons.join('、')}</li>)}</ul>
                  )}
                </div>
                <div className="card p-4">
                  <p className="font-medium text-ink">待處理回饋 {feedback.length}</p>
                  {feedback.length === 0 ? <p className="mt-2 text-sm text-muted">目前沒有待處理回饋</p> : (
                    <ul className="mt-2 space-y-3">{feedback.slice(0, 8).map(row => <li key={row.id} className="text-sm"><p className="text-ink">{row.category ?? '其他'}{row.comment ? `：${row.comment}` : ''}</p><button type="button" className="mt-1 text-sm text-accent hover:underline" onClick={async () => { await knowledgeControlApi.processFeedback(row.id, 'resolved', '管理員已檢視並完成處理'); await load() }}>標記完成</button></li>)}</ul>
                  )}
                </div>
              </div>
            </section>

            <section className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-ink">目前正式知識版本</h2>
                  <p className="mt-1 text-sm text-muted">先確認文件是否可回答，再把候選版本送去測試；正式版可回到上一個已驗收版本。</p>
                </div>
                <button type="button" disabled={releaseBusy} className="btn-primary" onClick={() => runReleaseAction(knowledgeControlApi.createCandidate, '候選知識版本已建立')}>
                  <Database className="h-4 w-4" aria-hidden /> 建立候選版本
                </button>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="card p-4"><p className="text-sm text-muted">可回答</p><p className="mt-1 text-2xl font-semibold text-success">{control?.readiness.ready ?? 0}</p></div>
                <div className="card p-4"><p className="text-sm text-muted">部分可用</p><p className="mt-1 text-2xl font-semibold text-highlight">{control?.readiness.partial ?? 0}</p></div>
                <div className="card p-4"><p className="text-sm text-muted">需處理</p><p className="mt-1 text-2xl font-semibold text-danger">{control?.readiness.needs_attention ?? 0}</p></div>
              </div>
              {(control?.knowledge_bases ?? []).map(kb => (
                <div key={kb.id} className="card overflow-hidden">
                  <div className="border-b border-line/70 px-4 py-3"><p className="font-medium text-ink">{kb.name}</p><p className="text-sm text-muted">目前正式使用 R{kb.active_revision || '—'}</p></div>
                  {kb.revisions.length === 0 ? <p className="p-4 text-sm text-muted">尚未建立知識版本</p> : (
                    <ul className="divide-y divide-line/70">
                      {kb.revisions.map(rev => (
                        <li key={rev.id} className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm">
                          <span className="font-medium text-ink">R{rev.revision}</span><span className="rounded bg-surface px-2 py-1 text-muted">{releaseStatus[rev.status] ?? rev.status}</span>
                          <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{rev.manifest_hash?.slice(0, 12) ?? '尚無 manifest'}</span>
                          {rev.status === 'shadow' && (
                            <span className={rev.promotion_ready ? 'text-success' : 'text-highlight'}>
                              驗收 {rev.passed_gates.length}/{rev.required_gate_count}
                            </span>
                          )}
                          {rev.status === 'candidate' && <button disabled={releaseBusy} className="btn-outline px-3" onClick={() => runReleaseAction(() => knowledgeControlApi.transition(rev.id, 'shadow'), '已進入唯讀試跑')}>開始試跑</button>}
                          {rev.status === 'shadow' && <button disabled={releaseBusy || !rev.manifest_hash || !rev.promotion_ready} title={rev.promotion_ready ? undefined : '所有資料、問答、角色操作與正式試跑驗收通過後才能設為正式'} className="btn-primary px-3" onClick={() => runReleaseAction(() => knowledgeControlApi.promote(rev.id, rev.manifest_hash!), '已切換為正式知識版本')}>設為正式</button>}
                          {rev.status === 'retired' && <button disabled={releaseBusy} className="btn-outline px-3" onClick={() => runReleaseAction(() => knowledgeControlApi.rollback(rev.id), '已回復此知識版本')}><RotateCcw className="h-4 w-4" aria-hidden /> 回復</button>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </section>

            <section className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-ink">知識缺口</h2>
                  <p className="mt-1 max-w-xl text-sm text-muted">
                    系統發現「大家常問、但知識庫還沒有資料能回答」的主題。補上相關文件後，回答就會更完整。
                    （這裡與「治理 → 問答品質」的未答覆問題不同：那邊是逐題紀錄，這裡是整理過的主題缺口。）
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleScan}
                  className="btn-primary shrink-0"
                >
                  <Search className="h-4 w-4" aria-hidden /> 掃描缺口
                </button>
              </div>
              {gaps.length === 0 ? (
                <div className="card p-8 text-center text-muted">
                  <CheckCircle2 className="mx-auto mb-2 h-10 w-10 text-success" aria-hidden />
                  <p className="text-sm">目前沒有待處理的知識缺口</p>
                </div>
              ) : (
                <div className="card divide-y divide-line/70">
                  {gaps.map(g => (
                    <div key={g.id} className="flex flex-wrap items-start gap-3 p-4">
                      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-highlight" aria-hidden />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-ink">{g.query_text}</p>
                        <p className="mt-1 text-sm text-muted">
                          相關度參考 {(g.confidence_score * 100).toFixed(0)}%
                          {g.suggested_topic && ` · 主題：${g.suggested_topic}`}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleResolve(g.id)}
                        className="btn-outline shrink-0 px-3"
                      >
                        標記解決
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="space-y-3">
              <h2 className="font-semibold text-ink">分類</h2>
              <div className="flex gap-2">
                <input
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  placeholder="新分類名稱"
                  className="input flex-1"
                  aria-label="新分類名稱"
                />
                <button
                  type="button"
                  disabled={adding || !newName.trim()}
                  onClick={handleAddCategory}
                  className="btn-primary shrink-0"
                >
                  <Plus className="h-4 w-4" aria-hidden /> 新增
                </button>
              </div>
              {categories.length === 0 ? (
                <p className="card p-8 text-center text-sm text-muted">
                  <Layers className="mx-auto mb-2 h-10 w-10 text-line" aria-hidden />
                  尚無分類
                </p>
              ) : (
                <ul className="card divide-y divide-line/70">
                  {categories.map(c => (
                    <li key={c.id} className="px-4 py-3 text-sm">
                      <p className="font-medium text-ink">{c.name}</p>
                      {c.description && <p className="text-sm text-muted">{c.description}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        </AsyncState>
      </div>
    </div>
  )
}
