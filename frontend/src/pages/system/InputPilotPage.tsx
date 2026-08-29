import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Play, Plus, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuth } from '../../auth'
import {
  operationsApi,
  parseApiError,
  formatErrorWithTrace,
  type InputPilotGate,
  type InputPilotSummary,
} from '../../api'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'
import type { ApiErrorInfo } from '../../api'
import InputPilotEvidenceWorkbench from './InputPilotEvidenceWorkbench'

const JOURNEYS = [
  { key: 'nas_batch', label: 'NAS 批次' },
  { key: 'document_batch', label: '文件批次' },
  { key: 'long_audio', label: '長時間錄音' },
  { key: 'machine_video', label: '機台影片' },
]

const ERROR_LABELS: Record<string, string> = {
  'pilot observation window is shorter than minimum days': '尚未累積連續 14 天資料',
  'signed customer acceptance is missing': '尚未附上客戶簽署驗收文件',
  'pilot has not started': '試行尚未開始',
  'missing passing audits: permission, quality, security': '品質、安全與權限稽核尚未全數通過',
}

export default function InputPilotPage() {
  const { user } = useAuth()
  const [pilots, setPilots] = useState<InputPilotSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [gate, setGate] = useState<InputPilotGate | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [evidenceVersion, setEvidenceVersion] = useState(0)
  const [name, setName] = useState('第一租戶 Input 試行')
  const [dpaRef, setDpaRef] = useState('')
  const [environmentHash, setEnvironmentHash] = useState('')
  const [glossaryRef, setGlossaryRef] = useState('')
  const [aclRef, setAclRef] = useState('')
  const [journeys, setJourneys] = useState<string[]>(['nas_batch', 'long_audio'])
  const selected = useMemo(
    () => pilots.find(item => item.id === selectedId) ?? pilots[0] ?? null,
    [pilots, selectedId],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const rows = await operationsApi.listInputPilots()
      setPilots(rows)
      setSelectedId(current => current ?? rows[0]?.id ?? null)
    } catch (err) {
      setError(parseApiError(err, '無法載入 Input 試行資料'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!selected?.id) { setGate(null); return }
    void operationsApi.inputPilotGate(selected.id).then(setGate).catch(() => setGate(null))
  }, [selected?.id, selected?.status, evidenceVersion])

  const toggleJourney = (key: string) => {
    setJourneys(current => current.includes(key)
      ? current.filter(item => item !== key)
      : current.length < 3 ? [...current, key] : current)
  }

  const createPilot = async () => {
    if (journeys.length < 2 || journeys.length > 3) {
      toast.error('請選擇 2–3 條 Input journey')
      return
    }
    try {
      const created = await operationsApi.createInputPilot({
        name,
        evidence_mode: 'live',
        dedicated_environment: true,
        environment_evidence_sha256: environmentHash,
        data_processing_agreement_ref: dpaRef,
        journeys: journeys.map(key => ({
          key,
          review_owner_id: user?.id,
          metadata_template: { plant: 'required', owner: 'required' },
          glossary_ref: glossaryRef,
          role_acl_ref: aclRef,
        })),
      })
      toast.success('Pilot 已建立，請確認後啟動')
      setShowCreate(false)
      setSelectedId(created.id)
      await load()
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '建立 Pilot 失敗')))
    }
  }

  const startPilot = async () => {
    if (!selected) return
    try {
      await operationsApi.startInputPilot(selected.id)
      toast.success('Pilot 已開始記錄')
      await load()
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '啟動 Pilot 失敗')))
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <PageHeader
          variant="section"
          title="Input 現場試行"
          subtitle="用真實租戶、裝置與資料累積 14–28 天證據；內部測試不能取代這個 gate。"
          actions={<div className="flex gap-2"><button type="button" className="btn-outline" onClick={() => void load()}><RefreshCw className="h-4 w-4" />重新整理</button><button type="button" className="btn-primary" onClick={() => setShowCreate(true)}><Plus className="h-4 w-4" />建立 Pilot</button></div>}
        />

        <AsyncState loading={loading} error={error} onRetry={load} empty={!loading && !error && pilots.length === 0 && !showCreate} emptyTitle="尚未建立現場 Pilot" emptyDescription="先準備專屬環境、DPA 與 2–3 條 Input journey，再開始累積真實證據。" emptyActionLabel="建立 Pilot" onEmptyAction={() => setShowCreate(true)}>
          {showCreate && (
            <section className="rounded-2xl border border-line bg-surface p-5 shadow-card" aria-labelledby="pilot-create-title">
              <h2 id="pilot-create-title" className="font-display text-lg font-semibold text-ink">建立受控 Pilot</h2>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <label className="text-sm text-muted">名稱<input className="input mt-1 w-full" value={name} onChange={event => setName(event.target.value)} /></label>
                <label className="text-sm text-muted">已簽 DPA 參照<input className="input mt-1 w-full" value={dpaRef} onChange={event => setDpaRef(event.target.value)} placeholder="contract://..." /></label>
                <label className="text-sm text-muted md:col-span-2">專屬環境證據 SHA-256<input className="input mt-1 w-full font-mono" value={environmentHash} onChange={event => setEnvironmentHash(event.target.value.trim())} maxLength={64} /></label>
                <label className="text-sm text-muted">租戶術語表參照<input className="input mt-1 w-full" value={glossaryRef} onChange={event => setGlossaryRef(event.target.value)} placeholder="tenant://glossary/v1" /></label>
                <label className="text-sm text-muted">角色／ACL 參照<input className="input mt-1 w-full" value={aclRef} onChange={event => setAclRef(event.target.value)} placeholder="tenant://acl/pilot" /></label>
              </div>
              <fieldset className="mt-4"><legend className="text-sm font-medium text-ink">選擇 2–3 條 journey</legend><div className="mt-2 grid gap-2 sm:grid-cols-2">{JOURNEYS.map(item => <label key={item.key} className="flex min-h-11 items-center gap-2 rounded-lg border border-line px-3 text-sm"><input type="checkbox" checked={journeys.includes(item.key)} onChange={() => toggleJourney(item.key)} />{item.label}</label>)}</div></fieldset>
              <div className="mt-5 flex justify-end gap-2"><button type="button" className="btn-outline" onClick={() => setShowCreate(false)}>取消</button><button type="button" className="btn-primary" onClick={() => void createPilot()}>建立</button></div>
            </section>
          )}

          {selected && (
            <section className="rounded-2xl border border-line bg-surface p-5 shadow-card">
              <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-medium uppercase tracking-wide text-muted">{selected.evidence_mode === 'live' ? '真實證據' : '模擬證據'}</p><h2 className="font-display text-xl font-semibold text-ink">{selected.name}</h2><p className="mt-1 text-sm text-muted">{selected.journeys.map(item => JOURNEYS.find(j => j.key === item.key)?.label ?? item.key).join('、')}</p></div><div className="flex items-center gap-2">{gate?.status === 'PASS' ? <CheckCircle2 className="text-success" /> : <AlertTriangle className="text-warning" />}<span className="font-semibold">{gate?.status ?? selected.status}</span></div></div>
              <div className="mt-5 grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-wash p-4"><p className="text-xs text-muted">觀察天數</p><p className="mt-1 text-2xl font-semibold">{gate?.observation_days ?? 0}<span className="ml-1 text-sm font-normal text-muted">/ 14</span></p></div><div className="rounded-xl bg-wash p-4"><p className="text-xs text-muted">通過稽核</p><p className="mt-1 text-2xl font-semibold">{gate?.passed_audits.length ?? 0}<span className="ml-1 text-sm font-normal text-muted">/ 3</span></p></div><div className="rounded-xl bg-wash p-4"><p className="text-xs text-muted">Incident</p><p className="mt-1 text-2xl font-semibold">{gate?.incident_count ?? 0}</p></div></div>
              {gate?.errors.length ? <div className="mt-5 rounded-xl border border-warning/30 bg-warning/5 p-4"><h3 className="text-sm font-semibold text-ink">尚未通過的項目</h3><ul className="mt-2 space-y-1 text-sm text-muted">{gate.errors.map(error => <li key={error}>• {ERROR_LABELS[error] ?? error}</li>)}</ul></div> : null}
              {selected.status === 'ready' && <div className="mt-5 flex justify-end"><button type="button" className="btn-primary" onClick={() => void startPilot()}><Play className="h-4 w-4" />開始 14 天試行</button></div>}
            </section>
          )}

          {selected && selected.status !== 'ready' && (
            <InputPilotEvidenceWorkbench
              pilot={selected}
              gate={gate}
              onChanged={async () => {
                setEvidenceVersion(value => value + 1)
                await load()
              }}
            />
          )}
        </AsyncState>
      </div>
    </div>
  )
}
