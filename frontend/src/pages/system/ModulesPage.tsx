import { RefreshCw } from 'lucide-react'

import { useAuth } from '../../auth'
import PageHeader from '../../components/PageHeader'

const STATUS_LABELS: Record<string, string> = {
  deployed: '已部署', not_deployed: '未部署', included: '方案內含', unavailable: '不可用',
  enabled: '已啟用', disabled: '未啟用', healthy: '正常', degraded: '降級',
  unknown: '待確認', allowed: '允許', denied: '未授權', not_applicable: '不適用',
}

function Status({ value }: { value: string }) {
  const positive = ['deployed', 'included', 'enabled', 'healthy', 'allowed'].includes(value)
  const negative = ['not_deployed', 'unavailable', 'disabled', 'denied'].includes(value)
  const tone = positive
    ? 'border-success/30 bg-success-soft text-success'
    : negative ? 'border-line bg-wash text-muted' : 'border-highlight/30 bg-highlight-soft text-highlight'
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${tone}`}>{STATUS_LABELS[value] || value}</span>
}

export default function ModulesPage() {
  const { experience, refreshExperience, experienceStatus } = useAuth()
  const entries = experience?.capability_catalog || []
  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <PageHeader
          variant="section"
          title="能力與應用目錄"
          subtitle="部署、租戶方案、執行健康與目前使用者權限是四個不同狀態；本頁顯示伺服器實際判定，不在瀏覽器推測。"
          actions={<button type="button" className="btn-outline" onClick={() => void refreshExperience()} disabled={experienceStatus === 'loading'}><RefreshCw className={`h-4 w-4 ${experienceStatus === 'loading' ? 'animate-spin' : ''}`} />重新整理</button>}
        />
        <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
          <table className="w-full min-w-[760px] text-left text-sm">
            <caption className="sr-only">平台能力及應用包的四維狀態</caption>
            <thead className="border-b border-line bg-wash/70 text-muted"><tr>
              <th scope="col" className="px-4 py-3 font-medium">能力／應用</th><th scope="col" className="px-4 py-3 font-medium">類型</th><th scope="col" className="px-4 py-3 font-medium">部署</th><th scope="col" className="px-4 py-3 font-medium">租戶授權</th><th scope="col" className="px-4 py-3 font-medium">執行狀態</th><th scope="col" className="px-4 py-3 font-medium">我的權限</th>
            </tr></thead>
            <tbody className="divide-y divide-line">{entries.map(entry => <tr key={`${entry.pack_key || 'platform'}:${entry.key}`}>
              <th scope="row" className="px-4 py-4 font-semibold text-ink">{entry.key}{entry.pack_key && <span className="mt-1 block text-xs font-normal text-muted">{entry.pack_key}</span>}</th>
              <td className="px-4 py-4 text-muted">{entry.kind === 'platform_capability' ? '平台能力' : '應用模組'}</td>
              <td className="px-4 py-4"><Status value={entry.deployment_status} /></td><td className="px-4 py-4"><Status value={entry.entitlement_status} /></td><td className="px-4 py-4"><Status value={entry.runtime_status} /></td><td className="px-4 py-4"><Status value={entry.user_permission_status} /></td>
            </tr>)}</tbody>
          </table>
          {!entries.length && <p className="p-6 text-center text-sm text-muted">伺服器尚未提供能力目錄。</p>}
        </div>
        <p className="rounded-xl border border-line bg-wash/60 px-4 py-3 text-sm text-muted">「已部署」不代表租戶已購買或啟用；「已啟用」也不代表目前服務健康或您具有操作權限。</p>
      </div>
    </div>
  )
}
