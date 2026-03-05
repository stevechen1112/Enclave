/**
 * Unified Usage Page — 合併用量統計 + 使用報告 + 組織用量
 *
 * Tabs:
 *   1. 總覽 — 總操作數、Token、成本、按操作類型分佈 (原 UsagePage)
 *   2. 部門分佈 — 部門圖表 + 熱門文件 + 熱門問題 (原 UsageReportPage)
 *   3. 成員明細 — 每人用量表格 (原 CompanyPage UsageTab)
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { auditApi, kbApi, companyApi } from '../api'
import type { UsageSummary, UsageByAction } from '../types'
import {
  BarChart3, Loader2, Coins, MessageSquare, Database, Cpu,
  FileSpreadsheet, FileText, Users, Building2, Search,
  RefreshCw, ExternalLink,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import toast from 'react-hot-toast'

/* ── helpers ──────────────────────────────────────────────────── */

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

function StatCard({ icon: Icon, label, value, sub, color }: {
  icon: typeof Coins; label: string; value: string | number; sub?: string; color: string
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-xs font-medium text-gray-500">{label}</p>
          <p className="text-xl font-bold text-gray-900">{value}</p>
          {sub && <p className="text-xs text-gray-400">{sub}</p>}
        </div>
      </div>
    </div>
  )
}

