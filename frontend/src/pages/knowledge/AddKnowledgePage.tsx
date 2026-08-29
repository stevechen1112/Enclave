import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Camera, CheckCircle2, FileUp, Link2, Loader2, Mic, RefreshCw, Square, Trash2, Video, XCircle } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { knowledgeAssetApi, uploadSessionApi, formatErrorWithTrace, parseApiError } from '../../api'
import { SectionPanel, WorkspacePage } from '../../components/WorkspacePage'
import { buildDropAccept, capabilitySummary, formatBytes, preflightFile } from '../../lib/inputCapabilities'
import { loadIntakeDrafts, replaceIntakeDrafts } from '../../lib/intakeDraftQueue'
import { rememberKnowledgeTask } from '../../lib/longTaskRecovery'
import { uploadFileResumable } from '../../lib/resumableUpload'
import CoreAudioRecorder from '../../platform/input/CoreAudioRecorder'
import type { CaptureSessionInfo } from '../../platform/input/captureApi'
import type { InputCapabilityContract, InputFormatCapability } from '../../types'

type Mode = 'file' | 'capture' | 'url' | 'record'
type QueueStatus = 'checking' | 'pending' | 'uploading' | 'done' | 'error' | 'cancelled'
type UploadItem = { key: string; file: File; idempotencyKey: string; uploadSessionId?: string; status: QueueStatus; progress: number; capability?: InputFormatCapability; warning?: string; assetId?: string; error?: string; preflightError?: string }
type ContextFields = { site: string; production_line: string; equipment: string; product: string; work_order: string; shift: string; tags: string }

const EMPTY_CONTEXT: ContextFields = { site: '', production_line: '', equipment: '', product: '', work_order: '', shift: '', tags: '' }

