import { Navigate, Outlet, useLocation } from 'react-router-dom'
import SubNav from '../../components/SubNav'
import DomainChrome from '../../components/DomainChrome'
import { SYSTEM_SUBNAV } from '../../navigation/capabilities'

export default function SystemLayout() {
  const { pathname } = useLocation()
  if (pathname === '/system' || pathname === '/system/') {
    return <Navigate to="/system/modules" replace />
  }
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <DomainChrome
        title="系統"
        subtitle="能力包、健康、備份與部署 — 營運人員的基礎設施面板。"
      />
      <SubNav items={SYSTEM_SUBNAV} />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  )
}
