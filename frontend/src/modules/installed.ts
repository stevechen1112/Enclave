import { salesQuoteBundle } from './sales_quote/routes'
import { trainingKnowhowBundle } from './training_knowhow/routes'
import { workflowBundle } from './workflow/routes'
import type { FrontendModuleBundle } from './registry'

// Build-time composition root. Packs own route keys, components and guards;
// this file only declares which independently maintained bundles are installed.
export const installedModuleBundles: FrontendModuleBundle[] = [
  workflowBundle,
  salesQuoteBundle,
  trainingKnowhowBundle,
]
