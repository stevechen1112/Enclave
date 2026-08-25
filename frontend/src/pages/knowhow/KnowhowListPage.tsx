/**
 * KnowhowListPage — 師傅經驗庫列表。
 *
 * 設計對象：現場人員查「老師傅怎麼做」。狀態用中文徽章＋顏色雙重編碼；
 * 已核准的卡片排在最前面（後端依更新時間排序）。
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, ChevronRight, Loader2, Mic, PenLine } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { knowhowApi, type KnowhowCard } from '../../services/mka'
import { useCanAuthorKnowhow } from '../../navigation/useKnowhowPermissions'

const STATUS_META: Record<string, { label: string; className: string }> = {
  approved: { label: '已核准', className: 'bg-accent/15 text-accent border-accent/40' },
  draft: { label: '草稿', className: 'bg-wash text-muted border-line' },
  pending_review: { label: '審核中', className: 'bg-amber-50 text-amber-700 border-amber-300' },
  rejected: { label: '已退回', className: 'bg-red-50 text-danger border-danger/40' },
  retired: { label: '已停用', className: 'bg-wash text-muted border-line' },
}

const RISK_LABELS: Record<string, string> = {
  low: '低風險',
  medium: '中風險',
  high: '高風險',
}

export default function KnowhowListPage() {
  const navigate = useNavigate()
  const canAuthor = useCanAuthorKnowhow()
  const [cards, setCards] = useState<KnowhowCard[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')

  useEffect(() => {
    knowhowApi
      .list()
      .then(setCards)
      .catch(() => {
        setCards([])
        toast.error('經驗庫載入失敗，請稍後再試')
      })
  }, [])

  const handleCreate = async () => {
    if (!newTitle.trim()) return
    try {
      const card = await knowhowApi.create({ title: newTitle.trim() })
      toast.success('已建立草稿，請補上做法步驟')
      navigate(`/knowhow/${card.id}`)
    } catch {
      toast.error('建立失敗，請再試一次')
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col gap-4 overflow-y-auto p-4 pb-8">
      <header className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/job')}
          aria-label="回上一頁"
          className="rounded-xl border-2 border-line p-3 text-muted hover:bg-wash"
        >
          <ArrowLeft className="h-6 w-6" aria-hidden />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-ink">師傅經驗庫</h1>
          <p className="text-base text-muted">老師傅留下的做法與注意事項。</p>
        </div>
      </header>

      {canAuthor && (
        <button
          type="button"
          onClick={() => navigate('/knowhow/interview')}
          className="flex min-h-20 items-center gap-3 rounded-2xl bg-accent px-5 text-left text-white shadow-sm hover:bg-accent-hover active:scale-[0.99]"
        >
          <Mic className="h-8 w-8 shrink-0" aria-hidden />
          <span>
            <span className="block text-xl font-bold">開始師傅訪談</span>
            <span className="mt-1 block text-base text-white/85">
              手機直接錄音，系統分段保存、轉成逐字稿，再整理成知識草稿
            </span>
          </span>
        </button>
      )}

      {canAuthor && (creating ? (
        <div className="flex flex-col gap-3 rounded-2xl border-2 border-accent bg-surface p-5">
          <label htmlFor="new-card-title" className="text-lg font-semibold text-ink">
            這個經驗的主題是什麼？
          </label>
          <input
            id="new-card-title"
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            placeholder="例如：CNC 車床換刀校正"
            className="min-h-16 rounded-xl border-2 border-line bg-wash px-4 text-xl text-ink focus:border-accent focus:outline-none"
          />
          <div className="flex gap-3">
            <button
              type="button"
              onClick={handleCreate}
              disabled={!newTitle.trim()}
              className="min-h-14 flex-1 rounded-xl bg-accent text-lg font-bold text-white hover:bg-accent-hover disabled:opacity-50"
            >
              建立
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="min-h-14 rounded-xl border-2 border-line px-5 text-lg font-bold text-muted"
            >
              取消
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="flex min-h-14 items-center justify-center gap-2 rounded-xl border-2 border-dashed border-line text-lg font-bold text-muted hover:border-accent hover:bg-accent/5 hover:text-accent active:scale-[0.99]"
        >
          <PenLine className="h-6 w-6" aria-hidden />
          手動建立經驗卡
        </button>
      ))}

      {cards === null && (
        <div className="flex flex-1 items-center justify-center" role="status">
          <Loader2 className="h-10 w-10 animate-spin text-accent" aria-label="載入中" />
        </div>
      )}

      {cards !== null && cards.length === 0 && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
          <BookOpen className="h-16 w-16 text-line" aria-hidden />
          <p className="text-xl font-bold text-ink">還沒有經驗卡片</p>
          <p className="text-lg text-muted">
            {canAuthor
              ? '可直接開始師傅訪談，或手動建立一張經驗卡。'
              : '目前沒有可查看的已核准經驗卡。'}
          </p>
        </div>
      )}

      {cards?.map(card => {
        const meta = STATUS_META[card.status] || STATUS_META.draft
        return (
          <button
            key={card.id}
            type="button"
            onClick={() => navigate(`/knowhow/${card.id}`)}
            className="flex min-h-20 w-full items-center justify-between gap-3 rounded-2xl border-2 border-line bg-surface px-5 text-left shadow-sm hover:border-accent active:scale-[0.99]"
          >
            <div className="min-w-0">
              <p className="truncate text-xl font-bold text-ink">{card.title}</p>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span
                  className={clsx(
                    'rounded-full border px-3 py-0.5 text-base font-semibold',
                    meta.className,
                  )}
                >
                  {meta.label}
                </span>
                <span className="text-base text-muted">
                  {RISK_LABELS[card.risk_level] || card.risk_level}
                </span>
                {card.equipment_ids.length > 0 && (
                  <span className="text-base text-muted">設備：{card.equipment_ids[0]}</span>
                )}
              </div>
            </div>
            <ChevronRight className="h-7 w-7 shrink-0 text-muted" aria-hidden />
          </button>
        )
      })}
    </div>
  )
}
