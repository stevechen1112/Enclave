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
        title="治理"
        subtitle="誰能看什麼、誰做了什麼、問答品質如何 — 權限與稽核都在這裡。"
      />
      <SubNav items={GOVERNANCE_SUBNAV} />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  )
}
