import { type ReactElement } from 'react'
import { Navigate, Route } from 'react-router-dom'
import type { UIModuleManifest } from '../../types'
import { enabledModuleRouteKeys } from '../manifests'
import type { FrontendModuleBundle } from '../registry'

function buildRoutes(manifests: UIModuleManifest[]): ReactElement[] {
  return enabledModuleRouteKeys(manifests).has('sales_quote.redirect')
    ? [<Route key="sales_quote.redirect" path="quote" element={<Navigate to="/forms/quote" replace />} />]
    : []
}

export const salesQuoteBundle: FrontendModuleBundle = {
  bundleKey: 'sales_quote',
  ownedRouteKeys: ['sales_quote.redirect'],
  buildRoutes,
}
