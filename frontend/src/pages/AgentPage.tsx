import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import api, { docApi, agentApi } from '../api'
import { useAuth } from '../auth'
import {
  FolderOpen,
  Play,
  Square,
  RefreshCw,
  Settings,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Plus,
  Loader2,
  AlertCircle,
  CheckCircle,
  Clock,
  FileText,
  BarChart2,
  XCircle,
  Download,
} from 'lucide-react'
import clsx from 'clsx'

// Wizard sub-components
import WizardStepSelect from './wizard/WizardStepSelect'
import WizardStepScanning from './wizard/WizardStepScanning'
import WizardStepConfirm from './wizard/WizardStepConfirm'
import { WizardStepImporting, WizardStepDone } from './wizard/WizardStepImport'
import type { WizardStep, FileWithPath, AddedFolder, SubfolderRow } from './wizard/types'

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentStatus {
  watcher_running: boolean
  scheduler_running: boolean
  active_folders: number
  pending_review_count: number
}

interface WatchFolder {
  id: string
  folder_path: string
  display_name: string | null
  is_active: boolean
  recursive: boolean
  last_scan_at: string | null
  total_files_watched: number
}

// ── Wizard Types (re-exported from ./wizard/types) ───────────────────────────
// Using: WizardStep, FileWithPath, AddedFolder, SubfolderRow from imports above

// Text-readable extensions for content sampling
const TEXT_EXT = new Set(['.txt', '.md', '.csv', '.json', '.html', '.htm', '.xml', '.yaml', '.yml', '.log', '.rst', '.tsv'])

/** Extract lowercase extension from filename. Returns '' if no dot present. */
function getFileExt(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot).toLowerCase() : ''   // dot at 0 = dotfile like .gitignore
}

async function readTextSample(file: File, maxChars = 600): Promise<string> {
  return new Promise(resolve => {
    const reader = new FileReader()
    reader.onload = e => {
      const text = (e.target?.result as string) || ''
      resolve(text.slice(0, maxChars))
    }
    reader.onerror = () => resolve('')
    reader.readAsText(file, 'utf-8')
  })
}

function buildSubfolderRows(
  addedFolders: AddedFolder[],
  supportedExts: Set<string>,
): { rows: SubfolderRow[]; skippedCount: number; skippedExtNames: string[] } {
  const dirFiles = new Map<string, FileWithPath[]>()
  let skippedCount = 0
  const skippedExtSet = new Set<string>()

  for (const folder of addedFolders) {
    for (const file of folder.files) {
      const rel = file.webkitRelativePath
      const parts = rel.split('/')
      if (parts.length < 2) continue
      const ext = getFileExt(file.name)
      if (!ext || !supportedExts.has(ext)) {
        if (ext) {
          skippedCount++
          skippedExtSet.add(ext)
        }
        continue
      }
      const dirPath = parts.slice(0, -1).join('/')
      if (!dirFiles.has(dirPath)) dirFiles.set(dirPath, [])
      dirFiles.get(dirPath)!.push(file)
    }
  }

  const rows = Array.from(dirFiles.entries())
    .map(([path, files]) => {
      const parts = path.split('/')
      return {
        path,
        name: parts[parts.length - 1],
        depth: parts.length - 1,
        fileCount: files.length,
        summary: '',
        hasContentSamples: false,
        expanded: false,
        selected: true,
        files,
      }
    })
    .sort((a, b) => a.path.localeCompare(b.path))

  return { rows, skippedCount, skippedExtNames: Array.from(skippedExtSet).sort() }
}

// ── Folder Import Wizard ──────────────────────────────────────────────────────

