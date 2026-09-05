import { RefreshCw } from 'lucide-react'

import { useAuth } from '../../auth'
import PageHeader from '../../components/PageHeader'

const STATUS_LABELS: Record<string, string> = {
  deployed: '已部署', not_deployed: '未部署', included: '方案內含', unavailable: '不可用',
  enabled: '已啟用', disabled: '未啟用', healthy: '正常', degraded: '降級',
  unknown: '待確認', allowed: '允許', denied: '未授權', not_applicable: '不適用',
}

const CAPABILITY_PRESENTATION: Record<string, { name: string; description: string }> = {
  enclave_base: { name: '企業知識核心', description: '來源匯入、治理、檢索與可追溯問答' },
  document_intelligence_pack: { name: '文件理解', description: '文件、表格與圖片的內容擷取與整理' },
  enterprise_connect_pack: { name: '企業系統串接', description: '連接既有企業系統與資料來源' },
  knowledge_compiler_pack: { name: '知識編譯', description: '將可確認內容整理成可治理的知識單元' },
  agent_automation_pack: { name: '自動化代理', description: '依規則執行可追蹤的例行工作' },
  mka: { name: '師傅經驗傳承', description: '保留現場經驗、操作脈絡與教育內容' },
  sales_quote: { name: '報價協作', description: '協助報價資料整理與追蹤' },
  incident_handover: { name: '現場異常交接', description: '保留事件脈絡、交接與後續追蹤' },
  quality_8d: { name: '8D 品質改善', description: '支援品質問題的結構化改善流程' },
  training_knowhow: { name: '教育訓練與技能傳承', description: '將經驗整理為訓練與作業參考' },
}

function presentationFor(key: string) {
  return CAPABILITY_PRESENTATION[key] || { name: '其他能力', description: '此項能力尚未提供租戶可讀說明' }
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
            <tbody className="divide-y divide-line">{entries.map(entry => { const present = presentationFor(entry.key); const pack = entry.pack_key ? presentationFor(entry.pack_key) : null; return <tr key={`${entry.pack_key || 'platform'}:${entry.key}`}>
              <th scope="row" className="px-4 py-4 font-semibold text-ink"><span>{present.name}</span><span className="mt-1 block text-xs font-normal text-muted">{present.description}</span>{pack && <span className="mt-1 block text-xs font-normal text-muted">所屬：{pack.name}</span>}<details className="mt-2 text-xs font-normal text-muted"><summary className="cursor-pointer">技術識別</summary><span className="mt-1 block font-mono">{entry.key}{entry.pack_key ? ` · ${entry.pack_key}` : ''}</span></details></th>
              <td className="px-4 py-4 text-muted">{entry.kind === 'platform_capability' ? '平台能力' : '應用模組'}</td>
              <td className="px-4 py-4"><Status value={entry.deployment_status} /></td><td className="px-4 py-4"><Status value={entry.entitlement_status} /></td><td className="px-4 py-4"><Status value={entry.runtime_status} /></td><td className="px-4 py-4"><Status value={entry.user_permission_status} /></td>
            </tr>})}</tbody>
          </table>
          {!entries.length && <p className="p-6 text-center text-sm text-muted">伺服器尚未提供能力目錄。</p>}
        </div>
        <p className="rounded-xl border border-line bg-wash/60 px-4 py-3 text-sm text-muted">「已部署」不代表貴公司已啟用；「已啟用」也不代表服務目前健康或您具有操作權限。未啟用的應用不會影響企業知識核心使用。</p>
      </div>
    </div>
  )
}
