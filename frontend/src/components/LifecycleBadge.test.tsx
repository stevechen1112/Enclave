import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import LifecycleBadge, { toLifecycle } from './LifecycleBadge'

describe('LifecycleBadge canonical answer readiness', () => {
  it('does not call a merely completed document searchable', () => {
    expect(toLifecycle('completed', null, false)).toBe('not_searchable')
    render(<LifecycleBadge status="completed" answerReady={false} />)
    expect(screen.getByText('尚不可查')).toBeInTheDocument()
  })

  it('uses the backend answer_ready truth for searchable state', () => {
    expect(toLifecycle('completed', null, true)).toBe('searchable')
    render(<LifecycleBadge status="completed" answerReady />)
    expect(screen.getByText('可搜尋')).toBeInTheDocument()
  })

  it('keeps revocation deny-first even if stale readiness is true', () => {
    expect(toLifecycle('completed', '2026-08-25T00:00:00Z', true)).toBe('revoked')
  })
})
