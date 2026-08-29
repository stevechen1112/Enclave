/* eslint-disable react-refresh/only-export-components */
import { lazy, type ReactElement, type ReactNode } from 'react'
import { Navigate, Route } from 'react-router-dom'
import { useDefaultHomePath, useHasCapability } from '../../navigation/useCapabilities'
import { useCanAuthorKnowhow } from '../../navigation/useKnowhowPermissions'
import type { UIModuleManifest } from '../../types'
import { enabledModuleRouteKeys } from '../manifests'
import type { FrontendModuleBundle } from '../registry'

const ListPage = lazy(() => import('../../pages/knowhow/KnowhowListPage'))
const DetailPage = lazy(() => import('../../pages/knowhow/KnowhowDetailPage'))
const InterviewPage = lazy(() => import('../../pages/knowhow/InterviewPage'))
function Field({ children }: { children: ReactNode }) { const ok = useHasCapability('field_work'); const home = useDefaultHomePath(); return ok ? <>{children}</> : <Navigate to={home} replace /> }
function Author({ children }: { children: ReactNode }) { return useCanAuthorKnowhow() ? <>{children}</> : <Navigate to="/knowhow" replace /> }
function buildRoutes(manifests: UIModuleManifest[]): ReactElement[] {
  const enabled = enabledModuleRouteKeys(manifests); const out: ReactElement[] = []
  if (enabled.has('training_knowhow.list')) out.push(<Route key="training_knowhow.list" path="knowhow" element={<Field><ListPage /></Field>} />)
  if (enabled.has('training_knowhow.interview')) out.push(<Route key="training_knowhow.interview" path="knowhow/interview" element={<Field><Author><InterviewPage /></Author></Field>} />)
  if (enabled.has('training_knowhow.detail')) out.push(<Route key="training_knowhow.detail" path="knowhow/:id" element={<Field><DetailPage /></Field>} />)
  return out
}
export const trainingKnowhowBundle: FrontendModuleBundle = {
  bundleKey: 'training_knowhow',
  ownedRouteKeys: ['training_knowhow.list', 'training_knowhow.interview', 'training_knowhow.detail'],
  buildRoutes,
}
