/** Unified Evidence Workspace: queue / evidence / governed decision. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft, ArrowRight, CheckCircle, Clock3, ExternalLink,
  FileSearch, Loader2, RefreshCw, ShieldAlert, XCircle,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

import { formatErrorWithTrace, knowledgeReviewApi, parseApiError, type ApiErrorInfo } from '../api'
import AsyncState from '../components/AsyncState'
import ConfirmDialog from '../components/ConfirmDialog'
import type { KnowledgeReviewInbox, KnowledgeReviewItem, ReviewEvidenceLocator } from '../types'
import { normalizeEvidenceDeepLink } from '../lib/evidenceLinks'

type MobileStep = 'list' | 'evidence' | 'decision'

const decisionId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`

const sourceLabels: Record<string, string> = {
  document_classification: '文件分類', extracted_text: '文件文字', ocr_region: 'OCR',
  table: '表格', transcript_segment: '逐字稿', procedure_candidate: '影片程序',
  sop_conflict_report: 'SOP 衝突', knowhow_card: '經驗知識卡', audio_event: '異常聲音',
}

const blockedLabels: Record<string, string> = {
  acl_policy_missing: '缺少權限政策', acl_policy_invalid: '權限政策無效',
  review_policy_expired: '審核政策已過期', approval_policy_missing: '簽核政策不存在',
  approval_policy_expired: '簽核政策已過期', separation_of_duty: '建立者不可自行核准',
  unresolved_sop_conflicts: '仍有 SOP 衝突', reviewer_role_not_allowed: '目前角色不在簽核步驟中',
  evidence_missing: '缺少可追溯來源證據',
}

function clock(ms?: number | null) {
  const seconds = Math.floor((ms || 0) / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function evidenceLabel(evidence: ReviewEvidenceLocator) {
  if (evidence.kind === 'audio' || evidence.kind === 'video') {
    return `${evidence.kind === 'video' ? '影片' : '音訊'} ${clock(evidence.start_ms)}${evidence.end_ms ? `–${clock(evidence.end_ms)}` : ''}${evidence.speaker ? ` · ${evidence.speaker}` : ''}`
  }
  if (evidence.kind === 'table') return `${evidence.worksheet || evidence.table_name || '表格'} · ${evidence.cell_range || `第 ${evidence.row_number || '?'} 列`}`
  if (evidence.kind === 'external_record') return `${evidence.source_system || '外部系統'} · ${evidence.source_record_id || ''}${evidence.field_path ? ` · ${evidence.field_path}` : ''}`
  if (evidence.kind === 'image') return `影像${evidence.bbox ? ' · 標記區域' : ''}${evidence.frame_index != null ? ` · frame ${evidence.frame_index}` : ''}`
  return `文件${evidence.page ? ` · 第 ${evidence.page} 頁` : ''}${evidence.section ? ` · ${evidence.section}` : ''}`
}

function JsonPreview({ value }: { value: unknown }) {
  if (value == null || value === '') return <p className="text-sm text-muted">沒有內容預覽。</p>
  if (typeof value === 'string') return <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{value}</p>
  if (Array.isArray(value)) return <ol className="space-y-2 text-sm">{value.map((entry, index) => <li key={index} className="rounded-lg bg-wash px-3 py-2">{typeof entry === 'string' ? entry : JSON.stringify(entry, null, 2)}</li>)}</ol>
  return <dl className="space-y-3">{Object.entries(value as Record<string, unknown>).filter(([, entry]) => entry != null && entry !== '' && (!Array.isArray(entry) || entry.length)).map(([key, entry]) => <div key={key}><dt className="text-xs font-semibold uppercase tracking-wide text-muted">{key.replaceAll('_', ' ')}</dt><dd className="mt-1 whitespace-pre-wrap text-sm text-ink">{typeof entry === 'string' ? entry : JSON.stringify(entry, null, 2)}</dd></div>)}</dl>
}

export default function ReviewQueuePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [inbox, setInbox] = useState<KnowledgeReviewInbox | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('item'))
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [risk, setRisk] = useState('')
  const [source, setSource] = useState('')
  const [policy, setPolicy] = useState('')
  const [assignee, setAssignee] = useState('')
  const [department, setDepartment] = useState('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [lowConfidenceOnly, setLowConfidenceOnly] = useState(false)
  const [notes, setNotes] = useState('')
  const [ackHigh, setAckHigh] = useState(false)
  const [ackLow, setAckLow] = useState(false)
  const [resolvedConflicts, setResolvedConflicts] = useState<Set<string>>(new Set())
  const [decisionKey, setDecisionKey] = useState(decisionId)
  const [acting, setActing] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [mobileStep, setMobileStep] = useState<MobileStep>('list')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await knowledgeReviewApi.list({
        risk_level: risk || undefined,
        source_type: source || undefined,
        policy_key: policy || undefined,
        assignee: assignee || undefined,
        department_id: department || undefined,
        overdue: overdueOnly || undefined,
        confidence_max: lowConfidenceOnly ? 0.7999 : undefined,
      })
      setInbox(data)
      setSelectedIds(new Set())
      setSelectedId(current => current && data.items.some(item => item.id === current) ? current : data.items[0]?.id || null)
    } catch (reason) {
      setError(parseApiError(reason, '無法載入審核工作台'))
    } finally {
      setLoading(false)
    }
  }, [assignee, department, lowConfidenceOnly, overdueOnly, policy, risk, source])

  useEffect(() => { void load() }, [load])
  const items = useMemo(() => inbox?.items || [], [inbox])
  const selected = useMemo(() => items.find(item => item.id === selectedId) || null, [items, selectedId])
  const evidenceLinks = useMemo(() => selected?.evidence.map(evidence => ({
    evidence,
    deepLink: normalizeEvidenceDeepLink(evidence.deep_link),
  })) || [], [selected])
  const evidenceLinksValid = evidenceLinks.length > 0 && evidenceLinks.every(item => item.deepLink)
  const conflicts = useMemo(() => {
    const value = selected?.proposal.conflicts
    return Array.isArray(value) ? value.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === 'object') : []
  }, [selected])
  const unresolvedIds = conflicts.filter(row => !row.resolved).map((row, index) => String(row.id || index))
  const hardBlocks = (selected?.blocked_reasons || []).filter(reason => reason !== 'unresolved_sop_conflicts')
  const approvalReady = Boolean(selected && hardBlocks.length === 0 && unresolvedIds.every(id => resolvedConflicts.has(id)) && (selected.risk_level !== 'high' || ackHigh) && (selected.confidence == null || selected.confidence >= 0.8 || ackLow))

  useEffect(() => {
    setNotes(''); setAckHigh(false); setAckLow(false); setResolvedConflicts(new Set())
    setDecisionKey(decisionId())
  }, [selectedId])

  const choose = (item: KnowledgeReviewItem) => {
    setSelectedId(item.id)
    setSearchParams({ item: item.id }, { replace: true })
    setMobileStep('evidence')
  }
  const toggleBatch = (item: KnowledgeReviewItem) => {
    if (!item.batch_eligible) return
    setSelectedIds(current => { const next = new Set(current); if (next.has(item.id)) next.delete(item.id); else next.add(item.id); return next })
  }
  const decide = async (decision: 'approved' | 'rejected') => {
    if (!selected) return
    setActing(true)
    try {
      await knowledgeReviewApi.decide(selected.id, {
        decision, notes: notes || undefined, acknowledgeHighRisk: ackHigh,
        acknowledgeLowConfidence: ackLow,
        conflictResolutions: Object.fromEntries([...resolvedConflicts].map(id => [id, 'sop_wins'])),
        idempotencyKey: decisionKey,
      })
      toast.success(decision === 'approved' ? '已核准並依發布契約處理' : '已駁回並保留稽核紀錄')
      setDecisionKey(decisionId()); setRejectOpen(false); setMobileStep('list'); await load()
    } catch (reason) { toast.error(formatErrorWithTrace(parseApiError(reason, '審核失敗'))) }
    finally { setActing(false) }
  }
  const batchApprove = async () => {
    setActing(true)
    try {
      await knowledgeReviewApi.batchApprove([...selectedIds], notes || undefined)
      toast.success(`已核准 ${selectedIds.size} 筆低風險同類項目`)
      setBatchOpen(false); await load()
    } catch (reason) { toast.error(formatErrorWithTrace(parseApiError(reason, '批量核准失敗'))) }
    finally { setActing(false) }
  }

  return <AsyncState loading={loading} error={error} onRetry={load} empty={false} className="h-full">
    <div className="flex h-full flex-col md:flex-row">
      <aside className={clsx('w-full flex-col border-b border-line bg-surface md:flex md:w-[22rem] md:border-b-0 md:border-r', mobileStep === 'list' ? 'flex flex-1' : 'hidden')} aria-label="審核佇列">
        <div className="border-b border-line p-4">
          <div className="flex items-center justify-between"><div><h1 className="font-display text-lg font-semibold text-ink">證據審核</h1><p className="text-sm text-muted">{inbox?.total || 0} 筆待處置</p></div><button type="button" className="icon-btn" onClick={() => void load()} aria-label="重新整理"><RefreshCw className="h-5 w-5" /></button></div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <select aria-label="風險" className="input min-h-10 py-1" value={risk} onChange={event => setRisk(event.target.value)}><option value="">所有風險</option><option value="high">高風險</option><option value="medium">中風險</option><option value="low">低風險</option></select>
            <select aria-label="來源類型" className="input min-h-10 py-1" value={source} onChange={event => setSource(event.target.value)}><option value="">所有來源</option>{inbox?.facets.source_types.map(value => <option key={value} value={value}>{sourceLabels[value] || value}</option>)}</select>
            <select aria-label="審核政策" className="input min-h-10 py-1" value={policy} onChange={event => setPolicy(event.target.value)}><option value="">所有政策</option>{inbox?.facets.policy_keys.map(value => <option key={value} value={value}>{value}</option>)}</select>
            <select aria-label="指派對象" className="input min-h-10 py-1" value={assignee} onChange={event => setAssignee(event.target.value)}><option value="">所有指派</option>{inbox?.facets.assignees.map(value => <option key={value} value={value}>{value}</option>)}</select>
          </div>
          <input aria-label="部門 ID" className="input mt-2 min-h-10 py-1" value={department} onChange={event => setDepartment(event.target.value)} placeholder="依部門 ID 篩選" />
          <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted"><label className="flex items-center gap-1"><input type="checkbox" checked={overdueOnly} onChange={event => setOverdueOnly(event.target.checked)} />已逾期</label><label className="flex items-center gap-1"><input type="checkbox" checked={lowConfidenceOnly} onChange={event => setLowConfidenceOnly(event.target.checked)} />低信心</label></div>
          {selectedIds.size > 0 && <button type="button" className="btn-primary mt-3 w-full" onClick={() => setBatchOpen(true)}>批量核准（{selectedIds.size}）</button>}
        </div>
        {items.length === 0 ? <div className="flex flex-1 flex-col items-center justify-center p-6 text-center"><CheckCircle className="h-10 w-10 text-success" /><p className="mt-3 font-medium">目前沒有待審項目</p><Link className="btn-primary mt-4" to="/knowledge/new">新增知識來源</Link></div> : <ul className="flex-1 overflow-y-auto">{items.map(item => <li key={item.id} className={clsx('flex border-b border-line', item.id === selectedId && 'bg-accent-soft/50')}><span className="flex items-start px-3 py-3"><input type="checkbox" checked={selectedIds.has(item.id)} disabled={!item.batch_eligible} onChange={() => toggleBatch(item)} aria-label={`選取 ${item.title}`} title={item.batch_eligible ? '加入批量核准' : '僅低風險、同策略項目可批量'} className="mt-1 h-5 w-5" /></span><button type="button" onClick={() => choose(item)} className="min-h-11 min-w-0 flex-1 py-3 pr-3 text-left hover:bg-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"><span className="block truncate text-sm font-medium text-ink">{item.title}</span><span className="block truncate text-xs text-muted">{sourceLabels[item.source_type] || item.source_type}{item.confidence != null ? ` · ${Math.round(item.confidence * 100)}%` : ''}</span><span className="mt-1 flex flex-wrap gap-1"><span className={clsx('rounded-full px-2 py-0.5 text-xs', item.risk_level === 'high' ? 'bg-danger-soft text-danger' : item.risk_level === 'medium' ? 'bg-highlight-soft text-highlight' : 'bg-success-soft text-success')}>{item.risk_level === 'high' ? '高風險' : item.risk_level === 'medium' ? '中風險' : '低風險'}</span>{item.blocked_reasons.map(reason => <span key={reason} className="rounded-full bg-danger-soft px-2 py-0.5 text-xs text-danger">{blockedLabels[reason] || reason}</span>)}</span></button></li>)}</ul>}
      </aside>

      <section className={clsx('min-h-0 flex-1 flex-col overflow-y-auto border-b border-line p-5 md:flex md:border-b-0 md:border-r lg:p-7', mobileStep === 'evidence' ? 'flex' : 'hidden')} aria-label="證據與建議">
        {!selected ? <div className="m-auto text-center text-muted"><FileSearch className="mx-auto h-10 w-10" /><p className="mt-3">請選擇待審項目</p></div> : <div className="mx-auto w-full max-w-3xl space-y-5">
          <button type="button" className="btn-ghost -ml-3 md:hidden" onClick={() => setMobileStep('list')}><ArrowLeft className="h-4 w-4" />返回佇列</button>
          <header><div className="flex flex-wrap items-center gap-2 text-xs text-muted"><span>{sourceLabels[selected.source_type] || selected.source_type}</span><span>·</span><span>{selected.provider}</span><span>·</span><span>{selected.policy_key} v{selected.policy_version}</span></div><h2 className="mt-2 font-display text-2xl font-semibold text-ink">{selected.title}</h2><p className="mt-1 text-sm text-muted">{selected.subtitle}</p></header>
          <section className="card p-5"><h3 className="font-semibold text-ink">AI 建議與候選內容</h3><div className="mt-4"><JsonPreview value={selected.proposal} /></div></section>
          <section className="card p-5"><h3 className="flex items-center gap-2 font-semibold text-ink"><FileSearch className="h-5 w-5" />來源證據</h3>{!evidenceLinksValid ? <p className="mt-3 rounded-lg bg-danger-soft p-3 text-sm text-danger">此項目缺少有效的站內證據定位器，不應核准。</p> : <ul className="mt-3 space-y-2">{evidenceLinks.map(({ evidence, deepLink }) => <li key={evidence.id}><Link to={deepLink!} className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-line px-3 py-2 text-sm hover:border-accent hover:bg-accent-soft/30"><span><span className="block font-medium text-ink">{evidenceLabel(evidence)}</span>{evidence.section && evidence.kind !== 'document' && <span className="line-clamp-2 text-xs text-muted">{evidence.section}</span>}</span><ExternalLink className="h-4 w-4 shrink-0 text-accent" /></Link></li>)}</ul>}</section>
          {conflicts.length > 0 && <section className="rounded-2xl border border-highlight/40 bg-highlight-soft p-5"><h3 className="flex items-center gap-2 font-semibold text-highlight"><ShieldAlert className="h-5 w-5" />正式 SOP 衝突</h3><p className="mt-1 text-sm text-highlight">逐項確認正式 SOP 優先，才可發布。</p><div className="mt-3 space-y-2">{conflicts.map((conflict, index) => { const id = String(conflict.id || index); return <label key={id} className="flex min-h-11 cursor-pointer items-start gap-2 rounded-lg bg-surface p-3 text-sm"><input type="checkbox" className="mt-1" checked={resolvedConflicts.has(id)} onChange={event => setResolvedConflicts(current => { const next = new Set(current); if (event.target.checked) next.add(id); else next.delete(id); return next })} /><span><strong>SOP：</strong>{String(conflict.sop_value || conflict.message || '')}<br /><span className="text-muted">候選：{String(conflict.knowhow_value || '')}</span></span></label> })}</div></section>}
          <button type="button" className="btn-primary w-full md:hidden" onClick={() => setMobileStep('decision')}>下一步：發布決策 <ArrowRight className="h-4 w-4" /></button>
        </div>}
      </section>

      <aside className={clsx('w-full flex-col bg-surface md:flex md:w-[22rem]', mobileStep === 'decision' ? 'flex flex-1' : 'hidden')} aria-label="發布決策">
        <div className="border-b border-line p-4"><h2 className="font-semibold text-ink">決策與發布契約</h2><p className="text-sm text-muted">核准前確認權限、版本與回滾方式</p></div>
        {!selected ? <p className="p-4 text-sm text-muted">尚未選擇項目</p> : <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <button type="button" className="btn-ghost -ml-3 self-start md:hidden" onClick={() => setMobileStep('evidence')}><ArrowLeft className="h-4 w-4" />返回證據</button>
          <dl className="rounded-xl bg-wash p-3 text-sm"><div className="flex justify-between gap-3"><dt className="text-muted">知識單元</dt><dd className="break-all text-right font-mono text-xs">{selected.publication.unit_key || '處理完成後建立'}</dd></div><div className="mt-2 flex justify-between"><dt className="text-muted">版本</dt><dd>v{selected.publication.next_revision}</dd></div><div className="mt-2 flex justify-between"><dt className="text-muted">生效</dt><dd>{selected.publication.effective_from}</dd></div><div className="mt-2"><dt className="text-muted">ACL</dt><dd className="mt-1 break-all font-mono text-xs">{JSON.stringify(selected.publication.acl)}</dd></div><div className="mt-2"><dt className="text-muted">回滾</dt><dd className="mt-1">{selected.publication.rollback}</dd></div>{selected.publication.sop_precedence && <div className="mt-2 flex items-center gap-2 text-highlight"><ShieldAlert className="h-4 w-4" /><span>正式 SOP 永遠優先</span></div>}</dl>
          {selected.blocked_reasons.length > 0 && <div className="rounded-xl bg-danger-soft p-3 text-sm text-danger"><p className="font-semibold">目前不可直接發布</p><ul className="mt-1 list-inside list-disc">{selected.blocked_reasons.map(reason => <li key={reason}>{blockedLabels[reason] || reason}</li>)}</ul></div>}
          {selected.risk_level === 'high' && <label className="flex min-h-11 cursor-pointer items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft p-3 text-sm text-danger"><input type="checkbox" className="mt-1" checked={ackHigh} onChange={event => setAckHigh(event.target.checked)} /><span>我已核對高風險內容、禁止動作及主管／正式 SOP 要求。</span></label>}
          {selected.confidence != null && selected.confidence < 0.8 && <label className="flex min-h-11 cursor-pointer items-start gap-2 rounded-xl border border-highlight/30 bg-highlight-soft p-3 text-sm text-highlight"><input type="checkbox" className="mt-1" checked={ackLow} onChange={event => setAckLow(event.target.checked)} /><span>我已逐一核對低信心辨識內容與原始證據。</span></label>}
          <div><label className="input-label" htmlFor="review-notes">覆核備註</label><textarea id="review-notes" className="input min-h-0 py-2" rows={4} maxLength={2000} value={notes} onChange={event => setNotes(event.target.value)} placeholder="記錄修正、核准依據或駁回原因" /></div>
          <p className="flex items-start gap-2 rounded-xl bg-accent-soft p-3 text-sm text-accent-ink"><Clock3 className="mt-0.5 h-4 w-4 shrink-0" />決策、審核人、政策版本與發布結果會留下不可變稽核證據。</p>
          <div className="mt-auto space-y-2"><button type="button" disabled={acting || !approvalReady || !evidenceLinksValid} className="btn-primary w-full" onClick={() => void decide('approved')}>{acting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle className="h-4 w-4" />}核准並發布</button><button type="button" disabled={acting} className="btn-outline w-full text-danger" onClick={() => setRejectOpen(true)}><XCircle className="h-4 w-4" />駁回</button></div>
        </div>}
      </aside>
      <ConfirmDialog open={rejectOpen} danger busy={acting} title="駁回此知識候選？" description="不會發布至知識檢索，決策與備註會保留在稽核紀錄。" confirmLabel="確認駁回" onCancel={() => !acting && setRejectOpen(false)} onConfirm={() => void decide('rejected')} />
      <ConfirmDialog open={batchOpen} busy={acting} title={`批量核准 ${selectedIds.size} 筆？`} description="系統只允許同一 provider、來源類型、政策版本且低風險無衝突的項目批量核准。" confirmLabel="批量核准" onCancel={() => !acting && setBatchOpen(false)} onConfirm={() => void batchApprove()} />
    </div>
  </AsyncState>
}
