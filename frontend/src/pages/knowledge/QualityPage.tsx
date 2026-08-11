import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Layers, Plus, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { kbApi, parseApiError, type ApiErrorInfo } from '../../api'
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [gaps, setGaps] = useState<KnowledgeGap[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [newName, setNewName] = useState('')
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [g, c] = await Promise.all([
        kbApi.listGaps('open'),
        kbApi.listCategories(true),
      ])
      setGaps(g)
      setCategories(c)
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
