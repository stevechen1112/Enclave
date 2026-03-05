/**
 * Unified Query Analytics — 合併 RAG 儀表板 + 問答日誌分析
 *
 * Tabs:
 *   1. 概覽 — RAG KPIs, 每日對話 BarChart, 回饋 PieChart, 延遲 + 回饋統計
 *   2. 熱門問題 — Top queries table (原 QueryAnalyticsPage tab)
 *   3. 知識缺口 — 未答覆問題 + 每日趨勢 (原 QueryAnalyticsPage tabs)
 */

import { useState, useEffect } from 'react'
import api from '../api'
import { chatApi } from '../api'
import {
  BarChart2, HelpCircle, MessageSquare, TrendingUp,
  AlertTriangle, CheckCircle, Loader2, RefreshCw,
  Clock, ThumbsUp,
} from 'lucide-react'
import { format, parseISO } from 'date-fns'
import clsx from 'clsx'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts'
import toast from 'react-hot-toast'

// ── API types ──

interface QuerySummary {
  total_queries: number
  answered_queries: number
  unanswered_queries: number
  answer_rate_pct: number
  avg_latency_ms: number | null
  period_days: number
}

interface DailyQueryCount {
  date: string; total: number; answered: number; unanswered: number
}

interface TopQuery { question: string; count: number; last_seen: string }
interface UnansweredQuery { question: string; asked_at: string; conversation_id: string }

interface RAGDashboard {
  total_conversations: number; total_messages: number
  avg_turns_per_conversation: number; avg_latency_ms: number
  p50_latency_ms: number; p95_latency_ms: number
  daily_conversations: { date: string; count: number }[]
  feedback: {
    total: number; positive: number; negative: number
    positive_rate: number; categories: { category: string; count: number }[]
  }
}

const COLORS = ['#22c55e', '#ef4444', '#f59e0b', '#3b82f6', '#8b5cf6']

// ── StatCard ──

function StatCard({ title, value, sub, icon: Icon, color }: {
  title: string; value: string | number; sub?: string
  icon: typeof BarChart2; color: string
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <div className={clsx('rounded-lg p-2', color)}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm text-gray-500">{title}</p>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
          {sub && <p className="text-xs text-gray-400">{sub}</p>}
        </div>
      </div>
    </div>
  )
}

type ActiveTab = 'overview' | 'top' | 'gaps'

