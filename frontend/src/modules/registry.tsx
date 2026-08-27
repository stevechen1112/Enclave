import type { ReactElement } from 'react'
import type { UIModuleManifest } from '../types'
import { installedModuleBundles } from './installed'

export interface FrontendModuleBundle {
  bundleKey: string
  /** Every route the bundle is allowed to render. Server manifests only enable this closed set. */
  ownedRouteKeys: readonly string[]
  buildRoutes: (manifests: UIModuleManifest[]) => ReactElement[]
}

export function validateModuleBundles(bundles: FrontendModuleBundle[]): void {
  const bundleKeys = new Set<string>()
  const routeKeys = new Set<string>()
  for (const bundle of bundles) {
    if (!/^[a-z][a-z0-9_-]*$/.test(bundle.bundleKey) || bundleKeys.has(bundle.bundleKey)) {
      throw new Error(`invalid or duplicate frontend bundle key: ${bundle.bundleKey}`)
    }
    bundleKeys.add(bundle.bundleKey)
    if (!bundle.ownedRouteKeys.length) throw new Error(`frontend bundle has no owned routes: ${bundle.bundleKey}`)
    for (const routeKey of bundle.ownedRouteKeys) {
      if (!routeKey.startsWith(`${bundle.bundleKey}.`) || routeKeys.has(routeKey)) {
        throw new Error(`invalid or duplicate frontend route key: ${routeKey}`)
      }
      routeKeys.add(routeKey)
    }
  }
}

validateModuleBundles(installedModuleBundles)

export function buildModuleRouteElements(
  manifests: UIModuleManifest[] | undefined,
): ReactElement[] {
  const available = manifests || []
  return installedModuleBundles.flatMap(bundle => {
    const allowed = new Set(bundle.ownedRouteKeys)
    const owned = available
      .filter(manifest => (manifest.bundle_key || manifest.pack_key) === bundle.bundleKey)
      .map(manifest => ({ ...manifest, route_keys: manifest.route_keys.filter(key => allowed.has(key)) }))
      .filter(manifest => manifest.route_keys.length > 0)
    return owned.length ? bundle.buildRoutes(owned) : []
  })
}
