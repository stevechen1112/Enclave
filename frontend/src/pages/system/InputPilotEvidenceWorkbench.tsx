import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ClipboardCheck, FileCheck2, Gauge, ShieldAlert } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  formatErrorWithTrace,
  operationsApi,
  parseApiError,
  type InputPilotEvidence,
  type InputPilotGate,
  type InputPilotSummary,
} from '../../api'

type FormKey = 'metric' | 'incident' | 'audit' | 'retrospective' | 'acceptance' | null

interface Props {
  pilot: InputPilotSummary
  gate: InputPilotGate | null
  onChanged: () => Promise<void> | void
}

const localDate = () => {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

const localDateTime = () => {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

const utcIso = (value: string) => new Date(value).toISOString()

const hashInputProps = {
  minLength: 64,
  maxLength: 64,
  pattern: '[0-9a-fA-F]{64}',
} as const

export default function InputPilotEvidenceWorkbench({ pilot, gate, onChanged }: Props) {
  const [evidence, setEvidence] = useState<InputPilotEvidence | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [activeForm, setActiveForm] = useState<FormKey>(null)
  const [metric, setMetric] = useState({
    metric_date: localDate(),
    journey_key: String(pilot.journeys[0]?.key ?? ''),
    total_attempts: '1', successful_attempts: '1', retry_count: '0',
    manual_correction_count: '0', processing_p95_ms: '60000',
    retrieval_checks: '1', cited_retrievals: '1', friction_count: '0',
    source_evidence_sha256: '', notes: '',
  })
  const [incident, setIncident] = useState({
    severity: 'medium', category: 'quality', summary: '', occurred_at: localDateTime(),
    near_miss: false, data_loss: false, unauthorized_access: false, false_completion: false,
  })
  const [audit, setAudit] = useState({
    audit_type: 'quality', status: 'pass', sample_size: '30', findings: '',
    evidence_sha256: '', audited_at: localDateTime(),
  })
  const [retrospective, setRetrospective] = useState({ retrospective_ref: '', retrospective_sha256: '' })
  const [acceptance, setAcceptance] = useState({
    decision: 'accepted', signer_name: '', signer_role: '', signed_document_ref: '',
    signed_document_sha256: '', statement: '', signed_at: localDateTime(),
  })
  const [resolutions, setResolutions] = useState<Record<string, {
    root_cause: string; corrective_action: string; retrospective_sha256: string
  }>>({})

  const loadEvidence = useCallback(async () => {
    setLoading(true)
    try {
      setEvidence(await operationsApi.inputPilotEvidence(pilot.id))
    } catch (error) {
      toast.error(formatErrorWithTrace(parseApiError(error, '無法載入 Pilot 證據')))
    } finally {
      setLoading(false)
    }
  }, [pilot.id])

  useEffect(() => { void loadEvidence() }, [loadEvidence])
  useEffect(() => {
    setMetric(current => ({ ...current, journey_key: String(pilot.journeys[0]?.key ?? '') }))
  }, [pilot.id, pilot.journeys])

  const submit = async (operation: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try {
      await operation()
      toast.success(success)
      setActiveForm(null)
      await loadEvidence()
      await onChanged()
    } catch (error) {
      toast.error(formatErrorWithTrace(parseApiError(error, 'Pilot 證據寫入失敗')))
    } finally {
      setBusy(false)
    }
  }

  const setResolution = (id: string, key: 'root_cause' | 'corrective_action' | 'retrospective_sha256', value: string) => {
    setResolutions(current => ({
      ...current,
      [id]: {
        root_cause: current[id]?.root_cause ?? '',
        corrective_action: current[id]?.corrective_action ?? '',
        retrospective_sha256: current[id]?.retrospective_sha256 ?? '',
        [key]: value,
      },
    }))
  }

  const running = pilot.status === 'running'
  const openIncidents = evidence?.incidents.filter(item => item.status !== 'resolved') ?? []
  const acceptancePreflightErrors = gate?.errors.filter(
    error => error !== 'signed customer acceptance is missing',
  ) ?? []
  const acceptancePreflightReady = Boolean(gate) && acceptancePreflightErrors.length === 0

  return (
    <section className="rounded-2xl border border-line bg-surface p-5 shadow-card" aria-labelledby="pilot-evidence-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="pilot-evidence-title" className="font-display text-lg font-semibold text-ink">Pilot 證據工作台</h2>
          <p className="mt-1 text-sm text-muted">證據採不可覆寫 ledger；SHA-256 必須對應已封存的原始報表或簽署文件。</p>
        </div>
        {loading && <span className="text-sm text-muted">載入中…</span>}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <button type="button" className="btn-outline justify-start" disabled={!running} onClick={() => setActiveForm('metric')}><Gauge className="h-4 w-4" />每日指標</button>
        <button type="button" className="btn-outline justify-start" disabled={!running} onClick={() => setActiveForm('incident')}><ShieldAlert className="h-4 w-4" />Incident</button>
        <button type="button" className="btn-outline justify-start" disabled={!running} onClick={() => setActiveForm('audit')}><ClipboardCheck className="h-4 w-4" />Audit</button>
        <button type="button" className="btn-outline justify-start" disabled={!running || Boolean(evidence?.retrospective)} onClick={() => setActiveForm('retrospective')}><FileCheck2 className="h-4 w-4" />整體復盤</button>
        <button type="button" className="btn-outline justify-start" disabled={!running || Boolean(evidence?.acceptance)} onClick={() => setActiveForm('acceptance')}><FileCheck2 className="h-4 w-4" />客戶簽署</button>
      </div>
      {!running && <p className="mt-3 text-sm text-muted">此 Pilot 已不在 running 狀態；證據保持唯讀。</p>}

      {activeForm === 'metric' && (
        <form className="mt-5 rounded-xl border border-line bg-wash p-4" onSubmit={event => {
          event.preventDefault()
          void submit(() => operationsApi.recordInputPilotMetric(pilot.id, {
            ...metric,
            total_attempts: Number(metric.total_attempts),
            successful_attempts: Number(metric.successful_attempts),
            retry_count: Number(metric.retry_count),
            manual_correction_count: Number(metric.manual_correction_count),
            processing_p95_ms: Number(metric.processing_p95_ms),
            retrieval_checks: Number(metric.retrieval_checks),
            cited_retrievals: Number(metric.cited_retrievals),
            friction_count: Number(metric.friction_count),
          }), '每日指標已封存')
        }}>
          <h3 className="font-semibold text-ink">登錄每日 journey 指標</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <label className="text-sm text-muted">日期<input required type="date" className="input mt-1 w-full" value={metric.metric_date} onChange={event => setMetric({ ...metric, metric_date: event.target.value })} /></label>
            <label className="text-sm text-muted">Journey<select className="input mt-1 w-full" value={metric.journey_key} onChange={event => setMetric({ ...metric, journey_key: event.target.value })}>{pilot.journeys.map(item => <option key={item.key} value={item.key}>{String(item.key)}</option>)}</select></label>
            <NumberField label="總嘗試數" value={metric.total_attempts} onChange={value => setMetric({ ...metric, total_attempts: value })} />
            <NumberField label="成功數" value={metric.successful_attempts} onChange={value => setMetric({ ...metric, successful_attempts: value })} />
            <NumberField label="重試數" value={metric.retry_count} onChange={value => setMetric({ ...metric, retry_count: value })} />
            <NumberField label="人工修正數" value={metric.manual_correction_count} onChange={value => setMetric({ ...metric, manual_correction_count: value })} />
            <NumberField label="處理 P95（ms）" value={metric.processing_p95_ms} onChange={value => setMetric({ ...metric, processing_p95_ms: value })} />
            <NumberField label="檢索檢查數" value={metric.retrieval_checks} onChange={value => setMetric({ ...metric, retrieval_checks: value })} />
            <NumberField label="具引用檢索數" value={metric.cited_retrievals} onChange={value => setMetric({ ...metric, cited_retrievals: value })} />
            <NumberField label="摩擦事件數" value={metric.friction_count} onChange={value => setMetric({ ...metric, friction_count: value })} />
            <label className="text-sm text-muted md:col-span-2">來源證據 SHA-256<input required {...hashInputProps} className="input mt-1 w-full font-mono" value={metric.source_evidence_sha256} onChange={event => setMetric({ ...metric, source_evidence_sha256: event.target.value.trim() })} /></label>
            <label className="text-sm text-muted md:col-span-3">備註<textarea className="input mt-1 w-full" value={metric.notes} onChange={event => setMetric({ ...metric, notes: event.target.value })} /></label>
          </div>
          <FormActions busy={busy} onCancel={() => setActiveForm(null)} />
        </form>
      )}

      {activeForm === 'incident' && (
        <form className="mt-5 rounded-xl border border-line bg-wash p-4" onSubmit={event => {
          event.preventDefault()
          void submit(() => operationsApi.recordInputPilotIncident(pilot.id, { ...incident, occurred_at: utcIso(incident.occurred_at) }), 'Incident 已建立')
        }}>
          <h3 className="font-semibold text-ink">建立 Incident／near miss</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-sm text-muted">嚴重度<select className="input mt-1 w-full" value={incident.severity} onChange={event => setIncident({ ...incident, severity: event.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label>
            <label className="text-sm text-muted">分類<input required className="input mt-1 w-full" value={incident.category} onChange={event => setIncident({ ...incident, category: event.target.value })} /></label>
            <label className="text-sm text-muted">發生時間<input required type="datetime-local" className="input mt-1 w-full" value={incident.occurred_at} onChange={event => setIncident({ ...incident, occurred_at: event.target.value })} /></label>
            <label className="text-sm text-muted md:col-span-2">摘要<textarea required className="input mt-1 w-full" value={incident.summary} onChange={event => setIncident({ ...incident, summary: event.target.value })} /></label>
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-sm text-ink">{([
            ['near_miss', 'Near miss'], ['data_loss', '資料遺失'], ['unauthorized_access', '越權'], ['false_completion', '假完成'],
          ] as const).map(([key, label]) => <label key={key} className="flex items-center gap-2"><input type="checkbox" checked={incident[key]} onChange={event => setIncident({ ...incident, [key]: event.target.checked })} />{label}</label>)}</div>
          <FormActions busy={busy} onCancel={() => setActiveForm(null)} />
        </form>
      )}

      {activeForm === 'audit' && (
        <form className="mt-5 rounded-xl border border-line bg-wash p-4" onSubmit={event => {
          event.preventDefault()
          void submit(() => operationsApi.recordInputPilotAudit(pilot.id, {
            ...audit,
            sample_size: Number(audit.sample_size),
            findings: audit.findings.trim() ? [{ note: audit.findings.trim() }] : [],
            audited_at: utcIso(audit.audited_at),
          }), 'Audit 已封存')
        }}>
          <h3 className="font-semibold text-ink">登錄品質／安全／權限 Audit</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-sm text-muted">類型<select className="input mt-1 w-full" value={audit.audit_type} onChange={event => setAudit({ ...audit, audit_type: event.target.value })}><option value="quality">Quality</option><option value="security">Security</option><option value="permission">Permission</option></select></label>
            <label className="text-sm text-muted">結果<select className="input mt-1 w-full" value={audit.status} onChange={event => setAudit({ ...audit, status: event.target.value })}><option value="pass">Pass</option><option value="fail">Fail</option><option value="pending">Pending</option></select></label>
            <NumberField label="抽樣數" value={audit.sample_size} onChange={value => setAudit({ ...audit, sample_size: value })} />
            <label className="text-sm text-muted">稽核時間<input required type="datetime-local" className="input mt-1 w-full" value={audit.audited_at} onChange={event => setAudit({ ...audit, audited_at: event.target.value })} /></label>
            <label className="text-sm text-muted md:col-span-2">證據 SHA-256<input required {...hashInputProps} className="input mt-1 w-full font-mono" value={audit.evidence_sha256} onChange={event => setAudit({ ...audit, evidence_sha256: event.target.value.trim() })} /></label>
            <label className="text-sm text-muted md:col-span-2">發現摘要<textarea className="input mt-1 w-full" value={audit.findings} onChange={event => setAudit({ ...audit, findings: event.target.value })} /></label>
          </div>
          <FormActions busy={busy} onCancel={() => setActiveForm(null)} />
        </form>
      )}

      {activeForm === 'retrospective' && (
        <form className="mt-5 rounded-xl border border-line bg-wash p-4" onSubmit={event => {
          event.preventDefault()
          void submit(() => operationsApi.recordInputPilotRetrospective(pilot.id, retrospective), 'Pilot 復盤已封存')
        }}>
          <h3 className="font-semibold text-ink">封存整體 Pilot 復盤</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-2"><label className="text-sm text-muted">文件參照<input required className="input mt-1 w-full" value={retrospective.retrospective_ref} onChange={event => setRetrospective({ ...retrospective, retrospective_ref: event.target.value })} /></label><label className="text-sm text-muted">文件 SHA-256<input required {...hashInputProps} className="input mt-1 w-full font-mono" value={retrospective.retrospective_sha256} onChange={event => setRetrospective({ ...retrospective, retrospective_sha256: event.target.value.trim() })} /></label></div>
          <FormActions busy={busy} onCancel={() => setActiveForm(null)} />
        </form>
      )}

      {activeForm === 'acceptance' && (
        <form className="mt-5 rounded-xl border border-line bg-wash p-4" onSubmit={event => {
          event.preventDefault()
          void submit(() => operationsApi.recordInputPilotAcceptance(pilot.id, { ...acceptance, signed_at: utcIso(acceptance.signed_at) }), '客戶驗收決定已封存')
        }}>
          <div className="flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-warning" /><h3 className="font-semibold text-ink">登錄客戶簽署驗收</h3></div>
          {acceptancePreflightReady
            ? <p className="mt-2 text-sm text-success">除客戶簽署外的 preflight 條件已通過；簽署後仍由後端重新驗證完整 gate。</p>
            : <p className="mt-2 text-sm text-warning">仍有 {acceptancePreflightErrors.length} 項 preflight blocker；accepted 決策會被拒絕。可先修正 blocker，或如實登錄 rejected。</p>}
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-sm text-muted">決定<select className="input mt-1 w-full" value={acceptance.decision} onChange={event => setAcceptance({ ...acceptance, decision: event.target.value })}><option value="accepted">Accepted</option><option value="rejected">Rejected</option></select></label>
            <label className="text-sm text-muted">簽署時間<input required type="datetime-local" className="input mt-1 w-full" value={acceptance.signed_at} onChange={event => setAcceptance({ ...acceptance, signed_at: event.target.value })} /></label>
            <label className="text-sm text-muted">簽署人<input required className="input mt-1 w-full" value={acceptance.signer_name} onChange={event => setAcceptance({ ...acceptance, signer_name: event.target.value })} /></label>
            <label className="text-sm text-muted">授權角色<input required className="input mt-1 w-full" value={acceptance.signer_role} onChange={event => setAcceptance({ ...acceptance, signer_role: event.target.value })} /></label>
            <label className="text-sm text-muted md:col-span-2">簽署文件參照<input required className="input mt-1 w-full" value={acceptance.signed_document_ref} onChange={event => setAcceptance({ ...acceptance, signed_document_ref: event.target.value })} /></label>
            <label className="text-sm text-muted md:col-span-2">簽署文件 SHA-256<input required {...hashInputProps} className="input mt-1 w-full font-mono" value={acceptance.signed_document_sha256} onChange={event => setAcceptance({ ...acceptance, signed_document_sha256: event.target.value.trim() })} /></label>
            <label className="text-sm text-muted md:col-span-2">驗收聲明<textarea required className="input mt-1 w-full" value={acceptance.statement} onChange={event => setAcceptance({ ...acceptance, statement: event.target.value })} /></label>
          </div>
          <FormActions busy={busy} onCancel={() => setActiveForm(null)} />
        </form>
      )}

      {openIncidents.length > 0 && (
        <div className="mt-5 space-y-3">
          <h3 className="font-semibold text-ink">待結案 Incident</h3>
          {openIncidents.map(item => {
            const resolution = resolutions[item.id] ?? { root_cause: '', corrective_action: '', retrospective_sha256: '' }
            const resolutionReady = Boolean(
              resolution.root_cause.trim()
              && resolution.corrective_action.trim()
              && /^[0-9a-fA-F]{64}$/.test(resolution.retrospective_sha256),
            )
            return <div key={item.id} className="rounded-xl border border-warning/30 bg-warning/5 p-4"><div className="flex flex-wrap justify-between gap-2"><p className="font-medium text-ink">{item.summary}</p><span className="text-xs uppercase text-warning">{item.severity} · {item.category}</span></div>{running && <div className="mt-3 grid gap-3 md:grid-cols-3"><input aria-label={`${item.summary} root cause`} className="input" placeholder="Root cause" value={resolution.root_cause} onChange={event => setResolution(item.id, 'root_cause', event.target.value)} /><input aria-label={`${item.summary} corrective action`} className="input" placeholder="Corrective action" value={resolution.corrective_action} onChange={event => setResolution(item.id, 'corrective_action', event.target.value)} /><input aria-label={`${item.summary} retrospective SHA-256`} {...hashInputProps} className="input font-mono" placeholder="Retrospective SHA-256" value={resolution.retrospective_sha256} onChange={event => setResolution(item.id, 'retrospective_sha256', event.target.value.trim())} /><div className="md:col-span-3 flex justify-end"><button type="button" disabled={busy || !resolutionReady} className="btn-primary" onClick={() => void submit(() => operationsApi.resolveInputPilotIncident(pilot.id, item.id, resolution), 'Incident 已結案')}>完成復盤並結案</button></div></div>}</div>
          })}
        </div>
      )}

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div><h3 className="text-sm font-semibold text-ink">最近每日指標（{evidence?.metric_rows ?? 0} 筆）</h3><div className="mt-2 max-h-64 overflow-auto rounded-xl border border-line"><table className="w-full text-left text-sm"><thead className="sticky top-0 bg-wash text-muted"><tr><th className="px-3 py-2">日期</th><th className="px-3 py-2">Journey</th><th className="px-3 py-2">成功</th></tr></thead><tbody>{evidence?.latest_metrics.map(row => <tr key={row.id} className="border-t border-line"><td className="px-3 py-2">{row.metric_date}</td><td className="px-3 py-2">{row.journey_key}</td><td className="px-3 py-2">{row.successful_attempts}/{row.total_attempts}</td></tr>)}{!evidence?.latest_metrics.length && <tr><td className="px-3 py-3 text-muted" colSpan={3}>尚無資料</td></tr>}</tbody></table></div></div>
        <div><h3 className="text-sm font-semibold text-ink">Audit 紀錄</h3><div className="mt-2 space-y-2">{evidence?.audits.slice(0, 6).map(row => <div key={row.id} className="flex items-center justify-between rounded-lg border border-line px-3 py-2 text-sm"><span>{row.audit_type} · sample {row.sample_size}</span><span className={row.status === 'pass' ? 'text-success' : 'text-warning'}>{row.status.toUpperCase()}</span></div>)}{!evidence?.audits.length && <p className="rounded-lg border border-line px-3 py-3 text-sm text-muted">尚無 Audit</p>}</div></div>
      </div>
    </section>
  )
}

function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="text-sm text-muted">{label}<input required type="number" min="0" className="input mt-1 w-full" value={value} onChange={event => onChange(event.target.value)} /></label>
}

function FormActions({ busy, onCancel }: { busy: boolean; onCancel: () => void }) {
  return <div className="mt-4 flex justify-end gap-2"><button type="button" className="btn-outline" onClick={onCancel}>取消</button><button type="submit" className="btn-primary" disabled={busy}>{busy ? '寫入中…' : '封存證據'}</button></div>
}
