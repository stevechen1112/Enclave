import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Circle, MessageCircleQuestion, RefreshCw, RotateCcw, UserCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { format } from 'date-fns'
import { knowledgeAssetApi, formatErrorWithTrace, parseApiError, type ApiErrorInfo } from '../../api'
import type { InputCapabilityResult, KnowledgeAsset, KnowledgeAssetEvent } from '../../types'
import AsyncState from '../../components/AsyncState'
import LifecycleBadge from '../../components/LifecycleBadge'
import { MetadataList, SectionPanel, WorkspacePage } from '../../components/WorkspacePage'
import { forgetKnowledgeTask } from '../../lib/longTaskRecovery'
import EvidenceLocatorBanner from '../../components/EvidenceLocatorBanner'

const PHASE_LABELS: Record<string, string> = {
  queued: '等待處理',
  fetch: '讀取來源',
  parsing: '解析內容',
  processing: '內容處理',
  audio_probe: '檢查音訊格式',
  audio_chunking: '建立安全處理分段',
  transcript_partial: '逐段產生逐字稿',
  proxy_ready: '預覽已可播放',
  probe_complete: '媒體格式檢查完成',
  audio_demuxed: '音訊軌分段完成',
  keyframes_extracted: '關鍵畫面擷取完成',
  visual_partial: '逐張辨識畫面文字',
  embedding: '建立搜尋索引',
  review_required: '等待人工覆核',
  ready: '處理完成',
  failed: '處理失敗',
  retry_queued: '重新處理',
  asset_tombstoned: '已撤銷',
  completed: '處理完成',
  completed_no_speech: '處理完成（未偵測到語音）',
}

const CAPABILITY_LABELS: Record<string, string> = {
  resumable_upload: '可續傳上傳',
  background_progress: '背景處理進度',
  partial_readiness: '分段處理結果',
  extract_text: '文字擷取',
  layout: '版面結構',
  table: '表格結構',
  browser_proxy: '瀏覽器預覽',
  probe_metadata: '媒體格式檢查',
  demux_audio: '音軌分離',
  transcribe: '語音轉文字',
  timestamp: '時間碼',
  terminology_correction: '企業詞彙校正',
  keyframe: '關鍵畫面',
  ocr: '畫面文字辨識',
  diarize: '說話者區分',
  scene_segment: '鏡頭切分',
  action_candidate: '動作事件候選',
  equipment_state: '設備狀態候選',
  audio_event: '異常聲音候選',
  temporal_align: '跨模態時間軸對齊',
  procedure_candidate: '程序候選',
}

const CAPABILITY_STATUS_LABELS = {
  available: '已完成',
  degraded: '有限可用',
  not_applicable: '本來源不適用',
  failed: '未完成',
} as const

function isInputCapabilityResult(value: unknown): value is InputCapabilityResult {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<InputCapabilityResult>
  return (
    typeof candidate.status === 'string'
    && Object.prototype.hasOwnProperty.call(CAPABILITY_STATUS_LABELS, candidate.status)
    && typeof candidate.artifact_count === 'number'
    && candidate.artifact_count >= 0
    && (candidate.reason_code === null || typeof candidate.reason_code === 'string')
  )
}

const CAPABILITY_REASON_LABELS: Record<string, string> = {
  no_speech_detected: '未偵測到可轉錄語音',
  no_audio_track: '來源沒有音軌',
  no_text_detected: '畫面未偵測到文字',
  browser_proxy_disabled: '此環境未啟用瀏覽器預覽檔',
  terminology_correction_not_implemented: '企業詞彙自動校正尚未啟用',
  speaker_labels_unavailable: '已有逐字稿，但無法可靠區分說話者',
  insufficient_signal: '訊號不足，無法可靠判斷',
  no_evidence_detected: '沒有足夠證據可產生結果',
  no_evidence_backed_procedure: '沒有足夠證據可建立程序候選',
  layout_fidelity_not_measured: '已抽出內容，但尚未量測版面還原品質',
  table_fidelity_not_measured: '已抽出表格內容，但尚未量測結構還原品質',
  capability_result_missing: '處理器沒有回報這項能力結果',
  provider_failed: '外部處理服務執行失敗',
}

