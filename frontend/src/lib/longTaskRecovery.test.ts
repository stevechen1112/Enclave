import { beforeEach, describe, expect, it, vi } from 'vitest'

import { forgetKnowledgeTask, recoverableKnowledgeTasks, rememberKnowledgeTask } from './longTaskRecovery'

describe('long task recovery', () => {
  beforeEach(() => window.localStorage.clear())

  it('persists, deduplicates and clears knowledge processing tasks', () => {
    const task = { assetId: 'asset-1', title: '換線影片', assetKind: 'video', createdAt: new Date().toISOString() }
    rememberKnowledgeTask(task)
    rememberKnowledgeTask({ ...task, title: '換線影片 v2' })
    expect(recoverableKnowledgeTasks()).toEqual([{ ...task, title: '換線影片 v2' }])
    forgetKnowledgeTask('asset-1')
    expect(recoverableKnowledgeTasks()).toEqual([])
  })

  it('drops malformed and expired storage values', () => {
    window.localStorage.setItem('enclave.recoverable-knowledge-tasks.v1', JSON.stringify([
      { assetId: '../bad', title: 'bad', assetKind: 'video', createdAt: new Date().toISOString() },
      { assetId: 'old', title: 'old', assetKind: 'video', createdAt: '2020-01-01T00:00:00Z' },
    ]))
    expect(recoverableKnowledgeTasks(Date.parse('2026-08-28T00:00:00Z'))).toEqual([])
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    expect(recoverableKnowledgeTasks()).toEqual([])
    spy.mockRestore()
  })
})
