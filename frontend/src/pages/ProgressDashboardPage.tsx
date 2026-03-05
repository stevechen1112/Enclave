/**
 * Phase 10 — 批次處理進度儀表板
 *
 * P10-15: 三角色視圖
 *   - owner/admin/superuser → 完整管理儀表板（觸發重建、Agent 狀態、佇列統計）
 *   - hr (助理)             → 待審核摘要 + 快速前往審核佇列
 *   - 其他使用者 (user)       → 知識庫更新狀態（已入庫文件數）
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../auth'
import {
  FileText,
  Clock,
  BarChart2,
  RefreshCw,
  CheckCircle,
  XCircle,
  Loader2,
  Play,
  AlertCircle,
  ArrowRight,
  Database,
  Download,
} from 'lucide-react'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────

interface StatusSummary {
  watcher_running: boolean
  scheduler_running: boolean
  active_folders: number
  pending_review_count: number
}

interface BatchSummary {
  status_summary: Record<string, number>
}

interface SystemHealthData {
  status: string
  database: string
  redis: string
  uptime_seconds: number
  python_version: string
}

// ── Status Color ──────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  pending: '待審核',
  approved: '已核准',
  modified: '修改確認',
  rejected: '已拒絕',
  processing: '向量化中',
  indexed: '已入庫',
  failed: '失敗',
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-blue-100 text-blue-700',
  modified: 'bg-indigo-100 text-indigo-700',
  rejected: 'bg-red-100 text-red-700',
  processing: 'bg-purple-100 text-purple-700',
  indexed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

// ── Role helpers ──────────────────────────────────────────────────────────────

function isAdminRole(role: string, superuser?: boolean) {
  return superuser || role === 'owner' || role === 'admin'
}

// ═══════════════════════════════════════════════════════════════════════════════
//  HR 視圖 — 待審核摘要
// ═══════════════════════════════════════════════════════════════════════════════

function HRDashboard({ status, batches, loading, onRefresh }: {
  status: StatusSummary | null
  batches: BatchSummary | null
  loading: boolean
  onRefresh: () => void
}) {
  const navigate = useNavigate()
  const summary = batches?.status_summary ?? {}
  const pendingCount = summary['pending'] ?? 0
  const indexedCount = summary['indexed'] ?? 0
  const modifiedCount = summary['modified'] ?? 0

  return (
    <div className="flex h-full flex-col bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">知識庫審核中心</h1>
          <p className="text-sm text-gray-500">待審核文件摘要 — 助理視圖</p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 transition-colors"
        >
          <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {/* Action card */}
        {pendingCount > 0 ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-3xl font-bold text-amber-700">{pendingCount}</p>
                <p className="mt-0.5 text-sm text-amber-600">份文件等待您審核</p>
                {modifiedCount > 0 && (
                  <p className="mt-1 text-xs text-amber-500">（另有 {modifiedCount} 份已修改待確認）</p>
                )}
              </div>
              <button
                onClick={() => navigate('/agent/review')}
                className="flex items-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2 text-sm text-white hover:bg-amber-700 transition-colors"
              >
                前往審核
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-green-200 bg-green-50 p-5 flex items-center gap-3">
            <CheckCircle className="h-6 w-6 text-green-500 shrink-0" />
            <div>
              <p className="font-medium text-green-700">審核佇列已清空</p>
              <p className="text-sm text-green-600">目前沒有待審核文件。</p>
            </div>
          </div>
        )}

        {/* Stats row */}
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <p className="text-xs text-gray-500 mb-1">已入庫文件</p>
            <p className="text-2xl font-bold text-gray-900">{loading ? '—' : indexedCount.toLocaleString()}</p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <p className="text-xs text-gray-500 mb-1">監控資料夾</p>
            <p className="text-2xl font-bold text-gray-900">{loading ? '—' : (status?.active_folders ?? '—')}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
//  User 視圖 — 知識庫狀態
// ═══════════════════════════════════════════════════════════════════════════════

