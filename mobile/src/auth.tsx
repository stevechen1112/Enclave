/**
 * Auth context for Enclave Mobile
 *
 * Mirrors web frontend/src/auth.tsx, adapted for React Native:
 * - Token stored in expo-secure-store (encrypted) instead of localStorage
 * - Exposes same interface: { user, token, loading, login, logout }
 */
import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react'
import * as SecureStore from 'expo-secure-store'
import { authApi } from './api'
import { unregisterPushNotifications } from './notifications'
import { clearCache } from './cache'
import {
  recordFailedLogin,
  clearFailedLogin,
  checkLoginLockout,
  detectSuspiciousLogin,
  reportSecurityEvent,
  revokeToken,
} from './security'
import type { User } from './types'

interface AuthState {
  user: User | null
  token: string | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Rehydrate token from SecureStore on app start
  useEffect(() => {
    SecureStore.getItemAsync('token').then((stored) => {
      if (stored) setToken(stored)
      else setLoading(false)
    })
  }, [])

  const fetchUser = useCallback(async () => {
    try {
      const u = await authApi.me()
      setUser(u)
    } catch {
      await SecureStore.deleteItemAsync('token')
      setToken(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (token) fetchUser()
  }, [token, fetchUser])

  const login = async (email: string, password: string): Promise<void> => {
    // P12-11: 登入冷卻鎖定檢查
    const { locked, remainingMs } = await checkLoginLockout()
    if (locked) {
      const minutes = Math.ceil(remainingMs / 60000)
      throw new Error(`帳號已暫時鎖定，請等候 ${minutes} 分鐘後再試`)
    }

    try {
      const { access_token } = await authApi.login(email, password)
      await clearFailedLogin()                  // 登入成功，重置失敗計數
      await SecureStore.setItemAsync('token', access_token)
      setToken(access_token)
    } catch (err: unknown) {
      // P12-11: 記錄失敗 + 異常偵測
      await recordFailedLogin()
      const rawCount = await SecureStore.getItemAsync('enclave.failed_login_attempts')
      const failedCount = parseInt(rawCount ?? '1', 10)
      const reasons = detectSuspiciousLogin(failedCount)
      if (reasons.length > 0) {
        void reportSecurityEvent('suspicious_login', { reasons, email })
      }
      throw err
    }
  }

  const logout = async (): Promise<void> => {
    // P12-9: 取消推播通知登記
    await unregisterPushNotifications()

    // P12-11: 遠端 Token 撤銷 — 讓後端將 JWT 加入黑名單
    const currentToken = await SecureStore.getItemAsync('token')
    if (currentToken) {
      await revokeToken(currentToken)
    }

    // 清除本機快取與 token
    await clearCache()
    await SecureStore.deleteItemAsync('token')
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
