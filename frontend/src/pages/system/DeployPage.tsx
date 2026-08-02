/**
 * System deploy mode (UIUX §6.2) — moved from governance organization
 */
import { useCallback, useEffect, useState } from 'react'
import { Cloud, Cpu } from 'lucide-react'
import { companyApi, parseApiError, formatErrorWithTrace } from '../../api'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'
import type { ApiErrorInfo } from '../../api'
import clsx from 'clsx'

export default function DeployPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState<'gpu' | 'nogpu'>('nogpu')
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setMsg('')
    try {
      const data = await companyApi.getDeploymentMode()
      setMode((data?.mode || 'nogpu') as 'gpu' | 'nogpu')
    } catch (err) {
      setError(parseApiError(err, '無法讀取部署模式'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const switchMode = async (next: 'gpu' | 'nogpu') => {
    if (next === mode) return
    setSaving(true)
    setMsg('')
    try {
      await companyApi.setDeploymentMode(next)
      setMode(next)
      setMsg(`已切換為「${next === 'gpu' ? '本機加速' : '雲端推論'}」模式（下一次請求立即生效）`)
    } catch (err) {
      setMsg(formatErrorWithTrace(parseApiError(err, '切換失敗')))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <PageHeader
          variant="section"
          title="部署"
          subtitle="選擇固定推論模式；不提供自由選模型，避免誤設。此設定會影響資料是否離開本機。"
        />

        <AsyncState loading={loading} error={error} onRetry={load}>
          <div className="rounded-xl border border-line bg-surface p-5 space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <button
                type="button"
                disabled={saving}
                onClick={() => switchMode('nogpu')}
                className={clsx(
                  'rounded-xl border p-4 text-left transition min-h-11 disabled:opacity-60',
                  mode === 'nogpu' ? 'border-accent bg-accent/5' : 'border-line hover:bg-wash',
                )}
              >
                <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Cloud className="h-4 w-4" aria-hidden /> 雲端推論
                </div>
                <p className="mt-2 text-xs text-muted">
                  使用雲端模型組合。登入後可能顯示「資料會送出本機做推論」提示。
                </p>
              </button>

              <button
                type="button"
                disabled={saving}
                onClick={() => switchMode('gpu')}
                className={clsx(
                  'rounded-xl border p-4 text-left transition min-h-11 disabled:opacity-60',
                  mode === 'gpu' ? 'border-accent bg-accent/5' : 'border-line hover:bg-wash',
                )}
              >
                <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Cpu className="h-4 w-4" aria-hidden /> 本機加速
                </div>
                <p className="mt-2 text-xs text-muted">
                  內部改寫／掃描與索引處理走本機固定模型組合，適合有加速硬體的環境。
                </p>
              </button>
            </div>
            {msg && (
              <div className="rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-sm text-ink">{msg}</div>
            )}
          </div>
        </AsyncState>
      </div>
    </div>
  )
}
