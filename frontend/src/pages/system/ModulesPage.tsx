/**
 * System modules — 產品能力包 + 職能模組管理（啟停／授權狀態）
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BookOpen, CheckCircle2, Loader2, Network, XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuth } from '../../auth'
import api from '../../api'
import ModuleStatus, { type ModuleStatusKind } from '../../components/ModuleStatus'
import PageHeader from '../../components/PageHeader'

type SurfaceStatus = {
  pack?: string
  surface?: string
  status?: string
  web_ui?: boolean
  production_write_path?: boolean
  message?: string
}

type JobModuleRow = {
  module_key: string
  name?: string
  description?: string
  status?: string
  version?: string
  allowed_roles?: string[]
  form_definition_ids?: string[]
}

type GatewayHealth = {
  gateway?: string
  packs?: Record<string, {
    enabled?: boolean
    available?: boolean
    state?: string
  }>
}

export default function ModulesPage() {
  const { experience, refreshExperience } = useAuth()
  const [wiki, setWiki] = useState<SurfaceStatus | null>(null)
  const [graph, setGraph] = useState<SurfaceStatus | null>(null)
  const [jobModules, setJobModules] = useState<JobModuleRow[]>([])
  const [gatewayHealth, setGatewayHealth] = useState<GatewayHealth | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        await refreshExperience()
        const [w, g, jm, gh] = await Promise.allSettled([
          api.get<SurfaceStatus>('/wiki/product-status'),
          api.get<SurfaceStatus>('/graph/product-status'),
          api.get<JobModuleRow[]>('/job-modules'),
          api.get<GatewayHealth>('/gateway/health'),
        ])
        if (cancelled) return
        if (w.status === 'fulfilled') setWiki(w.value.data)
        if (g.status === 'fulfilled') setGraph(g.value.data)
        if (jm.status === 'fulfilled') {
          const data = jm.value.data as JobModuleRow[] | { modules?: JobModuleRow[] }
          setJobModules(Array.isArray(data) ? data : data.modules || [])
        } else {
          const fromBootstrap = (experience?.job_modules || []) as JobModuleRow[]
          setJobModules(fromBootstrap)
        }
        if (gh.status === 'fulfilled') setGatewayHealth(gh.value.data)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [refreshExperience, experience?.job_modules])

  const toggleModule = async (moduleKey: string, enable: boolean) => {
    try {
      if (enable) {
        await api.post(`/job-modules/admin/${moduleKey}/enable`, {})
      } else {
        await api.delete(`/job-modules/admin/${moduleKey}/disable`)
      }
      toast.success(enable ? `已啟用 ${moduleKey}` : `已停用 ${moduleKey}`)
      await refreshExperience()
      const { data } = await api.get<JobModuleRow[] | { modules?: JobModuleRow[] }>('/job-modules')
      setJobModules(Array.isArray(data) ? data : data.modules || [])
    } catch {
      toast.error('模組啟停失敗')
    }
  }

  if (loading && !experience) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-7 w-7 animate-spin text-muted" />
      </div>
    )
  }

  const packs = experience?.packs || {}
  const packEntries = Object.entries(packs).filter(([k]) => k !== 'certified_connectors')
  const certified = packs.certified_connectors

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <PageHeader
          variant="section"
          title="產品能力包與職能模組"
          subtitle={
            experience?.product?.maturity_label
              ? `上半：平台能力包；下半：製造業職能模組（啟停／職能授權／版型狀態）。成熟度：${experience.product.maturity_label}`
              : '核心永遠可用；可選包關閉時入口會隱藏，不會假裝功能正常。'
          }
        />

        <h2 className="text-lg font-semibold text-ink">產品能力包</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {packEntries.map(([key, pack]) => {
            const verified = gatewayHealth?.packs?.[key]
            const rawState = verified?.state || pack.state || (pack.enabled ? 'unavailable' : 'disabled')
            const status: ModuleStatusKind = (
              ['enabled', 'disabled', 'degraded', 'unavailable'].includes(rawState)
                ? rawState
                : 'unavailable'
            ) as ModuleStatusKind
            return (
              <ModuleStatus
                key={key}
                label={pack.label || key}
                code={key}
                status={status}
                detail={
                  verified?.state === 'enabled'
                    ? '執行服務已通過即時健康探測'
                    : verified?.enabled
                      ? '已設定，但執行服務目前不可用或降級'
                      : pack.message
                }
              />
            )
          })}
        </div>

        {certified && (
          <section className="rounded-xl border border-line bg-surface p-5 space-y-3">
            <h3 className="font-medium text-ink">已認證來源類型</h3>
            <p className="text-sm text-muted">
              V1 僅 <strong className="text-ink">NAS／本機路徑（nas_smb）</strong> 已認證。
              SharePoint、Google Drive 需真實 OAuth 後才算完成，不在建立選單中假裝可用。
            </p>
            <div className="flex flex-wrap gap-2 text-xs">
              {(certified.items || []).map(i => (
                <span key={i} className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-800">已認證：{i}</span>
              ))}
              {(certified.not_certified || []).map(i => (
                <span key={i} className="rounded-full bg-wash px-2.5 py-1 text-muted">尚未認證：{i}</span>
              ))}
            </div>
            <Link to="/knowledge/sources" className="inline-block text-sm text-accent underline">
              管理知識來源
            </Link>
          </section>
        )}

        <section className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-line bg-surface p-5">
            <div className="flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-accent" />
              <h3 className="font-medium text-ink">Wiki</h3>
              <span className="rounded-full bg-wash px-2 py-0.5 text-[10px] text-muted">僅後端／試用</span>
            </div>
            <p className="mt-3 text-sm text-muted">{wiki?.message || '無法讀取狀態（可能未啟用 Knowledge Compiler）'}</p>
            <p className="mt-2 text-xs text-muted">無完整 Web 編輯器；不應期待介面內建 Wiki 產品。</p>
          </div>
          <div className="rounded-xl border border-line bg-surface p-5">
            <div className="flex items-center gap-2">
              <Network className="h-5 w-5 text-accent" />
              <h3 className="font-medium text-ink">Graph</h3>
              <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[10px] text-rose-700">無生產寫入</span>
            </div>
            <p className="mt-3 text-sm text-muted">{graph?.message || '無法讀取狀態'}</p>
            {graph?.production_write_path === false && (
              <p className="mt-2 text-xs text-rose-700">正式環境不應期待 Graph 實體有資料。</p>
            )}
          </div>
        </section>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-ink">職能模組</h2>
            <button
              type="button"
              className="text-sm text-accent underline"
              onClick={async () => {
                try {
                  await api.post('/job-roles/seed')
                  toast.success('已種子化五個正式模組與預設職能')
                  await refreshExperience()
                } catch {
                  toast.error('種子化失敗')
                }
              }}
            >
              種子化正式模組
            </button>
          </div>
          <div className="grid gap-3">
            {(jobModules.length ? jobModules : (experience?.job_modules as JobModuleRow[] | undefined) || []).map(m => (
              <div key={m.module_key} className="rounded-xl border border-line bg-surface p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="font-medium text-ink">{m.name || m.module_key}</h3>
                    <p className="mt-1 text-sm text-muted">{m.description || ''}</p>
                    <p className="mt-2 text-xs text-muted">
                      status={m.status || 'unknown'} · roles={(m.allowed_roles || []).join(', ') || '—'} ·
                      forms={(m.form_definition_ids || []).join(', ') || '—'}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="rounded-lg border border-line px-3 py-1.5 text-sm"
                      onClick={() => toggleModule(m.module_key, true)}
                    >
                      啟用
                    </button>
                    <button
                      type="button"
                      className="rounded-lg border border-line px-3 py-1.5 text-sm"
                      onClick={() => toggleModule(m.module_key, false)}
                    >
                      停用
                    </button>
                  </div>
                </div>
              </div>
            ))}
            {!jobModules.length && !(experience?.job_modules || []).length && (
              <p className="text-sm text-muted">尚無職能模組資料，請先種子化。</p>
            )}
          </div>
        </section>

        {experience?.features && (
          <section className="rounded-xl border border-line bg-surface p-5">
            <h3 className="font-medium text-ink">產品表面誠實清單</h3>
            <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
              {[
                ['sso', '企業 SSO 登入'],
                ['wiki_editor', 'Wiki 編輯 UI'],
                ['graph_production_write', 'Graph 生產寫入'],
                ['mobile_ga', 'Mobile GA'],
                ['sharepoint_certified', 'SharePoint 已認證'],
                ['google_drive_certified', 'Google Drive 已認證'],
              ].map(([key, label]) => (
                <li key={key} className="flex items-center gap-2 text-muted">
                  {experience.features[key] ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <XCircle className="h-4 w-4 text-muted" />
                  )}
                  {label}
                  <span className="text-xs">
                    {experience.features[key] ? '可用' : '未提供／未認證'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