function FolderImportWizard({
  onClose,
  onAdded,
}: {
  onClose: () => void
  onAdded: () => void
}) {
  const [step, setStep] = useState<WizardStep>('select')
  const [addedFolders, setAddedFolders] = useState<AddedFolder[]>([])
  const [subfolders, setSubfolders] = useState<SubfolderRow[]>([])
  const [scanError, setScanError] = useState('')
  const [scanStatus, setScanStatus] = useState({ current: '', done: 0, total: 0 })
  const [importProgress, setImportProgress] = useState({ done: 0, total: 0 })

  // Supported file extensions — fetched from backend on mount
  const [supportedExts, setSupportedExts] = useState<Set<string> | null>(null)
  // Skipped-files info computed during scan and shown in the confirm footer
  const [skippedInfo, setSkippedInfo] = useState<{ count: number; exts: string[] }>({ count: 0, exts: [] })
  // Final import result (success / failure breakdown)
  const [importResult, setImportResult] = useState<{ succeeded: number; failed: number; failedFiles: { name: string; reason: string }[] } | null>(null)

  // Fetch the live supported-formats list from the backend once on mount
  useEffect(() => {
    docApi.getSupportedFormats().then(exts => {
      if (exts.size > 0) setSupportedExts(exts)
    })
  }, [])

  const totalFiles = addedFolders.reduce((s, f) => s + f.files.length, 0)
  const selectedFileCount = subfolders.filter(s => s.selected).reduce((n, s) => n + s.fileCount, 0)

  const handleScan = async () => {
    setScanError('')
    if (!supportedExts || supportedExts.size === 0) {
      setScanError('正在載入支援格式清單，請稍後再試…')
      return
    }
    const { rows, skippedCount, skippedExtNames } = buildSubfolderRows(addedFolders, supportedExts)
    if (rows.length === 0) {
      setScanError('所選資料夾中無法辨識子資料夾結構，請重新選擇')
      return
    }
    setSkippedInfo({ count: skippedCount, exts: skippedExtNames })

    // Close select modal immediately — scan runs in background floating card
    setScanStatus({ current: '', done: 0, total: rows.length })
    setStep('scanning')

    try {
      // Step 1: read text samples locally (fast)
      const payloadRows = await Promise.all(
        rows.map(async r => {
          const textFiles = r.files
            .filter(f => TEXT_EXT.has(getFileExt(f.name)))
            .slice(0, 3)
          const rawSamples = await Promise.all(textFiles.map(f => readTextSample(f)))
          const content_samples = rawSamples.filter(s => s.trim().length > 30)
          return { row: r, payload: { path: r.path, name: r.name, files: r.files.map(f => f.name), content_samples } }
        })
      )

      // Step 2: call Ollama one folder at a time for live progress
      const resultMap = new Map<string, { summary: string; has_content_samples: boolean }>()
      for (let i = 0; i < payloadRows.length; i++) {
        const { row, payload } = payloadRows[i]
        setScanStatus({ current: row.name, done: i, total: payloadRows.length })
        const res = await agentApi.scanPreview([payload])
        const s = res.subfolders[0]
        if (s) resultMap.set(s.path, s)
      }

      setSubfolders(rows.map(r => {
        const s = resultMap.get(r.path)
        const summary = s?.summary || ''
        return {
          ...r,
          summary,
          hasContentSamples: s?.has_content_samples ?? false,
          expanded: summary.length > 120,
        }
      }))
      setStep('confirm')
    } catch (e: any) {
      setScanError(e?.response?.data?.detail || 'AI 掃描失敗，請確認 Ollama 是否已啟動（http://localhost:11434）')
      setStep('select')
    }
  }

  const handleImport = async () => {
    const selected = subfolders.filter(s => s.selected)
    const allFiles = selected.flatMap(s => s.files)
    setImportProgress({ done: 0, total: allFiles.length })
    setStep('importing')
    let done = 0
    let succeeded = 0
    const failedFiles: { name: string; reason: string }[] = []

    // Upload with concurrency limit of 3 for speed
    const CONCURRENCY = 3
    let idx = 0
    async function next(): Promise<void> {
      while (idx < allFiles.length) {
        const i = idx++
        const file = allFiles[i]
        try {
          await docApi.upload(file)
          succeeded++
        } catch (err: any) {
          const status = err?.response?.status ?? ''
          const detail = err?.response?.data?.detail
          const msg = typeof detail === 'string' ? detail : (detail?.message ?? '')
          failedFiles.push({ name: file.name, reason: status ? `${status} ${msg}`.trim() : '網路錯誤' })
        }
        done++
        setImportProgress({ done, total: allFiles.length })
      }
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, allFiles.length) }, () => next()))

    setImportResult({ succeeded, failed: failedFiles.length, failedFiles })
    onAdded()
    setStep('done')
  }

  // ── Render: delegate to wizard sub-components ──────────────────────────────
  if (step === 'select') return (
    <WizardStepSelect
      addedFolders={addedFolders}
      setAddedFolders={setAddedFolders}
      totalFiles={totalFiles}
      scanError={scanError}
      onScan={handleScan}
      onClose={onClose}
      supportedExtsReady={!!supportedExts}
    />
  )
  if (step === 'scanning') return <WizardStepScanning scanStatus={scanStatus} />
  if (step === 'confirm') return (
    <WizardStepConfirm
      subfolders={subfolders}
      setSubfolders={setSubfolders}
      selectedFileCount={selectedFileCount}
      skippedInfo={skippedInfo}
      onImport={handleImport}
      onBack={() => setStep('select')}
    />
  )
  if (step === 'importing') return <WizardStepImporting progress={importProgress} />
  if (step === 'done') return <WizardStepDone result={importResult} onClose={onClose} />
  return null
}


