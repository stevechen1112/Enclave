import { mkaBundle } from './mka/routes'
import type { FrontendModuleBundle } from './registry'

// Build-time composition root. Packs own route keys, components and guards;
// this file only declares which independently maintained bundles are installed.
export const installedModuleBundles: FrontendModuleBundle[] = [mkaBundle]
