/**
 * 我的草稿／待審／已核准表單清單與詳情入口。
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import PageHeader from '../../components/PageHeader'
import { formsApi, type FormInstance } from '../../services/mka'

const TABS = [
  { key: 'draft,changes_requested,rejected', label: '待處理' },
  { key: 'pending_review,pending_approval', label: '待審' },
  { key: 'approved,finalized', label: '已核准' },
] as const

export default function FormInstancesPage() {
  const [tab, setTab] = useState<string>(TABS[0].key)
  const [rows, setRows] = useState<FormInstance[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    formsApi
      .listInstances(tab)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [tab])

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-3xl space-y-4">
        <PageHeader variant="section" title="我的表單" subtitle="草稿、待審與已核准單據；核准後可回到同一張單預覽與下載。" />
        <div className="flex gap-2">
          {TABS.map(t => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`rounded-lg px-4 py-2 text-sm font-medium ${
                tab === t.key ? 'bg-accent text-white' : 'bg-surface border border-line text-ink'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-7 w-7 animate-spin text-muted" />
          </div>
        ) : rows.length === 0 ? (
          <p className="text-muted">這個狀態目前沒有單據。</p>
        ) : (
          <ul className="space-y-2">
            {rows.map(row => (
              <li key={row.id}>
                <Link
                  to={`/forms/instances/${row.id}`}
                  className="flex items-center justify-between rounded-xl border border-line bg-surface px-4 py-3 hover:border-accent"
                >
                  <span>
                    <span className="block font-semibold text-ink">{row.form_key || '表單'}</span>
                    <span className="block text-sm text-muted">
                      {row.status} · v{row.record_version}
                      {row.module_key ? ` · ${row.module_key}` : ''}
                    </span>
                  </span>
                  <span className="text-sm text-accent">詳情 →</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
