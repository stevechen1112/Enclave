import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Clock3, Image, Loader2, ShieldCheck, XCircle } from 'lucide-react'
import toast from 'react-hot-toast'

import { formatErrorWithTrace, parseApiError, videoApi } from '../../api'
import AsyncState from '../../components/AsyncState'
import { useAuth } from '../../auth'
import type { VideoArtifact, VideoAssetDetail } from '../../types'

function clock(ms: number | null | undefined) {
  const seconds = Math.floor((ms || 0) / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function firstTimestamp(artifact: VideoArtifact) {
  return artifact.evidence[0]?.start_ms ?? Number(artifact.metadata.start_ms ?? artifact.metadata.timestamp_ms ?? 0)
}

export default function VideoReviewPage() {
  const { assetId = '' } = useParams<{ assetId: string }>()
  const [params] = useSearchParams()
  const { user } = useAuth()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [detail, setDetail] = useState<VideoAssetDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [reviewing, setReviewing] = useState(false)
  const [notes, setNotes] = useState('')
  const [acknowledgeHighRisk, setAcknowledgeHighRisk] = useState(false)
  const [resolvedConflicts, setResolvedConflicts] = useState<Set<string>>(new Set())
  const [error, setError] = useState<ReturnType<typeof parseApiError> | null>(null)

  const load = useCallback(async () => {
    try {
      setDetail(await videoApi.get(assetId))
      setError(null)
    } catch (reason) {
      setError(parseApiError(reason, '無法載入影片覆核資料'))
    } finally {
      setLoading(false)
    }
  }, [assetId])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!detail || !['pending', 'running', 'retry'].includes(detail.job?.status || '')) return
    const timer = window.setInterval(() => { void load() }, 4000)
    return () => window.clearInterval(timer)
  }, [detail, load])
  useEffect(() => {
    const timestamp = Number(params.get('t') || 0)
    if (videoRef.current && timestamp >= 0) videoRef.current.currentTime = timestamp / 1000
  }, [detail, params])

  const artifacts = useMemo(() => detail?.artifacts || [], [detail?.artifacts])
  const transcripts = useMemo(() => artifacts.filter(item => item.kind === 'transcript_segment'), [artifacts])
  const keyframes = useMemo(() => artifacts.filter(item => item.kind === 'keyframe'), [artifacts])
  const ocr = useMemo(() => artifacts.filter(item => item.kind === 'ocr_region'), [artifacts])
  const observations = useMemo(() => artifacts.filter(item => ['speaker_turn', 'video_scene', 'action_event', 'equipment_state', 'audio_event'].includes(item.kind)), [artifacts])
  const alignment = [...artifacts].reverse().find(item => item.kind === 'timeline_alignment')
  const procedure = [...artifacts].reverse().find(item => item.kind === 'procedure_candidate')
  const conflictReport = [...artifacts].reverse().find(item =>
    item.kind === 'sop_conflict_report' && String(item.metadata.procedure_artifact_id || '') === procedure?.id,
  )
  const canReview = Boolean(user?.is_superuser || ['owner', 'admin'].includes(user?.role || ''))

  const seek = (ms: number) => {
    if (!videoRef.current) return
    videoRef.current.currentTime = Math.max(0, ms / 1000)
    void videoRef.current.play()
  }

  const review = async (decision: 'approved' | 'rejected') => {
    if (!procedure || reviewing) return
    setReviewing(true)
    try {
      await videoApi.review(procedure.id, decision, notes || undefined, {
        conflictResolutions: Object.fromEntries([...resolvedConflicts].map(id => [id, 'sop_wins'])),
        acknowledgeHighRisk,
      })
      toast.success(decision === 'approved' ? '已核准，此作業程序現在可供問答檢索' : '已駁回，不會進入問答')
      await load()
    } catch (reason) {
      toast.error(formatErrorWithTrace(parseApiError(reason, '覆核失敗')))
    } finally {
      setReviewing(false)
    }
  }

  if (loading) return <AsyncState loading>{null}</AsyncState>
  if (error || !detail) return <AsyncState error={error || parseApiError(null, '找不到影片')} onRetry={load}>{null}</AsyncState>

  const procedureContent = typeof procedure?.content === 'object' && procedure.content ? procedure.content : {}
  const steps = Array.isArray(procedureContent.steps) ? procedureContent.steps as Array<Record<string, unknown>> : []
  const conflicts = typeof conflictReport?.content === 'object' && conflictReport.content && Array.isArray(conflictReport.content.conflicts)
    ? conflictReport.content.conflicts as Array<Record<string, unknown>>
    : []
  const structuredSections = [
    ['前置條件', procedureContent.preconditions],
    ['判斷規則', procedureContent.decision_rules],
    ['風險', procedureContent.risks],
    ['例外', procedureContent.exceptions],
    ['禁止動作', procedureContent.prohibited_actions],
  ].filter((entry): entry is [string, Array<Record<string, unknown>>] => Array.isArray(entry[1]) && entry[1].length > 0)
  const highRisk = structuredSections.some(([label]) => label === '風險' || label === '禁止動作')
  const approvalReady = conflicts.every(conflict => resolvedConflicts.has(String(conflict.id))) && (!highRisk || acknowledgeHighRisk)

  return (
    <div className="h-full overflow-y-auto px-5 py-5 lg:px-8">
      <Link to={`/knowledge/assets/${assetId}`} className="mb-4 inline-flex min-h-11 items-center gap-2 rounded-lg pr-3 text-sm font-medium text-accent hover:bg-accent-soft/50"><ArrowLeft size={16} />回資產詳情</Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="font-display text-2xl font-semibold">{detail.title}</h1><p className="mt-1 text-sm text-muted">每筆內容都保留精確時間點；作業程序未核准前不會發布。</p></div>
        <span className="rounded-full bg-highlight-soft px-3 py-1 text-sm text-highlight">{detail.job?.phase || detail.job?.status || detail.status}</span>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
        <section className="space-y-5">
          <div className="overflow-hidden rounded-xl border border-line bg-black shadow-card">
            <video ref={videoRef} controls preload="metadata" src={detail.content_url} className="aspect-video w-full" aria-label={detail.title} />
          </div>

          <div className="card p-5">
            <h2 className="mb-3 flex items-center gap-2 font-semibold"><Clock3 size={18} />語音逐字時間軸</h2>
            {transcripts.length === 0 ? <p className="text-sm text-muted">尚無可用逐字稿。</p> : (
              <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                {transcripts.map(item => (
                  <button key={item.id} type="button" onClick={() => seek(firstTimestamp(item))} className="flex w-full gap-3 rounded-lg border border-line p-3 text-left hover:border-accent hover:bg-accent-soft/40">
                    <span className="font-mono text-xs text-accent">{clock(firstTimestamp(item))}</span>
                    <span className="text-sm">{String(item.content || '')}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="card p-5">
            <h2 className="mb-3 flex items-center gap-2 font-semibold"><Image size={18} />關鍵畫面與 OCR</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {keyframes.map(frame => (
                <button key={frame.id} type="button" onClick={() => seek(firstTimestamp(frame))} className="overflow-hidden rounded-lg border border-line text-left hover:border-accent">
                  {frame.content_url && <img src={frame.content_url} alt={`關鍵畫面 ${clock(firstTimestamp(frame))}`} className="aspect-video w-full bg-wash object-cover" />}
                  <span className="block px-3 py-2 font-mono text-xs text-accent">{clock(firstTimestamp(frame))}</span>
                </button>
              ))}
            </div>
            {ocr.length > 0 && <div className="mt-4 space-y-2">{ocr.map(item => <button key={item.id} type="button" onClick={() => seek(firstTimestamp(item))} className="block w-full rounded-lg bg-wash px-3 py-2 text-left text-sm"><span className="mr-2 font-mono text-xs text-accent">{clock(firstTimestamp(item))}</span>{String(item.content || '')}</button>)}</div>}
          </div>

          <div className="card p-5">
            <h2 className="mb-3 font-semibold">多模態時間軸候選</h2>
            {alignment && typeof alignment.content === 'object' && alignment.content && (
              <div className="mb-4 flex flex-wrap gap-2">
                {Object.entries((alignment.content.capability_states as Record<string, string>) || {}).map(([key, state]) => (
                  <span key={key} className={`rounded-full px-2.5 py-1 text-xs ${state === 'unavailable' || state === 'failed' ? 'bg-wash text-muted' : 'bg-accent-soft text-accent-ink'}`}>
                    {key}: {state}
                  </span>
                ))}
              </div>
            )}
            {observations.length === 0 ? <p className="text-sm text-muted">未產生動作、設備狀態或說話者候選；未啟用的專業辨識會明確標示 unavailable。</p> : (
              <div className="space-y-2">
                {observations.map(item => (
                  <button key={item.id} type="button" onClick={() => seek(firstTimestamp(item))} className="flex w-full items-start gap-3 rounded-lg border border-line p-3 text-left hover:border-accent">
                    <span className="rounded bg-wash px-2 py-1 font-mono text-xs text-muted">{item.kind}</span>
                    <span className="flex-1 text-sm">{String(item.content || item.metadata.label || '')}</span>
                    <span className="font-mono text-xs text-accent">{clock(firstTimestamp(item))}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>

        <aside className="card h-fit p-5 xl:sticky xl:top-4">
          <h2 className="flex items-center gap-2 font-semibold"><ShieldCheck size={19} />作業程序人員覆核</h2>
          {!procedure ? <p className="mt-3 text-sm text-muted">處理完成後，有證據的作業步驟將顯示於此。</p> : (
            <>
              <div className="mt-4 max-h-[55vh] space-y-2 overflow-y-auto pr-1">
                {steps.map((step, index) => (
                  <button key={`${String(step.evidence_artifact_id)}-${index}`} type="button" onClick={() => seek(Number(step.start_ms || 0))} className="flex w-full gap-3 rounded-lg border border-line p-3 text-left hover:border-accent">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">{String(step.sequence || index + 1)}</span>
                    <span><span className="block text-sm">{String(step.text || '')}</span><span className="mt-1 block font-mono text-xs text-muted">{clock(Number(step.start_ms || 0))}</span></span>
                  </button>
                ))}
                {structuredSections.map(([label, items]) => (
                  <div key={label} className="rounded-lg bg-wash p-3">
                    <div className="mb-1 text-xs font-semibold text-muted">{label}</div>
                    {items.map((item, index) => <button key={`${label}-${index}`} type="button" onClick={() => seek(Number(item.start_ms || 0))} className="block w-full py-1 text-left text-sm hover:text-accent">{String(item.text || '')} <span className="font-mono text-xs text-muted">{clock(Number(item.start_ms || 0))}</span></button>)}
                  </div>
                ))}
              </div>
              {procedure.review ? (
                <div className={`mt-4 rounded-lg p-3 text-sm ${procedure.review.decision === 'approved' ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger'}`}>
                  {procedure.review.decision === 'approved' ? '已核准並發布至知識檢索' : '已駁回，未發布至知識檢索'}
                </div>
              ) : canReview ? (
                <div className="mt-4 border-t border-line pt-4">
                  {conflicts.length > 0 && (
                    <div className="mb-4 rounded-lg border border-highlight/30 bg-highlight-soft p-3">
                      <div className="mb-2 text-sm font-semibold text-highlight">正式 SOP 衝突（必須逐項以 SOP 為準）</div>
                      <div className="space-y-2">
                        {conflicts.map(conflict => {
                          const id = String(conflict.id || '')
                          const evidence = conflict.sop_evidence as Record<string, unknown> | undefined
                          return <label key={id} className="flex cursor-pointer items-start gap-2 text-sm"><input type="checkbox" checked={resolvedConflicts.has(id)} onChange={event => setResolvedConflicts(current => { const next = new Set(current); if (event.target.checked) next.add(id); else next.delete(id); return next })} className="mt-1" /><span><strong>SOP：</strong>{String(conflict.sop_value || '')}{Boolean(evidence?.document_id) && <Link to={`/knowledge/documents/${String(evidence?.document_id)}`} className="ml-2 text-accent underline">查看正式來源 v{String(evidence?.document_revision || '')}</Link>}<br /><span className="text-muted">影片候選：{String(conflict.knowhow_value || '')}</span></span></label>
                        })}
                      </div>
                    </div>
                  )}
                  {highRisk && <label className="mb-4 flex cursor-pointer items-start gap-2 rounded-lg bg-danger-soft p-3 text-sm text-danger"><input type="checkbox" checked={acknowledgeHighRisk} onChange={event => setAcknowledgeHighRisk(event.target.checked)} className="mt-1" /><span>我已核對風險與禁止動作，並確認正式 SOP 與主管要求。</span></label>}
                  <label className="mb-1 block text-sm font-medium" htmlFor="review-notes">覆核備註（選填）</label>
                  <textarea id="review-notes" value={notes} onChange={event => setNotes(event.target.value)} maxLength={2000} rows={3} className="input w-full" placeholder="記錄修正建議或核准依據" />
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <button type="button" disabled={reviewing} onClick={() => void review('rejected')} className="btn-outline justify-center text-danger"><XCircle size={16} />駁回</button>
                    <button type="button" disabled={reviewing || !approvalReady} onClick={() => void review('approved')} className="btn-primary justify-center">{reviewing ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}核准發布</button>
                  </div>
                </div>
              ) : <p className="mt-4 rounded-lg bg-wash p-3 text-sm text-muted">僅租戶管理者或指定覆核角色可發布。</p>}
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
