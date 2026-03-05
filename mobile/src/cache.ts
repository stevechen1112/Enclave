/**
 * P12-8 — 離線快取模組
 *
 * 使用 AsyncStorage 快取近期對話與文件清單，
 * 讓 App 在無網路時仍可瀏覽本機快取資料。
 *
 * 快取策略：
 *   - 每次成功讀取 API 後寫入快取（write-through）
 *   - API 失敗時回退（fallback）到快取資料
 *   - 快取效期 24 小時（超過後顯示提示但仍可瀏覽）
 */
import AsyncStorage from '@react-native-async-storage/async-storage'
import NetInfo from '@react-native-community/netinfo'
import type { Conversation, Document } from './types'

// ── Cache Keys ────────────────────────────────────────────────────────────────

const KEYS = {
  CONVERSATIONS: '@enclave/conversations',
  CONVERSATIONS_TS: '@enclave/conversations_ts',
  DOCUMENTS: '@enclave/documents',
  DOCUMENTS_TS: '@enclave/documents_ts',
} as const

const CACHE_TTL_MS = 24 * 60 * 60 * 1000 // 24 hours

// ── Network check ─────────────────────────────────────────────────────────────

export async function isOnline(): Promise<boolean> {
  try {
    const state = await NetInfo.fetch()
    return !!(state.isConnected && state.isInternetReachable !== false)
  } catch {
    return true // assume online if check fails
  }
}

// ── Generic cache helpers ──────────────────────────────────────────────────────

async function writeCache<T>(key: string, tsKey: string, data: T): Promise<void> {
  try {
    await AsyncStorage.multiSet([
      [key, JSON.stringify(data)],
      [tsKey, Date.now().toString()],
    ])
  } catch {
    // ignore write errors
  }
}

async function readCache<T>(key: string, tsKey: string): Promise<{
  data: T | null; stale: boolean
}> {
  try {
    const results = await AsyncStorage.multiGet([key, tsKey])
    const raw = results[0][1]
    const ts = results[1][1]
    if (!raw) return { data: null, stale: true }
    const data = JSON.parse(raw) as T
    const age = ts ? Date.now() - parseInt(ts, 10) : Infinity
    return { data, stale: age > CACHE_TTL_MS }
  } catch {
    return { data: null, stale: true }
  }
}

// ── Conversations ─────────────────────────────────────────────────────────────

export async function cacheConversations(conversations: Conversation[]): Promise<void> {
  // Keep only the most recent 50
  const trimmed = conversations.slice(0, 50)
  await writeCache(KEYS.CONVERSATIONS, KEYS.CONVERSATIONS_TS, trimmed)
}

export async function getCachedConversations(): Promise<{
  conversations: Conversation[]; stale: boolean
}> {
  const { data, stale } = await readCache<Conversation[]>(
    KEYS.CONVERSATIONS, KEYS.CONVERSATIONS_TS,
  )
  return { conversations: data ?? [], stale }
}

// ── Documents ─────────────────────────────────────────────────────────────────

export async function cacheDocuments(documents: Document[]): Promise<void> {
  await writeCache(KEYS.DOCUMENTS, KEYS.DOCUMENTS_TS, documents)
}

export async function getCachedDocuments(): Promise<{
  documents: Document[]; stale: boolean
}> {
  const { data, stale } = await readCache<Document[]>(
    KEYS.DOCUMENTS, KEYS.DOCUMENTS_TS,
  )
  return { documents: data ?? [], stale }
}

// ── Clear all cache ────────────────────────────────────────────────────────────

export async function clearCache(): Promise<void> {
  try {
    await AsyncStorage.multiRemove(Object.values(KEYS))
  } catch {
    // ignore
  }
}
