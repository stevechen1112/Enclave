/**
 * UsageReportPage — Phase 13-8 Usage Statistics Report
 *
 * Period selector (7/30/90 days), KPI cards, department breakdown,
 * top documents ranking, top queries ranking.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Loader2, BarChart3, Users, MessageSquare, Cpu, FileText,
  Search, RefreshCw, Building2,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import toast from 'react-hot-toast'
import { kbApi } from '../api'

/* ── Types ───────────────────────────────────────────────────────── */
interface DeptUsage {
  department_name: string; query_count: number
  generate_count: number; total_tokens: number; active_users: number
}
interface TopDoc { document_id: string; filename: string; query_hit_count: number }
interface TopQuery { query_text: string; count: number }
interface UsageReport {
  period_start: string; period_end: string
  total_queries: number; total_generations: number
  total_tokens: number; active_users: number
  department_breakdown: DeptUsage[]
  top_documents: TopDoc[]; top_queries: TopQuery[]
}

/* ── KPI Card ────────────────────────────────────────────────────── */
function KPICard({ icon: Icon, label, value, color = 'blue' }: {
  icon: React.ElementType; label: string; value: string | number; color?: string
}) {
  const cls: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
    orange: 'bg-orange-50 text-orange-600',
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
    </div>
  )
}

/* ── Period Options ──────────────────────────────────────────────── */
const PERIODS = [
  { days: 7, label: '7 天' },
  { days: 30, label: '30 天' },
  { days: 90, label: '90 天' },
]

/* ── Main Page ───────────────────────────────────────────────────── */
export default function UsageReportPage() {
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)
  const [report, setReport] = useState<UsageReport | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await kbApi.usageReport(days)
      setReport(data)
    } catch { toast.error('載入失敗') }
    finally { setLoading(false) }
  }, [days])

  useEffect(() => { load() }, [load])

  const fmtNum = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n)

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    )
  }
  if (!report) return null

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-4 md:p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold text-gray-900">使用統計報告</h1>
            <p className="text-sm text-gray-500">Phase 13-8 — 查詢、生成、Token、部門細分</p>
          </div>
          <div className="flex items-center gap-2">
            {PERIODS.map(p => (
              <button key={p.days} onClick={() => setDays(p.days)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  days === p.days ? 'bg-blue-600 text-white' : 'border text-gray-600 hover:bg-gray-100'
                }`}
              >{p.label}</button>
            ))}
            <button onClick={load} className="ml-2 flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100">
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <KPICard icon={MessageSquare} label="總查詢數" value={fmtNum(report.total_queries)} color="blue" />
          <KPICard icon={Cpu} label="總生成次數" value={fmtNum(report.total_generations)} color="purple" />
          <KPICard icon={BarChart3} label="Token 使用量" value={fmtNum(report.total_tokens)} color="orange" />
          <KPICard icon={Users} label="活躍使用者" value={report.active_users} color="green" />
        </div>

        {/* Department Breakdown Chart + Table */}
        {report.department_breakdown.length > 0 && (
          <div className="rounded-xl border bg-white p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
              <Building2 className="h-4 w-4 text-purple-600" /> 部門使用統計
            </h3>
            <div className="h-64 mb-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={report.department_breakdown}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="department_name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="query_count" name="查詢" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="generate_count" name="生成" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-gray-500 border-b">
                  <th className="pb-2 font-medium">部門</th>
                  <th className="pb-2 font-medium text-right">查詢</th>
                  <th className="pb-2 font-medium text-right">生成</th>
                  <th className="pb-2 font-medium text-right">Token</th>
                  <th className="pb-2 font-medium text-right">使用者</th>
                </tr></thead>
                <tbody>
                  {report.department_breakdown.map(d => (
                    <tr key={d.department_name} className="border-b last:border-0">
                      <td className="py-2">{d.department_name}</td>
                      <td className="py-2 text-right font-mono">{fmtNum(d.query_count)}</td>
                      <td className="py-2 text-right font-mono">{fmtNum(d.generate_count)}</td>
                      <td className="py-2 text-right font-mono">{fmtNum(d.total_tokens)}</td>
                      <td className="py-2 text-right font-mono">{d.active_users}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="grid gap-6 md:grid-cols-2">
          {/* Top Documents */}
          {report.top_documents.length > 0 && (
            <div className="rounded-xl border bg-white p-5">
              <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                <FileText className="h-4 w-4 text-blue-600" /> 最常被檢索文件
              </h3>
              <div className="space-y-1">
                {report.top_documents.map((d, i) => (
                  <div key={d.document_id} className="flex items-center gap-3 py-1.5 border-b last:border-0">
                    <span className="w-6 text-right text-xs font-mono text-gray-400">{i + 1}</span>
                    <span className="flex-1 text-sm text-gray-700 truncate">{d.filename}</span>
                    <span className="text-xs font-mono text-gray-500">{d.query_hit_count} 次</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top Queries */}
          {report.top_queries.length > 0 && (
            <div className="rounded-xl border bg-white p-5">
              <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                <Search className="h-4 w-4 text-green-600" /> 最常被問的問題
              </h3>
              <div className="space-y-1">
                {report.top_queries.map((q, i) => (
                  <div key={i} className="flex items-center gap-3 py-1.5 border-b last:border-0">
                    <span className="w-6 text-right text-xs font-mono text-gray-400">{i + 1}</span>
                    <span className="flex-1 text-sm text-gray-700 truncate">{q.query_text}</span>
                    <span className="text-xs font-mono text-gray-500">{q.count} 次</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
