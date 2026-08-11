import { Navigate, Outlet, useLocation } from 'react-router-dom'
import SubNav from '../../components/SubNav'
import DomainChrome from '../../components/DomainChrome'
import { GOVERNANCE_SUBNAV } from '../../navigation/capabilities'

export default function GovernanceLayout() {
  const { pathname } = useLocation()
  if (pathname === '/governance' || pathname === '/governance/') {
    return <Navigate to="/governance/organization" replace />
  }
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <DomainChrome
        title="管理"
        subtitle="誰能用什麼功能、誰動過什麼資料、系統答得好不好 — 都在這裡看。"
      />
      <SubNav items={GOVERNANCE_SUBNAV} />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  )
}