// ── Progress Tab Types & Constants ────────────────────────────────────────────

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

// ── Progress Tab Component ────────────────────────────────────────────────────

function ProgressTab({ agentStatus, loading: parentLoading }: { agentStatus: AgentStatus | null; loading: boolean }) {
  const { user } = useAuth()
  const [batches, setBatches] = useState<BatchSummary | null>(null)
  const [health, setHealth] = useState<SystemHealthData | null>(null)
  const [batchLoading, setBatchLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [lastTriggered, setLastTriggered] = useState<string | null>(null)

  const load = useCallback(async () => {
    setBatchLoading(true)
    try {
      const batchRes = await api.get<BatchSummary>('/agent/batches')
      setBatches(batchRes.data)
      if (user?.is_superuser) {
        try {
          const healthRes = await api.get<SystemHealthData>('/admin/system/health')
          setHealth(healthRes.data)
        } catch { /* optional */ }
      }
    } catch { /* ignore */ }
    finally { setBatchLoading(false) }
  }, [user])

  useEffect(() => { load() }, [load])

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      const res = await api.post<{ triggered: boolean; triggered_at?: string }>('/agent/batches/trigger')
      setLastTriggered(res.data.triggered_at || new Date().toISOString())
      await load()
    } finally { setTriggering(false) }
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

  const isLoading = parentLoading || batchLoading
  const summary = batches?.status_summary ?? {}
  const totalDocs = Object.entries(summary)
    .filter(([k]) => k !== 'rejected' && k !== 'failed')
    .reduce((s, [, v]) => s + v, 0)
  const indexedCount = summary['indexed'] ?? 0
  const pendingCount = summary['pending'] ?? 0
  const processingCount = summary['processing'] ?? 0

  return (
    <div className="space-y-5">
      {/* Action bar */}
      <div className="flex items-center justify-end gap-2">
        <button
          onClick={handleDownloadReport}
          disabled={isLoading}
          className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          下載報告
        </button>
        <button
          onClick={handleTrigger}
          disabled={triggering || isLoading}
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {triggering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          立即重建索引
        </button>
      </div>

      {lastTriggered && (
        <div className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
          <CheckCircle className="h-4 w-4 shrink-0" />
          批次重建已觸發（{new Date(lastTriggered).toLocaleTimeString('zh-TW')}）
        </div>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { icon: FileText, label: '已入庫文件', value: isLoading ? '—' : indexedCount.toLocaleString(), color: 'bg-green-100 text-green-600' },
          { icon: Clock, label: '待審核', value: isLoading ? '—' : pendingCount.toLocaleString(), color: 'bg-orange-100 text-orange-600' },
          { icon: BarChart2, label: '向量化中', value: isLoading ? '—' : processingCount.toLocaleString(), color: 'bg-purple-100 text-purple-600' },
          { icon: FileText, label: '總提案數', value: isLoading ? '—' : totalDocs.toLocaleString(), color: 'bg-blue-100 text-blue-600' },
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
            {agentStatus?.watcher_running ? <CheckCircle className="h-4 w-4 text-green-500" /> : <AlertCircle className="h-4 w-4 text-gray-400" />}
            <span className={agentStatus?.watcher_running ? 'text-green-700' : 'text-gray-400'}>
              檔案監控：{agentStatus?.watcher_running ? '運行中' : '已停止'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {agentStatus?.scheduler_running ? <CheckCircle className="h-4 w-4 text-green-500" /> : <AlertCircle className="h-4 w-4 text-gray-400" />}
            <span className={agentStatus?.scheduler_running ? 'text-green-700' : 'text-gray-400'}>
              排程器：{agentStatus?.scheduler_running ? '運行中' : '已停止'}
            </span>
          </div>
          <div className="flex items-center gap-2 text-gray-500">
            <FileText className="h-4 w-4" />
            啟用資料夾：{agentStatus?.active_folders ?? '—'}
          </div>
        </div>
      </div>

      {/* System health */}
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
        {isLoading ? (
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
  )
}


// ── Main Page ─────────────────────────────────────────────────────────────────

type ActiveTab = 'folders' | 'progress'

export default function AgentPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab: ActiveTab = searchParams.get('tab') === 'progress' ? 'progress' : 'folders'
  const setTab = (tab: ActiveTab) => setSearchParams(tab === 'folders' ? {} : { tab })

  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [folders, setFolders] = useState<WatchFolder[]>([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [statusRes, foldersRes] = await Promise.all([
        api.get<AgentStatus>('/agent/status'),
        api.get<WatchFolder[]>('/agent/folders'),
      ])
      setStatus(statusRes.data)
      setFolders(foldersRes.data)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  const handleStart = async () => {
    setActing(true)
    try { await api.post('/agent/start'); await reload() } finally { setActing(false) }
  }

  const handleStop = async () => {
    setActing(true)
    try { await api.post('/agent/stop'); await reload() } finally { setActing(false) }
  }

  const handleScan = async () => {
    setActing(true)
    try { await api.post('/agent/scan'); await reload() } finally { setActing(false) }
  }

  const handleDeleteFolder = async (id: string) => {
    if (!confirm('確定移除此監控資料夾設定？')) return
    await api.delete(`/agent/folders/${id}`)
    await reload()
  }

  const handleToggleFolder = async (id: string) => {
    await api.patch(`/agent/folders/${id}/toggle`)
    await reload()
  }

  const running = status?.watcher_running || status?.scheduler_running

  return (
    <div className="flex h-full flex-col bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">智能索引 Agent</h1>
            <p className="text-sm text-gray-500">監控本機資料夾，自動發現並分類新文件</p>
          </div>
          <div className="flex items-center gap-2">
            {running ? (
              <button
                onClick={handleStop}
                disabled={acting}
                className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-50"
              >
                {acting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
                停止監控
              </button>
            ) : (
              <button
                onClick={handleStart}
                disabled={acting}
                className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
              >
                {acting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                啟動監控
              </button>
            )}
            <button
              onClick={handleScan}
              disabled={acting || loading}
              className="flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCw className={clsx('h-4 w-4', (acting || loading) && 'animate-spin')} />
              立即掃描
            </button>
          </div>
        </div>

        {/* Tab bar */}
        <div className="mt-3 flex gap-4 border-t border-gray-100 pt-3 -mb-4">
          {([
            { key: 'folders' as ActiveTab, label: '資料夾管理', icon: FolderOpen },
            { key: 'progress' as ActiveTab, label: '處理進度', icon: BarChart2 },
          ]).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={clsx(
                'flex items-center gap-1.5 border-b-2 px-1 pb-3 text-sm font-medium transition-colors',
                activeTab === key
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {activeTab === 'folders' ? (
          <>
            {/* Status cards */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs text-gray-500">監控狀態</p>
                <p className="mt-1 font-semibold">
                  {loading ? (
                    <span className="text-gray-400">載入中…</span>
                  ) : status?.watcher_running ? (
                    <span className="text-green-600 flex items-center gap-1">
                      <CheckCircle className="h-4 w-4" /> 監控中
                    </span>
                  ) : (
                    <span className="text-gray-400 flex items-center gap-1">
                      <Square className="h-4 w-4" /> 已停止
                    </span>
                  )}
                </p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs text-gray-500">排程狀態</p>
                <p className="mt-1 font-semibold">
                  {loading ? '—' : status?.scheduler_running ? (
                    <span className="text-green-600 flex items-center gap-1">
                      <Clock className="h-4 w-4" /> 排程中
                    </span>
                  ) : (
                    <span className="text-gray-400">停用</span>
                  )}
                </p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs text-gray-500">待審核文件</p>
                <p className="mt-1 text-2xl font-bold text-orange-500">
                  {loading ? '—' : status?.pending_review_count ?? 0}
                </p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs text-gray-500">啟用資料夾</p>
                <p className="mt-1 text-2xl font-bold text-blue-600">
                  {loading ? '—' : status?.active_folders ?? 0}
                </p>
              </div>
            </div>

            {/* Watch folders */}
            <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
              <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
                <div className="flex items-center gap-2">
                  <FolderOpen className="h-5 w-5 text-gray-500" />
                  <h2 className="font-semibold text-gray-800">監控資料夾</h2>
                </div>
                <button
                  onClick={() => setShowAddModal(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
                >
                  <Plus className="h-4 w-4" /> 新增資料夾
                </button>
              </div>

              {folders.length === 0 ? (
                <div className="flex flex-col items-center py-12 text-gray-400">
                  <FolderOpen className="mb-3 h-12 w-12 opacity-30" />
                  <p>尚未設定監控資料夾</p>
                  <p className="mt-1 text-sm">新增資料夾後，Agent 將自動發現並分類其中的文件</p>
                </div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium uppercase text-gray-500">
                      <th className="px-5 py-3">路徑</th>
                      <th className="px-5 py-3">上次掃描</th>
                      <th className="px-5 py-3 text-right">已掃描</th>
                      <th className="px-5 py-3 text-center">狀態</th>
                      <th className="px-5 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {folders.map(f => (
                      <tr key={f.id} className={clsx('hover:bg-gray-50', !f.is_active && 'opacity-50')}>
                        <td className="px-5 py-3">
                          <p className="font-medium text-sm text-gray-900 truncate max-w-xs">
                            {f.display_name || f.folder_path}
                          </p>
                          {f.display_name && (
                            <p className="text-xs text-gray-400 truncate max-w-xs">{f.folder_path}</p>
                          )}
                        </td>
                        <td className="px-5 py-3 text-xs text-gray-400">
                          {f.last_scan_at
                            ? new Date(f.last_scan_at).toLocaleDateString('zh-TW')
                            : '從未'}
                        </td>
                        <td className="px-5 py-3 text-right text-sm">{f.total_files_watched}</td>
                        <td className="px-5 py-3 text-center">
                          <button
                            onClick={() => handleToggleFolder(f.id)}
                            className="text-gray-400 hover:text-blue-600 transition-colors"
                            title={f.is_active ? '點击停用' : '點击啟用'}
                          >
                            {f.is_active
                              ? <ToggleRight className="h-5 w-5 text-green-500" />
                              : <ToggleLeft className="h-5 w-5" />}
                          </button>
                        </td>
                        <td className="px-5 py-3 text-right">
                          <button
                            onClick={() => handleDeleteFolder(f.id)}
                            className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* scheduler note */}
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="flex items-start gap-3">
                <Settings className="mt-0.5 h-5 w-5 shrink-0 text-gray-400" />
                <div>
                  <h2 className="font-semibold text-gray-800">排程設定</h2>
                  <p className="mt-1 text-sm text-gray-500">
                    批次排程時間與 CPU 上限可在 <code className="rounded bg-gray-100 px-1">.env</code> 中設定：
                    <code className="ml-1 rounded bg-gray-100 px-1">AGENT_BATCH_HOUR</code>（預設 2）、
                    <code className="ml-1 rounded bg-gray-100 px-1">AGENT_MAX_CPU_PERCENT</code>（預設 50）。
                  </p>
                  {status && !status.scheduler_running && (
                    <div className="mt-2 flex items-center gap-1.5 text-xs text-orange-600">
                      <AlertCircle className="h-4 w-4" />
                      排程器尚未運行；點擊「啟動監控」可同時啟動排程。
                    </div>
                  )}
                </div>
              </div>
            </div>
          </>
        ) : (
          <ProgressTab agentStatus={status} loading={loading} />
        )}
      </div>

      {showAddModal && (
        <FolderImportWizard
          onClose={() => setShowAddModal(false)}
          onAdded={reload}
        />
      )}
    </div>
  )
}

