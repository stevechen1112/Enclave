import { useState, useEffect, useCallback } from 'react'
import { companyApi } from '../api'
import {
  Loader2, AlertCircle, Building2, Users, FileText,
  MessageSquare, UserPlus, MoreVertical,
  BarChart3, CheckCircle2,
  Mail, Eye, EyeOff,
  Cpu, Cloud,
} from 'lucide-react'

type Tab = 'dashboard' | 'users' | 'deployment'

// ─── Shared ───
function Loader() {
  return <div className="flex h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>
}
function Empty({ text }: { text: string }) {
  return <div className="flex flex-col items-center py-16 text-gray-400"><AlertCircle className="mb-3 h-10 w-10" /><p className="text-sm">{text}</p></div>
}
function StatCard({ icon: Icon, label, value, sub, color }: {
  icon: typeof Users; label: string; value: string | number; sub?: string; color: string
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

// ═══ Dashboard Tab ═══
function DashboardTab() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    companyApi.dashboard().then(setData).catch(() => null).finally(() => setLoading(false))
  }, [])

  if (loading) return <Loader />
  if (!data) return <Empty text="無法載入儀表板" />

  const qs = data.quota_status

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={Users} label="員工人數" value={data.user_count} color="bg-blue-50 text-blue-600" />
        <StatCard icon={FileText} label="文件數" value={data.document_count} color="bg-green-50 text-green-600" />
        <StatCard icon={MessageSquare} label="對話數" value={data.conversation_count} color="bg-purple-50 text-purple-600" />
        <StatCard icon={BarChart3} label="本月查詢" value={data.monthly_queries} sub={`費用: $${(data.monthly_cost || 0).toFixed(4)}`} color="bg-amber-50 text-amber-600" />
      </div>

      {/* 地端版授權資訊 */}
      {qs && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2 mb-2">
            <Building2 className="h-4 w-4 text-blue-600" />
            <h3 className="text-sm font-semibold text-gray-700">系統授權資訊</h3>
            <span className="ml-auto inline-flex rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">地端版 On-Premise</span>
          </div>
          <p className="text-sm text-gray-500">智識庫資料在地端獨立運行，未設受使用者數、文件數、API 呼叫次數限制。</p>
        </div>
      )}
    </div>
  )
}