const fmtNum = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K`
    : String(n)

type Tab = 'overview' | 'department' | 'members'

/* ── Types for department report ─────────────────────────────── */
interface DeptUsage { department_name: string; query_count: number; generate_count: number; total_tokens: number; active_users: number }
interface TopDoc { document_id: string; filename: string; query_hit_count: number }
interface TopQuery { query_text: string; count: number }
interface UsageReport {
  period_start: string; period_end: string
  total_queries: number; total_generations: number
  total_tokens: number; active_users: number
  department_breakdown: DeptUsage[]
  top_documents: TopDoc[]; top_queries: TopQuery[]
}

/* ════════════════════════════════════════════════════════════════
   Tab 1 — 總覽
   ════════════════════════════════════════════════════════════════ */
function OverviewTab() {
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [byAction, setByAction] = useState<UsageByAction[]>([])
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState<'csv' | 'pdf' | null>(null)

  useEffect(() => {
    Promise.all([
      auditApi.usageSummary().catch(() => null),
      auditApi.usageByAction().catch(() => []),
    ]).then(([s, a]) => { setSummary(s); setByAction(a as UsageByAction[]) })
      .finally(() => setLoading(false))
  }, [])

  const handleExport = async (format: 'csv' | 'pdf') => {
    setExporting(format)
    try {
      const blob = await auditApi.exportUsage(format)
      downloadBlob(blob, `usage_records_${new Date().toISOString().slice(0, 10)}.${format}`)
    } catch { toast.error('匯出失敗') }
    finally { setExporting(null) }
  }

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>

  if (!summary) return (
    <div className="flex flex-col items-center py-12 text-gray-400">
      <BarChart3 className="mb-3 h-10 w-10" /><p className="text-sm">尚無用量資料</p>
    </div>
  )

  return (
    <div className="space-y-6">
      {/* Export buttons */}
      <div className="flex justify-end gap-2">
        <button onClick={() => handleExport('csv')} disabled={!!exporting}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
          {exporting === 'csv' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />} 匯出 CSV
        </button>
        <button onClick={() => handleExport('pdf')} disabled={!!exporting}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
          {exporting === 'pdf' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />} 匯出 PDF
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={MessageSquare} label="總操作次數" value={summary.total_actions.toLocaleString()} color="bg-blue-50 text-blue-600" />
        <StatCard icon={Cpu} label="輸入 Tokens" value={summary.total_input_tokens.toLocaleString()} sub={`輸出: ${summary.total_output_tokens.toLocaleString()}`} color="bg-purple-50 text-purple-600" />
        <StatCard icon={Database} label="向量查詢" value={summary.total_pinecone_queries.toLocaleString()} sub={`Embedding: ${summary.total_embedding_calls.toLocaleString()}`} color="bg-green-50 text-green-600" />
        <StatCard icon={Coins} label="預估成本" value={`$${summary.total_cost.toFixed(4)}`} sub="USD" color="bg-amber-50 text-amber-600" />
      </div>

      {/* By action type */}
      {byAction.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="border-b border-gray-100 px-5 py-3">
            <h2 className="text-sm font-semibold text-gray-700">依操作類型分佈</h2>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <th className="px-5 py-3">操作類型</th>
                <th className="px-5 py-3 text-right">次數</th>
                <th className="px-5 py-3 text-right">輸入 Tokens</th>
                <th className="px-5 py-3 text-right">輸出 Tokens</th>
                <th className="px-5 py-3 text-right">預估成本</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {byAction.map(item => (
                <tr key={item.action_type} className="hover:bg-gray-50">
                  <td className="px-5 py-3">
                    <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">{item.action_type}</span>
                  </td>
                  <td className="px-5 py-3 text-right text-sm text-gray-700 font-medium">{item.count.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right text-sm text-gray-500">{item.total_input_tokens.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right text-sm text-gray-500">{item.total_output_tokens.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right text-sm text-gray-700 font-medium">${item.total_cost.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ════════════════════════════════════════════════════════════════
   Tab 2 — 部門分佈
   ════════════════════════════════════════════════════════════════ */
function DepartmentTab() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)
  const [report, setReport] = useState<UsageReport | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setReport(await kbApi.usageReport(days)) }
    catch { toast.error('載入失敗') }
    finally { setLoading(false) }
  }, [days])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>
  if (!report) return null

  const PERIODS = [{ days: 7, label: '7 天' }, { days: 30, label: '30 天' }, { days: 90, label: '90 天' }]

  return (
    <div className="space-y-6">
      {/* Period selector + KPIs */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard icon={MessageSquare} label="總查詢數" value={fmtNum(report.total_queries)} color="bg-blue-50 text-blue-600" />
          <StatCard icon={Cpu} label="總生成次數" value={fmtNum(report.total_generations)} color="bg-purple-50 text-purple-600" />
          <StatCard icon={BarChart3} label="Token 使用量" value={fmtNum(report.total_tokens)} color="bg-amber-50 text-amber-600" />
          <StatCard icon={Users} label="活躍使用者" value={report.active_users} color="bg-green-50 text-green-600" />
        </div>
        <div className="flex items-center gap-2">
          {PERIODS.map(p => (
            <button key={p.days} onClick={() => setDays(p.days)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${days === p.days ? 'bg-blue-600 text-white' : 'border text-gray-600 hover:bg-gray-100'}`}>
              {p.label}
            </button>
          ))}
          <button onClick={load} className="ml-1 flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm text-gray-600 hover:bg-gray-100">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Department chart + table */}
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

        {/* Top Queries — link to analytics */}
        {report.top_queries.length > 0 && (
          <div className="rounded-xl border bg-white p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <Search className="h-4 w-4 text-green-600" /> 最常被問的問題
              </h3>
              <button onClick={() => navigate('/query-analytics')}
                className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline">
                查看完整分析 <ExternalLink className="h-3 w-3" />
              </button>
            </div>
            <div className="space-y-1">
              {report.top_queries.slice(0, 5).map((q, i) => (
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
  )
}

/* ════════════════════════════════════════════════════════════════
   Tab 3 — 成員明細
   ════════════════════════════════════════════════════════════════ */
function MembersTab() {
  const [summary, setSummary] = useState<any>(null)
  const [byUser, setByUser] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([companyApi.usageSummary(), companyApi.usageByUser()])
      .then(([s, u]) => { setSummary(s); setByUser(u as any[]) })
      .catch(() => null)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>
  if (!summary) return <div className="flex flex-col items-center py-12 text-gray-400"><Users className="mb-3 h-10 w-10" /><p className="text-sm">無法載入用量資料</p></div>

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={BarChart3} label="總操作數" value={summary.total_actions} color="bg-blue-50 text-blue-600" />
        <StatCard icon={MessageSquare} label="總 Token" value={(summary.total_input_tokens + summary.total_output_tokens).toLocaleString()} color="bg-green-50 text-green-600" />
        <StatCard icon={Database} label="向量查詢" value={summary.total_pinecone_queries} color="bg-purple-50 text-purple-600" />
        <StatCard icon={Coins} label="估計成本" value={`$${summary.total_cost?.toFixed(4) || '0'}`} color="bg-amber-50 text-amber-600" />
      </div>

      {/* By user */}
      {byUser.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <div className="border-b border-gray-100 px-5 py-3">
            <h2 className="text-sm font-semibold text-gray-700">按成員用量明細</h2>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <th className="px-5 py-3">成員</th>
                <th className="px-5 py-3 text-right">查詢次數</th>
                <th className="px-5 py-3 text-right">Token</th>
                <th className="px-5 py-3 text-right">成本</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {byUser.map((u: any, i: number) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-5 py-2">
                    <p className="text-sm font-medium text-gray-900">{u.full_name || u.email}</p>
                    {u.full_name && <p className="text-xs text-gray-400">{u.email}</p>}
                  </td>
                  <td className="px-5 py-2 text-right text-sm text-gray-600">{u.monthly_queries}</td>
                  <td className="px-5 py-2 text-right text-sm text-gray-600">{(u.monthly_tokens || 0).toLocaleString()}</td>
                  <td className="px-5 py-2 text-right text-sm font-medium text-gray-700">${(u.monthly_cost || 0).toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ════════════════════════════════════════════════════════════════
   Main Page
   ════════════════════════════════════════════════════════════════ */
export default function UsagePage() {
  const [tab, setTab] = useState<Tab>('overview')

  const tabs: { key: Tab; label: string; icon: typeof BarChart3 }[] = [
    { key: 'overview', label: '總覽', icon: BarChart3 },
    { key: 'department', label: '部門分佈', icon: Building2 },
    { key: 'members', label: '成員明細', icon: Users },
  ]

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center gap-2 mb-1">
          <BarChart3 className="h-5 w-5 text-blue-600" />
          <h1 className="text-lg font-semibold text-gray-900">用量統計</h1>
        </div>
        <p className="text-sm text-gray-500 mb-3">API 消耗、部門分佈、成員明細一站式查看</p>
        <div className="flex gap-1">
          {tabs.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                tab === t.key ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-100'
              }`}>
              <t.icon className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {tab === 'overview' && <OverviewTab />}
        {tab === 'department' && <DepartmentTab />}
        {tab === 'members' && <MembersTab />}
      </div>
    </div>
  )
}
