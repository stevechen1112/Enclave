import { Navigate, Outlet, useLocation } from 'react-router-dom'
import SubNav from '../../components/SubNav'
import DomainChrome from '../../components/DomainChrome'
import { KNOWLEDGE_SUBNAV } from '../../navigation/capabilities'

export default function KnowledgeLayout() {
  const { pathname } = useLocation()
  if (pathname === '/knowledge' || pathname === '/knowledge/') {
    return <Navigate to="/knowledge/documents" replace />
  }
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <DomainChrome
        title="知識"
        subtitle="文件進得來、審得過、問得到、撤得掉 — 完整生命週期都在這裡完成。"
      />
      <SubNav items={KNOWLEDGE_SUBNAV} />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  )
}
