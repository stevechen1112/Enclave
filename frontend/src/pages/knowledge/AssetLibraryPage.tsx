import { useCallback, useEffect, useMemo, useState } from 'react'
import { FileAudio, FileImage, FileSpreadsheet, FileText, Film, Globe2, Plus, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import api, { knowledgeAssetApi, parseApiError, type ApiErrorInfo } from '../../api'
import type { KnowledgeAsset } from '../../types'
import AsyncState from '../../components/AsyncState'
import LifecycleBadge from '../../components/LifecycleBadge'
import { SectionPanel, WorkspacePage } from '../../components/WorkspacePage'
import { useHasCapability } from '../../navigation/useCapabilities'

const KIND_LABELS: Record<string, string> = {
  document: '文件', spreadsheet: '試算表', image: '圖片', audio: '音訊', video: '影片',
  web_page: '網頁', external_record: '外部紀錄', email: '郵件', dataset: '資料集',
}
const ICONS: Record<string, typeof FileText> = {
  spreadsheet: FileSpreadsheet, image: FileImage, audio: FileAudio, video: Film, web_page: Globe2,
}

export default function AssetLibraryPage() {
  const [assets, setAssets] = useState<KnowledgeAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [source, setSource] = useState('')
  const [classification, setClassification] = useState('')
  const [department, setDepartment] = useState('')
  const [updatedDays, setUpdatedDays] = useState('')
  const [publication, setPublication] = useState('')
  const [departments, setDepartments] = useState<Array<{ id: string; name: string }>>([])
  const [query, setQuery] = useState('')
  const canAdd = useHasCapability('upload_documents')

  const load = useCallback(async () => {
    try {
      setAssets(await knowledgeAssetApi.list({
        kind: kind || undefined,
        processing_status: status || undefined,
        source_system: source || undefined,
        data_classification: classification || undefined,
        department_id: department || undefined,
        updated_after: updatedDays ? new Date(Date.now() - Number(updatedDays) * 86400000).toISOString() : undefined,
        publication_status: publication || undefined,
      }))
      setError(null)
    } catch (reason) { setError(parseApiError(reason, '無法載入知識資產')) }
    finally { setLoading(false) }
  }, [classification, department, kind, publication, source, status, updatedDays])

  useEffect(() => {
    void api.get<Array<{ id: string; name: string }>>('/departments/options')
      .then(response => setDepartments(response.data))
      .catch(() => setDepartments([]))
  }, [])

  useEffect(() => { setLoading(true); void load() }, [load])
  useEffect(() => {
    if (!assets.some(asset => ['queued', 'running'].includes(asset.job?.status || ''))) return
    const timer = window.setInterval(() => void load(), 4000)
    return () => window.clearInterval(timer)
  }, [assets, load])

  const visible = useMemo(() => assets.filter(asset => asset.title.toLowerCase().includes(query.toLowerCase())), [assets, query])

  const filtersActive = [kind, status, source, classification, department, updatedDays, publication, query].some(Boolean)
  const resetFilters = () => { setKind(''); setStatus(''); setSource(''); setClassification(''); setDepartment(''); setUpdatedDays(''); setPublication(''); setQuery('') }

  return (
    <WorkspacePage title="所有資產" subtitle="文件、表格、圖片、錄音、影片與外部來源，都使用同一套生命週期。" actions={canAdd && <Link className="btn-primary" to="/knowledge/new"><Plus className="h-4 w-4" />新增知識</Link>}>
      <SectionPanel className="mt-5" title="搜尋與篩選" description={`${visible.length} 筆符合目前條件`} actions={filtersActive && <button type="button" className="btn-ghost" onClick={resetFilters}>清除篩選</button>} bodyClassName="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="md:col-span-2"><span className="sr-only">搜尋資產</span><input className="input w-full" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜尋名稱" /></label>
        <select className="input" aria-label="資產類型" value={kind} onChange={event => setKind(event.target.value)}><option value="">所有類型</option>{Object.entries(KIND_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <select className="input" aria-label="處理狀態" value={status} onChange={event => setStatus(event.target.value)}><option value="">所有狀態</option><option value="answer_ready">已可問答</option><option value="processing">系統處理中</option><option value="awaiting_review">等待人工確認</option><option value="needs_attention">需要處理</option></select>
        <select className="input" aria-label="來源" value={source} onChange={event => setSource(event.target.value)}><option value="">所有來源</option><option value="upload">直接上傳</option><option value="capture">行動擷取</option><option value="web">網頁</option><option value="nas_smb">NAS</option><option value="sharepoint">SharePoint</option><option value="google_drive">Google Drive</option></select>
        <select className="input" aria-label="資料分類" value={classification} onChange={event => setClassification(event.target.value)}><option value="">所有分類</option><option value="public">公開</option><option value="internal">內部</option><option value="confidential">機密</option><option value="restricted">高度機密</option></select>
        <select className="input" aria-label="部門" value={department} onChange={event => setDepartment(event.target.value)}><option value="">所有部門</option>{departments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <select className="input" aria-label="更新日期" value={updatedDays} onChange={event => setUpdatedDays(event.target.value)}><option value="">所有日期</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option></select>
        <select className="input" aria-label="發布狀態" value={publication} onChange={event => setPublication(event.target.value)}><option value="">所有發布狀態</option><option value="published">已發布</option><option value="unpublished">未發布</option></select>
      </SectionPanel>
      {loading && assets.length === 0 ? <AsyncState loading>{null}</AsyncState> : error && assets.length === 0 ? <AsyncState error={error} onRetry={load}>{null}</AsyncState> : (
        <SectionPanel className="mt-5" bodyClassName="p-0">
          {visible.length === 0 ? <AsyncState empty emptyTitle="沒有符合條件的知識資產" emptyDescription="調整搜尋或使用上方的清除篩選後再試一次。">{null}</AsyncState> : visible.map(asset => {
            const Icon = ICONS[asset.asset_kind] || FileText
            return <Link key={asset.id} to={`/knowledge/assets/${asset.id}`} className="flex min-h-20 items-center gap-4 border-b border-line px-4 py-3 last:border-0 hover:bg-wash md:px-5">
              <span className="rounded-xl bg-accent-soft p-2.5 text-accent"><Icon className="h-5 w-5" aria-hidden /></span>
              <span className="min-w-0 flex-1"><span className="block truncate font-medium text-ink">{asset.title}</span><span className="mt-1 block text-xs text-muted">{KIND_LABELS[asset.asset_kind] || asset.asset_kind} · {asset.source_system} · v{asset.current_revision}</span></span>
              <span className="hidden text-sm text-muted sm:block">{asset.updated_at || asset.created_at ? format(new Date(asset.updated_at || asset.created_at), 'yyyy/MM/dd') : '—'}</span>
              <LifecycleBadge status={asset.lifecycle_status || asset.job?.status || asset.status} tombstoned={asset.tombstoned_at} answerReady={asset.answer_ready} />
            </Link>
          })}
        </SectionPanel>
      )}
      {error && assets.length > 0 && <button className="mt-3 inline-flex items-center gap-2 text-sm text-danger" onClick={() => void load()}><RefreshCw className="h-4 w-4" />更新失敗，重新整理</button>}
    </WorkspacePage>
  )
}