function capabilityDescription(result: InputCapabilityResult) {
  const parts: string[] = []
  if (result.reason_code) parts.push(CAPABILITY_REASON_LABELS[result.reason_code] || result.reason_code.replaceAll('_', ' '))
  if (result.provider?.name) {
    const model = result.provider.model ? ` / ${result.provider.model}` : ''
    parts.push(`處理來源：${result.provider.name}${model}`)
  }
  if (result.provider?.confidence_provider_supplied === false) parts.push('信心度：供應商未提供（不是 0%）')
  if (result.artifact_count > 0) parts.push(`產出 ${result.artifact_count} 筆`)
  return parts.join('；')
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
  useEffect(() => {
    if (asset && ['ready', 'failed', 'completed'].includes(asset.job?.status || asset.status)) {
      forgetKnowledgeTask(asset.id)
    }
  }, [asset])
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
  const explicitFailureMessage = typeof asset.job?.error?.user_message === 'string' ? asset.job.error.user_message : null
  const retryable = asset.job?.error?.retryable !== false
  const failureMessage = explicitFailureMessage || (failureCode === 'document_ingestion_failed'
    ? '內容處理服務目前不可用。原始來源已保留，可稍後重新處理；若持續失敗，請管理員檢查解析與索引服務。'
    : '系統已保留原始來源，請重新處理；若持續失敗，請聯絡管理員查看服務狀態。')
  const lifecycle = asset.lifecycle_status || asset.job?.status || asset.status
  const capabilityResults = asset.job?.readiness.capability_results
  const mediaArtifacts = asset.media_analysis?.artifacts || []
  const audioCorrections = mediaArtifacts.filter(item => item.kind === 'transcript_correction')
  const audioProfile = mediaArtifacts.find(item => item.kind === 'audio_quality_profile')
  return <WorkspacePage title={asset.title} subtitle={`${asset.asset_kind} · ${asset.source_system} · ${asset.data_classification}`} backTo="/knowledge/assets" backLabel="回所有資產" actions={<><LifecycleBadge status={lifecycle} answerReady={asset.answer_ready} />{failed && retryable && <button className="btn-outline" onClick={() => void retry()}><RefreshCw className="h-4 w-4" />重新處理</button>}</>}>
    <EvidenceLocatorBanner />
    {failed && <div className="mt-5 flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger" role="alert"><AlertCircle className="mt-0.5 h-5 w-5 shrink-0" /><span><strong className="block">需要處理</strong><span className="mt-1 block">{failureMessage}</span><span className="mt-2 block text-xs">{retryable ? '系統自動嘗試已結束；可按「重新處理」再試一次。' : '這類問題不會自動重試，請依上方說明更換來源或格式。'}{asset.job?.correlation_id ? ` 追蹤碼：${asset.job.correlation_id}` : ''}</span></span></div>}
    {asset.lifecycle_status === 'processing' && <div className="mt-5 flex items-start gap-3 rounded-2xl border border-accent/20 bg-accent-soft p-4 text-sm text-accent-ink"><RefreshCw className="mt-0.5 h-5 w-5 shrink-0 animate-spin" /><span><strong className="block">系統正在處理</strong><span className="mt-1 block">你可以離開此頁；系統會在背景繼續解析、OCR、轉錄或建立索引。</span></span></div>}
    {asset.lifecycle_status === 'awaiting_review' && <div className="mt-5 flex flex-wrap items-center gap-3 rounded-2xl border border-highlight/30 bg-highlight-soft p-4 text-sm text-highlight"><UserCheck className="h-5 w-5 shrink-0" /><span className="min-w-0 flex-1"><strong className="block">等待你確認內容</strong><span className="mt-1 block">系統處理已完成，共 {asset.pending_review_count || 0} 筆需要人員判斷的內容；原始文字可按來源一次確認，高風險推論仍須由另一位擁有者核准。</span></span><Link className="btn-outline shrink-0" to="/knowledge/review">前往人工確認</Link></div>}
    {asset.answer_ready && <div className="mt-5 flex flex-wrap items-center gap-3 rounded-2xl border border-success/30 bg-success-soft p-4 text-sm text-success"><CheckCircle2 className="h-5 w-5 shrink-0" /><span className="min-w-0 flex-1"><strong className="block">此來源已可問答</strong><span className="mt-1 block">問答結果會附上可追溯的來源證據。</span></span><Link className="btn-primary shrink-0" to="/ask"><MessageCircleQuestion className="h-4 w-4" />前往問知識</Link></div>}
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-5">
        <SectionPanel title="來源與專業工具" description="原始來源與衍生內容使用相同資產身分、權限及版本。">
          <div className="flex min-h-64 flex-col items-center justify-center rounded-xl bg-wash p-6 text-center text-muted">
            {asset.asset_kind === 'audio' && asset.preview_url ? <div className="w-full max-w-2xl"><p className="mb-3 text-sm text-ink">可先播放瀏覽器相容預覽；逐字稿會分段出現在覆核佇列。</p><audio controls preload="metadata" src={asset.preview_url} className="w-full" aria-label={`${asset.title} 音訊預覽`} /></div> : professionalTool ? <Link className="btn-primary" to={professionalTool.to}>{professionalTool.label}</Link> : asset.asset_kind === 'web_page' && typeof asset.metadata.source_url === 'string' ? <a className="btn-outline" href={asset.metadata.source_url} target="_blank" rel="noreferrer">開啟原始網址</a> : <p>此來源已安全保存；完成處理後，可引用內容與證據會在這個資產工作區持續更新。</p>}
          </div>
        </SectionPanel>
        <SectionPanel title="處理能力" description="每一項都顯示實際結果；未偵測到內容、有限可用與執行失敗會分開呈現。">
          {asset.job?.requested_capabilities?.length ? <ul className="space-y-2">{asset.job.requested_capabilities.map(capability => {
            const rawResult = capabilityResults?.[capability]
            const result = isInputCapabilityResult(rawResult) ? rawResult : undefined
            const description = result ? capabilityDescription(result) : ''
            return <li key={capability} className="rounded-xl border border-line bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium text-ink">{CAPABILITY_LABELS[capability] || capability.replaceAll('_', ' ')}</span>{result ? <span className={result.status === 'available' ? 'text-sm text-success' : result.status === 'failed' ? 'text-sm text-danger' : 'text-sm text-highlight'}>{CAPABILITY_STATUS_LABELS[result.status]}</span> : <span className="text-sm text-muted">{rawResult == null ? '尚未回報' : '狀態資料無法辨識'}</span>}</div>
              {description && <p className="mt-1 text-xs text-muted">{description}</p>}
            </li>
          })}</ul> : <p className="text-sm text-muted">此來源沒有額外處理能力紀錄。</p>}
        </SectionPanel>
        {asset.asset_kind === 'audio' && (audioProfile || audioCorrections.length > 0) && <SectionPanel title="音訊品質與校正候選" description="原始辨識與上下文精度候選分開保留；差異需要人員確認，不會靜默改寫。">
          {audioProfile && <div className="mb-3 rounded-xl bg-wash p-4 text-sm"><strong className="block text-ink">音訊品質剖析</strong><pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted">{JSON.stringify(audioProfile.content, null, 2)}</pre></div>}
          {audioCorrections.length === 0 ? <p className="text-sm text-muted">目前沒有上下文校正差異。</p> : <div className="space-y-3">{audioCorrections.map(item => {
            const content = typeof item.content === 'object' && item.content ? item.content : {}
            return <div key={item.id} className="rounded-xl border border-line p-4 text-sm"><div className="text-xs text-muted">{Math.floor(Number(item.metadata.start_ms || 0) / 1000)} 秒起 · 等待人工確認</div><div className="mt-2 text-muted line-through">{String(content.raw || '')}</div><div className="mt-1 text-ink">{String(content.candidate || '')}</div></div>
          })}</div>}
        </SectionPanel>}
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
