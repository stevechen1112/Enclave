import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { docApi, kbApi } from '../api'
import api from '../api'
import { useAuth } from '../auth'
import type { Document } from '../types'
import { Upload, FileText, Trash2, Loader2, Clock, RefreshCw, Filter, History, X, GitBranch } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import { format } from 'date-fns'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import LifecycleBadge from '../components/LifecycleBadge'
import ConfirmDialog from '../components/ConfirmDialog'
import AsyncState from '../components/AsyncState'
import { hasCapability } from '../navigation/capabilities'
import { parseApiError, formatErrorWithTrace, type ApiErrorInfo } from '../api'

function formatFileSize(bytes: number | null) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

/** User-facing source label (UIUX §9.5) — prefer source_system over default file type */
function documentSourceLabel(doc: Document): string {
  const sys = (doc.source_system || '').toLowerCase()
  const typ = (doc.source_type || '').toLowerCase()
  if (sys === 'nas_smb' || sys.includes('nas')) return 'NAS'
  if (sys.includes('sharepoint')) return 'SharePoint'
  if (sys.includes('google') || sys.includes('drive')) return 'Google Drive'
  if (sys === 'upload' || sys === 'manual') return '上傳'
  if (typ === 'web') return '網頁'
  if (sys) return '來源系統'
  if (typ === 'connector') return '來源系統'
  return '上傳'
}

