/**
 * Unified Usage Page — 用量統計 + 使用報告 + 組織用量 + 個人用量
 *
 * Tabs:
 *   1. 總覽 — 總操作數、Token、成本、按操作類型分佈 (admin)
 *   2. 部門分佈 — 部門圖表 + 熱門文件 + 熱門問題 (admin)
 *   3. 成員明細 — 每人用量表格 (admin)
 *   4. 我的用量 — 個人使用統計 (全員)
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { auditApi, kbApi, companyApi, parseApiError } from '../api'
import type { ApiErrorInfo } from '../api'
import api from '../api'
import { useAuth } from '../auth'
import type { UsageSummary, UsageByAction } from '../types'
import AsyncState from '../components/AsyncState'
import {
  BarChart3, Coins, MessageSquare, Database, Cpu,
  FileSpreadsheet, FileText, Users, Building2, Search,
  RefreshCw, ExternalLink, Activity,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import toast from 'react-hot-toast'

/* ── helpers ──────────────────────────────────────────────────── */

const ACTION_LABELS: Record<string, string> = {
  chat_query: '問答',
  document_upload: '文件上傳',
  document_parse: '文件解析',
  kb_search: '知識搜尋',
  embedding: '索引處理',
  content_generate: '內容生成',
}

const actionLabel = (actionType: string) => ACTION_LABELS[actionType] ?? '其他'

// 後端成本以 USD 回傳；對內呈現統一換算新台幣（內部估算匯率）
const TWD_PER_USD = 32
const fmtTwd = (usd: number) => `NT$ ${Math.round(usd * TWD_PER_USD).toLocaleString()}`

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

type StatTone = 'accent' | 'highlight' | 'success' | 'neutral'

const TONE_STYLES: Record<StatTone, string> = {
  accent: 'bg-accent-soft text-accent',
  highlight: 'bg-highlight-soft text-highlight',
  success: 'bg-success-soft text-success',
  neutral: 'bg-wash text-muted',
}