function fileKey(file: File) { return `${file.name}:${file.size}:${file.lastModified}` }
function newIdempotencyKey() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `input-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
function contextPayload(values: ContextFields): Record<string, string | string[]> {
  const result: Record<string, string | string[]> = {}
  for (const [key, raw] of Object.entries(values)) {
    if (!raw.trim()) continue
    result[key] = key === 'tags' ? raw.split(',').map(value => value.trim()).filter(Boolean).slice(0, 20) : raw.trim()
  }
  return result
}
async function mediaDurationSeconds(file: File): Promise<number | null> {
  if (typeof document === 'undefined' || typeof URL.createObjectURL !== 'function') return null
  return await new Promise(resolve => {
    const media = document.createElement('video')
    const objectUrl = URL.createObjectURL(file)
    let settled = false
    const timeout = window.setTimeout(() => done(null), 3000)
    const done = (value: number | null) => {
      if (settled) return
      settled = true
      window.clearTimeout(timeout)
      URL.revokeObjectURL(objectUrl)
      media.remove()
      resolve(value)
    }
    media.preload = 'metadata'
    media.onloadedmetadata = () => done(Number.isFinite(media.duration) ? media.duration : null)
    media.onerror = () => done(null)
    media.src = objectUrl
  })
}

export default function AddKnowledgePage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('file')
  const [queue, setQueue] = useState<UploadItem[]>([])
  const [capabilities, setCapabilities] = useState<InputCapabilityContract>()
  const [capabilityError, setCapabilityError] = useState('')
  const [departments, setDepartments] = useState<Array<{ id: string; name: string }>>([])
  const [draftsLoaded, setDraftsLoaded] = useState(false)
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [sourceSystem, setSourceSystem] = useState('')
  const [recordId, setRecordId] = useState('')
  const [captureConsent, setCaptureConsent] = useState(false)
  const [captureResult, setCaptureResult] = useState<CaptureSessionInfo | null>(null)
  const [classification, setClassification] = useState('internal')
  const [departmentId, setDepartmentId] = useState('')
  const [context, setContext] = useState<ContextFields>(EMPTY_CONTEXT)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const controllers = useRef(new Map<string, AbortController>())
  const sourceKeys = useRef(new Map<string, string>())

  const loadCapabilities = useCallback(async () => {
    setCapabilityError('')
    try { setCapabilities(await knowledgeAssetApi.capabilities()) }
    catch (reason) { setCapabilityError(formatErrorWithTrace(parseApiError(reason, '無法取得此環境的輸入能力'))) }
  }, [])

  useEffect(() => {
    void loadCapabilities()
    void knowledgeAssetApi.departments().then(setDepartments).catch(() => setDepartments([]))
  }, [loadCapabilities])

  useEffect(() => {
    if (!capabilities?.tenant_id || draftsLoaded) return
    void loadIntakeDrafts(capabilities.tenant_id)
      .then(drafts => setQueue(drafts.map(draft => ({ ...draft, status: draft.error ? 'error' : 'pending', progress: 0 }))))
      .catch(() => toast.error('無法還原上次未完成的上傳草稿'))
      .finally(() => setDraftsLoaded(true))
  }, [capabilities?.tenant_id, draftsLoaded])

  useEffect(() => {
    if (!draftsLoaded) return
    const drafts = queue.filter(item => item.status !== 'done').map(item => ({
      key: item.key, file: item.file, idempotencyKey: item.idempotencyKey, uploadSessionId: item.uploadSessionId,
      createdAt: new Date(item.file.lastModified || Date.now()).toISOString(),
      error: item.status === 'error' || item.status === 'cancelled' ? item.error : undefined,
    }))
    if (capabilities?.tenant_id) void replaceIntakeDrafts(capabilities.tenant_id, drafts).catch(() => undefined)
  }, [capabilities?.tenant_id, draftsLoaded, queue])

  useEffect(() => {
    if (!capabilities) return
    setQueue(current => current.map(item => {
      if (item.status === 'done' || item.status === 'uploading') return item
      const checked = preflightFile(item.file, capabilities, capabilities.quota?.remaining_storage_bytes)
      return { ...item, capability: checked.capability, warning: checked.warning, status: checked.error ? 'error' : 'pending', error: checked.error, preflightError: checked.error }
    }))
  }, [capabilities])

  const addFiles = useCallback(async (files: File[]) => {
    if (!capabilities) { toast.error('仍在取得此環境可用格式，請稍後再試。'); return }
    const remainingDocuments = capabilities.quota?.remaining_documents
    const existingCount = queue.filter(item => item.status !== 'done').length
    const accepted = remainingDocuments == null ? files : files.slice(0, Math.max(0, remainingDocuments - existingCount))
    if (accepted.length < files.length) toast.error('部分檔案未加入：已超過租戶剩餘文件數量。')
    const existing = new Set(queue.map(item => item.key))
    let remainingBytes = capabilities.quota?.remaining_storage_bytes
    if (remainingBytes != null) remainingBytes = Math.max(0, remainingBytes - queue.filter(item => item.status !== 'done').reduce((sum, item) => sum + item.file.size, 0))
    const incoming: UploadItem[] = []
    for (const file of accepted.filter(candidate => !existing.has(fileKey(candidate)))) {
      const checked = preflightFile(file, capabilities, remainingBytes)
      incoming.push({ key: fileKey(file), file, idempotencyKey: newIdempotencyKey(), status: checked.error ? 'error' : 'checking', progress: 0, capability: checked.capability, warning: checked.warning, error: checked.error, preflightError: checked.error })
      if (!checked.error && remainingBytes != null) remainingBytes = Math.max(0, remainingBytes - file.size)
    }
    setQueue(current => [...current, ...incoming])
    for (const item of incoming) {
      if (item.status === 'error') continue
      const maxDuration = item.capability?.max_duration_seconds
      if (item.capability?.asset_kind === 'video' && maxDuration) {
        const duration = await mediaDurationSeconds(item.file)
        if (duration != null && duration > maxDuration) {
          setQueue(current => current.map(candidate => candidate.key === item.key ? { ...candidate, status: 'error', error: `影片長度超過 ${Math.round(maxDuration / 60)} 分鐘上限` } : candidate))
          continue
        }
      }
      setQueue(current => current.map(candidate => candidate.key === item.key ? { ...candidate, status: 'pending' } : candidate))
    }
  }, [capabilities, queue])

  const accept = useMemo(() => buildDropAccept(capabilities), [capabilities])
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop: files => void addFiles(files), onDropRejected: rejected => toast.error(`${rejected.length} 個檔案格式不受支援，未加入佇列。`), accept, multiple: true, disabled: busy || !capabilities })
  const pendingFiles = useMemo(() => queue.filter(item => ['pending', 'error', 'cancelled'].includes(item.status) && !item.preflightError), [queue])
  const updateQueueItem = (key: string, patch: Partial<UploadItem>) => setQueue(current => current.map(item => item.key === key ? { ...item, ...patch } : item))
  const sharedInput = () => ({ dataClassification: classification, departmentId: departmentId || undefined, contextMetadata: contextPayload(context) })

  const submitFiles = async () => {
    const targets = queue.filter(item => ['pending', 'error', 'cancelled'].includes(item.status) && !item.preflightError)
    let succeeded = 0; let failed = 0; let lastAssetId = ''
    for (const item of targets) {
      const controller = new AbortController(); controllers.current.set(item.key, controller)
      updateQueueItem(item.key, { status: 'uploading', progress: 0, error: undefined })
      try {
        const input = { ...sharedInput(), file: item.file, title: queue.length === 1 ? title : '', idempotencyKey: item.idempotencyKey }
        const asset = capabilities?.policy.generic_resumable_upload
          ? await uploadFileResumable({
              ...input,
              sessionId: item.uploadSessionId,
              partSize: capabilities.policy.resumable_part_size,
            }, {
              signal: controller.signal,
              onSession: session => updateQueueItem(item.key, { uploadSessionId: session.id }),
              onProgress: value => updateQueueItem(item.key, { progress: value }),
            })
          : await knowledgeAssetApi.create(input, { signal: controller.signal, onProgress: value => updateQueueItem(item.key, { progress: value }) })
        updateQueueItem(item.key, { status: 'done', progress: 100, assetId: asset.id })
        rememberKnowledgeTask({ assetId: asset.id, title: asset.title || item.file.name, assetKind: asset.asset_kind, createdAt: new Date().toISOString() })
        succeeded += 1; lastAssetId = asset.id
      } catch (reason) {
        if (controller.signal.aborted) updateQueueItem(item.key, { status: 'cancelled', error: '已暫停；伺服器已確認的分塊會保留，可從中斷處繼續。' })
        else updateQueueItem(item.key, { status: 'error', error: formatErrorWithTrace(parseApiError(reason, `無法加入 ${item.file.name}`)) })
        failed += 1
      } finally { controllers.current.delete(item.key) }
    }
    if (failed) { toast.error(`${failed} 筆未完成；已完成 ${succeeded} 筆，可直接重試。`); return }
    toast.success(targets.length > 1 ? `已將 ${targets.length} 筆來源加入處理佇列` : '已加入知識處理佇列')
    navigate(targets.length === 1 && lastAssetId ? `/knowledge/assets/${lastAssetId}` : '/knowledge/assets')
  }

  const removeQueueItem = async (item: UploadItem) => {
    if (item.uploadSessionId) {
      try { await uploadSessionApi.abort(item.uploadSessionId) }
      catch (reason) { toast.error(formatErrorWithTrace(parseApiError(reason, '無法中止伺服器上的上傳工作'))); return }
    }
    setQueue(current => current.filter(candidate => candidate.key !== item.key))
  }

  const submitSingleSource = async () => {
    const identity = mode === 'url' ? `url:${url.trim()}` : `record:${sourceSystem.trim()}:${recordId.trim()}`
    const idempotencyKey = sourceKeys.current.get(identity) || newIdempotencyKey(); sourceKeys.current.set(identity, idempotencyKey)
    try {
      const asset = await knowledgeAssetApi.create({ ...sharedInput(), title, sourceUrl: mode === 'url' ? url : undefined, sourceSystem: mode === 'record' ? sourceSystem : undefined, sourceRecordId: mode === 'record' ? recordId : undefined, idempotencyKey }, { onProgress: setProgress })
      toast.success(asset.deduplicated ? '已找到相同內容，沿用既有資產' : '已加入知識處理佇列')
      rememberKnowledgeTask({ assetId: asset.id, title: asset.title || title || url || `${sourceSystem}:${recordId}`, assetKind: asset.asset_kind, createdAt: new Date().toISOString() })
      navigate(`/knowledge/assets/${asset.id}`)
    } catch (reason) { toast.error(formatErrorWithTrace(parseApiError(reason, '無法加入知識'))) }
  }
  const submit = async () => { setBusy(true); try { if (mode === 'file') await submitFiles(); else await submitSingleSource() } finally { setBusy(false) } }
  const invalid = mode === 'file' ? !capabilities || !queue.some(item => ['pending', 'error', 'cancelled'].includes(item.status) && !item.preflightError) : mode === 'capture' ? true : mode === 'url' ? !url.trim() : !sourceSystem.trim() || !recordId.trim()
  const modes: Mode[] = ['file', 'capture', 'url', 'record']
  const selectAdjacentMode = (current: Mode, offset: number) => { const next = modes[(modes.indexOf(current) + offset + modes.length) % modes.length]; setMode(next); window.requestAnimationFrame(() => document.getElementById(`source-tab-${next}`)?.focus()) }
  const configuredCount = capabilities?.formats.filter(format => format.processing_status === 'configured').length || 0
  const degradedCount = capabilities?.formats.filter(format => format.processing_status === 'degraded').length || 0

  return <WorkspacePage title="新增知識" subtitle="先檢查格式、容量與處理能力，再安全送入同一套企業知識管線。" backTo="/knowledge/assets" backLabel="回所有資產" width="reading">
    <SectionPanel className="mt-6" title="1. 選擇來源" description="可用格式與限制由目前部署環境即時提供，不使用前端猜測值。">
      {capabilityError && <div role="alert" className="mb-4 rounded-xl border border-danger/30 bg-danger/5 p-4 text-sm text-danger"><p>{capabilityError}</p><button type="button" className="btn-outline mt-3" onClick={() => void loadCapabilities()}><RefreshCw className="h-4 w-4" />重新取得能力</button></div>}
      {capabilities && <div className="mb-4 rounded-xl bg-wash p-3 text-sm text-muted"><p><span className="font-medium text-ink">此環境可處理 {configuredCount} 種格式</span>{degradedCount > 0 ? `；另有 ${degradedCount} 種會降級處理` : ''}</p><p className="mt-1">剩餘空間：{capabilities.quota?.remaining_storage_bytes == null ? '未設上限' : formatBytes(capabilities.quota.remaining_storage_bytes)} · 剩餘文件：{capabilities.quota?.remaining_documents ?? '未設上限'}</p>{capabilities.quota?.warnings.map(warning => <p key={warning} className="mt-1 text-warning">{warning}</p>)}</div>}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="tablist" aria-label="知識來源">
        {([['file', FileUp, '上傳檔案'], ['capture', Mic, '現場擷取'], ['url', Link2, '貼上網址'], ['record', FileUp, '外部紀錄']] as const).map(([value, Icon, label]) => <button key={value} id={`source-tab-${value}`} type="button" role="tab" aria-selected={mode === value} aria-controls={`source-panel-${value}`} tabIndex={mode === value ? 0 : -1} onClick={() => setMode(value)} onKeyDown={event => { if (event.key === 'ArrowRight') { event.preventDefault(); selectAdjacentMode(value, 1) } else if (event.key === 'ArrowLeft') { event.preventDefault(); selectAdjacentMode(value, -1) } else if (event.key === 'Home') { event.preventDefault(); setMode('file'); window.requestAnimationFrame(() => document.getElementById('source-tab-file')?.focus()) } else if (event.key === 'End') { event.preventDefault(); setMode('record'); window.requestAnimationFrame(() => document.getElementById('source-tab-record')?.focus()) } }} className={`min-h-16 rounded-xl border p-2 text-sm font-medium transition-colors ${mode === value ? 'border-accent bg-accent-soft text-accent' : 'border-line text-muted hover:border-accent/40 hover:text-ink'}`}><Icon className="mx-auto mb-1 h-5 w-5" aria-hidden />{label}</button>)}
      </div>
      <div id={`source-panel-${mode}`} role="tabpanel" aria-labelledby={`source-tab-${mode}`} className="mt-6 space-y-4">
        {mode === 'file' && <>
          <div {...getRootProps()} aria-disabled={!capabilities} className={`rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${capabilities ? 'cursor-pointer' : 'cursor-wait opacity-60'} ${isDragActive ? 'border-accent bg-accent-soft' : 'border-line hover:border-accent'}`}><input {...getInputProps()} aria-label="選擇檔案" />{capabilities ? <FileUp className="mx-auto h-8 w-8 text-accent" aria-hidden /> : <Loader2 className="mx-auto h-8 w-8 animate-spin text-accent" aria-hidden />}<span className="mt-2 block font-medium text-ink">選擇檔案、照片、錄音或影片</span><span className="mt-1 block text-sm text-muted">加入前先檢查格式、大小、影片長度與租戶配額；未完成項目會保存在此瀏覽器</span></div>
          <div className="grid grid-cols-3 gap-2 sm:hidden"><label className="btn-outline justify-center"><Camera className="h-4 w-4" aria-hidden />拍照<input className="sr-only" type="file" accept="image/*" capture="environment" onChange={event => void addFiles(Array.from(event.target.files || []))} /></label><label className="btn-outline justify-center"><Mic className="h-4 w-4" aria-hidden />錄音<input className="sr-only" type="file" accept="audio/*" capture onChange={event => void addFiles(Array.from(event.target.files || []))} /></label><label className="btn-outline justify-center"><Video className="h-4 w-4" aria-hidden />錄影<input className="sr-only" type="file" accept="video/*" capture="environment" onChange={event => void addFiles(Array.from(event.target.files || []))} /></label></div>
          {queue.some(item => item.capability?.asset_kind === 'video') && capabilities?.policy.video_allowed_codecs.length ? <p className="text-xs text-muted">影片容器已在本機預檢；伺服器會再驗證編碼：{capabilities.policy.video_allowed_codecs.join('、')}。</p> : null}
          {queue.length > 0 && <ul className="space-y-2" aria-label="待上傳來源">{queue.map(item => <li key={item.key} className="rounded-xl border border-line bg-wash p-3"><div className="flex items-start gap-3"><span className="mt-0.5 text-accent">{item.status === 'uploading' || item.status === 'checking' ? <Loader2 className="h-5 w-5 animate-spin" /> : item.status === 'done' ? <CheckCircle2 className="h-5 w-5 text-success" /> : item.status === 'error' || item.status === 'cancelled' ? <XCircle className="h-5 w-5 text-danger" /> : <FileUp className="h-5 w-5" />}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-ink">{item.file.name}</span><span className="mt-0.5 block text-xs text-muted">{capabilitySummary(item.capability)} · {formatBytes(item.file.size)}</span>{item.warning && <span className="mt-1 block text-xs text-warning">降級提示：{item.warning}</span>}{item.error && <span className="mt-1 block text-xs text-danger">{item.error}</span>}{item.status === 'uploading' && <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-line" role="progressbar" aria-label={`${item.file.name} 上傳進度`} aria-valuenow={item.progress}><span className="block h-full bg-accent" style={{ width: `${item.progress}%` }} /></span>}</span><span className="flex gap-1">{item.status === 'uploading' && <button type="button" className="icon-btn -m-2" aria-label={`暫停 ${item.file.name}`} onClick={() => controllers.current.get(item.key)?.abort()}><Square className="h-4 w-4" /></button>}{(item.status === 'error' || item.status === 'cancelled') && !item.preflightError ? <button type="button" className="icon-btn -m-2" aria-label={`重試 ${item.file.name}`} onClick={() => updateQueueItem(item.key, { status: 'pending', error: undefined })}><RefreshCw className="h-4 w-4" /></button> : null}{item.status !== 'uploading' && item.status !== 'done' && <button type="button" className="icon-btn -m-2" aria-label={`移除 ${item.file.name}`} onClick={() => void removeQueueItem(item)}><Trash2 className="h-4 w-4" /></button>}</span></div></li>)}</ul>}
        </>}
        {mode === 'capture' && <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="btn-outline min-h-20 cursor-pointer justify-center"><Camera className="h-5 w-5" aria-hidden /><span><span className="block font-medium">拍攝照片</span><span className="block text-xs text-muted">拍完後以 I2 安全續傳</span></span><input className="sr-only" type="file" accept="image/*" capture="environment" onChange={event => { void addFiles(Array.from(event.target.files || [])); setMode('file') }} /></label>
            <label className="btn-outline min-h-20 cursor-pointer justify-center"><Video className="h-5 w-5" aria-hidden /><span><span className="block font-medium">拍攝影片</span><span className="block text-xs text-muted">中斷後只補傳缺少分塊</span></span><input className="sr-only" type="file" accept="video/*" capture="environment" onChange={event => { void addFiles(Array.from(event.target.files || [])); setMode('file') }} /></label>
          </div>
          <label className="flex items-start gap-3 rounded-xl border border-line bg-wash p-4">
            <input type="checkbox" checked={captureConsent} onChange={event => setCaptureConsent(event.target.checked)} className="mt-1 h-5 w-5" />
            <span className="text-sm text-ink">我已取得錄音對象同意，並了解音訊、逐字稿與知識資產會依本租戶的保留與權限政策處理。</span>
          </label>
          <CoreAudioRecorder
            title={title}
            disabled={!captureConsent || !capabilities}
            captureStatus={captureResult?.status}
            departmentId={departmentId || undefined}
            dataClassification={classification}
            contextMetadata={contextPayload(context)}
            sourceModule="core"
            purpose="knowledge_capture"
            onQueued={session => {
              setCaptureResult(session)
              if (session.source_asset_id) {
                rememberKnowledgeTask({ assetId: session.source_asset_id, title: session.title, assetKind: 'audio', createdAt: new Date().toISOString() })
              }
            }}
            onError={message => toast.error(message)}
          />
          {captureResult?.source_asset_id && <button type="button" className="btn-primary w-full justify-center" onClick={() => navigate(`/knowledge/assets/${captureResult.source_asset_id}`)}>查看錄音知識資產</button>}
        </div>}
        {mode === 'url' && <label className="block text-sm font-medium text-ink">網址<input type="url" className="input mt-2 w-full" placeholder="https://…" value={url} onChange={event => setUrl(event.target.value)} /></label>}
        {mode === 'record' && <div className="grid gap-4 md:grid-cols-2"><label className="text-sm font-medium text-ink">來源系統<input className="input mt-2 w-full" placeholder="例如 ERP、MES、CRM" value={sourceSystem} onChange={event => setSourceSystem(event.target.value)} /></label><label className="text-sm font-medium text-ink">紀錄識別碼<input className="input mt-2 w-full" value={recordId} onChange={event => setRecordId(event.target.value)} /></label></div>}
      </div>
    </SectionPanel>
    <SectionPanel className="mt-5" title="2. 確認治理與現場脈絡" description="這些標記會在建立資產與處理工作時一起保存，供權限、檢索與追溯使用。">
      <div className="space-y-4">
        <label className="block text-sm font-medium text-ink">顯示名稱（選填）<input className="input mt-2 w-full" disabled={mode === 'file' && queue.length > 1} value={title} onChange={event => setTitle(event.target.value)} />{mode === 'file' && queue.length > 1 && <span className="mt-1 block text-xs text-muted">多檔加入時各自沿用檔名。</span>}</label>
        <div className="grid gap-4 md:grid-cols-2"><label className="block text-sm font-medium text-ink">資料分類<select className="input mt-2 w-full" value={classification} onChange={event => setClassification(event.target.value)}>{(capabilities?.policy.data_classifications || ['internal', 'confidential', 'restricted']).map(value => <option key={value} value={value}>{{ public: '公開', internal: '內部', confidential: '機密', restricted: '高度機密' }[value] || value}</option>)}</select></label><label className="block text-sm font-medium text-ink">適用部門（選填）<select className="input mt-2 w-full" value={departmentId} onChange={event => setDepartmentId(event.target.value)}><option value="">全租戶可見</option>{departments.map(department => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label></div>
        <details className="rounded-xl border border-line p-4"><summary className="cursor-pointer text-sm font-medium text-ink">加入廠區、產線、設備等檢索脈絡（選填）</summary><div className="mt-4 grid gap-3 md:grid-cols-2">{([['site', '廠區'], ['production_line', '產線'], ['equipment', '設備／機台'], ['product', '產品'], ['work_order', '工單'], ['shift', '班別'], ['tags', '標籤（逗號分隔）']] as const).map(([key, label]) => <label key={key} className="text-sm font-medium text-ink">{label}<input className="input mt-1 w-full" value={context[key]} onChange={event => setContext(current => ({ ...current, [key]: event.target.value }))} /></label>)}</div></details>
        <div className="rounded-xl bg-accent-soft p-4 text-sm text-accent-ink"><p className="font-medium">3. 加入後的流程</p><p className="mt-1">安全檢查 → 內容理解 → 品質確認 → 必要時人工覆核 → 正式發布。檔案會分塊校驗；網路中斷、重新登入或重開頁面後，只續傳尚未確認的部分。</p></div>
        {mode !== 'file' && busy && progress > 0 && <div role="progressbar" aria-valuenow={progress} className="h-2 overflow-hidden rounded bg-line"><div className="h-full bg-accent" style={{ width: `${progress}%` }} /></div>}
        {mode !== 'capture' && <button type="button" disabled={busy || invalid} onClick={() => void submit()} className="btn-primary w-full justify-center">{busy ? <><Loader2 className="h-4 w-4 animate-spin" />正在加入…</> : mode === 'file' && pendingFiles.length > 1 ? `加入 ${pendingFiles.length} 筆公司知識` : '加入公司知識'}</button>}
      </div>
    </SectionPanel>
  </WorkspacePage>
}
