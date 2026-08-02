import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Layers, Loader2, Plus, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { kbApi } from '../../api'

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
  const [loading, setLoading] = useState(true)
  const [gaps, setGaps] = useState<KnowledgeGap[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [newName, setNewName] = useState('')
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [g, c] = await Promise.all([
        kbApi.listGaps('open'),
        kbApi.listCategories(true),
      ])
      setGaps(g)
      setCategories(c)
    } catch {
      toast.error('無法載入知識品質資料')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleScan = async () => {
    try {
      await kbApi.scanGaps(7)
      toast.success('結構化缺口掃描已排程')
      setTimeout(load, 2000)
    } catch {
      toast.error('排程失敗')
    }
  }

  const handleResolve = async (id: string) => {
    try {
      await kbApi.resolveGap(id, { resolve_note: '已標記解決' })
      toast.success('已標記解決')
      load()
    } catch {
      toast.error('操作失敗')
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
    } catch {
      toast.error('新增失敗')
    } finally {
      setAdding(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-7 w-7 animate-spin text-muted" />
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-4xl space-y-8">
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-ink">結構化缺口</h2>
              <p className="text-sm text-muted">
                系統掃描出的知識覆蓋缺口（與「未答覆問題」不同，後者在治理 → 問答品質）。
              </p>
            </div>
            <button
              type="button"
              onClick={handleScan}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm text-white hover:bg-accent-hover"
            >
              <Search className="h-4 w-4" /> 掃描
            </button>
          </div>
          {gaps.length === 0 ? (
            <div className="rounded-xl border border-line bg-surface p-8 text-center text-muted">
              <CheckCircle2 className="mx-auto mb-2 h-10 w-10 text-emerald-400" />
              <p className="text-sm">目前沒有待處理的結構化缺口</p>
            </div>
          ) : (
            <div className="divide-y rounded-xl border border-line bg-surface">
              {gaps.map(g => (
                <div key={g.id} className="flex items-start gap-3 p-4">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink">{g.query_text}</p>
                    <p className="mt-1 text-xs text-muted">
                      相關度參考 {(g.confidence_score * 100).toFixed(0)}%
                      {g.suggested_topic && ` · 主題：${g.suggested_topic}`}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleResolve(g.id)}
                    className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:text-ink"
                  >
                    標記解決
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-ink">分類</h2>
          </div>
          <div className="flex gap-2">
            <input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="新分類名稱"
              className="flex-1 rounded-lg border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
            <button
              type="button"
              disabled={adding || !newName.trim()}
              onClick={handleAddCategory}
              className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-2 text-sm text-white hover:bg-accent-hover disabled:opacity-50"
            >
              <Plus className="h-4 w-4" /> 新增
            </button>
          </div>
          {categories.length === 0 ? (
            <p className="rounded-xl border border-line bg-surface p-8 text-center text-sm text-muted">
              <Layers className="mx-auto mb-2 h-10 w-10 text-line" />
              尚無分類
            </p>
          ) : (
            <ul className="divide-y rounded-xl border border-line bg-surface">
              {categories.map(c => (
                <li key={c.id} className="px-4 py-3 text-sm">
                  <p className="font-medium text-ink">{c.name}</p>
                  {c.description && <p className="text-xs text-muted">{c.description}</p>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
