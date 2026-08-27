import { describe, expect, it } from 'vitest'

import { isSafeAppPath, serverDefaultHome, serverNavigation, type Capability } from './capabilities'

describe('server-composed navigation', () => {
  const capabilities = new Set<Capability>(['home', 'ask', 'browse_knowledge'])

  it('does not keep a browser-side role capability authority', async () => {
    const source = await import('./capabilities?raw').then(module => module.default)
    expect(source).not.toContain('ROLE_CAPS')
    expect(source).not.toContain('capabilitiesFor')
  })

  it('accepts only safe, entitled and unique server navigation entries', () => {
    expect(serverNavigation([
      { to: '/overview', label: '總覽', capability: 'home' },
      { to: '/ask', label: '問答', capability: 'ask' },
      { to: '/system', label: '系統', capability: 'system_ops' },
      { to: '/ask', label: '重複' },
      { to: 'https://evil.invalid', label: '外部' },
      { to: '/blank', label: '   ' },
    ], capabilities).map(item => item.to)).toEqual(['/overview', '/ask'])
  })

  it('uses only reachable server defaults and otherwise fails closed to ask', () => {
    const navigation = serverNavigation([{ to: '/overview', label: '總覽', capability: 'home' }, { to: '/ask', label: '問答', capability: 'ask' }], capabilities)
    expect(serverDefaultHome('overview', navigation)).toBe('/overview')
    expect(serverDefaultHome('/overview/detail', navigation)).toBe('/overview/detail')
    expect(serverDefaultHome('job', navigation)).toBe('/ask')
    expect(serverDefaultHome('https://evil.invalid', navigation)).toBe('/ask')
  })

  it('rejects protocol, traversal, query and fragment paths', () => {
    expect(isSafeAppPath('/knowledge/assets')).toBe(true)
    for (const value of ['//evil.invalid', '/../admin', '/ask?q=secret', '/ask#x', 'javascript:alert(1)']) expect(isSafeAppPath(value)).toBe(false)
  })
})
