/**
 * Phase 10 — 人工審核介面
 *
 * 設計原則：
 *   - 高信心度項目（≥0.8）列在上方，可批量確認
 *   - 低信心度項目（<0.6）單獨列出，強制逐一確認
 *   - 每筆顯示：原始檔名、AI 建議分類、標籤、信心分數、AI 判斷依據
 *   - 操作：同意 / 拒絕 / 修改後確認
 */

import { useState, useEffect, useCallback } from 'react'
import api from '../api'
import {
  CheckCircle,
  XCircle,
  Edit2,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Helpers ───────────────────────────────────────────────────────────────────

const ConfidenceBadge = ({ score }: { score: number | null }) => {
  if (score === null) return null
  const pct = Math.round(score * 100)
  const color =
    score >= 0.8
      ? 'bg-green-100 text-green-700'
      : score >= 0.6
      ? 'bg-yellow-100 text-yellow-700'
      : 'bg-red-100 text-red-700'
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', color)}>
      {pct}%
    </span>
  )
}

// ── Modify Modal ──────────────────────────────────────────────────────────────

function ModifyModal({
  item,
  onClose,
  onDone,
}: {
  item: ReviewItem
  onClose: () => void
  onDone: () => void
}) {
  const [category, setCategory] = useState(item.suggested_category || '')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    setSaving(true)
    try {
      await api.post(`/agent/review/${item.id}/modify`, { category, note })
      onDone()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">修改分類後確認</h2>
        <p className="mb-3 text-sm text-gray-500 truncate">{item.file_name}</p>

        <label className="mb-1 block text-sm font-medium text-gray-700">分類</label>
        <input
          value={category}
          onChange={e => setCategory(e.target.value)}
          className="mb-3 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        <label className="mb-1 block text-sm font-medium text-gray-700">審核備註（選填）</label>
        <textarea
          value={note}
          onChange={e => setNote(e.target.value)}
          rows={2}
          className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border px-4 py-2 text-sm hover:bg-gray-50">
            取消
          </button>
          <button
            onClick={submit}
            disabled={saving}
            className="flex items-center gap-1 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle className="h-4 w-4" />}
            確認入庫
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function ReviewItemRow({
  item,
  selected,
  expanded,
  onToggleSelect,
  onToggleExpand,
  onApprove,
  onReject,
  onModify,
}: {
  item: ReviewItem
  selected: boolean
  expanded: boolean
  onToggleSelect: () => void
  onToggleExpand: () => void
  onApprove: () => void
  onReject: () => void
  onModify: () => void
}) {
  return (
    <div
      className={clsx(
        'overflow-hidden rounded-xl border bg-white transition-all',
        selected && 'border-blue-400 ring-1 ring-blue-100'
      )}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          className="h-4 w-4 rounded border-gray-300"
        />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-gray-900">{item.file_name}</p>
          <p className="truncate text-sm text-gray-500">
            {item.suggested_category || '（未分類）'}
            {item.suggested_subcategory && ` › ${item.suggested_subcategory}`}
          </p>
        </div>
        <ConfidenceBadge score={item.confidence_score} />
        <div className="flex items-center gap-1">
          <button
            onClick={onApprove}
            className="rounded-lg p-1.5 text-green-600 hover:bg-green-50 transition-colors"
            title="確認入庫"
          >
            <CheckCircle className="h-5 w-5" />
          </button>
          <button
            onClick={onModify}
            className="rounded-lg p-1.5 text-blue-600 hover:bg-blue-50 transition-colors"
            title="修改後確認"
          >
            <Edit2 className="h-4 w-4" />
          </button>
          <button
            onClick={onReject}
            className="rounded-lg p-1.5 text-red-500 hover:bg-red-50 transition-colors"
            title="拒絕入庫"
          >
            <XCircle className="h-5 w-5" />
          </button>
          <button
            onClick={onToggleExpand}
            className="rounded-lg p-1.5 hover:bg-gray-100 transition-colors"
          >
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t bg-gray-50 px-4 py-3 text-sm text-gray-600">
          {item.reasoning && (
            <p className="mb-1">
              <span className="font-medium">AI 判斷依據：</span>
              {item.reasoning}
            </p>
          )}
          <p>
            <span className="font-medium">原始路徑：</span>
            <span className="font-mono text-xs">{item.file_path}</span>
          </p>
          {item.suggested_tags && Object.keys(item.suggested_tags).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.entries(item.suggested_tags).map(([k, v]) => (
                <span
                  key={k}
                  className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                >
                  {k}: {v}
                </span>
              ))}
            </div>
          )}
          {item.related_documents && item.related_documents.length > 0 && (
            <div className="mt-2">
              <p className="mb-1 text-xs font-medium text-amber-700">⚠ 偵測到相關文件（{item.related_documents.length} 筆）：</p>
              <div className="flex flex-wrap gap-1">
                {item.related_documents.map(rel => (
                  <span
                    key={rel.id}
                    className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700 border border-amber-200"
                    title={`match: ${rel.match}`}
                  >
                    📄 {rel.file_name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [modifyItem, setModifyItem] = useState<ReviewItem | null>(null)
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get<{ items: ReviewItem[]; total: number }>(
        '/agent/review?limit=100'
      )
      setItems(res.data.items)
      setTotal(res.data.total)
      setSelectedIds(new Set())
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const highConf = items.filter(i => (i.confidence_score ?? 0) >= 0.8)
  const lowConf = items.filter(i => (i.confidence_score ?? 0) < 0.8)

  const approve = async (id: string) => {
    setActing(true)
    try { await api.post(`/agent/review/${id}/approve`); await load() } finally { setActing(false) }
  }

  const reject = async (id: string) => {
    if (!confirm('確定拒絕此文件入庫？')) return
    setActing(true)
    try { await api.post(`/agent/review/${id}/reject`, { reason: '' }); await load() } finally { setActing(false) }
  }

  const batchApprove = async () => {
    if (!selectedIds.size) return
    setActing(true)
    try {
      await api.post('/agent/review/batch-approve', { item_ids: [...selectedIds] })
      await load()
    } finally {
      setActing(false)
    }
  }

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="flex h-full flex-col bg-gray-50">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">文件審核佇列</h1>
          <p className="text-sm text-gray-500">確認 AI 的分類提案，再入庫至知識庫</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 transition-colors"
          >
            <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          </button>
          {selectedIds.size > 0 && (
            <button
              onClick={batchApprove}
              disabled={acting}
              className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
            >
              {acting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle className="h-4 w-4" />
              )}
              批量確認（{selectedIds.size}）
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center rounded-xl border border-gray-200 bg-white py-16 text-gray-400">
            <CheckCircle className="mb-3 h-12 w-12 text-green-400" />
            <p className="font-medium">佇列是空的</p>
            <p className="mt-1 text-sm">所有文件已完成審核，或尚未啟動 Agent 掃描</p>
          </div>
        ) : (
          <div className="space-y-6">
            {/* 高信心度 */}
            {highConf.length > 0 && (
              <section>
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    高信心度 ≥ 80% — 可批量確認（{highConf.length}）
                  </h2>
                  <button
                    onClick={() =>
                      setSelectedIds(prev => {
                        const next = new Set(prev)
                        highConf.forEach(i => next.add(i.id))
                        return next
                      })
                    }
                    className="text-xs text-blue-600 hover:underline"
                  >
                    全選
                  </button>
                </div>
                <div className="space-y-2">
                  {highConf.map(item => (
                    <ReviewItemRow
                      key={item.id}
                      item={item}
                      selected={selectedIds.has(item.id)}
                      expanded={expandedId === item.id}
                      onToggleSelect={() => toggleSelect(item.id)}
                      onToggleExpand={() =>
                        setExpandedId(expandedId === item.id ? null : item.id)
                      }
                      onApprove={() => approve(item.id)}
                      onReject={() => reject(item.id)}
                      onModify={() => setModifyItem(item)}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* 低信心度 */}
            {lowConf.length > 0 && (
              <section>
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-orange-600">
                  需逐一確認（信心度 &lt; 80%）（{lowConf.length}）
                </h2>
                <div className="space-y-2">
                  {lowConf.map(item => (
                    <ReviewItemRow
                      key={item.id}
                      item={item}
                      selected={false}
                      expanded={expandedId === item.id}
                      onToggleSelect={() => {}}
                      onToggleExpand={() =>
                        setExpandedId(expandedId === item.id ? null : item.id)
                      }
                      onApprove={() => approve(item.id)}
                      onReject={() => reject(item.id)}
                      onModify={() => setModifyItem(item)}
                    />
                  ))}
                </div>
              </section>
            )}

            <p className="text-center text-xs text-gray-400">共 {total} 筆待審核</p>
          </div>
        )}
      </div>

      {modifyItem && (
        <ModifyModal
          item={modifyItem}
          onClose={() => setModifyItem(null)}
          onDone={load}
        />
      )}
    </div>
  )
}