export default function DocumentsPage() {
  const { user } = useAuth()
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [uploadCurrent, setUploadCurrent] = useState(0)
  const [uploadTotal, setUploadTotal] = useState(0)
  const [departments, setDepartments] = useState<{ id: string; name: string }[]>([])
  const [selectedDept, setSelectedDept] = useState<string>('')

  const canManage = hasCapability(user?.role, 'upload_documents', user?.is_superuser)
  const [revokeTarget, setRevokeTarget] = useState<Document | null>(null)
  const [revoking, setRevoking] = useState(false)
  const [listError, setListError] = useState<ApiErrorInfo | null>(null)
  const [lastRevokeTrace, setLastRevokeTrace] = useState<string | null>(null)

  // ── Version history drawer ──
  const [versionDoc, setVersionDoc] = useState<Document | null>(null)
  const [versions, setVersions] = useState<Array<{ version_number: number; change_note: string | null; created_at: string; file_size: number | null }>>([])
  const [versionLoading, setVersionLoading] = useState(false)
  const [reuploadFile, setReuploadFile] = useState<File | null>(null)
  const [reuploadNote, setReuploadNote] = useState('')
  const [reuploading, setReuploading] = useState(false)

  const openVersions = async (doc: Document) => {
    setVersionDoc(doc)
    setVersionLoading(true)
    try {
      const data = await kbApi.listVersions(doc.id)
      setVersions(Array.isArray(data) ? data : (data.versions ?? []))
    } catch (err) {
      setVersions([])
      toast.error(formatErrorWithTrace(parseApiError(err, '無法載入版本記錄')))
    } finally { setVersionLoading(false) }
  }

  const handleReupload = async () => {
    if (!versionDoc || !reuploadFile) return
    setReuploading(true)
    try {
      await kbApi.reupload(versionDoc.id, reuploadFile, reuploadNote || undefined)
      toast.success('新版本上傳成功，開始重新處理…')
      setReuploadFile(null); setReuploadNote('')
      await openVersions(versionDoc)
      loadDocs()
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '上傳失敗')))
    } finally { setReuploading(false) }
  }

  // Load departments for filter
  useEffect(() => {
    api.get<{ id: string; name: string }[]>('/departments/')
      .then(r => setDepartments(r.data))
      .catch((err) => {
        toast.error(formatErrorWithTrace(parseApiError(err, '無法載入部門篩選')))
      })
  }, [])

  const loadDocs = useCallback(async () => {
    try {
      const params = selectedDept ? { department_id: selectedDept } : undefined
      const list = await docApi.listAll(params)
      setDocs(list)
      setListError(null)
    } catch (err) {
      setListError(parseApiError(err, '無法載入文件列表'))
    } finally {
      setLoading(false)
    }
  }, [selectedDept])

  useEffect(() => { loadDocs() }, [loadDocs])

  // Poll for processing status
  useEffect(() => {
    const processing = docs.some(d =>
      ['uploading', 'parsing', 'embedding', 'processing', 'pending_review'].includes(d.status),
    )
    if (!processing) return
    const timer = setInterval(loadDocs, 3000)
    return () => clearInterval(timer)
  }, [docs, loadDocs])

  const onDrop = useCallback(async (files: File[]) => {
    if (!files.length) return
    setUploading(true)
    setUploadTotal(files.length)
    let succeeded = 0
    let failed = 0
    for (let i = 0; i < files.length; i++) {
      setUploadCurrent(i + 1)
      setProgress(0)
      try {
        await docApi.upload(files[i], setProgress)
        succeeded++
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '上傳失敗'
        toast.error(`${files[i].name}：${msg}`)
        failed++
      }
    }
    if (succeeded > 0) {
      toast.success(files.length === 1 ? '文件上傳成功，開始處理...' : `${succeeded} 份文件上傳成功，開始處理...`)
    }
    setUploading(false)
    setProgress(0)
    setUploadTotal(0)
    setUploadCurrent(0)
    loadDocs()
  }, [loadDocs])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/plain': ['.txt'],
      'text/csv': ['.csv'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
    },
    disabled: !canManage || uploading,
    multiple: true,
  })

  const handleRevoke = async () => {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await docApi.delete(revokeTarget.id)
      const trace = revokeTarget.id
      setDocs(prev => prev.filter(d => d.id !== revokeTarget.id))
      setLastRevokeTrace(trace)
      toast.success(`知識已撤銷：問答將立即無法引用（追蹤：${trace.slice(0, 8)}…）`)
      setRevokeTarget(null)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '撤銷失敗，請稍後重試')))
    } finally {
      setRevoking(false)
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-ink md:text-lg">文件</h2>
          <p className="text-sm text-muted">{docs.length} 份 · 狀態顯示是否可被問到</p>
        </div>
        <div className="flex items-center gap-3">
          {departments.length > 0 && (
            <div className="flex items-center gap-1.5">
              <Filter className="h-4 w-4 text-gray-400" />
              <select
                value={selectedDept}
                onChange={e => { setSelectedDept(e.target.value); setLoading(true) }}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="">所有部門</option>
                {departments.map(d => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
          )}
          <button
            type="button"
            onClick={() => { setLoading(true); loadDocs() }}
            className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 transition-colors min-h-11 min-w-11"
            aria-label="重新整理"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {lastRevokeTrace && (
          <p className="rounded-lg border border-line bg-wash px-3 py-2 text-xs text-muted">
            最近撤銷追蹤：<span className="font-mono text-ink">{lastRevokeTrace}</span>
            （問答立即不可見；投影可能稍後收斂）
          </p>
        )}
        {/* Upload zone */}
        {canManage && (
          <div
            {...getRootProps()}
            className={clsx(
              'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-colors',
              isDragActive ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50',
              uploading && 'pointer-events-none opacity-60'
            )}
          >
            <input {...getInputProps()} />
            {uploading ? (
              <>
                <Loader2 className="mb-3 h-8 w-8 animate-spin text-blue-600" />
                {uploadTotal > 1 && (
                  <p className="text-xs text-gray-500 mb-1">第 {uploadCurrent} / {uploadTotal} 份</p>
                )}
                <p className="text-sm font-medium text-gray-700">上傳中 {progress}%</p>
                <div className="mt-2 h-2 w-48 overflow-hidden rounded-full bg-gray-200">
                  <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
                </div>
              </>
            ) : (
              <>
                <Upload className="mb-3 h-8 w-8 text-gray-400" />
                <p className="text-sm font-medium text-gray-700">拖放文件到此處，或點擊選擇（支援多選）</p>
                <p className="mt-1 text-xs text-gray-400">支援 PDF、DOCX、XLSX、CSV、TXT、JPG、PNG（最大 50MB）</p>
              </>
            )}
          </div>
        )}

        <AsyncState
          loading={loading}
          error={listError}
          onRetry={() => { setLoading(true); loadDocs() }}
          empty={!listError && docs.length === 0}
          emptyTitle="尚無可存取的文件"
          emptyDescription={canManage ? '上傳第一份文件，或到「來源」接上 NAS／監控資料夾。' : '目前沒有你可存取的知識文件。'}
          emptyActionLabel={canManage ? '了解來源設定' : undefined}
          onEmptyAction={canManage ? () => { window.location.href = '/knowledge/sources' } : undefined}
        >
          <div className="overflow-x-auto rounded-2xl border border-line/80 bg-surface shadow-sm">
            <table className="w-full min-w-[720px]">
              <thead>
                <tr className="border-b border-line/80 bg-wash/70 text-left text-[11px] font-medium tracking-wide text-muted">
                  <th className="px-4 py-3.5">名稱</th>
                  <th className="px-4 py-3.5">來源</th>
                  <th className="px-4 py-3.5">部門</th>
                  <th className="px-4 py-3.5">生命週期</th>
                  <th className="px-4 py-3.5">版本</th>
                  <th className="px-4 py-3.5">最近更新</th>
                  <th className="px-4 py-3.5">被引用</th>
                  {canManage && <th className="px-4 py-3.5 w-16"></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {docs.map(doc => {
                  const deptName = departments.find(d => d.id === doc.department_id)?.name
                  const versionLabel =
                    doc.external_version ||
                    (doc.version != null ? String(doc.version) : null)
                  return (
                    <tr key={doc.id} className="transition-colors hover:bg-wash/50">
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                          <Link
                            to={`/knowledge/documents/${doc.id}`}
                            className="max-w-[200px] truncate text-sm font-medium text-ink hover:text-accent hover:underline"
                          >
                            {doc.filename}
                          </Link>
                          {doc.is_new && (
                            <span className="inline-flex shrink-0 items-center rounded-md bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                              新
                            </span>
                          )}
                        </div>
                        {doc.error_message && (
                          <p className="mt-0.5 max-w-[250px] truncate text-xs text-danger">{doc.error_message}</p>
                        )}
                        <p className="mt-0.5 text-[11px] text-muted">{doc.file_type || '—'} · {formatFileSize(doc.file_size)}</p>
                      </td>
                      <td className="px-4 py-3.5 text-sm text-muted">{documentSourceLabel(doc)}</td>
                      <td className="px-4 py-3.5 text-sm text-muted">{deptName || '—'}</td>
                      <td className="px-4 py-3.5">
                        <LifecycleBadge status={doc.status} />
                      </td>
                      <td className="px-4 py-3.5 text-sm text-muted">{versionLabel || '—'}</td>
                      <td className="px-4 py-3.5 text-sm text-muted">
                        <div className="flex items-center gap-1">
                          <Clock className="h-3 w-3" aria-hidden />
                          {(doc.updated_at || doc.created_at)
                            ? format(new Date(doc.updated_at || doc.created_at!), 'yyyy/MM/dd HH:mm')
                            : '—'}
                        </div>
                      </td>
                      <td
                        className="px-4 py-3.5 text-sm text-muted/70"
                        title="引用計數契約待補"
                      >
                        —
                      </td>
                      {canManage && (
                        <td className="px-4 py-3">
                          <div className="flex gap-1">
                            <button
                              type="button"
                              onClick={() => openVersions(doc)}
                              className="rounded-lg p-1.5 text-gray-400 hover:bg-blue-50 hover:text-blue-500 transition-colors min-h-11 min-w-11"
                              aria-label={`版本記錄 ${doc.filename}`}
                            >
                              <GitBranch className="h-4 w-4" aria-hidden />
                            </button>
                            <button
                              type="button"
                              onClick={() => setRevokeTarget(doc)}
                              className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors min-h-11 min-w-11"
                              aria-label={`撤銷知識 ${doc.filename}`}
                            >
                              <Trash2 className="h-4 w-4" aria-hidden />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </AsyncState>
      </div>

      <ConfirmDialog
        open={!!revokeTarget}
        danger
        busy={revoking}
        title="撤銷此知識？"
        description={
          revokeTarget
            ? `「${revokeTarget.filename}」將立即停止出現在問答與搜尋中。後端投影可能稍後收斂；這不是單純的本機刪除。追蹤識別：${revokeTarget.id}`
            : ''
        }
        confirmLabel="確認撤銷"
        onCancel={() => !revoking && setRevokeTarget(null)}
        onConfirm={handleRevoke}
      />

      {/* Version History Drawer */}
      {versionDoc && (
        <div className="fixed inset-0 z-40 flex" role="presentation">
          <div className="flex-1 bg-black/30" onClick={() => setVersionDoc(null)} aria-hidden />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="version-drawer-title"
            className="w-full max-w-md bg-white shadow-xl flex flex-col"
          >
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <div>
                <div className="flex items-center gap-2">
                  <History className="h-5 w-5 text-blue-600" aria-hidden />
                  <h2 id="version-drawer-title" className="text-sm font-semibold text-gray-900">版本記錄</h2>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 truncate max-w-[280px]">{versionDoc.filename}</p>
              </div>
              <button
                type="button"
                onClick={() => setVersionDoc(null)}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg min-h-11 min-w-11"
                aria-label="關閉版本記錄"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>

            {/* Re-upload */}
            <div className="px-5 py-4 border-b bg-gray-50">
              <h3 className="text-xs font-semibold text-gray-700 mb-2">上傳新版本</h3>
              <input type="file" onChange={e => setReuploadFile(e.target.files?.[0] ?? null)}
                className="w-full text-xs text-gray-600 mb-2" />
              <input value={reuploadNote} onChange={e => setReuploadNote(e.target.value)}
                placeholder="更新説明（選填）"
                className="w-full text-sm border rounded-lg px-3 py-1.5 mb-2 focus:outline-none focus:ring-2 focus:ring-blue-300" />
              <button onClick={handleReupload} disabled={!reuploadFile || reuploading}
                className="flex items-center gap-2 w-full justify-center rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">
                <Upload className="h-4 w-4" />
                {reuploading ? '上傳中…' : '上傳新版本'}
              </button>
            </div>

            {/* Version list */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {versionLoading ? (
                <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-gray-400" /></div>
              ) : versions.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">尚無版本記錄</p>
              ) : (
                <div className="space-y-2">
                  {versions.map((v, i) => (
                    <div key={v.version_number} className={`rounded-lg border p-3 ${i === 0 ? 'border-blue-200 bg-blue-50' : 'border-gray-100'}`}>
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-gray-700">v{v.version_number}</span>
                        {i === 0 && <span className="text-xs bg-blue-600 text-white px-1.5 rounded">當前</span>}
                      </div>
                      {v.change_note && <p className="text-xs text-gray-600 mt-1">{v.change_note}</p>}
                      <p className="text-xs text-gray-400 mt-1">
                        {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                        {v.file_size && ` · ${(v.file_size / 1024).toFixed(1)} KB`}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
