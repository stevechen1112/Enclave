/**
 * TaskWorkspace — 職能任務主畫面（Phase 3）。
 *
 * 對話／語音是主路徑；右側欄位卡顯示來源與信心、可手動編輯；
 * 完整表單降為「檢視全部／手動備援」。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { ArrowLeft, ExternalLink, Plus, RotateCcw, Send } from 'lucide-react'
import PushToTalk from '../../components/mka/PushToTalk'
import { formsApi, type FormFieldSpec, type TranscribeResponse } from '../../services/mka'
import { tasksApi, type TaskDefinition, type TaskRun } from '../../services/tasks'

const SOURCE_LABEL: Record<string, string> = {
  voice: '語音',
  text: '文字',
  knowledge: '知識庫',
  tool: '工具',
  rule: '規則',
  user: '手動',
  default: '預設',
}

const TASK_INPUT_LABEL: Record<string, string> = {
  title: '訪談主題',
  summary: '經驗摘要',
  steps: '操作步驟（每行一步）',
}

function newIdempotencyKey(): string {
  return `ws-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function fieldInputType(type?: string): 'text' | 'number' | 'date' {
  if (type === 'date') return 'date'
  if (type === 'number' || type === 'amount') return 'number'
  return 'text'
}

const TASK_STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  in_progress: '填寫中',
  waiting_review: '已送審，等待審核',
  rejected: '需要修正',
  approved: '已核准',
  executed: '已完成',
  exported: '已匯出',
  failed: '執行失敗',
}

type ReviewInfo = {
  status?: string
  reason?: string
  decided_at?: string
}

export default function TaskWorkspacePage() {
  const { taskKey = '' } = useParams()
  const navigate = useNavigate()

  const [definition, setDefinition] = useState<TaskDefinition | null>(null)
  const [fields, setFields] = useState<FormFieldSpec[]>([])
  const [formKey, setFormKey] = useState<string | null>(null)
  const [run, setRun] = useState<TaskRun | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [formStatus, setFormStatus] = useState<string | null>(null)
  // 本地草稿值：輸入即時更新 UI，PATCH 以 debounce 合併送出
  const [draftValues, setDraftValues] = useState<Record<string, string>>({})
  const patchTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  const values = useMemo(() => {
    const base = (run?.input_snapshot?.values ?? {}) as Record<string, unknown>
    // A task keeps user-entered fields in its input snapshot while deterministic
    // results live in provenance.  Merge both so calculated amount fields stay
    // visible for review instead of looking blank/unfinished.
    const calculationSnapshot = (run?.provenance?.calculation_snapshot ?? {}) as {
      calculated?: Record<string, unknown>
    }
    const calculated = calculationSnapshot.calculated ?? {}
    return { ...base, ...calculated, ...draftValues }
  }, [run, draftValues])
  const sources = run?.field_sources ?? {}
  const manualEdits = useMemo(
    () => new Set(run?.provenance?.manual_edits ?? []),
    [run],
  )
  const missingRequired = useMemo(
    () =>
      fields
        .filter(
          f =>
            f.required &&
            !f.calculated &&
            (values[f.name] === undefined || values[f.name] === ''),
        )
        .map(f => f.name),
    [fields, values],
  )
  const editable = run?.status === 'draft' || run?.status === 'in_progress'
  const formInstanceId = run?.output_refs?.form_instance_id as string | undefined
  const review = (run?.provenance?.review ?? {}) as ReviewInfo

  // 表單狀態（簽核進度與 guarded 匯出）
  useEffect(() => {
    if (!formInstanceId) {
      setFormStatus(null)
      return
    }
    let cancelled = false
    formsApi
      .getInstance(formInstanceId)
      .then(inst => {
        if (!cancelled) setFormStatus(inst.status)
      })
      .catch(() => {
        if (!cancelled) setFormStatus(null)
      })
    return () => {
      cancelled = true
    }
  }, [formInstanceId])

  // 載入任務定義 + 表單 schema + resume／建立 run
  useEffect(() => {
    let cancelled = false
    async function boot() {
      try {
        const defs = await tasksApi.list()
        const def = defs.find(d => d.task_key === taskKey)
        if (!def) {
          if (!cancelled) setNotFound(true)
          return
        }
        if (cancelled) return
        setDefinition(def)

        const formBinding = def.output_bindings.find(b => b.kind === 'form' && b.form_key)
        if (formBinding?.form_key) {
          setFormKey(formBinding.form_key)
          try {
            const schema = await formsApi.schema(formBinding.form_key)
            if (!cancelled) {
              setFields((schema.fields ?? schema.json_schema?.fields ?? []) as FormFieldSpec[])
            }
          } catch {
            // 表單 schema 不可用時仍可進行對話式收集
          }
        } else {
          const inputSchema = def.input_schema as {
            properties?: Record<string, { type?: string }>
            required?: string[]
          }
          const required = new Set(inputSchema.required ?? [])
          const taskFields = Object.entries(inputSchema.properties ?? {}).map(
            ([name, spec]) => ({
              name,
              label: TASK_INPUT_LABEL[name] ?? name,
              type: spec.type === 'number' ? 'number' : 'text',
              required: required.has(name),
            }),
          )
          if (!cancelled) setFields(taskFields)
        }

        const runs = await tasksApi.listRuns({
          task_key: taskKey,
          status: 'draft,in_progress,waiting_review,rejected,approved,executed',
        })
        if (cancelled) return
        if (runs.length > 0) {
          setRun(runs[0])
        } else {
          const created = await tasksApi.startRun(taskKey, {
            idempotency_key: newIdempotencyKey(),
          })
          if (!cancelled) setRun(created)
        }
      } catch (err) {
        const status = (err as { response?: { status?: number } })?.response?.status
        if (!cancelled) {
          if (status === 403 || status === 404) setNotFound(true)
          else toast.error('工作區載入失敗，請稍後再試')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    boot()
    return () => {
      cancelled = true
    }
  }, [taskKey])

  const applyVoiceResult = useCallback(
    async (result: TranscribeResponse) => {
      if (!run || !editable) return
      setBusy(true)
      try {
        const { run: updated, detected_fields: detected } = await tasksApi.parseText(
          run.id,
          result.text,
          {
            source: 'voice',
            source_ref: result.session_id,
            confidence: result.confidence,
          },
        )
        const entries = Object.entries(detected || {}).filter(
          ([, value]) => value !== undefined && value !== '',
        )
        if (!entries.length) {
          toast('沒有辨識到可帶入的欄位，請說出欄位名稱後再說內容', { icon: 'ℹ️' })
          return
        }
        setRun(updated)
        toast.success(`已帶入 ${entries.length} 個欄位`)
      } catch {
        toast.error('欄位帶入失敗')
      } finally {
        setBusy(false)
      }
    },
    [run, editable],
  )

  const handleParseText = useCallback(async () => {
    if (!run || !text.trim() || !editable) return
    setBusy(true)
    try {
      const { run: updated } = await tasksApi.parseText(run.id, text.trim())
      setRun(updated)
      setText('')
    } catch {
      toast.error('文字解析失敗')
    } finally {
      setBusy(false)
    }
  }, [run, text, editable])

  const handleEditField = useCallback(
    (name: string, value: string) => {
      if (!run || !editable) return
      setDraftValues(prev => ({ ...prev, [name]: value }))
      clearTimeout(patchTimers.current[name])
      patchTimers.current[name] = setTimeout(async () => {
        try {
          const updated = await tasksApi.patchInputs(run.id, {
            values: { [name]: value },
            sources: { [name]: { source: 'user' } },
            edited_fields: [name],
          })
          setRun(updated)
          setDraftValues(prev => {
            const next = { ...prev }
            delete next[name]
            return next
          })
        } catch {
          toast.error('欄位更新失敗')
        }
      }, 600)
    },
    [run, editable],
  )

  // 卸載時清掉未送出的 debounce timer
  useEffect(() => {
    const timers = patchTimers.current
    return () => {
      Object.values(timers).forEach(clearTimeout)
    }
  }, [])

  const handleSubmitReview = useCallback(async () => {
    if (!run) return
    setBusy(true)
    try {
      const updated = await tasksApi.execute(run.id)
      setRun(updated)
      toast.success('已送出審核')
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 501) {
        toast.error('此任務類型尚未開放自動執行')
      } else {
        toast.error('送審失敗，請稍後再試')
      }
    } finally {
      setBusy(false)
    }
  }, [run])

  const handleStartRevision = useCallback(async () => {
    if (!run || run.status !== 'rejected') return
    setBusy(true)
    try {
      const updated = await tasksApi.transition(run.id, 'draft')
      setRun(updated)
      setDraftValues({})
      toast.success('已開啟修正；完成後可重新送審')
    } catch {
      toast.error('無法開啟修正，請重新整理後再試')
    } finally {
      setBusy(false)
    }
  }, [run])

  const handleStartNew = useCallback(async () => {
    setBusy(true)
    try {
      const created = await tasksApi.startRun(taskKey, {
        idempotency_key: newIdempotencyKey(),
      })
      setRun(created)
      setDraftValues({})
      setText('')
      setFormStatus(null)
      toast.success('已建立新單')
    } catch {
      toast.error('建立新單失敗，請稍後再試')
    } finally {
      setBusy(false)
    }
  }, [taskKey])

  // Guarded action：只有表單 approved 才能匯出（後端亦強制）
  const handleExport = useCallback(async () => {
    if (!formInstanceId || formStatus !== 'approved') return
    setBusy(true)
    try {
      const { blob, filename } = await formsApi.exportSync(formInstanceId, 'pdf')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      toast.success('已匯出')
    } catch {
      toast.error('匯出失敗：表單可能尚未核准')
    } finally {
      setBusy(false)
    }
  }, [formInstanceId, formStatus])

  if (loading) {
    return <div className="p-6 text-muted">載入工作區…</div>
  }
  if (notFound || !definition) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <p className="text-xl font-bold text-ink">此任務不適用於你目前的職能</p>
        <p className="mt-2 text-muted">請切換職能，或聯絡管理員調整指派。</p>
        <button
          type="button"
          onClick={() => navigate('/job')}
          className="mt-4 rounded-xl border-2 border-line px-4 py-2"
        >
          回工作區
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4 overflow-y-auto p-4 pb-8">
      <header className="flex items-center gap-3">
        <button
          type="button"
          aria-label="回工作區"
          onClick={() => navigate('/job')}
          className="rounded-xl border-2 border-line p-2"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-ink">{definition.name}</h1>
          <p className="text-base text-muted">
            狀態：{TASK_STATUS_LABEL[run?.status ?? ''] ?? run?.status ?? '—'}　版本：{definition.version}
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* 左：對話／語音主路徑 */}
        <section
          aria-label="對話輸入"
          className="flex flex-col gap-3 rounded-2xl border-2 border-line bg-surface p-5"
        >
          <h2 className="text-lg font-bold text-ink">用說的或打字</h2>
          <PushToTalk
            moduleKey={definition.module_key ?? undefined}
            onResult={applyVoiceResult}
            onError={msg => toast.error(msg, { duration: 5000 })}
            disabled={busy || !editable}
          />
          <div className="flex gap-2">
            <input
              type="text"
              value={text}
              onChange={e => setText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleParseText()}
              placeholder="例如：幫台中精機報價，料號 P-100，兩百個"
              disabled={busy || !editable}
              className="min-h-12 flex-1 rounded-xl border-2 border-line bg-surface px-3 text-lg"
            />
            <button
              type="button"
              aria-label="送出文字"
              onClick={handleParseText}
              disabled={busy || !editable || !text.trim()}
              className="rounded-xl bg-accent px-4 text-white disabled:opacity-40"
            >
              <Send className="h-5 w-5" />
            </button>
          </div>
          {!editable && (
            <p className="text-sm text-muted">此任務已送出，欄位不可再編輯。</p>
          )}
        </section>

        {/* 右：欄位卡 */}
        <section
          aria-label="欄位確認"
          className="flex flex-col gap-3 rounded-2xl border-2 border-line bg-surface p-5"
        >
          <h2 className="text-lg font-bold text-ink">欄位確認</h2>
          {fields.length === 0 && (
            <p className="text-muted">此任務沒有需要確認的欄位。</p>
          )}
          {fields.map(f => {
            const value = values[f.name]
            const src = sources[f.name]
            const missing = missingRequired.includes(f.name)
            const calculated = Boolean(f.calculated)
            return (
              <div
                key={f.name}
                className={`rounded-xl border-2 p-3 ${
                  missing ? 'border-amber-400 bg-amber-50' : 'border-line'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-ink">
                    {f.label || f.name}
                    {f.required && <span className="text-red-500"> *</span>}
                  </span>
                  <span className="flex items-center gap-2 text-xs">
                    {src?.source && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-700">
                        {SOURCE_LABEL[src.source] ?? src.source}
                        {manualEdits.has(f.name) && src.source !== 'user' ? '・已修改' : ''}
                      </span>
                    )}
                    {typeof src?.confidence === 'number' && (
                      <span className="text-muted">
                        信心 {Math.round((src.confidence ?? 0) * 100)}%
                      </span>
                    )}
                  </span>
                </div>
                {f.type === 'select' && Array.isArray(f.options) ? (
                  <select
                    aria-label={f.label || f.name}
                    value={value === undefined || value === null ? '' : String(value)}
                    onChange={e => handleEditField(f.name, e.target.value)}
                    disabled={!editable || calculated}
                    className="mt-2 min-h-10 w-full rounded-lg border border-line bg-surface px-3 text-base disabled:opacity-60"
                  >
                    <option value="">請選擇</option>
                    {f.options.map(option => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label={f.label || f.name}
                    type={fieldInputType(f.type)}
                    step={f.type === 'number' || f.type === 'amount' ? 'any' : undefined}
                    value={value === undefined || value === null ? '' : String(value)}
                    onChange={e => handleEditField(f.name, e.target.value)}
                    onInput={e => {
                      if (f.type === 'date') handleEditField(f.name, e.currentTarget.value)
                    }}
                    disabled={!editable || calculated}
                    placeholder={calculated ? '送審時由系統自動計算' : missing ? '缺少此欄位，請補上' : ''}
                    className="mt-2 min-h-10 w-full rounded-lg border border-line bg-surface px-3 text-base disabled:opacity-60"
                  />
                )}
              </div>
            )
          })}
        </section>
      </div>

      {run?.status === 'waiting_review' && (
        <section className="rounded-2xl border-2 border-amber-400 bg-amber-50 p-4 text-amber-950">
          <p className="font-bold">已送出審核，暫時不能修改</p>
          <p className="mt-1 text-sm">核准後可在這裡匯出；若被退回，系統會顯示原因並讓你回到此單修正。</p>
        </section>
      )}

      {run?.status === 'rejected' && (
        <section className="rounded-2xl border-2 border-red-300 bg-red-50 p-4 text-red-950">
          <p className="font-bold">此單需要修正後重新送審</p>
          {review.reason ? <p className="mt-1 text-sm">審核意見：{review.reason}</p> : null}
        </section>
      )}

      {run?.status === 'approved' && (
        <section className="rounded-2xl border-2 border-green-300 bg-green-50 p-4 text-green-950">
          <p className="font-bold">此單已核准，可以匯出正式文件。</p>
        </section>
      )}

      <footer className="flex flex-wrap items-center gap-3">
        {editable && (
          <button
            type="button"
            onClick={handleSubmitReview}
            disabled={busy || missingRequired.length > 0}
            className="min-h-12 rounded-xl bg-accent px-6 text-lg font-bold text-white disabled:opacity-40"
          >
            送出審核
          </button>
        )}
        {formStatus && (
          <span
            className={`rounded-full px-3 py-1 text-sm font-medium ${
              formStatus === 'approved'
                ? 'bg-green-100 text-green-800'
                : formStatus === 'rejected'
                  ? 'bg-red-100 text-red-800'
                  : 'bg-amber-100 text-amber-800'
            }`}
          >
            表單狀態：{formStatus}
          </span>
        )}
        {formStatus === 'approved' && (
          <button
            type="button"
            onClick={handleExport}
            disabled={busy}
            className="min-h-12 rounded-xl bg-green-700 px-6 text-lg font-bold text-white disabled:opacity-40"
          >
            匯出 PDF
          </button>
        )}
        {run?.status === 'rejected' && (
          <button
            type="button"
            onClick={handleStartRevision}
            disabled={busy}
            className="flex min-h-12 items-center gap-2 rounded-xl bg-amber-600 px-5 text-lg font-bold text-white disabled:opacity-40"
          >
            <RotateCcw className="h-5 w-5" aria-hidden />
            開始修正
          </button>
        )}
        {['approved', 'executed'].includes(run?.status ?? '') && (
          <button
            type="button"
            onClick={handleStartNew}
            disabled={busy}
            className="flex min-h-12 items-center gap-2 rounded-xl border-2 border-line px-5 text-lg font-bold text-ink disabled:opacity-40"
          >
            <Plus className="h-5 w-5" aria-hidden />
            建立新單
          </button>
        )}
        {missingRequired.length > 0 && (
          <span className="text-sm text-amber-700">
            還缺 {missingRequired.length} 個必填欄位
          </span>
        )}
        {formKey && (
          <button
            type="button"
            onClick={() => {
              if (formInstanceId) {
                navigate(`/forms/instances/${formInstanceId}`)
                return
              }
              navigate(`/forms/${formKey}`, {
                state: { prefill: values, taskRunId: run?.id },
              })
            }}
            className="flex min-h-12 items-center gap-2 rounded-xl border-2 border-line px-4 text-base text-muted"
          >
            <ExternalLink className="h-4 w-4" />
            檢視完整表單（手動備援）
          </button>
        )}
      </footer>
    </div>
  )
}