function StatCard({ icon: Icon, label, value, sub, tone = 'accent' }: {
  icon: typeof Coins; label: string; value: string | number; sub?: string; tone?: StatTone
}) {
  return (
    <div className="card p-5">
      <div className="flex items-center gap-3.5">
        <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${TONE_STYLES[tone]}`}>
          <Icon className="h-5 w-5" aria-hidden />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium text-muted">{label}</p>
          <p className="font-display text-2xl font-semibold tabular-nums text-ink">{value}</p>
          {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
        </div>
      </div>
    </div>
  )
}

const fmtNum = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K`
    : String(n)

type Tab = 'overview' | 'department' | 'members' | 'personal'

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
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [exporting, setExporting] = useState<'csv' | 'pdf' | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, a] = await Promise.all([auditApi.usageSummary(), auditApi.usageByAction()])
      setSummary(s)
      setByAction(a)
    } catch (err) {
      setError(parseApiError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleExport = async (format: 'csv' | 'pdf') => {
    setExporting(format)
    try {
      const blob = await auditApi.exportUsage(format)
      downloadBlob(blob, `usage_records_${new Date().toISOString().slice(0, 10)}.${format}`)
    } catch { toast.error('匯出失敗') }
    finally { setExporting(null) }
  }

  return (
    <AsyncState
      loading={loading}
      error={error}
      onRetry={load}
      empty={!summary}
      emptyTitle="尚無用量資料"
      emptyDescription="開始使用 AI 問答或上傳文件後，用量統計將顯示在這裡"
    >
      {summary && (
        <div className="space-y-6">
          {/* Export buttons */}
          <div className="flex justify-end gap-2">
            <button onClick={() => handleExport('csv')} disabled={!!exporting} className="btn-outline">
              {exporting === 'csv'
                ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-muted/30 border-t-muted" aria-hidden />
                : <FileSpreadsheet className="h-4 w-4" aria-hidden />}
              匯出 CSV
            </button>
            <button onClick={() => handleExport('pdf')} disabled={!!exporting} className="btn-outline">
              {exporting === 'pdf'
                ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-muted/30 border-t-muted" aria-hidden />
                : <FileText className="h-4 w-4" aria-hidden />}
              匯出 PDF
            </button>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard icon={MessageSquare} label="總操作次數" value={summary.total_actions.toLocaleString()} tone="accent" />
            <StatCard icon={Cpu} label="輸入用量" value={summary.total_input_tokens.toLocaleString()} sub={`輸出：${summary.total_output_tokens.toLocaleString()}`} tone="neutral" />
            <StatCard icon={Database} label="知識檢索" value={summary.total_pinecone_queries.toLocaleString()} sub={`索引處理：${summary.total_embedding_calls.toLocaleString()}`} tone="success" />
            <StatCard icon={Coins} label="預估費用" value={fmtTwd(summary.total_cost)} sub="內部估算（新台幣）" tone="highlight" />
          </div>

          {/* By action type */}
          {byAction.length > 0 && (
            <div className="card overflow-hidden">
              <div className="border-b border-line/70 px-5 py-4">
                <h2 className="font-display text-base font-semibold text-ink">依操作類型分佈</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[36rem]">
                  <thead>
                    <tr className="border-b border-line/70 bg-wash/60 text-left text-xs font-semibold tracking-wide text-muted">
                      <th className="px-5 py-3">操作類型</th>
                      <th className="px-5 py-3 text-right">次數</th>
                      <th className="px-5 py-3 text-right">輸入用量</th>
                      <th className="px-5 py-3 text-right">輸出用量</th>
                      <th className="px-5 py-3 text-right">預估費用</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/60">
                    {byAction.map(item => (
                      <tr key={item.action_type} className="transition-colors hover:bg-wash/50">
                        <td className="px-5 py-3">
                          <span className="chip-neutral">{actionLabel(item.action_type)}</span>
                        </td>
                        <td className="px-5 py-3 text-right text-sm font-semibold tabular-nums text-ink">{item.count.toLocaleString()}</td>
                        <td className="px-5 py-3 text-right text-sm tabular-nums text-muted">{item.total_input_tokens.toLocaleString()}</td>
                        <td className="px-5 py-3 text-right text-sm tabular-nums text-muted">{item.total_output_tokens.toLocaleString()}</td>
                        <td className="px-5 py-3 text-right text-sm font-semibold tabular-nums text-ink">{fmtTwd(item.total_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </AsyncState>
  )
}

/* ════════════════════════════════════════════════════════════════
   Tab 2 — 部門分佈
   ════════════════════════════════════════════════════════════════ */
function DepartmentTab() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [days, setDays] = useState(30)
  const [report, setReport] = useState<UsageReport | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try { setReport(await kbApi.usageReport(days)) }
    catch (err) { setError(parseApiError(err)) }
    finally { setLoading(false) }
  }, [days])

  useEffect(() => { load() }, [load])

  const PERIODS = [{ days: 7, label: '7 天' }, { days: 30, label: '30 天' }, { days: 90, label: '90 天' }]

  return (
    <AsyncState
      loading={loading}
      error={error}
      onRetry={load}
      empty={!report}
      emptyTitle="尚無部門用量資料"
    >
      {report && (
        <div className="space-y-6">
          {/* Period selector + KPIs */}
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="grid flex-1 grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard icon={MessageSquare} label="總查詢數" value={fmtNum(report.total_queries)} tone="accent" />
              <StatCard icon={Cpu} label="總生成次數" value={fmtNum(report.total_generations)} tone="neutral" />
              <StatCard icon={BarChart3} label="用量合計" value={fmtNum(report.total_tokens)} tone="highlight" />
              <StatCard icon={Users} label="活躍使用者" value={report.active_users} tone="success" />
            </div>
            <div className="flex items-center gap-2">
              <div className="seg-tabs" role="group" aria-label="統計週期">
                {PERIODS.map(p => (
                  <button key={p.days} onClick={() => setDays(p.days)}
                    aria-pressed={days === p.days}
                    className={days === p.days ? 'seg-tab-active' : 'seg-tab'}>
                    {p.label}
                  </button>
                ))}
              </div>
              <button onClick={load} className="icon-btn" aria-label="重新整理">
                <RefreshCw className="h-4 w-4" aria-hidden />
              </button>
            </div>
          </div>

          {/* Department chart + table */}
          {report.department_breakdown.length > 0 && (
            <div className="card p-5">
              <h3 className="mb-4 flex items-center gap-2 font-display text-base font-semibold text-ink">
                <Building2 className="h-4 w-4 text-accent" aria-hidden /> 部門使用統計
              </h3>
              <div className="mb-4 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={report.department_breakdown}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" />
                    <XAxis dataKey="department_name" tick={{ fontSize: 12, fill: 'var(--color-muted)' }} />
                    <YAxis tick={{ fontSize: 12, fill: 'var(--color-muted)' }} />
                    <Tooltip />
                    <Bar dataKey="query_count" name="查詢" fill="var(--color-accent)" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="generate_count" name="生成" fill="var(--color-highlight)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[32rem] text-sm">
                  <thead>
                    <tr className="border-b border-line/70 text-left text-xs font-semibold tracking-wide text-muted">
                      <th className="pb-2">部門</th>
                      <th className="pb-2 text-right">查詢</th>
                      <th className="pb-2 text-right">生成</th>
                      <th className="pb-2 text-right">用量</th>
                      <th className="pb-2 text-right">使用者</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.department_breakdown.map(d => (
                      <tr key={d.department_name} className="border-b border-line/60 last:border-0">
                        <td className="py-2.5 font-medium text-ink">{d.department_name}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-muted">{fmtNum(d.query_count)}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-muted">{fmtNum(d.generate_count)}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-muted">{fmtNum(d.total_tokens)}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-muted">{d.active_users}</td>
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
              <div className="card p-5">
                <h3 className="mb-3 flex items-center gap-2 font-display text-base font-semibold text-ink">
                  <FileText className="h-4 w-4 text-accent" aria-hidden /> 最常被檢索文件
                </h3>
                <div>
                  {report.top_documents.map((d, i) => (
                    <div key={d.document_id} className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-0">
                      <span className="w-6 text-right font-mono text-xs text-muted">{i + 1}</span>
                      <span className="flex-1 truncate text-sm text-ink">{d.filename}</span>
                      <span className="chip-neutral">{d.query_hit_count} 次</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Top Queries — link to analytics */}
            {report.top_queries.length > 0 && (
              <div className="card p-5">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 font-display text-base font-semibold text-ink">
                    <Search className="h-4 w-4 text-success" aria-hidden /> 最常被問的問題
                  </h3>
                  <button onClick={() => navigate('/query-analytics')}
                    className="inline-flex min-h-11 items-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-accent transition-colors hover:bg-accent-soft/60">
                    查看完整分析 <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
                <div>
                  {report.top_queries.slice(0, 5).map((q, i) => (
                    <div key={i} className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-0">
                      <span className="w-6 text-right font-mono text-xs text-muted">{i + 1}</span>
                      <span className="flex-1 truncate text-sm text-ink">{q.query_text}</span>
                      <span className="chip-neutral">{q.count} 次</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </AsyncState>
  )
}

/* ════════════════════════════════════════════════════════════════
   Tab 3 — 成員明細
   ════════════════════════════════════════════════════════════════ */
interface MemberSummary {
  total_actions: number
  total_input_tokens: number
  total_output_tokens: number
  total_pinecone_queries: number
  total_cost?: number
}
interface MemberUsageRow {
  full_name?: string
  email: string
  monthly_queries: number
  monthly_tokens?: number
  monthly_cost?: number
}

function MembersTab() {
  const [summary, setSummary] = useState<MemberSummary | null>(null)
  const [byUser, setByUser] = useState<MemberUsageRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, u] = await Promise.all([companyApi.usageSummary(), companyApi.usageByUser()])
      setSummary(s as MemberSummary)
      setByUser(u as MemberUsageRow[])
    } catch (err) {
      setError(parseApiError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <AsyncState
      loading={loading}
      error={error}
      onRetry={load}
      empty={!summary}
      emptyTitle="尚無成員用量資料"
    >
      {summary && (
        <div className="space-y-6">
          {/* Summary */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard icon={BarChart3} label="總操作數" value={summary.total_actions} tone="accent" />
            <StatCard icon={MessageSquare} label="總用量" value={(summary.total_input_tokens + summary.total_output_tokens).toLocaleString()} tone="success" />
            <StatCard icon={Database} label="知識檢索" value={summary.total_pinecone_queries} tone="neutral" />
            <StatCard icon={Coins} label="預估費用" value={fmtTwd(summary.total_cost || 0)} sub="內部估算（新台幣）" tone="highlight" />
          </div>

          {/* By user */}
          {byUser.length > 0 && (
            <div className="card overflow-hidden">
              <div className="border-b border-line/70 px-5 py-4">
                <h2 className="font-display text-base font-semibold text-ink">按成員用量明細</h2>
              </div>

              {/* 手機：卡片清單 */}
              <div className="divide-y divide-line/60 md:hidden">
                {byUser.map((u, i) => (
                  <div key={i} className="space-y-3 p-5">
                    <div>
                      <p className="text-sm font-semibold text-ink">{u.full_name || u.email}</p>
                      {u.full_name && <p className="text-xs text-muted">{u.email}</p>}
                    </div>
                    <dl className="grid grid-cols-3 gap-2 text-center">
                      <div className="rounded-xl bg-wash/70 px-2 py-2">
                        <dt className="text-xs text-muted">查詢次數</dt>
                        <dd className="mt-0.5 font-display text-base font-semibold tabular-nums text-ink">{u.monthly_queries}</dd>
                      </div>
                      <div className="rounded-xl bg-wash/70 px-2 py-2">
                        <dt className="text-xs text-muted">用量</dt>
                        <dd className="mt-0.5 font-display text-base font-semibold tabular-nums text-ink">{(u.monthly_tokens || 0).toLocaleString()}</dd>
                      </div>
                      <div className="rounded-xl bg-wash/70 px-2 py-2">
                        <dt className="text-xs text-muted">預估費用</dt>
                        <dd className="mt-0.5 font-display text-base font-semibold tabular-nums text-ink">{fmtTwd(u.monthly_cost || 0)}</dd>
                      </div>
                    </dl>
                  </div>
                ))}
              </div>

              {/* 桌面：表格 */}
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-line/70 bg-wash/60 text-left text-xs font-semibold tracking-wide text-muted">
                      <th className="px-5 py-3">成員</th>
                      <th className="px-5 py-3 text-right">查詢次數</th>
                      <th className="px-5 py-3 text-right">用量</th>
                      <th className="px-5 py-3 text-right">預估費用</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/60">
                    {byUser.map((u, i) => (
                      <tr key={i} className="transition-colors hover:bg-wash/50">
                        <td className="px-5 py-3">
                          <p className="text-sm font-semibold text-ink">{u.full_name || u.email}</p>
                          {u.full_name && <p className="text-xs text-muted">{u.email}</p>}
                        </td>
                        <td className="px-5 py-3 text-right text-sm tabular-nums text-muted">{u.monthly_queries}</td>
                        <td className="px-5 py-3 text-right text-sm tabular-nums text-muted">{(u.monthly_tokens || 0).toLocaleString()}</td>
                        <td className="px-5 py-3 text-right text-sm font-semibold tabular-nums text-ink">{fmtTwd(u.monthly_cost || 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </AsyncState>
  )
}

/* ════════════════════════════════════════════════════════════════
   Tab 4 — 我的用量（全員可見）
   ════════════════════════════════════════════════════════════════ */

interface PersonalUsage {
  total_queries: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost_usd: number
  recent_actions: {
    action_type: string
    count: number
    total_input_tokens: number
    total_output_tokens: number
    total_cost: number
  }[]
}

function PersonalTab() {
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [usage, setUsage] = useState<PersonalUsage | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [summary, byAction] = await Promise.all([
        api.get('/audit/usage/me/summary').then(r => r.data),
        api.get('/audit/usage/me/by-action').then(r => r.data),
      ])
      setUsage({
        total_queries: summary.total_actions || 0,
        total_input_tokens: summary.total_input_tokens || 0,
        total_output_tokens: summary.total_output_tokens || 0,
        total_cost_usd: summary.total_cost || 0,
        recent_actions: byAction || [],
      })
    } catch (err) {
      setError(parseApiError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const isEmpty = !usage || usage.total_queries === 0

  return (
    <AsyncState
      loading={loading}
      error={error}
      onRetry={load}
      empty={isEmpty}
      emptyTitle="尚無使用記錄"
      emptyDescription="開始使用 AI 問答或上傳文件後，您的用量統計將顯示在這裡"
    >
      {usage && !isEmpty && (
        <div className="space-y-6">
          <p className="text-sm text-muted">
            {user?.full_name || user?.email} 的個人使用統計
          </p>

          {/* Stats */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard icon={MessageSquare} label="總操作次數" value={usage.total_queries.toLocaleString()} tone="accent" />
            <StatCard icon={Cpu} label="輸入用量" value={usage.total_input_tokens.toLocaleString()} tone="neutral" />
            <StatCard icon={Cpu} label="輸出用量" value={usage.total_output_tokens.toLocaleString()} tone="success" />
            <StatCard icon={Coins} label="預估費用" value={fmtTwd(usage.total_cost_usd)} sub="內部估算（新台幣）" tone="highlight" />
          </div>

          {/* By action type */}
          {usage.recent_actions.length > 0 && (
            <div className="card overflow-hidden">
              <div className="border-b border-line/70 px-5 py-4">
                <h2 className="font-display text-base font-semibold text-ink">按類型分析</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[36rem] text-sm">
                  <thead>
                    <tr className="border-b border-line/70 bg-wash/60 text-left text-xs font-semibold tracking-wide text-muted">
                      <th className="px-5 py-3">操作類型</th>
                      <th className="px-5 py-3 text-right">次數</th>
                      <th className="px-5 py-3 text-right">輸入用量</th>
                      <th className="px-5 py-3 text-right">輸出用量</th>
                      <th className="px-5 py-3 text-right">預估費用</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/60">
                    {usage.recent_actions.map((a) => (
                      <tr key={a.action_type} className="transition-colors hover:bg-wash/50">
                        <td className="px-5 py-3">
                          <span className="chip-neutral">{actionLabel(a.action_type)}</span>
                        </td>
                        <td className="px-5 py-3 text-right font-semibold tabular-nums text-ink">{a.count.toLocaleString()}</td>
                        <td className="px-5 py-3 text-right tabular-nums text-muted">{a.total_input_tokens.toLocaleString()}</td>
                        <td className="px-5 py-3 text-right tabular-nums text-muted">{a.total_output_tokens.toLocaleString()}</td>
                        <td className="px-5 py-3 text-right font-semibold tabular-nums text-ink">{fmtTwd(a.total_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </AsyncState>
  )
}


/* ════════════════════════════════════════════════════════════════
   Main Page — role-aware tabs
   ════════════════════════════════════════════════════════════════ */
export default function UsagePage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const isAdmin = user?.role === 'owner' || user?.role === 'admin'

  const adminTabs: { key: Tab; label: string; icon: typeof BarChart3 }[] = [
    { key: 'overview', label: '總覽', icon: BarChart3 },
    { key: 'department', label: '部門分佈', icon: Building2 },
    { key: 'members', label: '成員明細', icon: Users },
    { key: 'personal', label: '我的用量', icon: Activity },
  ]

  const memberTabs: { key: Tab; label: string; icon: typeof BarChart3 }[] = [
    { key: 'personal', label: '我的用量', icon: Activity },
  ]

  const tabs = isAdmin ? adminTabs : memberTabs
  const urlTab = searchParams.get('tab') as Tab | null
  const defaultTab = isAdmin ? 'overview' : 'personal'
  const [tab, setTabState] = useState<Tab>(
    urlTab && tabs.some(t => t.key === urlTab) ? urlTab : defaultTab
  )

  const setTab = (t: Tab) => {
    setTabState(t)
    setSearchParams(t === defaultTab ? {} : { tab: t })
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-line/70 bg-surface px-4 py-5 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent-soft">
            <BarChart3 className="h-5 w-5 text-accent" aria-hidden />
          </div>
          <div>
            <h1 className="font-display text-xl font-semibold text-ink">用量統計</h1>
            <p className="text-sm text-muted">
              {isAdmin ? '組織用量、部門分佈與成員明細' : '你最近的問答與操作次數'}
            </p>
          </div>
        </div>
        {tabs.length > 1 && (
          <div className="seg-tabs mt-4" role="tablist" aria-label="用量統計分頁">
            {tabs.map(t => (
              <button key={t.key} onClick={() => setTab(t.key)}
                role="tab" id={`usage-tab-${t.key}`} aria-selected={tab === t.key}
                aria-controls={`usage-panel-${t.key}`}
                className={`${tab === t.key ? 'seg-tab-active' : 'seg-tab'} inline-flex items-center gap-1.5`}>
                <t.icon className="h-4 w-4" aria-hidden /> {t.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div
          role="tabpanel"
          id={`usage-panel-${tab}`}
          aria-labelledby={`usage-tab-${tab}`}
          className="animate-fade-in mx-auto max-w-6xl"
        >
          {tab === 'overview' && <OverviewTab />}
          {tab === 'department' && <DepartmentTab />}
          {tab === 'members' && <MembersTab />}
          {tab === 'personal' && <PersonalTab />}
        </div>
      </div>
    </div>
  )
}