// ════════════════════════════════════════════════════════════════
//  Tab 1 — 概覽 (RAG Dashboard data)
// ════════════════════════════════════════════════════════════════
function OverviewTab({ days }: { days: number }) {
  const [data, setData] = useState<RAGDashboard | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    chatApi.ragDashboard(days)
      .then(setData)
      .catch(() => toast.error('載入儀表板失敗'))
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>
  if (!data) return null

  const feedbackPieData = [
    { name: '正面', value: data.feedback.positive },
    { name: '負面', value: data.feedback.negative },
  ].filter(d => d.value > 0)

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard icon={MessageSquare} title="對話總數" value={data.total_conversations} color="bg-blue-100 text-blue-600" />
        <StatCard icon={TrendingUp} title="平均輪次" value={data.avg_turns_per_conversation} color="bg-purple-100 text-purple-600" />
        <StatCard icon={Clock} title="平均延遲" value={`${data.avg_latency_ms}ms`} color="bg-amber-100 text-amber-600" />
        <StatCard icon={ThumbsUp} title="好評率"
          value={data.feedback.total > 0 ? `${(data.feedback.positive_rate * 100).toFixed(1)}%` : 'N/A'}
          color="bg-green-100 text-green-600"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Daily conversations */}
        <div className="rounded-xl border bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">每日對話數</h3>
          {data.daily_conversations.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.daily_conversations}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={v => v.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} name="對話數" />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="text-center text-sm text-gray-400 py-12">此期間無數據</p>}
        </div>

        {/* Feedback pie */}
        <div className="rounded-xl border bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">回饋分佈</h3>
          {feedbackPieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={feedbackPieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80}
                  fill="#8884d8" dataKey="value"
                  label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}>
                  {feedbackPieData.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
                </Pie>
                <Legend /><Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : <p className="text-center text-sm text-gray-400 py-12">尚無回饋數據</p>}
        </div>
      </div>

      {/* Latency + Feedback stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="rounded-xl border bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">回覆延遲統計</h3>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-2xl font-bold text-gray-900">{data.avg_latency_ms}<span className="text-sm text-gray-400">ms</span></p>
              <p className="text-xs text-gray-500 mt-1">平均</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{data.p50_latency_ms}<span className="text-sm text-gray-400">ms</span></p>
              <p className="text-xs text-gray-500 mt-1">P50</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{data.p95_latency_ms}<span className="text-sm text-gray-400">ms</span></p>
              <p className="text-xs text-gray-500 mt-1">P95</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">回饋統計</h3>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-2xl font-bold text-blue-600">{data.feedback.total}</p>
              <p className="text-xs text-gray-500 mt-1">總回饋數</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-green-600">{data.feedback.positive}</p>
              <p className="text-xs text-gray-500 mt-1">👍 正面</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-red-500">{data.feedback.negative}</p>
              <p className="text-xs text-gray-500 mt-1">👎 負面</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════
//  Tab 2 — 熱門問題
// ════════════════════════════════════════════════════════════════
function TopQueriesTab({ topQueries }: { topQueries: TopQuery[] }) {
  if (topQueries.length === 0) return (
    <div className="flex flex-col items-center py-12 text-gray-400">
      <HelpCircle className="mb-3 h-10 w-10" /><p className="text-sm">此期間尚無查詢記錄</p>
    </div>
  )

  return (
    <div className="rounded-xl border bg-white overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium text-gray-500 uppercase">
            <th className="px-4 py-3">#</th>
            <th className="px-4 py-3">問題</th>
            <th className="px-4 py-3 text-right">次數</th>
            <th className="px-4 py-3">最近提問</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {topQueries.map((q, i) => (
            <tr key={i} className="hover:bg-gray-50">
              <td className="px-4 py-3 text-sm text-gray-400">{i + 1}</td>
              <td className="px-4 py-3 text-sm text-gray-900 max-w-lg truncate">{q.question}</td>
              <td className="px-4 py-3 text-right">
                <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">{q.count}</span>
              </td>
              <td className="px-4 py-3 text-xs text-gray-400">
                {q.last_seen ? format(parseISO(q.last_seen), 'MM/dd HH:mm') : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════
//  Tab 3 — 知識缺口 (未答覆 + 趨勢)
// ════════════════════════════════════════════════════════════════
function GapsTab({ unanswered, trend }: { unanswered: UnansweredQuery[]; trend: DailyQueryCount[] }) {
  const maxTotal = Math.max(...trend.map(d => d.total), 1)

  return (
    <div className="space-y-6">
      {/* Unanswered */}
      <div className="rounded-xl border bg-white overflow-hidden">
        <div className="border-b border-gray-100 px-5 py-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-orange-500" /> 未答覆問題
          </h3>
          {unanswered.length > 0 && (
            <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs text-orange-600">{unanswered.length}</span>
          )}
        </div>
        {unanswered.length === 0 ? (
          <div className="flex flex-col items-center py-12 text-gray-400">
            <CheckCircle className="mb-3 h-10 w-10 text-green-400" />
            <p className="text-sm">太棒了！此期間所有問題都有找到相關文件</p>
          </div>
        ) : (
          <>
            <div className="border-b border-gray-100 bg-orange-50 px-4 py-2">
              <p className="text-xs text-orange-700">以下問題在知識庫中未找到相關文件，建議補充對應的文件以提升答覆率。</p>
            </div>
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium text-gray-500 uppercase">
                  <th className="px-4 py-3">問題</th>
                  <th className="px-4 py-3">提問時間</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {unanswered.map((q, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900 max-w-lg truncate">{q.question}</td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {q.asked_at ? format(parseISO(q.asked_at), 'yyyy/MM/dd HH:mm') : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      {/* Daily trend */}
      <div className="rounded-xl border bg-white overflow-hidden">
        <div className="border-b border-gray-100 px-5 py-3">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <BarChart2 className="h-4 w-4 text-blue-600" /> 每日趨勢
          </h3>
        </div>
        <div className="p-4 space-y-1">
          {trend.filter(d => d.total > 0).length === 0 ? (
            <div className="flex flex-col items-center py-12 text-gray-400">
              <BarChart2 className="mb-3 h-10 w-10" /><p className="text-sm">此期間尚無查詢記錄</p>
            </div>
          ) : (
            <>
              {trend.slice(-30).reverse().map(d => (
                <div key={d.date} className="flex items-center gap-3 text-sm">
                  <span className="w-20 shrink-0 text-xs text-gray-400">{format(parseISO(d.date), 'MM/dd')}</span>
                  <div className="flex-1 overflow-hidden rounded-full bg-gray-100 h-5">
                    <div className="flex h-5 overflow-hidden rounded-full"
                      style={{ width: `${(d.total / maxTotal) * 100}%` }}>
                      <div className="bg-green-400" style={{ width: d.total > 0 ? `${(d.answered / d.total) * 100}%` : '0%' }} />
                      <div className="flex-1 bg-orange-300" />
                    </div>
                  </div>
                  <span className="w-12 shrink-0 text-right text-xs font-medium text-gray-600">{d.total}</span>
                </div>
              ))}
              <div className="flex items-center gap-4 pt-2 text-xs text-gray-400">
                <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm bg-green-400" />已答覆</span>
                <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-sm bg-orange-300" />未答覆</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════
//  Main Page
// ════════════════════════════════════════════════════════════════
export default function QueryAnalyticsPage() {
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<QuerySummary | null>(null)
  const [trend, setTrend] = useState<DailyQueryCount[]>([])
  const [topQueries, setTopQueries] = useState<TopQuery[]>([])
  const [unanswered, setUnanswered] = useState<UnansweredQuery[]>([])
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview')

  const load = async () => {
    setLoading(true)
    try {
      const [summaryRes, trendRes, topRes, unansweredRes] = await Promise.all([
        api.get<QuerySummary>(`/chat/analytics/summary?days=${days}`),
        api.get<DailyQueryCount[]>(`/chat/analytics/trend?days=${Math.min(days, 30)}`),
        api.get<TopQuery[]>(`/chat/analytics/top-queries?days=${days}&limit=20`),
        api.get<UnansweredQuery[]>(`/chat/analytics/unanswered?days=${days}&limit=50`),
      ])
      setSummary(summaryRes.data)
      setTrend(trendRes.data)
      setTopQueries(topRes.data)
      setUnanswered(unansweredRes.data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [days])

  const tabItems: { key: ActiveTab; label: string; icon: typeof BarChart2; badge?: number }[] = [
    { key: 'overview', label: '概覽', icon: TrendingUp },
    { key: 'top', label: '熱門問題', icon: MessageSquare },
    { key: 'gaps', label: '知識缺口', icon: AlertTriangle, badge: unanswered.length || undefined },
  ]

  return (
    <div className="flex h-full flex-col bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <BarChart2 className="h-5 w-5 text-blue-600" />
              <h1 className="text-lg font-semibold text-gray-900">問答分析</h1>
            </div>
            <p className="text-sm text-gray-500">RAG 品質監控、熱門問題、知識缺口一站式掌握</p>
          </div>
          <div className="flex items-center gap-3">
            <select value={days} onChange={e => setDays(Number(e.target.value))}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm">
              <option value={7}>最近 7 天</option>
              <option value={30}>最近 30 天</option>
              <option value={90}>最近 90 天</option>
            </select>
            <button onClick={load} disabled={loading}
              className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 transition-colors">
              <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
            </button>
          </div>
        </div>

        {/* Summary KPIs (always visible) */}
        {summary && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-3">
            <StatCard title="總查詢" value={summary.total_queries.toLocaleString()} sub={`最近 ${summary.period_days} 天`} icon={MessageSquare} color="bg-blue-100 text-blue-600" />
            <StatCard title="答覆率" value={`${summary.answer_rate_pct}%`} sub={`${summary.answered_queries} / ${summary.total_queries}`} icon={CheckCircle} color="bg-green-100 text-green-600" />
            <StatCard title="未答覆" value={summary.unanswered_queries.toLocaleString()} icon={AlertTriangle} color="bg-orange-100 text-orange-600" />
            <StatCard title="平均延遲" value={summary.avg_latency_ms !== null ? `${(summary.avg_latency_ms / 1000).toFixed(1)}s` : '-'} icon={Clock} color="bg-purple-100 text-purple-600" />
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1">
          {tabItems.map(t => (
            <button key={t.key} onClick={() => setActiveTab(t.key)}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                activeTab === t.key ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-100'
              )}>
              <t.icon className="h-4 w-4" /> {t.label}
              {t.badge && t.badge > 0 && (
                <span className={clsx('ml-1 rounded-full px-1.5 py-0.5 text-xs',
                  activeTab === t.key ? 'bg-white/20 text-white' : 'bg-orange-100 text-orange-600'
                )}>{t.badge}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading && !summary ? (
          <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>
        ) : (
          <>
            {activeTab === 'overview' && <OverviewTab days={days} />}
            {activeTab === 'top' && <TopQueriesTab topQueries={topQueries} />}
            {activeTab === 'gaps' && <GapsTab unanswered={unanswered} trend={trend} />}
          </>
        )}
      </div>
    </div>
  )
}
