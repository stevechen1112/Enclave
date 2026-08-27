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

  it('maps canonical asset and ingestion states without an unknown badge', () => {
    expect(toLifecycle('active')).toBe('not_searchable')
    expect(toLifecycle('queued')).toBe('processing')
    expect(toLifecycle('running')).toBe('processing')
    expect(toLifecycle('review_required')).toBe('pending_review')
    expect(toLifecycle('ready', null, true)).toBe('searchable')
  })
})
