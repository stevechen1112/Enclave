/**
 * Knowledge sources hub — NAS + folder monitoring (V1 certified path only)
 * Steps: path → scope → department/review → check → enable (UIUX §9.6)
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FolderOpen, Pause, Play, Plug, Plus, RefreshCw, Square } from 'lucide-react'
import api, { parseApiError, formatErrorWithTrace, type ApiErrorInfo } from '../../api'
import toast from 'react-hot-toast'
import AsyncState from '../../components/AsyncState'
import SourceHealth from '../../components/SourceHealth'
import PageHeader from '../../components/PageHeader'
import clsx from 'clsx'

type Connector = {
  id: string
  connector_type: string
  name: string
  status: string
  last_sync_at?: string | null
  last_error?: string | null
}

type WatchFolder = {
  id: string
  folder_path: string
  display_name: string | null
  is_active: boolean
  last_scan_at: string | null
  total_files_watched: number
}

type AgentStatus = {
  watcher_running: boolean
  scheduler_running: boolean
  active_folders: number
  pending_review_count: number
}

const STEPS = ['路徑', '掃描範圍', '部門與審核', '檢查路徑', '啟用'] as const

export default function SourcesPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [folders, setFolders] = useState<WatchFolder[]>([])
  const [agent, setAgent] = useState<AgentStatus | null>(null)
  const [busy, setBusy] = useState(false)

  const [step, setStep] = useState(0)
  const [name, setName] = useState('NAS 分享')
  const [rootPath, setRootPath] = useState('')
  const [maxFiles, setMaxFiles] = useState(200)
  const [departmentHint, setDepartmentHint] = useState('')
  const [requireReview, setRequireReview] = useState(true)
  const [testOk, setTestOk] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, f, s] = await Promise.allSettled([
        api.get<Connector[]>('/connectors/'),
        api.get<WatchFolder[]>('/agent/folders'),
        api.get<AgentStatus>('/agent/status'),
      ])
      if (c.status === 'fulfilled') {
        setConnectors(c.value.data.filter(x => x.connector_type === 'nas_smb'))
      } else {
        setError(parseApiError(c.reason, '無法載入來源'))
      }
      if (f.status === 'fulfilled') setFolders(f.value.data)
      if (s.status === 'fulfilled') setAgent(s.value.data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const createNas = async () => {
    if (!rootPath.trim() || !testOk) return
    setBusy(true)
    try {
      await api.post('/connectors/', {
        connector_type: 'nas_smb',
        name: name || 'NAS 分享',
        config: {
          root_path: rootPath,
          principal_external_id: 'nas-local-reader',
          max_files: maxFiles,
          department_hint: departmentHint || undefined,
          require_review: requireReview,
        },
      })
      toast.success('NAS 來源已建立並可同步')
      setRootPath('')
      setTestOk(false)
      setStep(0)
      await load()
    } catch (e: unknown) {
      toast.error(formatErrorWithTrace(parseApiError(e, '建立失敗')))
    } finally {
      setBusy(false)
    }
  }

  const runTest = async () => {
    if (!rootPath.trim()) {
      toast.error('請先填寫路徑')
      return
    }
    setBusy(true)
    try {
      // 僅前端格式檢查；後端目前無即時連線測試端點，實際連線於啟用後首次同步時驗證
      const ok = rootPath.trim().length >= 3
      setTestOk(ok)
      if (ok) toast.success('路徑格式正確（實際連線會在啟用後首次同步時驗證）')
      else toast.error('路徑過短，請確認')
    } finally {
      setBusy(false)
    }
  }

  const sync = async (id: string) => {
    setBusy(true)
    try {
      await api.post(`/connectors/${id}/sync`)
      toast.success('已觸發同步')
      await load()
    } catch (e: unknown) {
      toast.error(formatErrorWithTrace(parseApiError(e, '同步失敗')))
    } finally {
      setBusy(false)
    }
  }

  const pauseResume = async (id: string, action: 'pause' | 'resume') => {
    setBusy(true)
    try {
      await api.post(`/connectors/${id}/${action}`)
      toast.success(action === 'pause' ? '已暫停此來源' : '已恢復此來源')
      await load()
    } catch (e: unknown) {
      toast.error(formatErrorWithTrace(parseApiError(e, action === 'pause' ? '暫停失敗' : '恢復失敗')))
    } finally {
      setBusy(false)
    }
  }

  const toggleMonitor = async () => {
    setBusy(true)
    try {
      if (agent?.watcher_running) await api.post('/agent/stop')
      else await api.post('/agent/start')
      await load()
    } catch (e) {
      toast.error(formatErrorWithTrace(parseApiError(e, '無法切換監控')))
    } finally {
      setBusy(false)
    }
  }

  const canNext =
    (step === 0 && !!rootPath.trim()) ||
    (step === 1 && maxFiles > 0) ||
    step === 2 ||
    (step === 3 && testOk) ||
    step === 4

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8">
      <div className="mx-auto max-w-4xl space-y-8">
        <PageHeader
          variant="section"
          title="來源"
          subtitle="V1 已認證：手動上傳（文件頁）與 NAS／監控資料夾。SharePoint、Google Drive 尚未認證。"
          actions={(
            <>
              <Link to="/knowledge/documents" className="btn-primary">
                手動上傳文件
              </Link>
              <button
                type="button"
                onClick={load}
                className="btn-outline"
                aria-label="重新整理來源"
              >
                <RefreshCw className="h-4 w-4" aria-hidden /> 重新整理
              </button>
            </>
          )}
        />

        <AsyncState loading={loading} error={error} onRetry={load}>
          <>
            <section className="card space-y-4 p-5">
              <div className="flex items-center gap-2">
                <Plug className="h-5 w-5 text-accent" aria-hidden />
                <h2 className="font-semibold text-ink">新增 NAS／本機路徑</h2>
              </div>

              <ol className="flex flex-wrap gap-2" aria-label="建立步驟">
                {STEPS.map((label, i) => (
                  <li
                    key={label}
                    className={clsx(
                      i === step ? 'chip-accent' : i < step ? 'chip-success' : 'chip-neutral',
                    )}
                  >
                    {i + 1}. {label}
                  </li>
                ))}
              </ol>

              {step === 0 && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label htmlFor="src-name" className="input-label">名稱</label>
                    <input
                      id="src-name"
                      className="input"
                      placeholder="名稱"
                      value={name}
                      onChange={e => setName(e.target.value)}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label htmlFor="src-path" className="input-label">根路徑</label>
                    <input
                      id="src-path"
                      className="input"
                      placeholder="本機或 UNC 路徑，例如 C:\shares\docs"
                      value={rootPath}
                      onChange={e => { setRootPath(e.target.value); setTestOk(false) }}
                    />
                  </div>
                </div>
              )}
              {step === 1 && (
                <div>
                  <label htmlFor="src-max" className="input-label">最大掃描檔案數</label>
                  <input
                    id="src-max"
                    type="number"
                    min={1}
                    max={5000}
                    className="input"
                    value={maxFiles}
                    onChange={e => setMaxFiles(Number(e.target.value) || 200)}
                  />
                </div>
              )}
              {step === 2 && (
                <div className="space-y-3 text-sm">
                  <div>
                    <label htmlFor="src-dept" className="input-label">部門提示（選填）</label>
                    <input
                      id="src-dept"
                      className="input"
                      value={departmentHint}
                      onChange={e => setDepartmentHint(e.target.value)}
                      placeholder="例如：人資／法務"
                    />
                  </div>
                  <label className="flex min-h-11 items-center gap-2">
                    <input
                      type="checkbox"
                      checked={requireReview}
                      onChange={e => setRequireReview(e.target.checked)}
                      className="h-5 w-5"
                    />
                    入庫前需審核（建議開啟）
                  </label>
                </div>
              )}
              {step === 3 && (
                <div className="space-y-3">
                  <p className="text-sm text-muted">路徑：<span className="font-mono text-ink">{rootPath || '—'}</span></p>
                  <p className="rounded-xl bg-wash px-3 py-2 text-sm text-muted">
                    這一步只檢查路徑格式是否正確，還不會真的連線；實際連線會在啟用後首次同步時驗證。
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={runTest}
                    className="btn-outline"
                  >
                    檢查路徑格式
                  </button>
                  {testOk && <p className="text-sm text-success">格式正確，可進入啟用</p>}
                </div>
              )}
              {step === 4 && (
                <div className="space-y-3 text-sm text-muted">
                  <p>將建立來源「{name}」，路徑 {rootPath}，掃描上限 {maxFiles}。</p>
                  <p>審核：{requireReview ? '需要' : '略過'} · 部門提示：{departmentHint || '無'}</p>
                  <button
                    type="button"
                    disabled={busy || !testOk}
                    onClick={createNas}
                    className="btn-primary"
                  >
                    <Plus className="h-4 w-4" aria-hidden /> 啟用來源
                  </button>
                </div>
              )}

              <div className="flex justify-between gap-2">
                <button
                  type="button"
                  disabled={step === 0 || busy}
                  onClick={() => setStep(s => Math.max(0, s - 1))}
                  className="btn-outline"
                >
                  上一步
                </button>
                {step < 4 && (
                  <button
                    type="button"
                    disabled={!canNext || busy}
                    onClick={() => setStep(s => Math.min(4, s + 1))}
                    className="btn-primary"
                  >
                    下一步
                  </button>
                )}
              </div>
            </section>

            <section className="space-y-3">
              <h2 className="font-semibold text-ink">已建立來源</h2>
              {connectors.length === 0 ? (
                <p className="card p-6 text-sm text-muted">尚未建立 NAS 來源</p>
              ) : (
                connectors.map(c => (
                  <SourceHealth
                    key={c.id}
                    data={{
                      name: c.name,
                      status: c.status,
                      lastSuccessAt: c.last_sync_at,
                      failureReason: c.last_error,
                    }}
                    actions={(
                      <div className="flex gap-1">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => sync(c.id)}
                          className="btn-outline px-3"
                          aria-label={`同步 ${c.name}`}
                        >
                          <RefreshCw className="h-4 w-4" aria-hidden /> 同步
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => pauseResume(c.id, 'pause')}
                          className="icon-btn"
                          aria-label={`暫停 ${c.name}`}
                        >
                          <Pause className="h-4 w-4" aria-hidden />
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => pauseResume(c.id, 'resume')}
                          className="icon-btn"
                          aria-label={`恢復 ${c.name}`}
                        >
                          <Play className="h-4 w-4" aria-hidden />
                        </button>
                      </div>
                    )}
                  />
                ))
              )}
            </section>

            <section className="card space-y-4 p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <FolderOpen className="h-5 w-5 text-accent" aria-hidden />
                  <div>
                    <h2 className="font-semibold text-ink">監控資料夾</h2>
                    <p className="text-sm text-muted">啟用後自動發現新檔並送入審核（若已開啟審核佇列）</p>
                  </div>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={toggleMonitor}
                  className={agent?.watcher_running ? 'btn-danger' : 'btn-primary'}
                >
                  {agent?.watcher_running ? (
                    <><Square className="h-4 w-4" aria-hidden /> 停止監控</>
                  ) : (
                    <><Play className="h-4 w-4" aria-hidden /> 啟用監控</>
                  )}
                </button>
              </div>

              <ul className="divide-y divide-line/70 rounded-2xl border border-line">
                {folders.length === 0 && (
                  <li className="px-4 py-6 text-sm text-muted">尚未設定監控資料夾。</li>
                )}
                {folders.map(f => (
                  <li key={f.id} className="px-4 py-3 text-sm">
                    <p className="font-medium text-ink">{f.display_name || f.folder_path}</p>
                    {f.display_name && <p className="font-mono text-xs text-muted">{f.folder_path}</p>}
                    <p className="mt-1 text-sm text-muted">
                      {f.is_active ? '啟用' : '停用'} · 已掃描 {f.total_files_watched}
                      {f.last_scan_at && ` · 上次 ${new Date(f.last_scan_at).toLocaleDateString()}`}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="text-sm text-muted">
                <Link to="/advanced/agent-wizard" className="text-accent underline-offset-2 hover:underline">
                  開啟監控資料夾進階精靈
                </Link>
              </p>
            </section>
          </>
        </AsyncState>
      </div>
    </div>
  )
}
