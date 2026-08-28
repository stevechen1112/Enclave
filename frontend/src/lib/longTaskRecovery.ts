export type RecoverableKnowledgeTask = {
  assetId: string
  title: string
  assetKind: string
  createdAt: string
}

const STORAGE_KEY = 'enclave.recoverable-knowledge-tasks.v1'
const MAX_TASKS = 10
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

function isTask(value: unknown): value is RecoverableKnowledgeTask {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return typeof row.assetId === 'string' && /^[a-zA-Z0-9-]{1,128}$/.test(row.assetId)
    && typeof row.title === 'string' && row.title.length <= 300
    && typeof row.assetKind === 'string' && row.assetKind.length <= 64
    && typeof row.createdAt === 'string' && Number.isFinite(Date.parse(row.createdAt))
}

export function recoverableKnowledgeTasks(now = Date.now()): RecoverableKnowledgeTask[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(isTask)
      .filter(task => now - Date.parse(task.createdAt) <= MAX_AGE_MS)
      .slice(0, MAX_TASKS)
  } catch {
    return []
  }
}

function write(tasks: RecoverableKnowledgeTask[]) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks.slice(0, MAX_TASKS)))
  window.dispatchEvent(new CustomEvent('enclave:long-task'))
}

export function rememberKnowledgeTask(task: RecoverableKnowledgeTask) {
  if (!isTask(task)) return
  write([task, ...recoverableKnowledgeTasks().filter(item => item.assetId !== task.assetId)])
}

export function forgetKnowledgeTask(assetId: string) {
  write(recoverableKnowledgeTasks().filter(task => task.assetId !== assetId))
}
