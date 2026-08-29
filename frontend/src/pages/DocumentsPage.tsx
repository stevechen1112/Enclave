import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { docApi, kbApi, knowledgeAssetApi } from '../api'
import api from '../api'
import type { Document, InputCapabilityContract } from '../types'
import { Upload, FileText, Trash2, Loader2, Clock, RefreshCw, History, X, GitBranch } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import { format } from 'date-fns'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import LifecycleBadge from '../components/LifecycleBadge'
import ConfirmDialog from '../components/ConfirmDialog'
import AsyncState from '../components/AsyncState'
import PageHeader from '../components/PageHeader'
import { useHasCapability } from '../navigation/useCapabilities'
import { parseApiError, formatErrorWithTrace, type ApiErrorInfo } from '../api'
import { buildDropAccept } from '../lib/inputCapabilities'

function formatFileSize(bytes: number | null) {
  if (!bytes) return '—'
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

function versionLabelOf(doc: Document): string {
  return doc.external_version || (doc.version != null ? String(doc.version) : '—')
}

function updatedLabel(doc: Document): string {
  const ts = doc.updated_at || doc.created_at
  return ts ? format(new Date(ts), 'yyyy/MM/dd HH:mm') : '—'
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [uploadCurrent, setUploadCurrent] = useState(0)
  const [uploadTotal, setUploadTotal] = useState(0)
  const [departments, setDepartments] = useState<{ id: string; name: string }[]>([])
  const [selectedDept, setSelectedDept] = useState<string>('')
  const [inputCapabilities, setInputCapabilities] = useState<InputCapabilityContract>()

  const canManage = useHasCapability('upload_documents')
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
    api.get<{ id: string; name: string }[]>('/departments/options')
      .then(r => setDepartments(r.data))
      .catch((err) => {
        toast.error(formatErrorWithTrace(parseApiError(err, '無法載入部門篩選')))
      })
  }, [])

  useEffect(() => {
    void knowledgeAssetApi.capabilities().then(setInputCapabilities).catch(() => undefined)
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
    for (let i = 0; i < files.length; i++) {
      setUploadCurrent(i + 1)
      setProgress(0)
      try {
        await docApi.upload(files[i], setProgress)
        succeeded++
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '上傳失敗'
        toast.error(`${files[i].name}：${msg}`)
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

  const documentAccept = useMemo(() => buildDropAccept(inputCapabilities ? {
    ...inputCapabilities,
    formats: inputCapabilities.formats.filter(format => ['document', 'spreadsheet', 'image'].includes(format.asset_kind)),
  } : undefined), [inputCapabilities])
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: documentAccept,
    disabled: !canManage || uploading || !inputCapabilities,
    multiple: true,
  })

  const handleRevoke = async () => {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await docApi.delete(revokeTarget.id)
      const trace = revokeTarget.id.slice(0, 8)
      setDocs(prev => prev.filter(d => d.id !== revokeTarget.id))
      setLastRevokeTrace(trace)
      toast.success(`知識已撤銷：問答將立即無法引用（追蹤：${trace}…）`)
      setRevokeTarget(null)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '撤銷失敗，請稍後重試')))
    } finally {
      setRevoking(false)
    }
  }

  const retryList = () => { setLoading(true); loadDocs() }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="border-b border-line/60 bg-surface/70 px-4 py-4 backdrop-blur-sm md:px-8">
        <PageHeader
          variant="section"
          title="文件"
          subtitle={`${docs.length} 份 · 狀態顯示是否可被問到`}
          actions={(
            <>
              {departments.length > 0 && (
                <select
                  value={selectedDept}
                  onChange={e => { setSelectedDept(e.target.value); setLoading(true) }}
                  className="input w-auto min-w-[10rem]"
                  aria-label="依部門篩選"
                >
                  <option value="">所有部門</option>
                  {departments.map(d => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              )}
              <button
                type="button"
                onClick={retryList}
                className="icon-btn"
                aria-label="重新整理"
              >
                <RefreshCw className="h-5 w-5" aria-hidden />
              </button>
            </>
          )}
        />
      </div>

      <div className="flex-1 space-y-6 overflow-y-auto p-4 md:p-8">
        {lastRevokeTrace && (
          <p className="card animate-fade-in px-4 py-3 text-sm text-muted">
            最近撤銷追蹤：<span className="font-mono text-ink">{lastRevokeTrace}…</span>
            （問答已立即停用此文件）
          </p>
        )}

        {/* Upload zone */}
        {canManage && (
          <div
            {...getRootProps()}
            className={clsx(
              'flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 transition-colors',
              isDragActive ? 'border-accent bg-accent-soft/50' : 'border-line bg-surface hover:border-accent/50 hover:bg-accent-soft/30',
              uploading && 'pointer-events-none opacity-60'
            )}
          >
            <input {...getInputProps()} />
            {uploading ? (
              <>
                <Loader2 className="mb-3 h-8 w-8 animate-spin text-accent" aria-hidden />
                {uploadTotal > 1 && (
                  <p className="mb-1 text-sm text-muted">第 {uploadCurrent} / {uploadTotal} 份</p>
                )}
                <p className="text-sm font-semibold text-ink">上傳中 {progress}%</p>
                <div className="mt-2 h-2 w-48 overflow-hidden rounded-full bg-wash">
                  <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progress}%` }} />
                </div>
              </>
            ) : (
              <>
                <Upload className="mb-3 h-8 w-8 text-muted" aria-hidden />
                <p className="text-sm font-semibold text-ink">拖放文件到此處，或點擊選擇（支援多選）</p>
                <p className="mt-1 text-sm text-muted">支援 PDF、DOCX、XLSX、CSV、TXT、JPG、PNG（最大 50MB）</p>
              </>
            )}
          </div>
        )}

        <AsyncState
          loading={loading}
          error={listError}
          onRetry={retryList}
          empty={!listError && docs.length === 0}
          emptyTitle="尚無可存取的文件"
          emptyDescription={canManage ? '上傳第一份文件，或到「來源」接上 NAS／監控資料夾。' : '目前沒有你可存取的知識文件。'}
          emptyActionLabel={canManage ? '了解來源設定' : undefined}
          onEmptyAction={canManage ? () => { window.location.href = '/knowledge/sources' } : undefined}
        >
          {/* 手機：大卡片清單 */}
          <ul className="space-y-3 md:hidden">
            {docs.map(doc => {
              const deptName = departments.find(d => d.id === doc.department_id)?.name
              return (
                <li key={doc.id} className="card animate-rise-in p-4">
                  <div className="flex items-start gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft">
                      <FileText className="h-5 w-5 text-accent" aria-hidden />
                    </span>
                    <div className="min-w-0 flex-1">
                      <Link
                        to={`/knowledge/documents/${doc.id}`}
                        className="block truncate text-base font-semibold text-ink hover:text-accent"
                      >
                        {doc.filename}
                      </Link>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <LifecycleBadge status={doc.status} answerReady={doc.answer_ready} />
                        <span className="chip-neutral">{doc.file_type || '檔案'} · {formatFileSize(doc.file_size)}</span>
                        <span className="chip-neutral">{documentSourceLabel(doc)}</span>
                        {doc.is_new && <span className="chip-accent">新</span>}
                      </div>
                      <p className="mt-2 flex items-center gap-1 text-sm text-muted">
                        <Clock className="h-3.5 w-3.5" aria-hidden />
                        {updatedLabel(doc)}
                        {deptName && ` · ${deptName}`}
                        {versionLabelOf(doc) !== '—' && ` · 版本 ${versionLabelOf(doc)}`}
                      </p>
                      {doc.error_message && (
                        <p className="mt-1 text-sm text-danger">{doc.error_message}</p>
                      )}
                    </div>
                  </div>
                  {canManage && (
                    <div className="mt-3 flex gap-2 border-t border-line/60 pt-3">
                      <button
                        type="button"
                        onClick={() => openVersions(doc)}
                        className="btn-outline flex-1"
                        aria-label={`版本記錄 ${doc.filename}`}
                      >
                        <GitBranch className="h-4 w-4" aria-hidden /> 版本記錄
                      </button>
                      <button
                        type="button"
                        onClick={() => setRevokeTarget(doc)}
                        className="btn-outline flex-1 text-danger hover:border-danger/40 hover:bg-danger-soft"
                        aria-label={`撤銷知識 ${doc.filename}`}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden /> 撤銷
                      </button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>

          {/* 桌面：表格（可橫向捲動） */}
          <div className="card hidden overflow-x-auto md:block">
            <table className="w-full min-w-[720px]">
              <thead>
                <tr className="border-b border-line/80 bg-wash/70 text-left text-xs font-semibold tracking-wide text-muted">
                  <th className="px-4 py-3.5">名稱</th>
                  <th className="px-4 py-3.5">來源</th>
                  <th className="px-4 py-3.5">部門</th>
                  <th className="px-4 py-3.5">生命週期</th>
                  <th className="px-4 py-3.5">版本</th>
                  <th className="px-4 py-3.5">最近更新</th>
                  {canManage && <th className="w-28 px-4 py-3.5"><span className="sr-only">操作</span></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                {docs.map(doc => {
                  const deptName = departments.find(d => d.id === doc.department_id)?.name
                  return (
                    <tr key={doc.id} className="transition-colors hover:bg-wash/50">
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                          <Link
                            to={`/knowledge/documents/${doc.id}`}
                            className="max-w-[220px] truncate text-sm font-semibold text-ink hover:text-accent hover:underline"
                          >
                            {doc.filename}
                          </Link>
                          {doc.is_new && <span className="chip-accent shrink-0">新</span>}
                        </div>
                        {doc.error_message && (
                          <p className="mt-0.5 max-w-[250px] truncate text-xs text-danger">{doc.error_message}</p>
                        )}
                        <p className="mt-0.5 text-xs text-muted">{doc.file_type || '—'} · {formatFileSize(doc.file_size)}</p>
                      </td>
                      <td className="px-4 py-3.5 text-sm text-muted">{documentSourceLabel(doc)}</td>
                      <td className="px-4 py-3.5 text-sm text-muted">{deptName || '—'}</td>
                      <td className="px-4 py-3.5">
                        <LifecycleBadge status={doc.status} answerReady={doc.answer_ready} />
                      </td>
                      <td className="px-4 py-3.5 text-sm text-muted">{versionLabelOf(doc)}</td>
                      <td className="px-4 py-3.5 text-sm text-muted">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5" aria-hidden />
                          {updatedLabel(doc)}
                        </span>
                      </td>
                      {canManage && (
                        <td className="px-4 py-3">
                          <div className="flex gap-1">
                            <button
                              type="button"
                              onClick={() => openVersions(doc)}
                              className="icon-btn"
                              aria-label={`版本記錄 ${doc.filename}`}
                            >
                              <GitBranch className="h-4 w-4" aria-hidden />
                            </button>
                            <button
                              type="button"
                              onClick={() => setRevokeTarget(doc)}
                              className="icon-btn hover:bg-danger-soft hover:text-danger"
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
            ? `「${revokeTarget.filename}」將立即停止出現在問答與搜尋中，且無法復原。追蹤識別：${revokeTarget.id.slice(0, 8)}…`
            : ''
        }
        confirmLabel="確認撤銷"
        onCancel={() => !revoking && setRevokeTarget(null)}
        onConfirm={handleRevoke}
      />

      {/* Version History Drawer */}
      {versionDoc && (
        <div className="fixed inset-0 z-40 flex" role="presentation">
          <div className="flex-1 bg-ink/30" onClick={() => setVersionDoc(null)} aria-hidden />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="version-drawer-title"
            className="flex w-full max-w-md flex-col bg-surface shadow-lift"
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <div>
                <div className="flex items-center gap-2">
                  <History className="h-5 w-5 text-accent" aria-hidden />
                  <h2 id="version-drawer-title" className="text-base font-semibold text-ink">版本記錄</h2>
                </div>
                <p className="mt-0.5 max-w-[280px] truncate text-sm text-muted">{versionDoc.filename}</p>
              </div>
              <button
                type="button"
                onClick={() => setVersionDoc(null)}
                className="icon-btn"
                aria-label="關閉版本記錄"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>

            {/* Re-upload */}
            <div className="border-b border-line bg-wash/60 px-5 py-4">
              <h3 className="input-label">上傳新版本</h3>
              <input
                type="file"
                onChange={e => setReuploadFile(e.target.files?.[0] ?? null)}
                className="mb-2 w-full text-sm text-muted"
                aria-label="選擇新版本檔案"
              />
              <input
                value={reuploadNote}
                onChange={e => setReuploadNote(e.target.value)}
                placeholder="更新說明（選填）"
                className="input mb-3"
              />
              <button
                type="button"
                onClick={handleReupload}
                disabled={!reuploadFile || reuploading}
                className="btn-primary w-full"
              >
                <Upload className="h-4 w-4" aria-hidden />
                {reuploading ? '上傳中…' : '上傳新版本'}
              </button>
            </div>

            {/* Version list */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {versionLoading ? (
                <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted" aria-hidden /></div>
              ) : versions.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted">尚無版本記錄</p>
              ) : (
                <div className="space-y-2">
                  {versions.map((v, i) => (
                    <div key={v.version_number} className={clsx('card p-3', i === 0 && 'border-accent/40 bg-accent-soft/40')}>
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold text-ink">版本 {v.version_number}</span>
                        {i === 0 && <span className="chip-accent">目前版本</span>}
                      </div>
                      {v.change_note && <p className="mt-1 text-sm text-muted">{v.change_note}</p>}
                      <p className="mt-1 text-xs text-muted">
                        {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                        {v.file_size ? ` · ${(v.file_size / 1024).toFixed(1)} KB` : ''}
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
