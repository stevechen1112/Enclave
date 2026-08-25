/**
 * 租戶設定中心（Phase 5）— 職能／任務／模組／版型／簽核。
 *
 * 安全角色（系統權限）與業務職能（工作內容）分離管理；
 * 這裡是租戶管理員設定「職能」與「任務」的地方。
 */
import { useCallback, useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import api from '../../api'
import { formsApi } from '../../services/mka'
import {
  tenantAdminApi,
  type ApprovalPolicyRow,
  type JobRole,
  type JobRoleAssignment,
  type ModuleBindingInfo,
  type TaskDefinitionRow,
} from '../../services/tenantAdmin'

type Tab = 'roles' | 'tasks' | 'modules' | 'templates' | 'approvals' | 'metrics'

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'roles', label: '職能管理' },
  { key: 'tasks', label: '任務定義' },
  { key: 'modules', label: '模組設定' },
  { key: 'templates', label: '公司版型' },
  { key: 'approvals', label: '簽核政策' },
  { key: 'metrics', label: '使用指標' },
]

export default function TenantAdminPage() {
  const [tab, setTab] = useState<Tab>('roles')

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4 overflow-y-auto p-4 pb-8">
      <header>
        <h1 className="text-2xl font-bold text-ink">租戶設定中心</h1>
        <p className="mt-1 text-base text-muted">
          管理這家公司的職能、任務、模組、版型與簽核流程。
        </p>
      </header>

      <nav aria-label="設定分類" className="flex flex-wrap gap-2">
        {TABS.map(t => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            aria-pressed={tab === t.key}
            className={`min-h-11 rounded-xl border-2 px-4 text-base font-medium ${
              tab === t.key
                ? 'border-accent bg-accent text-white'
                : 'border-line bg-surface text-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'roles' && <RolesSection />}
      {tab === 'tasks' && <TasksSection />}
      {tab === 'modules' && <ModulesSection />}
      {tab === 'templates' && <TemplatesSection />}
      {tab === 'approvals' && <ApprovalsSection />}
      {tab === 'metrics' && <MetricsSection />}
    </div>
  )
}

/* ── 使用指標（Phase 7）── */

type MetricsSummary = {
  total_runs: number
  by_status: Record<string, number>
  completion_rate: number | null
  error_rate: number | null
  manual_edit_rate: number | null
  field_source_distribution: Record<string, number>
  approval_decided_count: number
  approval_cycle_hours_avg: number | null
  event_count: number
}

function MetricsSection() {
  const [m, setM] = useState<MetricsSummary | null>(null)

  useEffect(() => {
    api
      .get<MetricsSummary>('/tasks/metrics/summary')
      .then(r => setM(r.data))
      .catch(() => toast.error('指標載入失敗'))
  }, [])

  if (!m) return <p className="text-muted">載入中…</p>

  const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

  return (
    <section aria-label="使用指標" className="rounded-2xl border-2 border-line bg-surface p-5">
      <h2 className="text-lg font-bold text-ink">任務使用指標</h2>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label="任務總數" value={String(m.total_runs)} />
        <MetricCard label="完成率" value={pct(m.completion_rate)} />
        <MetricCard label="手動修改率" value={pct(m.manual_edit_rate)} />
        <MetricCard label="錯誤率" value={pct(m.error_rate)} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-line p-3">
          <h3 className="font-bold text-ink">欄位來源分布</h3>
          <ul className="mt-2 text-sm">
            {Object.entries(m.field_source_distribution).map(([src, n]) => (
              <li key={src} className="flex justify-between">
                <span>{src}</span>
                <span className="text-muted">{n}</span>
              </li>
            ))}
            {Object.keys(m.field_source_distribution).length === 0 && (
              <li className="text-muted">尚無資料</li>
            )}
          </ul>
        </div>
        <div className="rounded-xl border border-line p-3">
          <h3 className="font-bold text-ink">簽核效率</h3>
          <p className="mt-2 text-sm">
            已決議簽核：{m.approval_decided_count} 件
            <br />
            平均耗時：
            {m.approval_cycle_hours_avg === null
              ? '—'
              : `${m.approval_cycle_hours_avg} 小時`}
          </p>
        </div>
      </div>
    </section>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line p-3 text-center">
      <div className="text-2xl font-bold text-ink">{value}</div>
      <div className="text-sm text-muted">{label}</div>
    </div>
  )
}

/* ── 職能管理 ── */

function RolesSection() {
  const [roles, setRoles] = useState<JobRole[]>([])
  const [assignments, setAssignments] = useState<JobRoleAssignment[]>([])
  const [users, setUsers] = useState<Array<{ id: string; email: string; full_name?: string }>>([])
  const [modules, setModules] = useState<ModuleBindingInfo[]>([])
  const [newKey, setNewKey] = useState('')
  const [newName, setNewName] = useState('')
  const [assignUser, setAssignUser] = useState('')
  const [assignRole, setAssignRole] = useState('')

  const reload = useCallback(async () => {
    try {
      const [r, a, u, m] = await Promise.all([
        tenantAdminApi.listJobRoles(),
        tenantAdminApi.listAssignments(),
        tenantAdminApi.listUsers().catch(() => []),
        tenantAdminApi.listModules(),
      ])
      setRoles(r)
      setAssignments(a)
      setUsers(Array.isArray(u) ? u : [])
      setModules(m)
    } catch {
      toast.error('載入失敗')
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload()
  }, [reload])

  const userLabel = (id: string) => {
    const u = users.find(x => x.id === id)
    return u ? u.full_name || u.email : id.slice(0, 8)
  }

  return (
    <div className="flex flex-col gap-6">
      <section aria-label="職能清單" className="rounded-2xl border-2 border-line bg-surface p-5">
        <h2 className="text-lg font-bold text-ink">職能清單</h2>
        <ul className="mt-3 flex flex-col gap-3">
          {roles.map(r => (
            <li key={r.id} className="rounded-xl border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-bold text-ink">{r.name}</span>
                  <span className="ml-2 text-sm text-muted">{r.role_key}</span>
                  {!r.active && (
                    <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs">已停用</span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    await tenantAdminApi.updateJobRole(r.id, { active: !r.active })
                    reload()
                  }}
                  className="rounded-lg border border-line px-3 py-1 text-sm"
                >
                  {r.active ? '停用' : '啟用'}
                </button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {modules.map(m => {
                  const on = r.default_module_keys.includes(m.module_key)
                  return (
                    <button
                      key={m.module_key}
                      type="button"
                      aria-pressed={on}
                      onClick={async () => {
                        const next = on
                          ? r.default_module_keys.filter(k => k !== m.module_key)
                          : [...r.default_module_keys, m.module_key]
                        await tenantAdminApi.updateJobRole(r.id, { default_module_keys: next })
                        reload()
                      }}
                      className={`rounded-full px-3 py-1 text-xs ${
                        on ? 'bg-accent text-white' : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {m.name || m.module_key}
                    </button>
                  )
                })}
              </div>
            </li>
          ))}
        </ul>

        <div className="mt-4 flex flex-wrap gap-2">
          <input
            value={newKey}
            onChange={e => setNewKey(e.target.value)}
            placeholder="role_key（如 purchasing）"
            className="min-h-10 rounded-lg border border-line px-3"
          />
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="顯示名稱（如 採購）"
            className="min-h-10 rounded-lg border border-line px-3"
          />
          <button
            type="button"
            disabled={!newKey.trim() || !newName.trim()}
            onClick={async () => {
              try {
                await tenantAdminApi.createJobRole({
                  role_key: newKey.trim(),
                  name: newName.trim(),
                })
                setNewKey('')
                setNewName('')
                toast.success('已建立職能')
                reload()
              } catch {
                toast.error('建立失敗（role_key 可能重複）')
              }
            }}
            className="min-h-10 rounded-lg bg-accent px-4 text-white disabled:opacity-40"
          >
            新增職能
          </button>
        </div>
      </section>

      <section aria-label="職能指派" className="rounded-2xl border-2 border-line bg-surface p-5">
        <h2 className="text-lg font-bold text-ink">職能指派</h2>
        <ul className="mt-3 flex flex-col gap-2">
          {assignments.filter(a => a.active).map(a => (
            <li key={a.id} className="flex items-center justify-between rounded-xl border border-line p-3">
              <span>
                {userLabel(a.user_id)} → {a.role?.name || a.job_role_id.slice(0, 8)}
                {a.is_primary && (
                  <span className="ml-2 rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-800">主要</span>
                )}
              </span>
              <button
                type="button"
                onClick={async () => {
                  await tenantAdminApi.deactivateAssignment(a.id)
                  reload()
                }}
                className="rounded-lg border border-line px-3 py-1 text-sm text-red-600"
              >
                移除
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex flex-wrap gap-2">
          <select
            value={assignUser}
            onChange={e => setAssignUser(e.target.value)}
            className="min-h-10 rounded-lg border border-line px-3"
          >
            <option value="">選擇使用者</option>
            {users.map(u => (
              <option key={u.id} value={u.id}>{u.full_name || u.email}</option>
            ))}
          </select>
          <select
            value={assignRole}
            onChange={e => setAssignRole(e.target.value)}
            className="min-h-10 rounded-lg border border-line px-3"
          >
            <option value="">選擇職能</option>
            {roles.filter(r => r.active).map(r => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
          <button
            type="button"
            disabled={!assignUser || !assignRole}
            onClick={async () => {
              try {
                await tenantAdminApi.assign({ user_id: assignUser, job_role_id: assignRole })
                toast.success('已指派')
                setAssignUser('')
                setAssignRole('')
                reload()
              } catch {
                toast.error('指派失敗')
              }
            }}
            className="min-h-10 rounded-lg bg-accent px-4 text-white disabled:opacity-40"
          >
            指派
          </button>
        </div>
      </section>
    </div>
  )
}

/* ── 任務定義 ── */

function TasksSection() {
  const [rows, setRows] = useState<TaskDefinitionRow[]>([])

  const reload = useCallback(async () => {
    try {
      setRows(await tenantAdminApi.listTaskDefinitions())
    } catch {
      toast.error('載入失敗')
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  // 每個 task_key 取全域 + 租戶覆寫併列
  const grouped = rows.reduce<Record<string, TaskDefinitionRow[]>>((acc, r) => {
    ;(acc[r.task_key] ||= []).push(r)
    return acc
  }, {})

  return (
    <section aria-label="任務定義" className="rounded-2xl border-2 border-line bg-surface p-5">
      <h2 className="text-lg font-bold text-ink">任務定義</h2>
      <p className="mt-1 text-sm text-muted">
        全域定義由平台維護；租戶可建立覆寫版本調整適用職能與風險等級。
      </p>
      <ul className="mt-3 flex flex-col gap-3">
        {Object.entries(grouped).map(([key, defs]) => {
          const tenantDef = defs.find(d => d.scope === 'tenant')
          const globalDef = defs.find(d => d.scope === 'global')
          const shown = tenantDef || globalDef
          if (!shown) return null
          return (
            <li key={key} className="rounded-xl border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-bold text-ink">{shown.name}</span>
                  <span className="ml-2 text-sm text-muted">{key}</span>
                  <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                    {tenantDef ? `租戶覆寫 v${tenantDef.version}` : `全域 v${shown.version}`}
                  </span>
                  <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
                    shown.status === 'enabled' ? 'bg-green-100 text-green-800' : 'bg-slate-100'
                  }`}>
                    {shown.status}
                  </span>
                </div>
                <div className="flex gap-2">
                  {!tenantDef && (
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await tenantAdminApi.overrideTaskDefinition(key, {})
                          toast.success('已建立租戶覆寫')
                          reload()
                        } catch {
                          toast.error('建立覆寫失敗')
                        }
                      }}
                      className="rounded-lg border border-line px-3 py-1 text-sm"
                    >
                      建立覆寫
                    </button>
                  )}
                  {tenantDef && (
                    <button
                      type="button"
                      onClick={async () => {
                        await tenantAdminApi.setTaskDefinitionStatus(
                          tenantDef.id,
                          tenantDef.status === 'enabled' ? 'disabled' : 'enabled',
                        )
                        reload()
                      }}
                      className="rounded-lg border border-line px-3 py-1 text-sm"
                    >
                      {tenantDef.status === 'enabled' ? '停用覆寫' : '啟用覆寫'}
                    </button>
                  )}
                </div>
              </div>
              <p className="mt-1 text-sm text-muted">
                適用職能：{shown.applicable_job_role_keys.length
                  ? shown.applicable_job_role_keys.join('、')
                  : '不限'}
                {'　'}風險：{shown.risk_level}
              </p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/* ── 模組設定 ── */

function ModulesSection() {
  const [modules, setModules] = useState<ModuleBindingInfo[]>([])
  const [configJson, setConfigJson] = useState<Record<string, string>>({})

  const reload = useCallback(async () => {
    try {
      setModules(await tenantAdminApi.listModules())
    } catch {
      toast.error('載入失敗')
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload()
  }, [reload])

  return (
    <section aria-label="模組設定" className="rounded-2xl border-2 border-line bg-surface p-5">
      <h2 className="text-lg font-bold text-ink">模組設定</h2>
      <p className="mt-1 text-sm text-muted">
        新租戶預設不啟用任何模組；在此逐個 opt-in，並可覆寫公司專屬設定（版本化）。
      </p>
      <ul className="mt-3 flex flex-col gap-3">
        {modules.map(m => (
          <li key={m.module_key} className="rounded-xl border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="font-bold text-ink">{m.name || m.module_key}</span>
                <span className="ml-2 text-sm text-muted">{m.module_key}</span>
                {m.bound && (
                  <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                    config v{m.config_version}
                  </span>
                )}
              </div>
              <button
                type="button"
                aria-pressed={m.enabled}
                onClick={async () => {
                  await tenantAdminApi.setBinding(m.module_key, !m.enabled)
                  reload()
                }}
                className={`rounded-lg px-3 py-1 text-sm ${
                  m.enabled ? 'bg-green-700 text-white' : 'border border-line'
                }`}
              >
                {m.enabled ? '已啟用' : '啟用'}
              </button>
            </div>
            {m.enabled && (
              <details className="mt-2">
                <summary className="cursor-pointer text-sm text-accent">覆寫設定（JSON）</summary>
                <div className="mt-2 flex flex-col gap-2">
                  <textarea
                    rows={4}
                    value={configJson[m.module_key] ?? ''}
                    onChange={e =>
                      setConfigJson(prev => ({ ...prev, [m.module_key]: e.target.value }))
                    }
                    placeholder='{"tax_rate": 5}'
                    className="w-full rounded-lg border border-line p-2 font-mono text-sm"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          const parsed = JSON.parse(configJson[m.module_key] || '{}')
                          const result = await tenantAdminApi.updateConfig(m.module_key, parsed)
                          toast.success(`已儲存（config v${result.config_version}）`)
                          reload()
                        } catch (err) {
                          const detail = (err as { response?: { data?: { detail?: string } } })
                            ?.response?.data?.detail
                          toast.error(detail || 'JSON 格式或 schema 驗證失敗')
                        }
                      }}
                      className="rounded-lg bg-accent px-3 py-1 text-sm text-white"
                    >
                      儲存設定
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        const eff = await tenantAdminApi.effectiveConfig(m.module_key)
                        setConfigJson(prev => ({
                          ...prev,
                          [m.module_key]: JSON.stringify(eff.overrides, null, 2),
                        }))
                      }}
                      className="rounded-lg border border-line px-3 py-1 text-sm"
                    >
                      載入目前覆寫
                    </button>
                  </div>
                </div>
              </details>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

/* ── 公司版型 ── */

function TemplatesSection() {
  const [templates, setTemplates] = useState<Array<Record<string, unknown>>>([])

  useEffect(() => {
    formsApi
      .listTemplates()
      .then(rows => setTemplates(rows))
      .catch(() => toast.error('版型載入失敗'))
  }, [])

  return (
    <section aria-label="公司版型" className="rounded-2xl border-2 border-line bg-surface p-5">
      <h2 className="text-lg font-bold text-ink">公司版型</h2>
      <p className="mt-1 text-sm text-muted">
        公司上傳的 DOCX／XLSX 版型；匯出時以此為準。
      </p>
      {templates.length === 0 ? (
        <p className="mt-3 text-muted">尚未上傳版型。可透過 /forms/templates API 上傳。</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {templates.map(t => (
            <li key={String(t.id)} className="rounded-xl border border-line p-3">
              <span className="font-bold text-ink">{String(t.name)}</span>
              <span className="ml-2 text-sm text-muted">
                {String(t.form_key)}・{String(t.format)}・v{String(t.version)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/* ── 簽核政策 ── */

function ApprovalsSection() {
  const [policies, setPolicies] = useState<ApprovalPolicyRow[]>([])
  const [objectType, setObjectType] = useState('form')
  const [moduleKey, setModuleKey] = useState('')
  const [riskLevel, setRiskLevel] = useState('medium')

  const reload = useCallback(async () => {
    try {
      setPolicies(await tenantAdminApi.listApprovalPolicies())
    } catch {
      toast.error('載入失敗')
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload()
  }, [reload])

  return (
    <section aria-label="簽核政策" className="rounded-2xl border-2 border-line bg-surface p-5">
      <h2 className="text-lg font-bold text-ink">簽核政策</h2>
      <ul className="mt-3 flex flex-col gap-2">
        {policies.map(p => (
          <li key={p.id} className="rounded-xl border border-line p-3">
            <span className="font-bold text-ink">{p.object_type}</span>
            <span className="ml-2 text-sm text-muted">
              {p.module_key || '全部模組'}・風險 {p.risk_level}・{p.status}
            </span>
          </li>
        ))}
        {policies.length === 0 && (
          <p className="text-muted">尚未設定政策；系統會使用預設單級簽核。</p>
        )}
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <select
          value={objectType}
          onChange={e => setObjectType(e.target.value)}
          className="min-h-10 rounded-lg border border-line px-3"
        >
          <option value="form">表單</option>
          <option value="knowhow">知識卡</option>
          <option value="tool">工具</option>
        </select>
        <input
          value={moduleKey}
          onChange={e => setModuleKey(e.target.value)}
          placeholder="模組（留空 = 全部）"
          className="min-h-10 rounded-lg border border-line px-3"
        />
        <select
          value={riskLevel}
          onChange={e => setRiskLevel(e.target.value)}
          className="min-h-10 rounded-lg border border-line px-3"
        >
          <option value="low">低風險</option>
          <option value="medium">中風險</option>
          <option value="high">高風險</option>
        </select>
        <button
          type="button"
          onClick={async () => {
            try {
              await tenantAdminApi.upsertApprovalPolicy({
                object_type: objectType,
                module_key: moduleKey || null,
                risk_level: riskLevel,
              })
              toast.success('已儲存政策')
              reload()
            } catch {
              toast.error('儲存失敗')
            }
          }}
          className="min-h-10 rounded-lg bg-accent px-4 text-white"
        >
          儲存政策
        </button>
      </div>
    </section>
  )
}
