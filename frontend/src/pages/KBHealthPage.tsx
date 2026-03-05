/**
 * KBHealthPage — Phase 13 Knowledge Base Health Dashboard
 *
 * P13-3: Stale documents, index coverage, top queries, knowledge gaps
 * P13-4: Knowledge gap list + resolve
 * P13-6: Integrity check trigger + report list
 * P13-7: Backup management
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Loader2, HeartPulse, AlertTriangle, FileWarning, ShieldCheck,
  Database, RefreshCw, Archive, Search, CheckCircle2, Clock,
  HardDrive, Layers, Plus, Pencil, Trash2, ChevronRight, ExternalLink,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { kbApi } from '../api'

/* ── Types (mirrors backend schemas) ─────────────────────────────── */
interface StaleDoc {
  id: string; filename: string; file_type: string | null
  status: string; days_since_update: number; department_name: string | null
}
interface TopQuery { query_text: string; count: number; avg_confidence?: number }
interface KBHealth {
  total_documents: number; completed_documents: number
  failed_documents: number; stale_documents: number
  stale_threshold_days: number; index_coverage_pct: number
  avg_confidence_7d: number | null
  stale_document_list: StaleDoc[]
  top_queries: TopQuery[]; recent_gaps: number
}
interface KnowledgeGap {
  id: string; query_text: string; confidence_score: number
  suggested_topic: string | null; status: string
  created_at: string | null
}
interface IntegrityReport {
  id: string; status: string; total_documents: number; total_chunks: number
  orphan_chunks: number; missing_embeddings: number
  failed_documents: number; stale_documents: number
  started_at: string | null; completed_at: string | null
}
interface Backup {
  id: string; backup_type: string; status: string
  file_size_bytes: number | null; document_count: number | null
  chunk_count: number | null; started_at: string | null
  completed_at: string | null; error_message: string | null
}
interface Category {
  id: string; name: string; description: string | null
  parent_id: string | null; sort_order: number; is_active: boolean
  created_at: string | null
}

/* ── KPI Card ────────────────────────────────────────────────────── */
function KPICard({ icon: Icon, label, value, sub, color = 'blue' }: {
  icon: React.ElementType; label: string; value: string | number
  sub?: string; color?: string
}) {
  const cls: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    red: 'bg-red-50 text-red-600',
    yellow: 'bg-yellow-50 text-yellow-600',
    purple: 'bg-purple-50 text-purple-600',
  }
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center gap-3 mb-2">
        <div className={`rounded-lg p-2 ${cls[color] ?? cls.blue}`}>
          <Icon className="h-5 w-5" />
        </div>
        <span className="text-sm text-gray-500">{label}</span>
      </div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

/* ── Main Page ───────────────────────────────────────────────────── */
export default function KBHealthPage() {
  const [loading, setLoading] = useState(true)
  const [health, setHealth] = useState<KBHealth | null>(null)
  const [gaps, setGaps] = useState<KnowledgeGap[]>([])
  const [reports, setReports] = useState<IntegrityReport[]>([])
  const [backups, setBackups] = useState<Backup[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [tab, setTab] = useState<'overview' | 'gaps' | 'integrity' | 'backups' | 'categories'>('overview')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [h, g, r, b, cats] = await Promise.all([
        kbApi.health(),
        kbApi.listGaps('open'),
        kbApi.listIntegrityReports(5),
        kbApi.listBackups(10),
        kbApi.listCategories(true),
      ])
      setHealth(h); setGaps(g); setReports(r); setBackups(b); setCategories(cats)
    } catch { toast.error('載入失敗') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    )
  }

  if (!health) return null

  const tabs = [
    { key: 'overview' as const, label: '總覽', icon: HeartPulse },
    { key: 'gaps' as const, label: `知識缺口 (${gaps.length})`, icon: AlertTriangle },
    { key: 'integrity' as const, label: '完整性檢查', icon: ShieldCheck },
    { key: 'backups' as const, label: '備份管理', icon: Archive },
    { key: 'categories' as const, label: `分類管理 (${categories.length})`, icon: Layers },
  ]

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-4 md:p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">知識庫健康度儀表板</h1>
            <p className="text-sm text-gray-500">Phase 13 — 主動維護與監控</p>
          </div>
          <button onClick={load} className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100">
            <RefreshCw className="h-4 w-4" /> 重新整理
          </button>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <KPICard icon={Database} label="總文件數" value={health.total_documents} color="blue" />
          <KPICard icon={CheckCircle2} label="索引覆蓋率" value={`${health.index_coverage_pct}%`} color="green"
            sub={`${health.completed_documents} / ${health.total_documents} 完成`} />
          <KPICard icon={FileWarning} label="過期文件" value={health.stale_documents} color="yellow"
            sub={`超過 ${health.stale_threshold_days} 天未更新`} />
          <KPICard icon={AlertTriangle} label="知識缺口" value={health.recent_gaps} color="red"
            sub="待處理" />
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b">
          {tabs.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition ${
                tab === t.key ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <t.icon className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {tab === 'overview' && <OverviewTab health={health} />}
        {tab === 'gaps' && <GapsTab gaps={gaps} onReload={load} />}
        {tab === 'integrity' && <IntegrityTab reports={reports} onReload={load} />}
        {tab === 'backups' && <BackupsTab backups={backups} onReload={load} />}
        {tab === 'categories' && <CategoriesTab categories={categories} onReload={load} />}
      </div>
    </div>
  )
}