function UserDashboard({ batches, loading, onRefresh }: {
  batches: BatchSummary | null
  loading: boolean
  onRefresh: () => void
}) {
  const summary = batches?.status_summary ?? {}
  const indexedCount = summary['indexed'] ?? 0

  return (
    <div className="flex h-full flex-col bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">知識庫狀態</h1>
          <p className="text-sm text-gray-500">文件索引即時狀態</p>
        </div>
        <button onClick={onRefresh} disabled={loading} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 transition-colors">
          <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="rounded-xl border border-gray-200 bg-white p-6 flex items-center gap-5">
          <div className="rounded-xl bg-green-100 p-3">
            <Database className="h-7 w-7 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">已入庫可查詢文件</p>
            <p className="text-3xl font-bold text-gray-900">{loading ? '—' : indexedCount.toLocaleString()}</p>
            <p className="mt-0.5 text-xs text-gray-400">AI 問答功能可使用上述文件進行搜尋</p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
//  Admin 視圖 — 完整儀表板
// ═══════════════════════════════════════════════════════════════════════════════

function AdminDashboard({ status, batches, health, loading, triggering, lastTriggered, onRefresh, onTrigger, onDownloadReport }: {
  status: StatusSummary | null
  batches: BatchSummary | null
  health: SystemHealthData | null
  loading: boolean
  triggering: boolean
  lastTriggered: string | null
  onRefresh: () => void
  onTrigger: () => void
  onDownloadReport: () => void
}) {
  const summary = batches?.status_summary ?? {}
  const totalDocs = Object.entries(summary)
    .filter(([k]) => k !== 'rejected' && k !== 'failed')
    .reduce((s, [, v]) => s + v, 0)
  const indexedCount = summary['indexed'] ?? 0
  const pendingCount = summary['pending'] ?? 0
  const processingCount = summary['processing'] ?? 0

  return (
    <div className="flex h-full flex-col bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">處理進度儀表板</h1>
          <p className="text-sm text-gray-500">知識庫索引狀態與批次處理統計</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onRefresh} disabled={loading} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 transition-colors">
            <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          </button>
          <button
            onClick={onDownloadReport}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            下載報告
          </button>
          <button
            onClick={onTrigger}
            disabled={triggering || loading}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {triggering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            立即重建索引
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {lastTriggered && (
          <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
            <CheckCircle className="h-4 w-4 shrink-0" />
            批次重建已觸發（{new Date(lastTriggered).toLocaleTimeString('zh-TW')}）
          </div>
        )}

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { icon: FileText, label: '已入庫文件', value: loading ? '—' : indexedCount.toLocaleString(), color: 'bg-green-100 text-green-600' },
            { icon: Clock, label: '待審核', value: loading ? '—' : pendingCount.toLocaleString(), color: 'bg-orange-100 text-orange-600' },
            { icon: BarChart2, label: '向量化中', value: loading ? '—' : processingCount.toLocaleString(), color: 'bg-purple-100 text-purple-600' },
            { icon: FileText, label: '總提案數', value: loading ? '—' : totalDocs.toLocaleString(), color: 'bg-blue-100 text-blue-600' },
          ].map(({ icon: Icon, label, value, color }) => (
            <div key={label} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                <div className={clsx('rounded-lg p-1', color)}><Icon className="h-4 w-4" /></div>
                {label}
              </div>
              <p className="text-2xl font-bold text-gray-900">{value}</p>
            </div>
          ))}
        </div>

        {/* Agent status */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 font-semibold text-gray-800">Agent 狀態</h2>
          <div className="flex flex-wrap gap-4 text-sm">
            <div className="flex items-center gap-2">
              {status?.watcher_running ? <CheckCircle className="h-4 w-4 text-green-500" /> : <AlertCircle className="h-4 w-4 text-gray-400" />}
              <span className={status?.watcher_running ? 'text-green-700' : 'text-gray-400'}>
                檔案監控：{status?.watcher_running ? '運行中' : '已停止'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {status?.scheduler_running ? <CheckCircle className="h-4 w-4 text-green-500" /> : <AlertCircle className="h-4 w-4 text-gray-400" />}
              <span className={status?.scheduler_running ? 'text-green-700' : 'text-gray-400'}>
                排程器：{status?.scheduler_running ? '運行中' : '已停止'}
              </span>
            </div>
            <div className="flex items-center gap-2 text-gray-500">
              <FileText className="h-4 w-4" />
              啟用資料夾：{status?.active_folders ?? '—'}
            </div>
          </div>
        </div>

        {/* System health (superuser only) */}
        {health && (
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="mb-3 font-semibold text-gray-800">系統健康（IT）</h2>
            <div className="flex flex-wrap gap-4 text-sm">
              {[
                { label: 'DB', value: health.database, ok: health.database === 'healthy' },
                { label: 'Redis', value: health.redis, ok: health.redis === 'healthy' },
              ].map(({ label, value, ok }) => (
                <div key={label} className="flex items-center gap-2">
                  {ok ? <CheckCircle className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-red-500" />}
                  <span className={ok ? 'text-green-700' : 'text-red-600'}>{label}：{value}</span>
                </div>
              ))}
              <span className="text-gray-400">Python {health.python_version}</span>
            </div>
          </div>
        )}

        {/* Status breakdown */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-4 font-semibold text-gray-800">審核佇列狀態分佈</h2>
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>
          ) : Object.keys(summary).length === 0 ? (
            <div className="flex flex-col items-center py-10 text-gray-400">
              <BarChart2 className="mb-2 h-10 w-10 opacity-30" />
              <p className="text-sm">尚無紀錄，Agent 啟動後自動統計</p>
            </div>
          ) : (
            <div className="space-y-2">
              {Object.entries(summary).sort((a, b) => b[1] - a[1]).map(([st, count]) => {
                const total = Object.values(summary).reduce((s, v) => s + v, 1)
                const pct = Math.round((count / total) * 100)
                return (
                  <div key={st} className="flex items-center gap-3">
                    <span className={clsx('w-20 shrink-0 rounded-full px-2 py-0.5 text-center text-xs font-medium', STATUS_COLOR[st] || 'bg-gray-100 text-gray-500')}>
                      {STATUS_LABEL[st] || st}
                    </span>
                    <div className="flex-1 overflow-hidden rounded-full bg-gray-100 h-4">
                      <div
                        className={clsx('h-4 rounded-full transition-all',
                          st === 'indexed' ? 'bg-green-400' :
                          st === 'pending' ? 'bg-yellow-400' :
                          st === 'rejected' || st === 'failed' ? 'bg-red-400' :
                          st === 'processing' ? 'bg-purple-400' : 'bg-blue-400'
                        )}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="w-12 shrink-0 text-right text-sm font-medium text-gray-700">{count}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {(summary['failed'] ?? 0) > 0 && (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4">
            <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
            <div className="text-sm text-red-700">
              <p className="font-medium">有 {summary['failed']} 個文件向量化失敗</p>
              <p className="mt-0.5 text-xs">請檢查 Celery Worker 日誌，或重新觸發批次重建索引。</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
//  Main Page — role router
// ═══════════════════════════════════════════════════════════════════════════════

export default function ProgressDashboardPage() {
  const { user } = useAuth()
  const [status, setStatus] = useState<StatusSummary | null>(null)
  const [batches, setBatches] = useState<BatchSummary | null>(null)
  const [health, setHealth] = useState<SystemHealthData | null>(null)
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [lastTriggered, setLastTriggered] = useState<string | null>(null)

  const adminRole = user ? isAdminRole(user.role, user.is_superuser) : false
  const hrRole = !adminRole && user?.role === 'hr'

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [statusRes, batchRes] = await Promise.all([
        api.get<StatusSummary>('/agent/status'),
        api.get<BatchSummary>('/agent/batches'),
      ])
      setStatus(statusRes.data)
      setBatches(batchRes.data)

      if (user?.is_superuser) {
        try {
          const healthRes = await api.get<SystemHealthData>('/admin/system/health')
          setHealth(healthRes.data)
        } catch { /* optional */ }
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => { load() }, [load])

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      const res = await api.post<{ triggered: boolean; triggered_at?: string }>('/agent/batches/trigger')
      setLastTriggered(res.data.triggered_at || new Date().toISOString())
      await load()
    } finally {
      setTriggering(false)
    }
  }

  const handleDownloadReport = async () => {
    try {
      const res = await api.get('/agent/batches/report', { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `batch_report_${new Date().toISOString().slice(0, 10)}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch { /* ignore */ }
  }

  if (adminRole) {
    return (
      <AdminDashboard
        status={status}
        batches={batches}
        health={health}
        loading={loading}
        triggering={triggering}
        lastTriggered={lastTriggered}
        onRefresh={load}
        onTrigger={handleTrigger}
        onDownloadReport={handleDownloadReport}
      />
    )
  }

  if (hrRole) {
    return <HRDashboard status={status} batches={batches} loading={loading} onRefresh={load} />
  }

  return <UserDashboard batches={batches} loading={loading} onRefresh={load} />
}
