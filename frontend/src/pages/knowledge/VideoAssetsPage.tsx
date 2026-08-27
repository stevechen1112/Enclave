import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock3, Film, Loader2, RefreshCw, Upload } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import toast from 'react-hot-toast'

import { formatErrorWithTrace, parseApiError, videoApi } from '../../api'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'
import { useHasCapability } from '../../navigation/useCapabilities'
import type { VideoAsset } from '../../types'

function formatDuration(durationMs: number | null) {
  if (!durationMs) return '—'
  const seconds = Math.floor(durationMs / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function statusLabel(asset: VideoAsset) {
  const state = asset.job?.status || asset.status
  const labels: Record<string, string> = {
    pending: '排隊中', running: '處理中', retry: '等待重試', failed: '處理失敗',
    review_required: '待人員覆核', ready: '已完成', active: '已啟用',
  }
  return labels[state] || state
}

export default function VideoAssetsPage() {
  const [assets, setAssets] = useState<VideoAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [equipmentIds, setEquipmentIds] = useState('')
  const [applicableRoles, setApplicableRoles] = useState('')
  const [error, setError] = useState<ReturnType<typeof parseApiError> | null>(null)
  const canUpload = useHasCapability('upload_documents')

  const load = useCallback(async () => {
    try {
      setAssets(await videoApi.list())
      setError(null)
    } catch (reason) {
      setError(parseApiError(reason, '無法載入影音知識來源'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!assets.some(asset => ['pending', 'running', 'retry'].includes(asset.job?.status || ''))) return
    const timer = window.setInterval(() => { void load() }, 4000)
    return () => window.clearInterval(timer)
  }, [assets, load])

  const onDrop = useCallback(async (accepted: File[]) => {
    const file = accepted[0]
    if (!file || uploading) return
    setUploading(true)
    setProgress(0)
    try {
      await videoApi.upload(file, { equipmentIds, applicableRoles }, setProgress)
      toast.success('影片已接收，正在建立時間軸與知識候選')
      await load()
    } catch (reason) {
      toast.error(formatErrorWithTrace(parseApiError(reason, '影片上傳失敗')))
    } finally {
      setUploading(false)
      setProgress(0)
    }
  }, [applicableRoles, equipmentIds, load, uploading])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled: !canUpload || uploading,
    multiple: false,
    accept: {
      'video/mp4': ['.mp4'],
      'video/quicktime': ['.mov'],
      'video/webm': ['.webm'],
      'video/x-matroska': ['.mkv'],
    },
  })

  if (loading) return <AsyncState loading>{null}</AsyncState>
  if (error && assets.length === 0) return <AsyncState error={error} onRetry={load}>{null}</AsyncState>

  return (
    <div className="h-full overflow-y-auto px-5 py-5 lg:px-8">
      <PageHeader
        title="影音知識"
        subtitle="將操作影片轉成可追溯的逐字稿、關鍵畫面、OCR 與作業步驟。"
        actions={(
          <button type="button" className="btn-outline" onClick={() => void load()}>
            <RefreshCw size={16} /> 重新整理
          </button>
        )}
      />

      {canUpload && (
        <div className="mb-6 rounded-xl border border-line bg-surface p-4">
          <div className="mb-4 grid gap-3 md:grid-cols-2">
            <label className="text-sm font-medium">適用機台（選填，逗號分隔）<input value={equipmentIds} onChange={event => setEquipmentIds(event.target.value)} className="input mt-1 w-full" placeholder="EQ-100, LINE-02" /></label>
            <label className="text-sm font-medium">適用角色（選填，逗號分隔）<input value={applicableRoles} onChange={event => setApplicableRoles(event.target.value)} className="input mt-1 w-full" placeholder="操作員, 班長" /></label>
          </div>
          <div
          {...getRootProps()}
          className={`cursor-pointer rounded-xl border-2 border-dashed p-7 text-center transition ${isDragActive ? 'border-accent bg-accent-soft' : 'border-line bg-surface hover:border-accent'}`}
        >
          <input {...getInputProps()} aria-label="上傳影片" />
          {uploading ? <Loader2 className="mx-auto mb-2 animate-spin text-accent" /> : <Upload className="mx-auto mb-2 text-accent" />}
          <p className="font-medium">{uploading ? `上傳中 ${progress}%` : '拖曳影片到這裡，或點選檔案'}</p>
          <p className="mt-1 text-sm text-muted">MP4、MOV、WebM、MKV；完成後需由有權限人員核准才會進入問答。</p>
          {uploading && <div className="mx-auto mt-3 h-2 max-w-md overflow-hidden rounded-full bg-line"><div className="h-full bg-accent" style={{ width: `${progress}%` }} /></div>}
          </div>
        </div>
      )}

      {assets.length === 0 ? (
        <div className="rounded-xl border border-line bg-surface p-12 text-center text-muted">
          <Film className="mx-auto mb-3" size={36} />
          <p>尚未建立影音知識來源。</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {assets.map(asset => (
            <Link key={asset.id} to={`/knowledge/videos/${asset.id}`} className="card flex items-center gap-4 p-4 hover:border-accent">
              <div className="rounded-lg bg-accent-soft p-3 text-accent"><Film size={22} /></div>
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold">{asset.title}</div>
                <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted">
                  <span className="inline-flex items-center gap-1"><Clock3 size={14} />{formatDuration(asset.duration_ms)}</span>
                  <span>{asset.media_type}</span>
                  <span>{new Date(asset.created_at).toLocaleString('zh-TW')}</span>
                </div>
              </div>
              <span className={`rounded-full px-3 py-1 text-sm ${asset.job?.status === 'failed' ? 'bg-danger-soft text-danger' : asset.job?.status === 'review_required' ? 'bg-highlight-soft text-highlight' : 'bg-accent-soft text-accent-ink'}`}>
                {statusLabel(asset)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
