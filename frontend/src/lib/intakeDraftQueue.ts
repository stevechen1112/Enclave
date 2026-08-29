export type IntakeDraft = {
  key: string
  tenantId: string
  file: File
  idempotencyKey: string
  uploadSessionId?: string
  createdAt: string
  error?: string
}

const DB_PREFIX = 'enclave-input-drafts-v1'
const STORE = 'drafts'

function available() {
  return typeof indexedDB !== 'undefined'
}

function openDb(tenantId: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(`${DB_PREFIX}-${tenantId}`, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: 'key' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('無法開啟上傳草稿'))
  })
}

export async function loadIntakeDrafts(tenantId: string): Promise<IntakeDraft[]> {
  if (!available()) return []
  const db = await openDb(tenantId)
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).getAll()
      request.onsuccess = () => resolve((request.result as IntakeDraft[]).filter(item => item.tenantId === tenantId))
      request.onerror = () => reject(request.error || new Error('無法讀取上傳草稿'))
    })
  } finally {
    db.close()
  }
}

export async function replaceIntakeDrafts(tenantId: string, drafts: Omit<IntakeDraft, 'tenantId'>[]): Promise<void> {
  if (!available()) return
  const db = await openDb(tenantId)
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      const store = tx.objectStore(STORE)
      store.clear()
      drafts.forEach(draft => store.put({ ...draft, tenantId }))
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error || new Error('無法保存上傳草稿'))
      tx.onabort = () => reject(tx.error || new Error('保存上傳草稿已中止'))
    })
  } finally {
    db.close()
  }
}
