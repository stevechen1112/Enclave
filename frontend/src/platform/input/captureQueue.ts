export interface PendingCaptureChunk {
  key: string
  sessionId: string
  sequence: number
  offsetMs: number
  durationMs: number
  sha256: string
  blob: Blob
}

const DB_NAME = 'enclave-long-interview-v1'
const STORE = 'chunks'

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: 'key' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Unable to open offline recording storage'))
  })
}

export async function savePendingCaptureChunk(chunk: PendingCaptureChunk): Promise<void> {
  const db = await openDb()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(chunk)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('Unable to save offline recording'))
    tx.onabort = () => reject(tx.error ?? new Error('Offline recording storage aborted'))
  })
  db.close()
}

export async function listPendingCaptureChunks(sessionId: string): Promise<PendingCaptureChunk[]> {
  const db = await openDb()
  const items = await new Promise<PendingCaptureChunk[]>((resolve, reject) => {
    const request = db.transaction(STORE, 'readonly').objectStore(STORE).getAll()
    request.onsuccess = () => resolve((request.result as PendingCaptureChunk[])
      .filter(item => item.sessionId === sessionId)
      .sort((a, b) => a.sequence - b.sequence))
    request.onerror = () => reject(request.error ?? new Error('Unable to read offline recording'))
  })
  db.close()
  return items
}

export async function removePendingCaptureChunk(key: string): Promise<void> {
  const db = await openDb()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).delete(key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('Unable to clear uploaded recording'))
  })
  db.close()
}
