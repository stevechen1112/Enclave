import { describe, expect, it } from 'vitest'
import type { UIModuleManifest } from '../types'
import {
  enabledModuleNavigationPaths,
  enabledModuleRouteKeys,
} from './manifests'
import { buildModuleRouteElements, validateModuleBundles } from './registry'

const workspace: UIModuleManifest = {
  pack_key: 'mka',
  ui_key: 'mka.workspace',
  version: '1.0.0',
  route_keys: [
    'mka.job.home',
    'mka.job.task',
    'mka.forms.mine',
    'mka.forms.instance',
    'mka.forms.form',
    'mka.approvals',
  ],
  required_capabilities: ['workflow.approval', 'workflow.fixed_form'],
  navigation: [{ to: '/job', label: '現場作業' }],
}

const salesQuote: UIModuleManifest = {
  pack_key: 'mka',
  ui_key: 'mka.sales_quote',
  version: '1.0.0',
  module_key: 'sales_quote',
  route_keys: ['mka.quote.redirect'],
  required_capabilities: ['workflow.fixed_form'],
  navigation: [],
}

const knowhow: UIModuleManifest = {
  pack_key: 'mka',
  ui_key: 'mka.knowhow',
  version: '1.0.0',
  module_key: 'training_knowhow',
  route_keys: [
    'mka.knowhow.list',
    'mka.knowhow.interview',
    'mka.knowhow.detail',
  ],
  required_capabilities: ['knowledge.knowhow.read'],
  navigation: [],
}

describe('tenant UI module registry', () => {
  it.each([
    ['owner/all modules', [workspace, salesQuote, knowhow], true, true, true],
    ['admin/quality only', [workspace], true, false, false],
    ['sales/quote only', [workspace, salesQuote], true, false, true],
    ['master/training', [workspace, knowhow], true, true, false],
    ['viewer/no binding', [], false, false, false],
    ['hr/deployment disabled', [], false, false, false],
  ] as const)('%s consumes the bootstrap manifest', (_persona, manifests, hasJob, hasKnowhow, hasQuote) => {
    const keys = enabledModuleRouteKeys([...manifests])
    const navigation = enabledModuleNavigationPaths([...manifests])

    expect(keys.has('mka.job.home')).toBe(hasJob)
    expect(keys.has('mka.knowhow.list')).toBe(hasKnowhow)
    expect(keys.has('mka.quote.redirect')).toBe(hasQuote)
    expect(navigation.has('/job')).toBe(hasJob)
  })

  it('builds routes only for keys provided by the backend', () => {
    expect(buildModuleRouteElements([])).toHaveLength(0)
    expect(buildModuleRouteElements([knowhow])).toHaveLength(3)
    expect(buildModuleRouteElements([workspace, salesQuote, knowhow])).toHaveLength(10)
  })

  it('drops route keys not owned by the installed bundle', () => {
    expect(buildModuleRouteElements([{ ...workspace, route_keys: ['mka.job.home', 'other.admin'] }])).toHaveLength(1)
  })

  it('rejects duplicate or cross-bundle route ownership at startup', () => {
    const noop = () => []
    expect(() => validateModuleBundles([
      { bundleKey: 'first', ownedRouteKeys: ['first.home'], buildRoutes: noop },
      { bundleKey: 'second', ownedRouteKeys: ['first.home'], buildRoutes: noop },
    ])).toThrow('invalid or duplicate frontend route key')
  })
})
