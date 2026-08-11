/**
 * FormPage — 通用 Fixed Form 流程（MKA 表單引擎前端）。
 *
 * 支援所有後端已註冊的表單：報價單、採購單、異常回報、交接班紀錄…
 * 流程：語音/手動填值 → 檢查（建檔＋計算＋驗證）→ 送出審核 → 核准後匯出。
 * 設計對象：傳產業務/現場人員——大欄位、大按鈕、錯誤逐條列出、
 * 每個狀態都說明「現在在哪一步、下一步是什麼」。
 */
import { useEffect, useMemo, useState, useCallback } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Calculator,
  Send,
  FileDown,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import SceneContextBanner from '../../components/mka/SceneContextBanner'
import {
  downloadBlob,
  formsApi,
  type FormDefinition,
  type FormFieldSpec,
  type FormInstance,
  type SceneContext,
} from '../../services/mka'

type FormState = 'loading' | 'error' | 'editing' | 'checking' | 'checked' | 'submitting' | 'submitted'

const NUMERIC_TYPES = new Set(['number', 'amount'])

function fieldInputMode(type?: string) {
  if (type === 'amount') return 'decimal' as const
  if (type === 'number') return 'numeric' as const
  return 'text' as const
}

export default function FormPage() {
  const { formKey = 'quote' } = useParams<{ formKey: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const navState = useMemo(
    () =>
      ((location.state || {}) as {
        prefill?: Record<string, string>
        transcript?: string
        scene?: SceneContext | null
      }),
    [location.state],
  )

  const [state, setState] = useState<FormState>('loading')
  const [schema, setSchema] = useState<FormDefinition | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [instance, setInstance] = useState<FormInstance | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [exporting, setExporting] = useState(false)
  const scene = navState.scene ?? null

  // schema 端點會把 json_schema 展平覆蓋 name，故優先取 description（中文表單名）
  const desc = schema?.json_schema?.description
  const formTitle = (typeof desc === 'string' && desc) || schema?.name || '表單'

  const loadSchema = useCallback(() => {
    setState('loading')
    setInstance(null)
    setErrors([])
    formsApi
      .schema(formKey)
      .then(def => {
        setSchema(def)
        const initial: Record<string, string> = {}
        const fields = def.fields ?? def.json_schema?.fields ?? []
        const scenePrefill = (navState.scene || {}) as Record<string, string>
        for (const f of fields) {
          const pre = navState.prefill?.[f.name] ?? scenePrefill[f.name]
          initial[f.name] = pre !== undefined && pre !== null && pre !== ''
            ? String(pre)
            : f.default != null
              ? String(f.default)
              : ''
        }
        setValues(initial)
        setState('editing')
      })
      .catch(() => {
        toast.error('表單格式載入失敗')
        setSchema(null)
        setState('error')
      })
  }, [formKey, navState.prefill, navState.scene])

  useEffect(() => {
    loadSchema()
  }, [loadSchema])

  const fields: FormFieldSpec[] = useMemo(
    () => (schema?.fields ?? schema?.json_schema?.fields ?? []) as FormFieldSpec[],
    [schema],
  )

  const provenance = useMemo(() => {
    if (!navState.transcript) return {}
    const prov: Record<string, string> = {}
    for (const key of Object.keys(navState.prefill || {})) {
      prov[key] = `語音輸入：${navState.transcript}`
    }
    return prov
  }, [navState])

  const setValue = (name: string, value: string) => {
    setValues(prev => ({ ...prev, [name]: value }))
    setErrors([])
  }

  const typedValues = () => {
    const out: Record<string, unknown> = {}
    for (const f of fields) {
      const raw = (values[f.name] ?? '').trim()
      if (raw === '') continue
      if (NUMERIC_TYPES.has(String(f.type))) {
        const n = Number(raw)
        out[f.name] = Number.isFinite(n) ? n : raw
      } else {
        out[f.name] = raw
      }
    }
    return out
  }

  const handleCheck = async () => {
    setState('checking')
    setErrors([])
    try {
      let inst = instance
      if (!inst) {
        inst = await formsApi.createInstance(formKey, typedValues(), provenance, formKey, scene)
      } else {
        inst = await formsApi.patchInstance(inst.id, inst.record_version, typedValues(), provenance)
      }
      inst = await formsApi.calculate(inst.id, inst.record_version)
      inst = await formsApi.validate(inst.id, inst.record_version)
      setInstance(inst)
      const validationErrors = (inst.validation_result?.errors as string[]) || []
      setErrors(validationErrors)
      setState('checked')
      if (validationErrors.length === 0) {
        toast.success('檢查通過，可以送出審核')
      }
    } catch (err) {
      setState(instance ? 'checked' : 'editing')
      const msg = (err as { apiError?: { message?: string } })?.apiError?.message
      toast.error(msg || '檢查失敗，請確認網路後再試一次')
    }
  }

  const handleSubmit = async () => {
    if (!instance) return
    setState('submitting')
    try {
      const { approval } = await formsApi.submit(
        instance.id,
        instance.record_version,
        `${formKey}-submit-${instance.id}`,
      )
      setInstance(prev => (prev ? { ...prev, status: 'pending_review' } : prev))
      setState('submitted')
      toast.success(`已送出審核（單號 ${approval.id.slice(0, 8)}…）`)
    } catch (err) {
      setState('checked')
      const msg = (err as { apiError?: { message?: string } })?.apiError?.message
      toast.error(msg || '送出失敗，請再試一次')
    }
  }

  const handleExport = async (format: 'pdf' | 'docx' | 'xlsx' | 'md') => {
    if (!instance) return
    setExporting(true)
    try {
      const { blob, filename } = await formsApi.exportSync(instance.id, format)
      downloadBlob(blob, filename)
      toast.success('已下載 ' + filename)
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        toast.error('這張單還沒核准，核准後才能匯出正式文件')
      } else {
        toast.error('匯出失敗，請再試一次')
      }
    } finally {
      setExporting(false)
    }
  }

  if (state === 'loading') {
    return (
      <div className="flex h-full items-center justify-center" role="status">
        <Loader2 className="h-10 w-10 animate-spin text-accent" aria-label="載入中" />
      </div>
    )
  }

  if (state === 'error') {
    return (
      <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center gap-4 p-6 text-center">
        <AlertCircle className="h-12 w-12 text-danger" aria-hidden />
        <div>
          <p className="text-lg font-semibold text-ink">無法載入這張表單</p>
          <p className="mt-1 text-sm text-muted">請檢查網路連線後再試，或先回現場作業。</p>
        </div>
        <div className="flex flex-wrap justify-center gap-3">
          <button type="button" onClick={loadSchema} className="btn-primary">
            重試
          </button>
          <button type="button" onClick={() => navigate('/job')} className="btn-outline">
            回現場作業
          </button>
        </div>
      </div>
    )
  }

  if (!schema) {
    return null
  }

  const calc = (instance?.calculation_snapshot || {}) as Record<string, unknown>
  const readOnly = state === 'submitted'
  const approved = instance?.status === 'approved'

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col gap-4 overflow-y-auto p-4 pb-8">
      <header className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/job')}
          aria-label="回上一頁"
          className="rounded-xl border-2 border-line p-3 text-muted hover:bg-wash"
        >
          <ArrowLeft className="h-6 w-6" aria-hidden />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-ink">{formTitle}</h1>
          <p className="text-base text-muted">
            {state === 'submitted'
              ? '已送出，等主管核准後就能匯出正式文件。'
              : '填好後按「檢查」，沒問題再送出給主管審核。'}
          </p>
        </div>
      </header>

      {scene && <SceneContextBanner scene={scene} />}

      {navState.transcript && (
        <p className="rounded-xl bg-accent/10 px-4 py-3 text-base text-ink">
          <span className="font-bold text-accent">語音帶入：</span>
          {navState.transcript}
        </p>
      )}

      <section aria-label="表單欄位" className="flex flex-col gap-4 rounded-2xl border-2 border-line bg-surface p-5">
        {fields.map(f => {
          const id = `form-field-${f.name}`
          const common =
            'min-h-16 w-full rounded-xl border-2 border-line bg-wash px-4 text-xl text-ink focus:border-accent focus:outline-none disabled:opacity-60'
          return (
            <div key={f.name}>
              <label htmlFor={id} className="mb-1 block text-lg font-semibold text-ink">
                {f.label || f.name}
                {f.required && <span className="ml-1 text-danger">*</span>}
              </label>
              {f.type === 'select' && Array.isArray(f.options) ? (
                <select
                  id={id}
                  value={values[f.name] ?? ''}
                  onChange={e => setValue(f.name, e.target.value)}
                  disabled={readOnly}
                  className={common}
                >
                  <option value="">請選擇</option>
                  {f.options.map(opt => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : (
                <input
                  id={id}
                  type="text"
                  inputMode={fieldInputMode(String(f.type))}
                  value={values[f.name] ?? ''}
                  onChange={e => setValue(f.name, e.target.value)}
                  disabled={readOnly}
                  placeholder={typeof f.description === 'string' ? f.description : ''}
                  className={common}
                />
              )}
            </div>
          )
        })}
      </section>

      {Object.keys(calc).length > 0 && (
        <section aria-label="計算結果" className="rounded-2xl border-2 border-accent/40 bg-accent/5 p-5">
          <h2 className="mb-2 flex items-center gap-2 text-lg font-bold text-ink">
            <Calculator className="h-6 w-6 text-accent" aria-hidden />
            系統計算結果
          </h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(calc).map(([key, value]) => (
              <div key={key} className="flex justify-between text-lg">
                <dt className="text-muted">{key}</dt>
                <dd className="font-mono font-semibold text-ink">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {errors.length > 0 && (
        <section aria-label="錯誤清單" className="rounded-2xl border-2 border-danger/50 bg-red-50 p-5">
          <h2 className="mb-2 flex items-center gap-2 text-lg font-bold text-danger">
            <AlertCircle className="h-6 w-6" aria-hidden />
            有 {errors.length} 個地方要修正
          </h2>
          <ul className="list-disc space-y-1 pl-6 text-lg text-red-900">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </section>
      )}

      {state !== 'submitted' && (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            onClick={handleCheck}
            disabled={state === 'checking'}
            className={clsx(
              'flex min-h-16 items-center justify-center gap-2 rounded-xl border-2 border-accent text-xl font-bold text-accent',
              'hover:bg-accent/10 active:scale-[0.98] disabled:opacity-50',
            )}
          >
            {state === 'checking' ? (
              <Loader2 className="h-7 w-7 animate-spin" aria-hidden />
            ) : (
              <Calculator className="h-7 w-7" aria-hidden />
            )}
            {state === 'checking' ? '檢查中…' : '檢查'}
          </button>

          <button
            type="button"
            onClick={handleSubmit}
            disabled={state !== 'checked' || errors.length > 0}
            className={clsx(
              'flex min-h-16 items-center justify-center gap-2 rounded-xl text-xl font-bold text-white',
              'bg-accent hover:bg-accent-hover active:scale-[0.98] disabled:opacity-40',
            )}
          >
            <Send className="h-7 w-7" aria-hidden />
            送出給主管審核
          </button>
          {state === 'editing' && (
            <p className="text-center text-base text-muted">先按「檢查」才能送出</p>
          )}
        </div>
      )}

      {state === 'submitted' && (
        <section aria-label="送審結果" className="flex flex-col gap-3 rounded-2xl border-2 border-accent bg-accent/5 p-5">
          <p className="flex items-center gap-2 text-xl font-bold text-accent">
            <CheckCircle2 className="h-7 w-7" aria-hidden />
            已送出審核
          </p>
          <p className="text-lg text-ink">
            主管核准後，回到這張單就能下載 PDF / Word / Excel 正式文件。
          </p>
          {approved && (
            <div className="grid grid-cols-3 gap-2">
              {(['pdf', 'docx', 'xlsx'] as const).map(fmt => (
                <button
                  key={fmt}
                  type="button"
                  disabled={exporting}
                  onClick={() => void handleExport(fmt)}
                  className="flex min-h-14 items-center justify-center gap-1 rounded-xl bg-accent text-lg font-bold text-white hover:bg-accent-hover disabled:opacity-50"
                >
                  <FileDown className="h-5 w-5" aria-hidden />
                  {fmt.toUpperCase()}
                </button>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={() => navigate('/job')}
            className="min-h-14 rounded-xl border-2 border-line text-lg font-bold text-muted hover:bg-wash"
          >
            回首頁
          </button>
        </section>
      )}
    </div>
  )
}