/* ═══════ Overview Tab ═══════ */
function OverviewTab({ health }: { health: KBHealth }) {
  const navigate = useNavigate()
  return (
    <div className="space-y-6">
      {/* Stale Documents */}
      {health.stale_document_list.length > 0 && (
        <div className="rounded-xl border bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Clock className="h-4 w-4 text-yellow-600" /> 過期文件（超過 {health.stale_threshold_days} 天未更新）
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-gray-500 border-b">
                <th className="pb-2 font-medium">檔名</th>
                <th className="pb-2 font-medium">類型</th>
                <th className="pb-2 font-medium">部門</th>
                <th className="pb-2 font-medium text-right">天數</th>
              </tr></thead>
              <tbody>
                {health.stale_document_list.map(d => (
                  <tr key={d.id} className="border-b last:border-0">
                    <td className="py-2 max-w-[200px] truncate">{d.filename}</td>
                    <td className="py-2 text-gray-500">{d.file_type ?? '-'}</td>
                    <td className="py-2 text-gray-500">{d.department_name ?? '-'}</td>
                    <td className="py-2 text-right font-mono text-yellow-700">{d.days_since_update} 天</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Top Queries — link to unified analytics page */}
      {health.top_queries.length > 0 && (
        <div className="rounded-xl border bg-white p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <Search className="h-4 w-4 text-blue-600" /> 最常被問的問題
            </h3>
            <button onClick={() => navigate('/query-analytics')}
              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline">
              查看完整分析 <ExternalLink className="h-3 w-3" />
            </button>
          </div>
          <div className="space-y-1">
            {health.top_queries.slice(0, 5).map((q, i) => (
              <div key={i} className="flex items-center gap-3 py-1.5 border-b last:border-0">
                <span className="w-6 text-right text-xs font-mono text-gray-400">{i + 1}</span>
                <span className="flex-1 text-sm text-gray-700 truncate">{q.query_text}</span>
                <span className="text-xs font-mono text-gray-500">{q.count} 次</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Confidence */}
      {health.avg_confidence_7d != null && (
        <div className="rounded-xl border bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-1">7 日平均信心分數</h3>
          <p className="text-3xl font-bold text-blue-600">{(health.avg_confidence_7d * 100).toFixed(1)}%</p>
        </div>
      )}
    </div>
  )
}

/* ═══════ Gaps Tab ═══════ */
function GapsTab({ gaps, onReload }: { gaps: KnowledgeGap[]; onReload: () => void }) {
  const handleScan = async () => {
    try {
      await kbApi.scanGaps(7)
      toast.success('知識缺口掃描已排程')
      setTimeout(onReload, 2000)
    } catch { toast.error('排程失敗') }
  }

  const handleResolve = async (id: string) => {
    try {
      await kbApi.resolveGap(id, { resolve_note: '已標記解決' })
      toast.success('已標記為已解決')
      onReload()
    } catch { toast.error('操作失敗') }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={handleScan} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700">
          <Search className="h-4 w-4" /> 立即掃描
        </button>
      </div>
      {gaps.length === 0 ? (
        <div className="rounded-xl border bg-white p-8 text-center text-gray-400">
          <CheckCircle2 className="mx-auto h-12 w-12 text-green-300 mb-2" />
          目前沒有待處理的知識缺口
        </div>
      ) : (
        <div className="rounded-xl border bg-white divide-y">
          {gaps.map(g => (
            <div key={g.id} className="p-4 flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-800 line-clamp-2">{g.query_text}</p>
                <p className="text-xs text-gray-400 mt-1">
                  信心度 {(g.confidence_score * 100).toFixed(1)}%
                  {g.suggested_topic && ` · 主題: ${g.suggested_topic}`}
                  {g.created_at && ` · ${new Date(g.created_at).toLocaleDateString()}`}
                </p>
              </div>
              <button onClick={() => handleResolve(g.id)}
                className="shrink-0 rounded-lg border px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50">
                標記解決
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ═══════ Integrity Tab ═══════ */
function IntegrityTab({ reports, onReload }: { reports: IntegrityReport[]; onReload: () => void }) {
  const handleScan = async () => {
    try {
      await kbApi.triggerIntegrityCheck()
      toast.success('完整性檢查已排程')
      setTimeout(onReload, 3000)
    } catch { toast.error('排程失敗') }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={handleScan} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700">
          <ShieldCheck className="h-4 w-4" /> 立即檢查
        </button>
      </div>
      {reports.length === 0 ? (
        <div className="rounded-xl border bg-white p-8 text-center text-gray-400">尚無掃描報告</div>
      ) : (
        <div className="space-y-3">
          {reports.map(r => (
            <div key={r.id} className="rounded-xl border bg-white p-5">
              <div className="flex items-center justify-between mb-3">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                  r.status === 'completed' ? 'bg-green-100 text-green-700' :
                  r.status === 'running' ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-700'
                }`}>{r.status}</span>
                <span className="text-xs text-gray-400">{r.started_at ? new Date(r.started_at).toLocaleString() : ''}</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div><span className="text-gray-500">文件數</span><p className="font-semibold">{r.total_documents}</p></div>
                <div><span className="text-gray-500">Chunk 數</span><p className="font-semibold">{r.total_chunks}</p></div>
                <div><span className="text-gray-500">孤立 Chunk</span><p className={`font-semibold ${r.orphan_chunks > 0 ? 'text-red-600' : ''}`}>{r.orphan_chunks}</p></div>
                <div><span className="text-gray-500">缺失向量</span><p className={`font-semibold ${r.missing_embeddings > 0 ? 'text-red-600' : ''}`}>{r.missing_embeddings}</p></div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ═══════ Categories Tab ═══════ */
function CategoriesTab({ categories, onReload }: { categories: Category[]; onReload: () => void }) {
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [adding, setAdding] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [saving, setSaving] = useState(false)

  const handleAdd = async () => {
    if (!newName.trim()) return
    setSaving(true)
    try {
      await kbApi.createCategory({ name: newName.trim(), description: newDesc.trim() || undefined })
      toast.success('分類已新增')
      setNewName(''); setNewDesc(''); setAdding(false)
      onReload()
    } catch { toast.error('新增失敗') }
    finally { setSaving(false) }
  }

  const handleSaveEdit = async (id: string) => {
    setSaving(true)
    try {
      await kbApi.updateCategory(id, { name: editName.trim(), description: editDesc.trim() || null })
      toast.success('已更新')
      setEditId(null)
      onReload()
    } catch { toast.error('更新失敗') }
    finally { setSaving(false) }
  }

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`確定刪除分類「${name}」？`)) return
    try {
      await kbApi.deleteCategory(id)
      toast.success('已刪除')
      onReload()
    } catch { toast.error('刪除失敗') }
  }

  const startEdit = (cat: Category) => {
    setEditId(cat.id); setEditName(cat.name); setEditDesc(cat.description ?? '')
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => setAdding(a => !a)}
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700">
          <Plus className="h-4 w-4" /> 新增分類
        </button>
      </div>

      {adding && (
        <div className="rounded-xl border bg-white p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-700">新增知識庫分類</h3>
          <input value={newName} onChange={e => setNewName(e.target.value)}
            placeholder="分類名稱 *"
            className="w-full text-sm border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300" />
          <input value={newDesc} onChange={e => setNewDesc(e.target.value)}
            placeholder="說明（選填）"
            className="w-full text-sm border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300" />
          <div className="flex justify-end gap-2">
            <button onClick={() => setAdding(false)}
              className="px-3 py-1.5 text-sm border rounded-lg hover:bg-gray-50">取消</button>
            <button onClick={handleAdd} disabled={saving || !newName.trim()}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {saving ? '儲存中…' : '新增'}
            </button>
          </div>
        </div>
      )}

      {categories.length === 0 ? (
        <div className="rounded-xl border bg-white p-8 text-center text-gray-400">
          <Layers className="mx-auto h-12 w-12 text-gray-200 mb-2" />
          尚無分類，點擊「新增分類」建立第一個
        </div>
      ) : (
        <div className="rounded-xl border bg-white divide-y">
          {categories.map(cat => (
            <div key={cat.id} className="p-4">
              {editId === cat.id ? (
                <div className="space-y-2">
                  <input value={editName} onChange={e => setEditName(e.target.value)}
                    className="w-full text-sm border rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300" />
                  <input value={editDesc} onChange={e => setEditDesc(e.target.value)}
                    placeholder="說明（選填）"
                    className="w-full text-sm border rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300" />
                  <div className="flex gap-2">
                    <button onClick={() => setEditId(null)}
                      className="px-3 py-1 text-xs border rounded-lg hover:bg-gray-50">取消</button>
                    <button onClick={() => handleSaveEdit(cat.id)} disabled={saving}
                      className="px-3 py-1 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                      {saving ? '儲存…' : '儲存'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3">
                  <ChevronRight className="h-4 w-4 text-gray-400 mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800">{cat.name}
                      {!cat.is_active && <span className="ml-2 text-xs bg-gray-100 text-gray-500 px-1.5 rounded">停用</span>}
                    </p>
                    {cat.description && <p className="text-xs text-gray-400 mt-0.5">{cat.description}</p>}
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button onClick={() => startEdit(cat)}
                      className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button onClick={() => handleDelete(cat.id, cat.name)}
                      className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ═══════ Backups Tab ═══════ */
function BackupsTab({ backups, onReload }: { backups: Backup[]; onReload: () => void }) {
  const [restoring, setRestoring] = useState<string | null>(null)

  const handleBackup = async () => {
    try {
      await kbApi.createBackup('full')
      toast.success('備份已排程，稍後可在列表中查看')
      setTimeout(onReload, 3000)
    } catch { toast.error('排程失敗') }
  }

  const handleRestore = async (id: string) => {
    if (!confirm('確定要還原此備份？這將覆蓋現有資料。')) return
    setRestoring(id)
    try {
      await kbApi.restore(id)
      toast.success('還原已排程')
      setTimeout(onReload, 3000)
    } catch { toast.error('還原失敗') }
    finally { setRestoring(null) }
  }

  const fmtSize = (bytes: number | null) => {
    if (!bytes) return '-'
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={handleBackup} className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700">
          <HardDrive className="h-4 w-4" /> 立即備份
        </button>
      </div>
      {backups.length === 0 ? (
        <div className="rounded-xl border bg-white p-8 text-center text-gray-400">尚無備份記錄</div>
      ) : (
        <div className="rounded-xl border bg-white divide-y">
          {backups.map(b => (
            <div key={b.id} className="p-4 flex items-center gap-4">
              <Archive className={`h-5 w-5 shrink-0 ${b.status === 'completed' ? 'text-green-500' : b.status === 'running' ? 'text-blue-500' : 'text-red-500'}`} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800">
                  {b.backup_type === 'full' ? '完整備份' : '增量備份'}
                  <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
                    b.status === 'completed' ? 'bg-green-100 text-green-700' :
                    b.status === 'running' ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-700'
                  }`}>{b.status}</span>
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {b.started_at ? new Date(b.started_at).toLocaleString() : ''}
                  {b.document_count != null && ` · ${b.document_count} 文件`}
                  {b.chunk_count != null && ` · ${b.chunk_count} chunks`}
                  {` · ${fmtSize(b.file_size_bytes)}`}
                </p>
              </div>
              {b.status === 'completed' && (
                <button onClick={() => handleRestore(b.id)} disabled={restoring === b.id}
                  className="shrink-0 rounded-lg border px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                  {restoring === b.id ? '還原中…' : '還原'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
