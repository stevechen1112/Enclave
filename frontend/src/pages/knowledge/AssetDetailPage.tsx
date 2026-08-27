import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Circle, RefreshCw, RotateCcw } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { format } from 'date-fns'
import { knowledgeAssetApi, formatErrorWithTrace, parseApiError, type ApiErrorInfo } from '../../api'
import type { KnowledgeAsset, KnowledgeAssetEvent } from '../../types'
import AsyncState from '../../components/AsyncState'
import LifecycleBadge from '../../components/LifecycleBadge'
import { MetadataList, SectionPanel, WorkspacePage } from '../../components/WorkspacePage'

const PHASE_LABELS: Record<string, string> = {
  queued: '等待處理',
  fetch: '讀取來源',
  parsing: '解析內容',
  processing: '內容處理',
  embedding: '建立搜尋索引',
  review_required: '等待人工覆核',
  ready: '處理完成',
  failed: '處理失敗',
  retry_queued: '重新處理',
  asset_tombstoned: '已撤銷',
  completed: '處理完成',
}

export default function AssetDetailPage() {
  const { assetId = '' } = useParams()
  const [asset, setAsset] = useState<KnowledgeAsset | null>(null)
  const [events, setEvents] = useState<KnowledgeAssetEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const load = useCallback(async () => {
    try { const [detail, timeline] = await Promise.all([knowledgeAssetApi.get(assetId), knowledgeAssetApi.events(assetId)]); setAsset(detail); setEvents(timeline); setError(null) }
    catch (reason) { setError(parseApiError(reason, '無法載入知識資產')) }
    finally { setLoading(false) }
  }, [assetId])
  useEffect(() => { void load() }, [load])
  if (loading) return <AsyncState loading>{null}</AsyncState>
  if (error || !asset) return <AsyncState error={error || '找不到資產'} onRetry={load}>{null}</AsyncState>
  const retry = async () => { try { await knowledgeAssetApi.retry(asset.id); toast.success('已重新排入處理'); await load() } catch (reason) { toast.error(formatErrorWithTrace(parseApiError(reason, '無法重試'))) } }
  const documentId = typeof asset.metadata.document_id === 'string' ? asset.metadata.document_id : null
  const professionalTool = asset.asset_kind === 'video'
    ? { to: `/knowledge/videos/${asset.id}`, label: '開啟影片與證據時間軸' }
    : documentId
      ? { to: `/knowledge/documents/${documentId}`, label: '開啟文件與引用內容' }
      : null
  const failed = asset.job?.status === 'failed' || asset.status === 'failed'
  const failureCode = typeof asset.job?.error?.code === 'string' ? asset.job.error.code : null
  const failureMessage = failureCode === 'document_ingestion_failed'
    ? '內容處理服務目前不可用。原始來源已保留，可稍後重新處理；若持續失敗，請管理員檢查解析與索引服務。'
    : '系統已保留原始來源，請重新處理；若持續失敗，請聯絡管理員查看服務狀態。'
  return <WorkspacePage title={asset.title} subtitle={`${asset.asset_kind} · ${asset.source_system} · ${asset.data_classification}`} backTo="/knowledge/assets" backLabel="回所有資產" actions={<><LifecycleBadge status={asset.job?.status || asset.status} answerReady={asset.job?.status === 'ready'} />{(asset.job?.status === 'failed' || asset.status === 'failed') && <button className="btn-outline" onClick={() => void retry()}><RefreshCw className="h-4 w-4" />重新處理</button>}</>}>
    {failed && <div className="mt-5 flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger" role="alert"><AlertCircle className="mt-0.5 h-5 w-5 shrink-0" /><span><strong className="block">來源處理失敗</strong><span className="mt-1 block">{failureMessage}</span></span></div>}
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-5">
        <SectionPanel title="來源與專業工具" description="原始來源與衍生內容使用相同資產身分、權限及版本。">
          <div className="flex min-h-64 flex-col items-center justify-center rounded-xl bg-wash p-6 text-center text-muted">
            {professionalTool ? <Link className="btn-primary" to={professionalTool.to}>{professionalTool.label}</Link> : asset.asset_kind === 'web_page' && typeof asset.metadata.source_url === 'string' ? <a className="btn-outline" href={asset.metadata.source_url} target="_blank" rel="noreferrer">開啟原始網址</a> : <p>此來源已安全保存；完成處理後，可引用內容與證據會在這個資產工作區持續更新。</p>}
          </div>
        </SectionPanel>
        <SectionPanel title="處理能力" description="由系統依來源類型選擇，完成狀態仍以後端工作紀錄為準。">
          {asset.job?.requested_capabilities?.length ? <ul className="flex flex-wrap gap-2">{asset.job.requested_capabilities.map(capability => <li key={capability} className="chip-neutral">{capability.replaceAll('_', ' ')}</li>)}</ul> : <p className="text-sm text-muted">此來源沒有額外處理能力紀錄。</p>}
        </SectionPanel>
      </div>
      <aside className="space-y-5">
        <SectionPanel title="處理進度" bodyClassName="p-4">
          {events.length ? <ol className="space-y-4">{events.map(event => <li key={event.id} className="flex gap-3">{event.to_status === 'failed' ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> : ['completed', 'ready', 'review_required'].includes(event.to_status) ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-accent" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-line" />}<span><span className="block text-sm font-medium text-ink">{PHASE_LABELS[event.phase] || event.phase.replaceAll('_', ' ')}</span><span className="text-xs text-muted">{format(new Date(event.created_at), 'yyyy/MM/dd HH:mm')}</span></span></li>)}</ol> : <p className="text-sm text-muted">尚無處理事件。</p>}
        </SectionPanel>
        <SectionPanel title="來源資訊" bodyClassName="p-4"><MetadataList items={[{ label: '目前版本', value: `v${asset.current_revision}` }, { label: '來源系統', value: asset.source_system }, { label: '資料分類', value: asset.data_classification }, { label: '資產 ID', value: asset.id, mono: true }]} /></SectionPanel>
        <SectionPanel title="版本" bodyClassName="p-4"><div className="space-y-2">{(asset.revisions || []).map(revision => <div key={revision.id} className="flex items-center justify-between rounded-lg bg-wash px-3 py-2 text-sm"><span className="flex items-center gap-2"><RotateCcw className="h-3.5 w-3.5" />v{revision.revision}</span><span className="text-muted">{revision.ingestion_status}</span></div>)}</div></SectionPanel>
      </aside>
    </div>
  </WorkspacePage>
}
