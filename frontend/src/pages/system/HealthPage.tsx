/**
 * System health — integrity checks (UIUX §6.2)
 */
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, CircleAlert, PlugZap, RefreshCw, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { companyApi, kbApi, parseApiError, formatErrorWithTrace } from '../../api'
import AsyncState from '../../components/AsyncState'
import PageHeader from '../../components/PageHeader'
import type { ApiErrorInfo } from '../../api'

interface IntegrityReport {
  id: string
  status: string
  total_documents: number
  total_chunks: number
  orphan_chunks: number
  missing_embeddings: number
  failed_documents: number
  stale_documents: number
  started_at: string | null
}

interface ProviderConfiguration {
  role: string
  label: string
  provider: string
  model: string
  enabled: boolean
  credential_configured: boolean
}

interface ProviderProbeResult extends ProviderConfiguration {
  status: 'pass' | 'fail'
  elapsed_ms: number
  detail: string
}

export default function HealthPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [reports, setReports] = useState<IntegrityReport[]>([])
  const [providers, setProviders] = useState<ProviderConfiguration[]>([])
  const [providerResults, setProviderResults] = useState<ProviderProbeResult[]>([])
  const [probing, setProbing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [integrityReports, providerHealth] = await Promise.all([
        kbApi.listIntegrityReports(5),
        companyApi.providerHealth(),
      ])
      setReports(integrityReports)
      setProviders(providerHealth.providers || [])
    } catch (err) {
      setError(parseApiError(err, '無法載入健康資料'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleIntegrity = async () => {
    try {
      await kbApi.triggerIntegrityCheck()
      toast.success('完整性檢查已排程')
      setTimeout(load, 3000)
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '排程失敗')))
    }
  }

  const handleProviderProbe = async () => {
    setProbing(true)
    try {
      const report = await companyApi.probeProviderHealth()
      setProviderResults(report.results || [])
      if (report.status === 'pass') {
        toast.success(`外部服務實測 ${report.passed}/${report.total} 通過`)
      } else {
        toast.error(`外部服務實測僅 ${report.passed}/${report.total} 通過`)
      }
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '外部服務實測失敗')))
    } finally {
      setProbing(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <PageHeader
          variant="section"
          title="健康"
          subtitle="確認外部 AI 服務、文件與可搜尋索引都能實際運作。"
          actions={(
            <div className="flex gap-2">
              <button
                type="button"
                onClick={load}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-muted hover:text-ink"
                aria-label="重新整理"
              >
                <RefreshCw className="h-4 w-4" aria-hidden /> 重新整理
              </button>
              <button
                type="button"
                onClick={handleIntegrity}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm text-white hover:bg-accent-hover"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden /> 立即檢查
              </button>
            </div>
          )}
        />

        <section className="rounded-xl border border-line bg-surface p-4 md:p-5" aria-labelledby="provider-health-heading">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="provider-health-heading" className="flex items-center gap-2 font-semibold text-ink">
                <PlugZap className="h-5 w-5 text-accent" aria-hidden /> 外部 AI 服務
              </h2>
              <p className="mt-1 text-sm text-muted">
                顯示目前實際採用的服務。按下實際檢查才會送出少量測試資料並產生 API 用量。
              </p>
            </div>
            <button
              type="button"
              onClick={handleProviderProbe}
              disabled={probing || loading}
              className="inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${probing ? 'animate-spin' : ''}`} aria-hidden />
              {probing ? '檢查中…' : '實際檢查 Provider'}
            </button>
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            {providers.map(provider => {
              const result = providerResults.find(item => item.role === provider.role)
              const configured = provider.enabled && provider.credential_configured
              return (
                <div key={provider.role} className="rounded-lg border border-line px-3 py-3 text-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium text-ink">{provider.label}</div>
                      <div className="mt-1 truncate text-xs text-muted" title={`${provider.provider} · ${provider.model}`}>
                        {provider.provider}{provider.model ? ` · ${provider.model}` : ''}
                      </div>
                    </div>
                    {result ? (
                      <span className={`inline-flex items-center gap-1 text-xs font-medium ${result.status === 'pass' ? 'text-success' : 'text-danger'}`}>
                        {result.status === 'pass' ? <CheckCircle2 className="h-4 w-4" aria-hidden /> : <CircleAlert className="h-4 w-4" aria-hidden />}
                        {result.status === 'pass' ? '實測通過' : '實測失敗'}
                      </span>
                    ) : (
                      <span className={`text-xs ${configured ? 'text-muted' : 'text-danger'}`}>
                        {configured ? '尚未實測' : '未完成設定'}
                      </span>
                    )}
                  </div>
                  {result && (
                    <div className={`mt-2 text-xs ${result.status === 'pass' ? 'text-muted' : 'text-danger'}`}>
                      {result.detail} · {(result.elapsed_ms / 1000).toFixed(1)} 秒
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>

        <AsyncState loading={loading} error={error} onRetry={load} empty={!loading && !error && reports.length === 0} emptyTitle="尚無掃描報告" emptyDescription="執行檢查可確認文件與可搜尋索引是否一致。" emptyActionLabel="立即檢查" onEmptyAction={handleIntegrity}>
          <div className="space-y-2">
            {reports.map(r => (
              <div key={r.id} className="rounded-xl border border-line bg-surface p-4 text-sm">
                <div className="flex justify-between text-xs text-muted">
                  <span>{r.status === 'completed' ? '完成' : r.status}</span>
                  <span>{r.started_at ? new Date(r.started_at).toLocaleString() : ''}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
                  <div>文件 <strong>{r.total_documents}</strong></div>
                  <div>處理片段 <strong>{r.total_chunks}</strong></div>
                  <div className={r.orphan_chunks > 0 ? 'text-danger' : ''} title="索引中有片段但找不到對應文件">
                    無主片段 <strong>{r.orphan_chunks}</strong>
                  </div>
                  <div className={r.missing_embeddings > 0 ? 'text-danger' : ''} title="文件尚未完成可搜尋索引">
                    未完成索引 <strong>{r.missing_embeddings}</strong>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </AsyncState>
      </div>
    </div>
  )
}
