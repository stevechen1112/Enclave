/* eslint-disable react-refresh/only-export-components */
import { lazy, type ReactElement, type ReactNode } from 'react'
import { Navigate, Route } from 'react-router-dom'
import type { Capability } from '../../navigation/capabilities'
import { useDefaultHomePath, useHasCapability } from '../../navigation/useCapabilities'
import type { UIModuleManifest } from '../../types'
import { enabledModuleRouteKeys } from '../manifests'
import type { FrontendModuleBundle } from '../registry'

const JobHomePage = lazy(() => import('../../pages/job/JobHomePage'))
const TaskWorkspacePage = lazy(() => import('../../pages/job/TaskWorkspacePage'))
const FormPage = lazy(() => import('../../pages/forms/FormPage'))
const FormInstancesPage = lazy(() => import('../../pages/forms/FormInstancesPage'))
const FormInstanceDetailPage = lazy(() => import('../../pages/forms/FormInstanceDetailPage'))
const ApprovalsPage = lazy(() => import('../../pages/approvals/ApprovalsPage'))

function Guard({ children, capability }: { children: ReactNode; capability: Capability }) {
  const allowed = useHasCapability(capability)
  const home = useDefaultHomePath()
  return allowed ? <>{children}</> : <Navigate to={home} replace />
}

function buildRoutes(manifests: UIModuleManifest[]): ReactElement[] {
  const enabled = enabledModuleRouteKeys(manifests)
  const routes: ReactElement[] = []
  const add = (key: string, path: string, element: ReactElement) => {
    if (enabled.has(key)) routes.push(<Route key={key} path={path} element={<Guard capability="field_work">{element}</Guard>} />)
  }
  add('workflow.job.home', 'job', <JobHomePage />)
  add('workflow.job.task', 'job/tasks/:taskKey', <TaskWorkspacePage />)
  add('workflow.forms.mine', 'forms/mine', <FormInstancesPage />)
  add('workflow.forms.instance', 'forms/instances/:instanceId', <FormInstanceDetailPage />)
  add('workflow.forms.form', 'forms/:formKey', <FormPage />)
  add('workflow.approvals', 'approvals', <ApprovalsPage />)
  return routes
}

export const workflowBundle: FrontendModuleBundle = {
  bundleKey: 'workflow',
  ownedRouteKeys: ['workflow.job.home', 'workflow.job.task', 'workflow.forms.mine', 'workflow.forms.instance', 'workflow.forms.form', 'workflow.approvals'],
  buildRoutes,
}
