import { describe, expect, it } from 'vitest'

import { normalizeEvidenceDeepLink } from './evidenceLinks'

describe('normalizeEvidenceDeepLink', () => {
  it('keeps safe internal evidence locators', () => {
    expect(normalizeEvidenceDeepLink('/knowledge/documents/doc-1?page=2&section=safety')).toBe('/knowledge/documents/doc-1?page=2&section=safety')
    expect(normalizeEvidenceDeepLink('/knowledge/assets/a1?t=402000&end=438000&frame=42&bbox=1,2,3,4')).toBe('/knowledge/assets/a1?t=402000&end=438000&frame=42&bbox=1,2,3,4')
    expect(normalizeEvidenceDeepLink('/knowhow/card-1?evidence=2')).toBe('/knowhow/card-1?evidence=2')
    expect(normalizeEvidenceDeepLink('/knowledge/videos/a1?evidence=550e8400-e29b-41d4-a716-446655440000&t=402000&end=438000')).toBe('/knowledge/videos/a1?evidence=550e8400-e29b-41d4-a716-446655440000&t=402000&end=438000')
  })

  it.each([
    'https://evil.example/knowledge/assets/a1',
    '//evil.example/knowledge/assets/a1',
    '/governance/audit',
    '/knowledge/assets/a1?redirect=https://evil.example',
    '/knowledge/assets/a1?t=6:42',
    '/knowledge/assets/a1?page=0',
    '/knowledge/assets/a1?bbox=1,2,3',
    '/knowledge/assets/a1#unexpected',
    '/knowledge/not-a-surface/a1',
  ])('fails closed for %s', value => {
    expect(normalizeEvidenceDeepLink(value)).toBeNull()
  })
})
