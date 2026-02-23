import { useState, useEffect, useCallback } from 'react'
import { docApi } from '../api'
import api from '../api'
import { useAuth } from '../auth'
import type { Document } from '../types'
import { Upload, FileText, Trash2, Loader2, CheckCircle, AlertCircle, Clock, RefreshCw, Filter } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import { format } from 'date-fns'
import clsx from 'clsx'
import toast from 'react-hot-toast'

const statusConfig: Record<string, { label: string; color: string; icon: typeof Loader2 }> = {
  uploading: { label: '上傳中', color: 'text-yellow-600 bg-yellow-50', icon: Loader2 },
  parsing: { label: '解析中', color: 'text-blue-600 bg-blue-50', icon: Loader2 },
  embedding: { label: '向量化中', color: 'text-purple-600 bg-purple-50', icon: Loader2 },
  completed: { label: '完成', color: 'text-green-600 bg-green-50', icon: CheckCircle },
  failed: { label: '失敗', color: 'text-red-600 bg-red-50', icon: AlertCircle },
}

function formatFileSize(bytes: number | null) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
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

  const canManage = ['owner', 'admin', 'hr'].includes(user?.role ?? '')

  // Load departments for filter
  useEffect(() => {
    api.get<{ id: string; name: string }[]>('/departments/')
      .then(r => setDepartments(r.data))
      .catch(() => {})
  }, [])

  const loadDocs = useCallback(async () => {
    try {
      const params = selectedDept ? { department_id: selectedDept } : undefined
      const list = await docApi.list(params)
      setDocs(list)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [selectedDept])

  useEffect(() => { loadDocs() }, [loadDocs])

  // Poll for processing status
  useEffect(() => {
    const processing = docs.some(d => ['uploading', 'parsing', 'embedding'].includes(d.status))
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

  const handleDelete = async (doc: Document) => {
    if (!confirm(`確定要刪除「${doc.filename}」？此操作無法復原。`)) return
    try {
      await docApi.delete(doc.id)
      setDocs(prev => prev.filter(d => d.id !== doc.id))
      toast.success('文件已刪除')
    } catch {
      toast.error('刪除失敗')
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">文件管理</h1>
          <p className="text-sm text-gray-500">{docs.length} 個文件</p>
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
          <button onClick={loadDocs} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 transition-colors" title="重新整理">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
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

        {/* Document list */}
        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>
        ) : docs.length === 0 ? (
          <div className="flex flex-col items-center py-12 text-gray-400">
            <FileText className="mb-3 h-10 w-10" />
            <p className="text-sm">尚無文件</p>
          </div>
        ) : (
          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  <th className="px-4 py-3">文件名稱</th>
                  <th className="px-4 py-3">類型</th>
                  <th className="px-4 py-3">大小</th>
                  <th className="px-4 py-3">狀態</th>
                  <th className="px-4 py-3">切片數</th>
                  <th className="px-4 py-3">上傳時間</th>
                  {canManage && <th className="px-4 py-3 w-16"></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {docs.map(doc => {
                  const st = statusConfig[doc.status] || statusConfig.failed
                  const StatusIcon = st.icon
                  return (
                    <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 text-gray-400 shrink-0" />
                          <span className="text-sm font-medium text-gray-900 truncate max-w-[200px]">{doc.filename}</span>
                        </div>
                        {doc.error_message && (
                          <p className="mt-0.5 text-xs text-red-500 truncate max-w-[250px]">{doc.error_message}</p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500 uppercase">{doc.file_type || '-'}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">{formatFileSize(doc.file_size)}</td>
                      <td className="px-4 py-3">
                        <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', st.color)}>
                          <StatusIcon className={clsx('h-3 w-3', ['uploading','parsing','embedding'].includes(doc.status) && 'animate-spin')} />
                          {st.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">{doc.chunk_count ?? '-'}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        <div className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {doc.created_at ? format(new Date(doc.created_at), 'yyyy/MM/dd HH:mm') : '-'}
                        </div>
                      </td>
                      {canManage && (
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleDelete(doc)}
                            className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
                            title="刪除"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