// ═══ Users Tab ═══
function UsersTab() {
  const [users, setUsers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showInvite, setShowInvite] = useState(false)
  const [inviteForm, setInviteForm] = useState({ email: '', full_name: '', role: 'employee', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editRole, setEditRole] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    companyApi.users().then(setUsers).catch(() => []).finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setMsg('')
    try {
      await companyApi.inviteUser(inviteForm)
      setInviteForm({ email: '', full_name: '', role: 'employee', password: '' })
      setShowInvite(false)
      setMsg('已邀請使用者')
      load()
    } catch (err: any) {
      setMsg(err.response?.data?.detail || '邀請失敗')
    }
    finally { setSubmitting(false) }
  }

  const handleUpdateRole = async (userId: string) => {
    try {
      await companyApi.updateUser(userId, { role: editRole })
      setEditingId(null)
      load()
    } catch { /* noop */ }
  }

  const handleDeactivate = async (userId: string) => {
    if (!confirm('確定要停用此使用者？')) return
    try {
      await companyApi.deactivateUser(userId)
      load()
    } catch { /* noop */ }
  }

  if (loading) return <Loader />

  const roles = ['owner', 'admin', 'hr', 'employee', 'viewer']

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">成員管理 ({users.length})</h3>
        <button
          onClick={() => setShowInvite(!showInvite)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          <UserPlus className="h-4 w-4" /> 邀請成員
        </button>
      </div>

      {msg && (
        <div className="rounded-lg bg-blue-50 border border-blue-200 px-4 py-2 text-sm text-blue-700 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4" /> {msg}
        </div>
      )}

      {/* Invite modal */}
      {showInvite && (
        <form onSubmit={handleInvite} className="rounded-xl border border-blue-200 bg-blue-50/50 p-5 space-y-3">
          <h4 className="text-sm font-semibold text-gray-700 flex items-center gap-2"><Mail className="h-4 w-4" /> 邀請新成員</h4>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input
              type="email" required placeholder="Email *"
              value={inviteForm.email}
              onChange={e => setInviteForm(p => ({ ...p, email: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <input
              type="text" placeholder="姓名"
              value={inviteForm.full_name}
              onChange={e => setInviteForm(p => ({ ...p, full_name: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <select
              value={inviteForm.role}
              onChange={e => setInviteForm(p => ({ ...p, role: e.target.value }))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {roles.filter(r => r !== 'owner').map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'} required placeholder="初始密碼 *"
                value={inviteForm.password}
                onChange={e => setInviteForm(p => ({ ...p, password: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-9 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div className="flex gap-2">
            <button type="submit" disabled={submitting} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {submitting ? '邀請中...' : '送出邀請'}
            </button>
            <button type="button" onClick={() => setShowInvite(false)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
              取消
            </button>
          </div>
        </form>
      )}

      {/* User table */}
      {users.length === 0 ? <Empty text="尚無成員" /> : (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <th className="px-5 py-3">Email</th>
                <th className="px-5 py-3">姓名</th>
                <th className="px-5 py-3">角色</th>
                <th className="px-5 py-3">狀態</th>
                <th className="px-5 py-3">加入時間</th>
                <th className="px-5 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map((u: any) => (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 text-sm text-gray-900">{u.email}</td>
                  <td className="px-5 py-3 text-sm text-gray-600">{u.full_name || '—'}</td>
                  <td className="px-5 py-3">
                    {editingId === u.id ? (
                      <div className="flex items-center gap-1">
                        <select
                          value={editRole}
                          onChange={e => setEditRole(e.target.value)}
                          className="rounded border border-gray-300 px-2 py-1 text-xs"
                        >
                          {roles.map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                        <button onClick={() => handleUpdateRole(u.id)} className="text-xs text-blue-600 hover:underline">確定</button>
                        <button onClick={() => setEditingId(null)} className="text-xs text-gray-400 hover:underline">取消</button>
                      </div>
                    ) : (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">{u.role}</span>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex items-center gap-1 text-xs font-medium ${u.status === 'active' ? 'text-green-600' : 'text-red-500'}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${u.status === 'active' ? 'bg-green-500' : 'bg-red-400'}`} />
                      {u.status || 'active'}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-xs text-gray-500">{u.created_at ? new Date(u.created_at).toLocaleDateString('zh-TW') : '—'}</td>
                  <td className="px-5 py-3 text-right">
                    <div className="relative inline-block">
                      <DropdownMenu
                        onEdit={() => { setEditingId(u.id); setEditRole(u.role || 'employee') }}
                        onDeactivate={() => handleDeactivate(u.id)}
                        disabled={u.role === 'owner'}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function DropdownMenu({ onEdit, onDeactivate, disabled }: { onEdit: () => void; onDeactivate: () => void; disabled: boolean }) {
  const [open, setOpen] = useState(false)
  if (disabled) return <span className="text-xs text-gray-300">—</span>
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="rounded p-1 hover:bg-gray-100">
        <MoreVertical className="h-4 w-4 text-gray-400" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 w-32 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
            <button onClick={() => { onEdit(); setOpen(false) }} className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50">變更角色</button>
            <button onClick={() => { onDeactivate(); setOpen(false) }} className="block w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50">停用帳號</button>
          </div>
        </>
      )}
    </div>
  )
}

function DeploymentTab() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState<'gpu' | 'nogpu'>('nogpu')
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setMsg('')
    try {
      const data = await companyApi.getDeploymentMode()
      setMode((data?.mode || 'nogpu') as 'gpu' | 'nogpu')
    } catch {
      setMsg('無法讀取部署模式')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const switchMode = async (next: 'gpu' | 'nogpu') => {
    if (next === mode) return
    setSaving(true)
    setMsg('')
    try {
      await companyApi.setDeploymentMode(next)
      setMode(next)
      setMsg(`已切換為 ${next === 'gpu' ? 'GPU 模式' : '無 GPU 模式'}（下一次請求立即生效）`)
    } catch (err: any) {
      setMsg(err.response?.data?.detail || '切換失敗')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Loader />

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-gray-800">部署模式切換（固定策略）</h3>
        <p className="mt-1 text-sm text-gray-500">切換後會套用固定 LLM preset；不提供自由選模型，避免誤設。</p>

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <button
            disabled={saving}
            onClick={() => switchMode('nogpu')}
            className={`rounded-xl border p-4 text-left transition ${mode === 'nogpu' ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'} disabled:opacity-60`}
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-800"><Cloud className="h-4 w-4" /> 無 GPU（目前雲端設定）</div>
            <div className="mt-2 text-xs text-gray-600">①② Gemini、③④ Gemini Flash-Lite；其餘維持目前 .env 設定</div>
          </button>

          <button
            disabled={saving}
            onClick={() => switchMode('gpu')}
            className={`rounded-xl border p-4 text-left transition ${mode === 'gpu' ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'} disabled:opacity-60`}
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-800"><Cpu className="h-4 w-4" /> 有 GPU（固定本地）</div>
            <div className="mt-2 text-xs text-gray-600">主模型固定 qwen3.5:27b；內部改寫/掃描固定 qwen3:14b；Embedding 固定 bge-m3:latest</div>
          </button>
        </div>

        {msg && (
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{msg}</div>
        )}
      </div>
    </div>
  )
}

// ─── Usage Tab moved to unified UsagePage ───

// ═══ Main Page ═══
export default function CompanyPage() {
  const [tab, setTab] = useState<Tab>('dashboard')

  const tabs: { key: Tab; label: string; icon: typeof Building2 }[] = [
    { key: 'dashboard', label: '總覽', icon: Building2 },
    { key: 'users', label: '成員管理', icon: Users },
    { key: 'deployment', label: '部署模式', icon: Cpu },
  ]

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center gap-2">
          <Building2 className="h-5 w-5 text-blue-600" />
          <h1 className="text-lg font-semibold text-gray-900">公司管理</h1>
        </div>
        <div className="mt-3 flex gap-1">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                tab === t.key ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              <t.icon className="h-4 w-4" /> {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {tab === 'dashboard' && <DashboardTab />}
        {tab === 'users' && <UsersTab />}
        {tab === 'deployment' && <DeploymentTab />}
      </div>
    </div>
  )
}
