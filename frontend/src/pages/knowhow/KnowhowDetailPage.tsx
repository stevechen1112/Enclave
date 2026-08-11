/**
 * KnowhowDetailPage — 師傅經驗卡詳情。
 *
 * 步驟與注意事項用編號大列表呈現（現場邊做邊看）；草稿可送出審核。
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  AlertTriangle,
  ListOrdered,
  Loader2,
  Quote,
  Send,
  ShieldAlert,
  Pencil,
  Save,
  X,
  Archive,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { knowhowApi, type KnowhowCard } from '../../services/mka'

export default function KnowhowDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [card, setCard] = useState<KnowhowCard | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editSummary, setEditSummary] = useState('')
  const [editSteps, setEditSteps] = useState('')
  const [editCautions, setEditCautions] = useState('')
  const [saving, setSaving] = useState(false)
  const [retiring, setRetiring] = useState(false)

  useEffect(() => {
    if (!id) return
    knowhowApi
      .get(id)
      .then(setCard)
      .catch(() => setNotFound(true))
  }, [id])

  const startEditing = () => {
    if (!card) return
    setEditTitle(card.title)
    setEditSummary(card.summary || '')
    setEditSteps(card.steps.join('\n'))
    setEditCautions(card.cautions.join('\n'))
    setEditing(true)
  }

  const cancelEditing = () => {
    setEditing(false)
  }

  const handleSave = async () => {
    if (!card) return
    setSaving(true)
    try {
      const updated = await knowhowApi.update(card.id, card.version, {
        title: editTitle,
        summary: editSummary,
        steps: editSteps.split('\n').filter(s => s.trim()),
        cautions: editCautions.split('\n').filter(s => s.trim()),
      })
      setCard(updated)
      setEditing(false)
      toast.success('已儲存')
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      toast.error(status === 409 ? '卡片已被更新，請重新整理後再試' : '儲存失敗')
    } finally {
      setSaving(false)
    }
  }

  const handleSubmit = async () => {
    if (!card) return
    setSubmitting(true)
    try {
      await knowhowApi.submit(card.id, card.version)
      toast.success('已送出審核，核准後大家就查得到了')
      setCard({ ...card, status: 'pending_review' })
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      toast.error(status === 409 ? '卡片已被更新，請重新整理後再送' : '送出失敗，請再試一次')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRetire = async () => {
    if (!card) return
    if (!window.confirm('確定要退休這張知識卡嗎？退休後將不再出現在搜尋結果中。')) return
    setRetiring(true)
    try {
      const updated = await knowhowApi.retire(card.id)
      setCard(updated)
      toast.success('已退休')
    } catch {
      toast.error('退休失敗')
    } finally {
      setRetiring(false)
    }
  }

  if (notFound) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <p className="text-xl font-bold text-ink">找不到這張經驗卡</p>
        <button
          type="button"
          onClick={() => navigate('/knowhow')}
          className="min-h-14 rounded-xl bg-accent px-8 text-lg font-bold text-white"
        >
          回經驗庫
        </button>
      </div>
    )
  }

  if (!card) {
    return (
      <div className="flex h-full items-center justify-center" role="status">
        <Loader2 className="h-10 w-10 animate-spin text-accent" aria-label="載入中" />
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col gap-4 overflow-y-auto p-4 pb-8">
      <header className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/knowhow')}
          aria-label="回上一頁"
          className="rounded-xl border-2 border-line p-3 text-muted hover:bg-wash"
        >
          <ArrowLeft className="h-6 w-6" aria-hidden />
        </button>
        <h1 className="flex-1 text-2xl font-bold text-ink">
          {editing ? (
            <input
              type="text"
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              className="w-full rounded-lg border-2 border-line bg-white px-3 py-2 text-2xl font-bold"
              aria-label="知識卡標題"
            />
          ) : (
            card.title
          )}
        </h1>
        {!editing && card.status === 'draft' && (
          <button
            type="button"
            onClick={startEditing}
            className="rounded-xl border-2 border-line p-3 text-muted hover:bg-wash"
            aria-label="編輯"
          >
            <Pencil className="h-6 w-6" aria-hidden />
          </button>
        )}
        {!editing && card.status === 'approved' && (
          <button
            type="button"
            onClick={handleRetire}
            disabled={retiring}
            className="rounded-xl border-2 border-amber-400 p-3 text-amber-600 hover:bg-amber-50 disabled:opacity-50"
            aria-label="退休"
          >
            {retiring ? <Loader2 className="h-6 w-6 animate-spin" aria-hidden /> : <Archive className="h-6 w-6" aria-hidden />}
          </button>
        )}
      </header>

      {card.risk_level === 'high' && (
        <p className="flex items-center gap-2 rounded-xl border-2 border-danger/50 bg-red-50 px-4 py-3 text-lg font-bold text-danger">
          <ShieldAlert className="h-6 w-6 shrink-0" aria-hidden />
          高風險作業：請確認已受過訓練再操作
        </p>
      )}

      {editing ? (
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-lg font-bold text-ink">摘要</span>
            <textarea
              value={editSummary}
              onChange={e => setEditSummary(e.target.value)}
              className="min-h-20 rounded-lg border-2 border-line bg-white px-3 py-2 text-lg"
              rows={3}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-lg font-bold text-ink">做法步驟（一行一步驟）</span>
            <textarea
              value={editSteps}
              onChange={e => setEditSteps(e.target.value)}
              className="min-h-32 rounded-lg border-2 border-line bg-white px-3 py-2 text-lg"
              rows={6}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-lg font-bold text-ink">注意事項（一行一項）</span>
            <textarea
              value={editCautions}
              onChange={e => setEditCautions(e.target.value)}
              className="min-h-20 rounded-lg border-2 border-line bg-white px-3 py-2 text-lg"
              rows={4}
            />
          </label>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-accent py-4 text-lg font-bold text-white hover:bg-accent-hover disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-6 w-6 animate-spin" aria-hidden /> : <Save className="h-6 w-6" aria-hidden />}
              儲存
            </button>
            <button
              type="button"
              onClick={cancelEditing}
              disabled={saving}
              className="flex items-center justify-center gap-2 rounded-xl border-2 border-line bg-white px-6 py-4 text-lg font-bold text-muted hover:bg-wash disabled:opacity-50"
            >
              <X className="h-6 w-6" aria-hidden />
              取消
            </button>
          </div>
        </div>
      ) : (
        <>
          {card.summary && (
            <p className="rounded-xl bg-surface px-4 py-3 text-lg leading-relaxed text-ink shadow-sm">
              {card.summary}
            </p>
          )}

          {card.steps.length > 0 && (
        <section aria-label="做法步驟" className="rounded-2xl border-2 border-line bg-surface p-5">
          <h2 className="mb-3 flex items-center gap-2 text-xl font-bold text-ink">
            <ListOrdered className="h-6 w-6 text-accent" aria-hidden />
            做法步驟
          </h2>
          <ol className="flex flex-col gap-3">
            {card.steps.map((step, i) => (
              <li key={i} className="flex gap-3 text-lg leading-relaxed text-ink">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-lg font-bold text-white">
                  {i + 1}
                </span>
                <span className="pt-1">{step}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {card.cautions.length > 0 && (
        <section aria-label="注意事項" className="rounded-2xl border-2 border-amber-400 bg-amber-50 p-5">
          <h2 className="mb-3 flex items-center gap-2 text-xl font-bold text-amber-900">
            <AlertTriangle className="h-6 w-6" aria-hidden />
            注意事項
          </h2>
          <ul className="list-disc space-y-2 pl-6 text-lg text-amber-900">
            {card.cautions.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </section>
      )}

      {card.source_quotes.length > 0 && (
        <section aria-label="師傅原話" className="rounded-2xl border-2 border-line bg-surface p-5">
          <h2 className="mb-3 flex items-center gap-2 text-xl font-bold text-ink">
            <Quote className="h-6 w-6 text-accent" aria-hidden />
            師傅原話
          </h2>
          {card.source_quotes.map((q, i) => (
            <blockquote key={i} className="mb-2 border-l-4 border-accent/40 pl-3 text-lg italic text-muted">
              {q}
            </blockquote>
          ))}
        </section>
      )}

      {card.status === 'draft' && (
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting}
          className="flex min-h-16 items-center justify-center gap-2 rounded-xl bg-accent text-xl font-bold text-white hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50"
        >
          {submitting ? (
            <Loader2 className="h-7 w-7 animate-spin" aria-hidden />
          ) : (
            <Send className="h-7 w-7" aria-hidden />
          )}
          送出審核，讓大家都能查
        </button>
      )}
        </>
      )}
    </div>
  )
}
