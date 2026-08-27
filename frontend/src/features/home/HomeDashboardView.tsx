import { ArrowRight, BookOpen, CheckCircle2, Clock3, FileWarning, Inbox, MessageCircleQuestion, Plus, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'

import AsyncState from '../../components/AsyncState'
import type { HomeDashboardModel } from './useHomeDashboard'

function Stat({ label, value, tone = 'normal' }: { label: string; value: number; tone?: 'normal' | 'warning' | 'danger' }) {
  const colors = tone === 'danger' ? 'border-danger/30 bg-danger-soft text-danger' : tone === 'warning' ? 'border-highlight/30 bg-highlight-soft text-highlight' : 'border-line bg-surface text-ink'
  return <div className={`rounded-2xl border p-4 ${colors}`}><dt className="text-sm font-medium">{label}</dt><dd className="mt-1 text-3xl font-bold tabular-nums">{value}</dd></div>
}

export default function HomeDashboardView({ model }: { model: HomeDashboardModel }) {
  const todos = [
    model.canReview && model.stats.review > 0 ? { key: 'review', icon: Inbox, title: `${model.stats.review} 筆知識等待覆核`, to: '/knowledge/review', action: '開始覆核' } : null,
    model.canManage && model.stats.failed > 0 ? { key: 'failed', icon: FileWarning, title: `${model.stats.failed} 筆來源處理失敗`, to: '/knowledge/assets?status=failed', action: '查看問題' } : null,
    model.canUpload && model.stats.total === 0 ? { key: 'empty', icon: Plus, title: '新增第一筆企業知識', to: '/knowledge/new', action: '新增知識' } : null,
  ].filter((item): item is NonNullable<typeof item> => item !== null)
  return <div className="h-full overflow-y-auto">
    <header className="border-b border-line bg-wash/50"><div className="mx-auto flex max-w-5xl flex-wrap items-end justify-between gap-4 px-5 py-8"><div><h1 className="font-display text-3xl font-semibold text-ink">{model.title}</h1><p className="mt-2 text-base text-muted">{model.subtitle}</p></div><button type="button" className="btn-outline" onClick={() => void model.reload()} disabled={model.loading} aria-label="重新整理首頁"><RefreshCw className={`h-4 w-4 ${model.loading ? 'animate-spin' : ''}`} />重新整理</button></div></header>
    <div className="mx-auto max-w-5xl space-y-7 px-5 py-7">
      <AsyncState loading={model.loading} error={model.error} onRetry={model.reload}>
        <section aria-labelledby="personal-tasks"><h2 id="personal-tasks" className="text-xl font-semibold text-ink">我的待辦</h2>{todos.length ? <ul className="mt-3 grid gap-3 md:grid-cols-2">{todos.map(todo => <li key={todo.key} className="card flex items-center gap-3 p-4"><todo.icon className="h-6 w-6 shrink-0 text-highlight" /><span className="min-w-0 flex-1 font-medium text-ink">{todo.title}</span><Link to={todo.to} className="btn-outline shrink-0">{todo.action}<ArrowRight className="h-4 w-4" /></Link></li>)}</ul> : <div className="mt-3 flex items-center gap-3 rounded-2xl border border-success/30 bg-success-soft p-4 text-success"><CheckCircle2 className="h-6 w-6" /><p className="font-medium">目前沒有需要處理的知識工作。</p></div>}</section>
        <section aria-labelledby="knowledge-health"><h2 id="knowledge-health" className="text-xl font-semibold text-ink">知識健康與處理狀態</h2><dl className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-5"><Stat label="全部資產" value={model.stats.total} /><Stat label="可使用" value={model.stats.ready} /><Stat label="處理中" value={model.stats.processing} /><Stat label="待覆核" value={model.stats.review} tone={model.stats.review ? 'warning' : 'normal'} /><Stat label="失敗" value={model.stats.failed} tone={model.stats.failed ? 'danger' : 'normal'} /></dl></section>
        <section aria-labelledby="quick-start"><h2 id="quick-start" className="text-xl font-semibold text-ink">快速開始</h2><div className="mt-3 grid gap-3 sm:grid-cols-2"><Link to="/ask" className="card flex min-h-24 items-center gap-4 p-5 hover:border-accent"><MessageCircleQuestion className="h-8 w-8 text-accent" /><span><span className="block font-semibold text-ink">詢問企業知識</span><span className="text-sm text-muted">取得附證據的答案</span></span></Link><Link to="/knowledge/assets" className="card flex min-h-24 items-center gap-4 p-5 hover:border-accent"><BookOpen className="h-8 w-8 text-accent" /><span><span className="block font-semibold text-ink">瀏覽知識資產</span><span className="text-sm text-muted">文件、圖片、音訊與影片集中管理</span></span></Link></div></section>
        <section aria-labelledby="enabled-apps"><h2 id="enabled-apps" className="text-xl font-semibold text-ink">已啟用應用</h2>{model.applications.length ? <ul className="mt-3 grid gap-3 sm:grid-cols-2">{model.applications.map(app => <li key={app.to}><Link to={app.to} className="card flex min-h-20 items-center justify-between p-4 hover:border-accent"><span><span className="block font-semibold text-ink">{app.label}</span><span className="text-xs text-muted">{app.pack}</span></span><ArrowRight className="h-5 w-5 text-accent" /></Link></li>)}</ul> : <p className="mt-3 rounded-2xl border border-line bg-surface p-5 text-sm text-muted">目前未啟用額外職能應用；核心知識與問答仍可使用。</p>}</section>
        {model.stats.processing > 0 && <p className="flex items-center gap-2 text-sm text-muted"><Clock3 className="h-4 w-4" />內容處理會在背景繼續，完成後此頁會反映最新狀態。</p>}
      </AsyncState>
    </div>
  </div>
}
