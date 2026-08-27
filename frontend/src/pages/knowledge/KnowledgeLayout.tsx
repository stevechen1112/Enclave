import { Navigate, Outlet, useLocation } from 'react-router-dom'
import SubNav from '../../components/SubNav'
import DomainChrome from '../../components/DomainChrome'
import { KNOWLEDGE_SUBNAV } from '../../navigation/capabilities'

export default function KnowledgeLayout() {
  const { pathname } = useLocation()
  if (pathname === '/knowledge' || pathname === '/knowledge/') {
    return <Navigate to="/knowledge/assets" replace />
  }
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <DomainChrome
        title="知識"
        subtitle="任何來源都能在同一處加入、處理、審核、發布與追溯。"
      />
      <SubNav items={KNOWLEDGE_SUBNAV} />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  )
}
