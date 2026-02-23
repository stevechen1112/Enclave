import { useState, useEffect } from 'react'
import { useAuth } from '../auth'
import { Activity, Loader2, MessageSquare, Coins, Cpu } from 'lucide-react'
import api from '../api'

interface MyUsage {
  total_queries: number
  total_input_tokens: number
  total_output_tokens: number
  total_documents_uploaded: number
  total_cost_usd: number
  recent_actions: {
    action_type: string
    count: number
    total_input_tokens: number
    total_output_tokens: number
    total_cost: number
  }[]
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

const ACTION_LABELS: Record<string, string> = {
  chat_query: 'AI 問答',
  document_upload: '文件上傳',
  document_parse: '文件解析',
  kb_search: '知識庫搜尋',
  embedding: '向量化',
}

export default function MyUsagePage() {
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [usage, setUsage] = useState<MyUsage | null>(null)

  useEffect(() => {
    // Fetch personal usage from personal-only endpoints (filtered by current user_id server-side)
    Promise.all([
      api.get('/audit/usage/me/summary').then(r => r.data).catch(() => null),
      api.get('/audit/usage/me/by-action').then(r => r.data).catch(() => []),
    ]).then(([summary, byAction]) => {
      if (summary) {
        setUsage({
          total_queries: summary.total_actions || 0,
          total_input_tokens: summary.total_input_tokens || 0,
          total_output_tokens: summary.total_output_tokens || 0,
          total_documents_uploaded: 0,
          total_cost_usd: summary.total_cost || 0,
          recent_actions: byAction || [],
        })
      }
    }).finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-auto">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <Activity className="h-6 w-6 text-blue-600" />
          <h1 className="text-xl font-bold text-gray-900">我的用量</h1>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          {user?.full_name || user?.email} 的個人使用統計
        </p>
      </div>

      <div className="flex-1 p-6">
        <div className="mx-auto max-w-4xl space-y-6">
          {/* Stats */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              icon={MessageSquare}
              label="總操作次數"
              value={usage?.total_queries?.toLocaleString() ?? '0'}
              color="bg-blue-50 text-blue-600"
            />
            <StatCard
              icon={Cpu}
              label="輸入 Tokens"
              value={usage?.total_input_tokens?.toLocaleString() ?? '0'}
              color="bg-purple-50 text-purple-600"
            />
            <StatCard
              icon={Cpu}
              label="輸出 Tokens"
              value={usage?.total_output_tokens?.toLocaleString() ?? '0'}
              color="bg-indigo-50 text-indigo-600"
            />
            <StatCard
              icon={Coins}
              label="估算費用"
              value={`$${(usage?.total_cost_usd ?? 0).toFixed(4)}`}
              color="bg-amber-50 text-amber-600"
            />
          </div>

          {/* By action type */}
          {usage?.recent_actions && usage.recent_actions.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white">
              <div className="border-b border-gray-200 px-6 py-4">
                <h2 className="text-sm font-semibold text-gray-900">按類型分析</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left">
                      <th className="px-6 py-3 text-xs font-medium text-gray-500">操作類型</th>
                      <th className="px-6 py-3 text-xs font-medium text-gray-500 text-right">次數</th>
                      <th className="px-6 py-3 text-xs font-medium text-gray-500 text-right">輸入 Tokens</th>
                      <th className="px-6 py-3 text-xs font-medium text-gray-500 text-right">輸出 Tokens</th>
                      <th className="px-6 py-3 text-xs font-medium text-gray-500 text-right">費用 (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.recent_actions.map((a) => (
                      <tr key={a.action_type} className="border-b border-gray-50 hover:bg-gray-50">
                        <td className="px-6 py-3 font-medium text-gray-900">
                          {ACTION_LABELS[a.action_type] || a.action_type}
                        </td>
                        <td className="px-6 py-3 text-right text-gray-600">{a.count.toLocaleString()}</td>
                        <td className="px-6 py-3 text-right text-gray-600">{a.total_input_tokens.toLocaleString()}</td>
                        <td className="px-6 py-3 text-right text-gray-600">{a.total_output_tokens.toLocaleString()}</td>
                        <td className="px-6 py-3 text-right text-gray-600">${a.total_cost.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Empty state */}
          {(!usage || usage.total_queries === 0) && (
            <div className="flex flex-col items-center py-16 text-gray-400">
              <Activity className="mb-3 h-12 w-12" />
              <p className="text-sm font-medium">尚無使用記錄</p>
              <p className="mt-1 text-xs">開始使用 AI 問答或上傳文件後，您的用量統計將顯示在這裡</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
