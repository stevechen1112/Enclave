/* eslint-disable react-refresh/only-export-components */
import { lazy, type ReactElement, type ReactNode } from 'react'
import { Navigate, Route } from 'react-router-dom'
import type { Capability } from '../../navigation/capabilities'
import { useDefaultHomePath, useHasCapability } from '../../navigation/useCapabilities'
import { useCanAuthorKnowhow } from '../../navigation/useKnowhowPermissions'
import type { UIModuleManifest } from '../../types'
import { enabledModuleRouteKeys } from '../manifests'
import type { FrontendModuleBundle } from '../registry'

const JobHomePage = lazy(() => import('../../pages/job/JobHomePage'))
const TaskWorkspacePage = lazy(() => import('../../pages/job/TaskWorkspacePage'))
const FormPage = lazy(() => import('../../pages/forms/FormPage'))
const FormInstancesPage = lazy(() => import('../../pages/forms/FormInstancesPage'))
const FormInstanceDetailPage = lazy(() => import('../../pages/forms/FormInstanceDetailPage'))
const ApprovalsPage = lazy(() => import('../../pages/approvals/ApprovalsPage'))
const KnowhowListPage = lazy(() => import('../../pages/knowhow/KnowhowListPage'))
const KnowhowDetailPage = lazy(() => import('../../pages/knowhow/KnowhowDetailPage'))
const InterviewPage = lazy(() => import('../../pages/knowhow/InterviewPage'))

function CapabilityGuard({ children, capability }: { children: ReactNode; capability: Capability }) {
  const allowed = useHasCapability(capability)
  const home = useDefaultHomePath()
  return allowed ? <>{children}</> : <Navigate to={home} replace />
}

function KnowhowAuthorGuard({ children }: { children: ReactNode }) {
  const allowed = useCanAuthorKnowhow()
  return allowed ? <>{children}</> : <Navigate to="/knowhow" replace />
}

function buildRoutes(manifests: UIModuleManifest[]): ReactElement[] {
  const enabled = enabledModuleRouteKeys(manifests)
  const routes: ReactElement[] = []
  const add = (routeKey: string, path: string, element: ReactElement) => {
    if (enabled.has(routeKey)) routes.push(<Route key={routeKey} path={path} element={element} />)
  }
  const fieldGuard = (element: ReactElement) => (
    <CapabilityGuard capability="field_work">{element}</CapabilityGuard>
  )

  add('mka.job.home', 'job', fieldGuard(<JobHomePage />))
  add('mka.job.task', 'job/tasks/:taskKey', fieldGuard(<TaskWorkspacePage />))
  add('mka.quote.redirect', 'quote', <Navigate to="/forms/quote" replace />)
  add('mka.forms.mine', 'forms/mine', fieldGuard(<FormInstancesPage />))
  add('mka.forms.instance', 'forms/instances/:instanceId', fieldGuard(<FormInstanceDetailPage />))
  add('mka.forms.form', 'forms/:formKey', fieldGuard(<FormPage />))
  add('mka.approvals', 'approvals', fieldGuard(<ApprovalsPage />))
  add('mka.knowhow.list', 'knowhow', fieldGuard(<KnowhowListPage />))
  add(
    'mka.knowhow.interview',
    'knowhow/interview',
    fieldGuard(<KnowhowAuthorGuard><InterviewPage /></KnowhowAuthorGuard>),
  )
  add('mka.knowhow.detail', 'knowhow/:id', fieldGuard(<KnowhowDetailPage />))
  return routes
}

export const mkaBundle: FrontendModuleBundle = {
  bundleKey: 'mka',
  ownedRouteKeys: [
    'mka.job.home',
    'mka.job.task',
    'mka.quote.redirect',
    'mka.forms.mine',
    'mka.forms.instance',
    'mka.forms.form',
    'mka.approvals',
    'mka.knowhow.list',
    'mka.knowhow.interview',
    'mka.knowhow.detail',
  ],
  buildRoutes,
}
