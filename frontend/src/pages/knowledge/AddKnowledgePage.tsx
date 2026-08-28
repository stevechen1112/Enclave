import { useCallback, useMemo, useState } from 'react'
import { Camera, CheckCircle2, FileUp, Link2, Loader2, Mic, Trash2, Video, XCircle } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { knowledgeAssetApi, formatErrorWithTrace, parseApiError } from '../../api'
import { SectionPanel, WorkspacePage } from '../../components/WorkspacePage'
import { rememberKnowledgeTask } from '../../lib/longTaskRecovery'

type Mode = 'file' | 'url' | 'record'
type QueueStatus = 'pending' | 'uploading' | 'done' | 'error'
type UploadItem = { key: string; file: File; status: QueueStatus; progress: number; assetId?: string; error?: string }

const DROP_ACCEPT = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'text/csv': ['.csv'],
  'text/plain': ['.txt'],
  'image/*': ['.jpg', '.jpeg', '.png'],
  'audio/*': ['.mp3', '.wav', '.m4a', '.ogg', '.flac'],
  'video/*': ['.mp4', '.mov', '.webm', '.mkv'],
}

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`
}

function capabilitySummary(file: File) {
  if (file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv)$/i.test(file.name)) return '語音轉寫、說話者與時間碼、鏡頭、關鍵畫面、OCR、事件候選與跨模態時間軸'
  if (file.type.startsWith('audio/') || /\.(mp3|wav|m4a|ogg|flac)$/i.test(file.name)) return '長時間轉寫、說話者與時間碼、術語校正'
  if (file.type.startsWith('image/') || /\.(jpg|jpeg|png)$/i.test(file.name)) return 'OCR、版面與影像證據定位'
  if (/\.(xlsx|csv)$/i.test(file.name)) return '工作表、表格與欄位結構解析'
  return '文字、版面、章節與引用定位'
}

export default function AddKnowledgePage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('file')
  const [queue, setQueue] = useState<UploadItem[]>([])
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [sourceSystem, setSourceSystem] = useState('')
  const [recordId, setRecordId] = useState('')
  const [classification, setClassification] = useState('internal')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)

  const addFiles = useCallback((files: File[]) => {
    setQueue(current => {
      const existing = new Set(current.map(item => item.key))
      const incoming = files
        .filter(file => !existing.has(fileKey(file)))
        .map(file => ({ key: fileKey(file), file, status: 'pending' as const, progress: 0 }))
      return [...current, ...incoming]
    })
  }, [])
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: addFiles,
    onDropRejected: rejected => toast.error(`${rejected.length} 個檔案格式不受支援，未加入佇列。`),
    accept: DROP_ACCEPT,
    multiple: true,
    disabled: busy,
  })
  const pendingFiles = useMemo(() => queue.filter(item => item.status !== 'done'), [queue])
  const updateQueueItem = (key: string, patch: Partial<UploadItem>) => {
    setQueue(current => current.map(item => item.key === key ? { ...item, ...patch } : item))
  }

  const submitFiles = async () => {
    const targets = queue.filter(item => item.status !== 'done')
    let succeeded = 0
    let failed = 0
    let lastAssetId = ''
    for (const item of targets) {
      updateQueueItem(item.key, { status: 'uploading', progress: 0, error: undefined })
      try {
        const asset = await knowledgeAssetApi.create({
          file: item.file,
          title: queue.length === 1 ? title : '',
          dataClassification: classification,
        }, value => updateQueueItem(item.key, { progress: value }))
        updateQueueItem(item.key, { status: 'done', progress: 100, assetId: asset.id })
        rememberKnowledgeTask({
          assetId: asset.id,
          title: asset.title || item.file.name,
          assetKind: asset.asset_kind,
          createdAt: new Date().toISOString(),
        })
        succeeded += 1
        lastAssetId = asset.id
      } catch (reason) {
        const info = parseApiError(reason, `無法加入 ${item.file.name}`)
        updateQueueItem(item.key, { status: 'error', error: formatErrorWithTrace(info) })
        failed += 1
      }
    }
    if (failed) {
      toast.error(`${failed} 筆加入失敗；已完成 ${succeeded} 筆，可直接重試失敗項目。`)
      return
    }
    toast.success(targets.length > 1 ? `已將 ${targets.length} 筆來源加入處理佇列` : '已加入知識處理佇列')
    navigate(targets.length === 1 && lastAssetId ? `/knowledge/assets/${lastAssetId}` : '/knowledge/assets')
  }

  const submitSingleSource = async () => {
    try {
      const asset = await knowledgeAssetApi.create({
        title,
        sourceUrl: mode === 'url' ? url : undefined,
        sourceSystem: mode === 'record' ? sourceSystem : undefined,
        sourceRecordId: mode === 'record' ? recordId : undefined,
        dataClassification: classification,
      }, setProgress)
      toast.success(asset.deduplicated ? '已找到相同內容，沿用既有資產' : '已加入知識處理佇列')
      rememberKnowledgeTask({
        assetId: asset.id,
        title: asset.title || title || url || `${sourceSystem}:${recordId}`,
        assetKind: asset.asset_kind,
        createdAt: new Date().toISOString(),
      })
      navigate(`/knowledge/assets/${asset.id}`)
    } catch (reason) {
      toast.error(formatErrorWithTrace(parseApiError(reason, '無法加入知識')))
    }
  }

  const submit = async () => {
    setBusy(true)
    try {
      if (mode === 'file') await submitFiles()
      else await submitSingleSource()
    } finally {
      setBusy(false)
    }
  }
  const invalid = mode === 'file' ? pendingFiles.length === 0 : mode === 'url' ? !url.trim() : !sourceSystem.trim() || !recordId.trim()
  const modes: Mode[] = ['file', 'url', 'record']
  const selectAdjacentMode = (current: Mode, offset: number) => {
    const index = modes.indexOf(current)
    const next = modes[(index + offset + modes.length) % modes.length]
    setMode(next)
    window.requestAnimationFrame(() => document.getElementById(`source-tab-${next}`)?.focus())
  }

  return <WorkspacePage title="新增知識" subtitle="選擇來源即可；系統會自動判斷文字擷取、表格解析、OCR、轉寫或影音分析。" backTo="/knowledge/assets" backLabel="回所有資產" width="reading">
    <SectionPanel className="mt-6" title="1. 選擇來源" description="不同來源共用相同的權限、處理、覆核與發布生命週期。">
      <div className="grid grid-cols-3 gap-2" role="tablist" aria-label="知識來源">
        {([['file', FileUp, '上傳／拍攝'], ['url', Link2, '貼上網址'], ['record', Mic, '外部紀錄']] as const).map(([value, Icon, label]) => <button key={value} id={`source-tab-${value}`} type="button" role="tab" aria-selected={mode === value} aria-controls={`source-panel-${value}`} tabIndex={mode === value ? 0 : -1} onClick={() => setMode(value)} onKeyDown={event => { if (event.key === 'ArrowRight') { event.preventDefault(); selectAdjacentMode(value, 1) } else if (event.key === 'ArrowLeft') { event.preventDefault(); selectAdjacentMode(value, -1) } else if (event.key === 'Home') { event.preventDefault(); setMode('file'); window.requestAnimationFrame(() => document.getElementById('source-tab-file')?.focus()) } else if (event.key === 'End') { event.preventDefault(); setMode('record'); window.requestAnimationFrame(() => document.getElementById('source-tab-record')?.focus()) } }} className={`min-h-16 rounded-xl border p-2 text-sm font-medium transition-colors ${mode === value ? 'border-accent bg-accent-soft text-accent' : 'border-line text-muted hover:border-accent/40 hover:text-ink'}`}><Icon className="mx-auto mb-1 h-5 w-5" aria-hidden />{label}</button>)}
      </div>
      <div id={`source-panel-${mode}`} role="tabpanel" aria-labelledby={`source-tab-${mode}`} className="mt-6 space-y-4">
        {mode === 'file' && <>
          <div {...getRootProps()} className={`cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${isDragActive ? 'border-accent bg-accent-soft' : 'border-line hover:border-accent'}`}>
            <input {...getInputProps()} aria-label="選擇檔案" />
            <FileUp className="mx-auto h-8 w-8 text-accent" aria-hidden />
            <span className="mt-2 block font-medium text-ink">選擇檔案、照片、錄音或影片</span>
            <span className="mt-1 block text-sm text-muted">可一次拖放多個來源；系統會逐檔建立可追蹤的處理工作</span>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:hidden">
            <label className="btn-outline justify-center"><Camera className="h-4 w-4" aria-hidden />拍照<input className="sr-only" type="file" accept="image/*" capture="environment" onChange={event => addFiles(Array.from(event.target.files || []))} /></label>
            <label className="btn-outline justify-center"><Mic className="h-4 w-4" aria-hidden />錄音<input className="sr-only" type="file" accept="audio/*" capture onChange={event => addFiles(Array.from(event.target.files || []))} /></label>
            <label className="btn-outline justify-center"><Video className="h-4 w-4" aria-hidden />錄影<input className="sr-only" type="file" accept="video/*" capture="environment" onChange={event => addFiles(Array.from(event.target.files || []))} /></label>
          </div>
          {queue.length > 0 && <ul className="space-y-2" aria-label="待上傳來源">{queue.map(item => <li key={item.key} className="rounded-xl border border-line bg-wash p-3"><div className="flex items-start gap-3"><span className="mt-0.5 text-accent">{item.status === 'uploading' ? <Loader2 className="h-5 w-5 animate-spin" /> : item.status === 'done' ? <CheckCircle2 className="h-5 w-5 text-success" /> : item.status === 'error' ? <XCircle className="h-5 w-5 text-danger" /> : <FileUp className="h-5 w-5" />}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-ink">{item.file.name}</span><span className="mt-0.5 block text-xs text-muted">{capabilitySummary(item.file)}</span>{item.error && <span className="mt-1 block text-xs text-danger">{item.error}</span>}{item.status === 'uploading' && <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuenow={item.progress}><span className="block h-full bg-accent" style={{ width: `${item.progress}%` }} /></span>}</span>{item.status !== 'uploading' && item.status !== 'done' && <button type="button" className="icon-btn -m-2" aria-label={`移除 ${item.file.name}`} onClick={event => { event.stopPropagation(); setQueue(current => current.filter(candidate => candidate.key !== item.key)) }}><Trash2 className="h-4 w-4" /></button>}</div></li>)}</ul>}
        </>}
        {mode === 'url' && <label className="block text-sm font-medium text-ink">網址<input type="url" className="input mt-2 w-full" placeholder="https://…" value={url} onChange={event => setUrl(event.target.value)} /></label>}
        {mode === 'record' && <div className="grid gap-4 md:grid-cols-2"><label className="text-sm font-medium text-ink">來源系統<input className="input mt-2 w-full" placeholder="例如 CRM" value={sourceSystem} onChange={event => setSourceSystem(event.target.value)} /></label><label className="text-sm font-medium text-ink">紀錄識別碼<input className="input mt-2 w-full" value={recordId} onChange={event => setRecordId(event.target.value)} /></label></div>}
      </div>
    </SectionPanel>
    <SectionPanel className="mt-5" title="2. 確認治理資訊" description="資料分類會套用到本次建立的每一個來源。">
      <div className="space-y-4">
        <label className="block text-sm font-medium text-ink">顯示名稱（選填）<input className="input mt-2 w-full" disabled={mode === 'file' && queue.length > 1} value={title} onChange={event => setTitle(event.target.value)} />{mode === 'file' && queue.length > 1 && <span className="mt-1 block text-xs text-muted">多檔加入時各自沿用檔名。</span>}</label>
        <label className="block text-sm font-medium text-ink">資料分類<select className="input mt-2 w-full" value={classification} onChange={event => setClassification(event.target.value)}><option value="internal">內部</option><option value="confidential">機密</option><option value="restricted">高度機密</option></select></label>
        <div className="rounded-xl bg-accent-soft p-4 text-sm text-accent-ink"><p className="font-medium">3. 加入後的流程</p><p className="mt-1">安全檢查 → 內容理解 → 品質確認 → 必要時人工覆核 → 正式發布。每個來源都能在資產頁查看獨立進度與證據。</p></div>
        {mode !== 'file' && busy && progress > 0 && <div role="progressbar" aria-valuenow={progress} className="h-2 overflow-hidden rounded bg-line"><div className="h-full bg-accent" style={{ width: `${progress}%` }} /></div>}
        <button type="button" disabled={busy || invalid} onClick={() => void submit()} className="btn-primary w-full justify-center">{busy ? <><Loader2 className="h-4 w-4 animate-spin" />正在加入…</> : mode === 'file' && pendingFiles.length > 1 ? `加入 ${pendingFiles.length} 筆公司知識` : '加入公司知識'}</button>
      </div>
    </SectionPanel>
  </WorkspacePage>
}
