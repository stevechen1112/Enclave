/**
 * 審核工作台 — 桌面三欄：清單 / 預覽建議 / 核准設定
 * 手機改為步驟式：選項目 → 預覽 → 決策
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CheckCircle, XCircle, Loader2, RefreshCw, AlertTriangle, ArrowRight, ArrowLeft,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import api, { parseApiError, formatErrorWithTrace, type ApiErrorInfo } from '../api'
import ConfirmDialog from '../components/ConfirmDialog'
import PermissionScope from '../components/PermissionScope'
import AsyncState from '../components/AsyncState'

interface ReviewItem {
  id: string
  file_name: string
  file_path: string
  file_ext: string | null
  file_size: number | null
  suggested_category: string | null
  suggested_subcategory: string | null
  suggested_tags: Record<string, string> | null
  confidence_score: number | null
  reasoning: string | null
  related_documents: Array<{ id: string; file_name: string; match: string }>
  status: string
  created_at: string
}

function riskFlags(item: ReviewItem): string[] {
  const flags: string[] = []
  const score = item.confidence_score ?? 0
  if (score < 0.6) flags.push('低信心')
  else if (score < 0.8) flags.push('需確認')
  if (item.related_documents?.length) flags.push('可能重複')
  return flags
}

type MobileStep = 'list' | 'preview' | 'decide'

export default function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [category, setCategory] = useState('')
  const [note, setNote] = useState('')
  const [acting, setActing] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [mobileStep, setMobileStep] = useState<MobileStep>('list')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<{ items: ReviewItem[]; total: number }>('/agent/review?limit=100')
      setItems(res.data.items)
      setTotal(res.data.total)
      setSelectedIds(new Set())
      setSelectedId(prev => {
        if (prev && res.data.items.some(i => i.id === prev)) return prev
        return res.data.items[0]?.id ?? null
      })
    } catch (err) {
      setError(parseApiError(err, '無法載入審核佇列'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const selected = useMemo(
    () => items.find(i => i.id === selectedId) || null,
    [items, selectedId],
  )

  useEffect(() => {
    if (!selected) {
      setCategory('')
      setNote('')
      return
    }
    setCategory(selected.suggested_category || '')
    setNote('')
  }, [selected])

  const highConf = items.filter(i => (i.confidence_score ?? 0) >= 0.8 && riskFlags(i).length === 0)

  const approve = async (id: string) => {
    setActing(true)
    try {
      await api.post(`/agent/review/${id}/approve`)
      toast.success('已確認入庫')
      setMobileStep('list')
      await load()
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '核准失敗')))
    } finally {
      setActing(false)
    }
  }

  const modifyApprove = async () => {
    if (!selected) return
    setActing(true)
    try {
      await api.post(`/agent/review/${selected.id}/modify`, { category, note })
      toast.success('已修改並入庫')
      setMobileStep('list')
      await load()
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '操作失敗')))
    } finally {
      setActing(false)
    }
  }

  const reject = async () => {
    if (!selected) return
    setActing(true)
    try {
      await api.post(`/agent/review/${selected.id}/reject`, { reason: note || '' })
      toast.success('已拒絕入庫')
      setRejectOpen(false)
      setMobileStep('list')
      await load()
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '拒絕失敗')))
    } finally {
      setActing(false)
    }
  }

  const batchApprove = async () => {
    setActing(true)
    try {
      await api.post('/agent/review/batch-approve', { item_ids: [...selectedIds] })
      toast.success(`已批量確認 ${selectedIds.size} 筆`)
      setBatchOpen(false)
      await load()
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '批量核准失敗')))
    } finally {
      setActing(false)
    }
  }

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectItem = (id: string) => {
    setSelectedId(id)
    setMobileStep('preview')
  }

  const emptyQueue = items.length === 0

  return (
    <AsyncState loading={loading} error={error} onRetry={load} empty={false} className="h-full">
      <div className="flex h-full flex-col md:flex-row">
        {/* Column 1 — list（手機步驟一：選項目） */}
        <aside
          className={clsx(
            'w-full flex-col border-b border-line bg-surface md:flex md:w-80 md:border-b-0 md:border-r',
            mobileStep === 'list' ? 'flex flex-1' : 'hidden',
          )}
        >
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">待審核</h2>
              <p className="text-sm text-muted">共 {total} 筆</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={load}
                className="icon-btn"
                aria-label="重新整理"
              >
                <RefreshCw className="h-5 w-5" aria-hidden />
              </button>
              {!emptyQueue && selectedIds.size > 0 && (
                <button
                  type="button"
                  onClick={() => setBatchOpen(true)}
                  className="btn-primary px-3"
                >
                  批量（{selectedIds.size}）
                </button>
              )}
            </div>
          </div>
          {emptyQueue ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-muted">
              <CheckCircle className="h-10 w-10 text-success" aria-hidden />
              <p className="font-medium text-ink">佇列是空的</p>
              <p className="text-sm">
                所有文件已完成審核，或尚未啟用來源監控。
              </p>
              <Link to="/knowledge/sources" className="btn-primary">
                前往來源
              </Link>
            </div>
          ) : (
            <>
              {highConf.length > 0 && (
                <button
                  type="button"
                  className="min-h-11 border-b border-line px-4 py-2 text-left text-sm font-semibold text-accent hover:bg-wash"
                  onClick={() => setSelectedIds(new Set(highConf.map(i => i.id)))}
                >
                  全選低風險高信心（{highConf.length}）
                </button>
              )}
              <ul className="flex-1 overflow-y-auto">
                {items.map(item => {
                  const flags = riskFlags(item)
                  const active = item.id === selectedId
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => selectItem(item.id)}
                        className={clsx(
                          'flex min-h-11 w-full items-start gap-2 border-b border-line px-3 py-3 text-left transition-colors',
                          active ? 'bg-accent-soft/50' : 'hover:bg-wash',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={selectedIds.has(item.id)}
                          disabled={flags.length > 0}
                          onChange={() => toggleSelect(item.id)}
                          onClick={e => e.stopPropagation()}
                          className="mt-1 h-5 w-5"
                          title={flags.length ? '有風險標記，不可批量' : '選取批量'}
                          aria-label={`選取 ${item.file_name}`}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-ink">{item.file_name}</p>
                          <p className="truncate text-sm text-muted">
                            {item.suggested_category || '未分類'}
                            {item.confidence_score != null && ` · ${Math.round(item.confidence_score * 100)}%`}
                          </p>
                          {flags.length > 0 && (
                            <p className="mt-1 flex flex-wrap gap-1">
                              {flags.map(f => (
                                <span key={f} className="chip-highlight">{f}</span>
                              ))}
                            </p>
                          )}
                        </div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </aside>

        {/* Column 2 — preview（手機步驟二：預覽） */}
        <section
          className={clsx(
            'min-h-0 flex-1 flex-col overflow-y-auto border-b border-line p-4 md:flex md:border-b-0 md:border-r md:p-6',
            mobileStep === 'preview' ? 'flex' : 'hidden',
          )}
        >
          {emptyQueue ? (
            <div className="flex h-full flex-col items-center justify-center text-center text-muted">
              <p className="text-sm font-medium text-ink">選取或佇列為空</p>
              <p className="mt-1 max-w-sm text-sm">左側有待審項目時，可在此預覽 AI 建議與風險旗標。</p>
            </div>
          ) : !selected ? (
            <p className="text-sm text-muted">選擇左側項目以預覽</p>
          ) : (
            <div className="space-y-4 animate-fade-in">
              <button
                type="button"
                onClick={() => setMobileStep('list')}
                className="btn-ghost -ml-3 md:hidden"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden /> 返回清單
              </button>
              <div>
                <h2 className="font-display text-lg font-semibold text-ink">{selected.file_name}</h2>
                <p className="mt-1 break-all font-mono text-xs text-muted">{selected.file_path}</p>
              </div>
              <div className="card p-4">
                <h3 className="text-sm font-semibold tracking-wide text-muted">AI 建議</h3>
                <p className="mt-2 text-sm text-ink">
                  {selected.suggested_category || '（未分類）'}
                  {selected.suggested_subcategory && ` › ${selected.suggested_subcategory}`}
                </p>
                {selected.confidence_score != null && (
                  <p className="mt-1 text-sm text-muted">
                    信心參考 {Math.round(selected.confidence_score * 100)}%（非正確率）
                  </p>
                )}
                {selected.reasoning && (
                  <p className="mt-3 text-sm leading-relaxed text-muted">
                    <span className="font-medium text-ink">判斷依據：</span>
                    {selected.reasoning}
                  </p>
                )}
              </div>
              {selected.related_documents?.length > 0 && (
                <div className="rounded-2xl border border-highlight/30 bg-highlight-soft p-4 text-sm">
                  <div className="flex items-center gap-2 font-medium text-highlight">
                    <AlertTriangle className="h-4 w-4" aria-hidden />
                    偵測到相關文件
                  </div>
                  <ul className="mt-2 space-y-1 text-highlight/80">
                    {selected.related_documents.map(r => (
                      <li key={r.id}>{r.file_name}</li>
                    ))}
                  </ul>
                </div>
              )}
              {selected.suggested_tags && Object.keys(selected.suggested_tags).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(selected.suggested_tags).map(([k, v]) => (
                    <span key={k} className="chip-neutral">
                      {k}: {v}
                    </span>
                  ))}
                </div>
              )}
              <button
                type="button"
                onClick={() => setMobileStep('decide')}
                className="btn-primary w-full md:hidden"
              >
                下一步：核准設定 <ArrowRight className="h-4 w-4" aria-hidden />
              </button>
            </div>
          )}
        </section>

        {/* Column 3 — actions（手機步驟三：決策） */}
        <aside
          className={clsx(
            'w-full flex-col bg-surface md:flex md:w-80',
            mobileStep === 'decide' ? 'flex flex-1' : 'hidden',
          )}
        >
          <div className="border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold text-ink">核准設定</h2>
            <p className="text-sm text-muted">確認分類與可見範圍後入庫</p>
          </div>
          {emptyQueue || !selected ? (
            <div className="pointer-events-none flex flex-1 flex-col gap-4 p-4 opacity-60" aria-disabled>
              <PermissionScope
                department={null}
                visibility="佇列為空或尚未選取項目時無法核准；僅 owner／admin 可操作審核。"
              />
              <button type="button" disabled className="btn-primary w-full">
                <CheckCircle className="h-4 w-4" aria-hidden />
                確認入庫
              </button>
              <button type="button" disabled className="btn-outline w-full text-danger">
                <XCircle className="h-4 w-4" aria-hidden /> 拒絕
              </button>
            </div>
          ) : (
            <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
              <button
                type="button"
                onClick={() => setMobileStep('preview')}
                className="btn-ghost -ml-3 self-start md:hidden"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden /> 返回預覽
              </button>
              <div>
                <label htmlFor="rev-cat" className="input-label">分類</label>
                <input
                  id="rev-cat"
                  value={category}
                  onChange={e => setCategory(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="rev-note" className="input-label">審核備註</label>
                <textarea
                  id="rev-note"
                  value={note}
                  onChange={e => setNote(e.target.value)}
                  rows={3}
                  className="input min-h-0 py-2"
                  placeholder="選填"
                />
              </div>
              <PermissionScope
                department={selected.suggested_subcategory || null}
                visibility="核准後依部門與角色可見；未授權者不會在問答中看到此內容"
                tags={category ? [category] : Object.values(selected.suggested_tags || {})}
              />
              <p className="rounded-xl bg-wash px-3 py-2 text-sm text-muted">
                核准後文件會進入處理 → 可搜尋。入庫完成後建議用測試提問驗證證據。
              </p>
              <div className="mt-auto space-y-2">
                <button
                  type="button"
                  disabled={acting}
                  onClick={() => {
                    if (category && category !== selected.suggested_category) modifyApprove()
                    else approve(selected.id)
                  }}
                  className="btn-primary w-full"
                >
                  {acting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle className="h-4 w-4" aria-hidden />}
                  確認入庫
                </button>
                <button
                  type="button"
                  disabled={acting}
                  onClick={() => setRejectOpen(true)}
                  className="btn-outline w-full text-danger hover:border-danger/40 hover:bg-danger-soft"
                >
                  <XCircle className="h-4 w-4" aria-hidden /> 拒絕
                </button>
                <Link
                  to={`/ask?q=${encodeURIComponent(`請說明與「${selected.file_name}」相關的重點`)}`}
                  className="btn-outline w-full"
                >
                  測試提問 <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
              </div>
            </div>
          )}
        </aside>

        <ConfirmDialog
          open={rejectOpen}
          danger
          busy={acting}
          title="拒絕此文件入庫？"
          description={selected ? `「${selected.file_name}」將不會進入可搜尋知識庫。` : ''}
          confirmLabel="確認拒絕"
          onCancel={() => !acting && setRejectOpen(false)}
          onConfirm={reject}
        />
        <ConfirmDialog
          open={batchOpen}
          busy={acting}
          title={`批量確認 ${selectedIds.size} 筆？`}
          description="僅應批量核准低風險、高信心且策略一致的項目。核准後將開始處理入庫。"
          confirmLabel="批量確認"
          onCancel={() => !acting && setBatchOpen(false)}
          onConfirm={batchApprove}
        />
      </div>
    </AsyncState>
  )
}
