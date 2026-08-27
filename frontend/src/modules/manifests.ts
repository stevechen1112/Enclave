import type { UIModuleManifest } from '../types'

export function enabledModuleRouteKeys(
  manifests: UIModuleManifest[] | undefined,
): Set<string> {
  return new Set((manifests || []).flatMap(manifest => manifest.route_keys || []))
}

export function enabledModuleNavigationPaths(
  manifests: UIModuleManifest[] | undefined,
): Set<string> {
  return new Set(
    (manifests || []).flatMap(manifest =>
      (manifest.navigation || []).map(item => item.to),
    ),
  )
}
