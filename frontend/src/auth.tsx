import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react'
import { authApi } from './api'
import type { ExperienceBootstrap, User } from './types'

interface AuthState {
  user: User | null
  experience: ExperienceBootstrap | null
  token: string | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  refreshExperience: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [experience, setExperience] = useState<ExperienceBootstrap | null>(null)
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [loading, setLoading] = useState(true)

  const refreshExperience = useCallback(async () => {
    try {
      const exp = await authApi.experience()
      setExperience(exp)
    } catch {
      setExperience(null)
    }
  }, [])

  const fetchUser = useCallback(async () => {
    try {
      const u = await authApi.me()
      setUser(u)
      try {
        const exp = await authApi.experience()
        setExperience(exp)
      } catch {
        setExperience(null)
      }
    } catch {
      setToken(null)
      setUser(null)
      setExperience(null)
      localStorage.removeItem('token')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (token) {
      fetchUser()
    } else {
      setLoading(false)
    }
  }, [token, fetchUser])

  const login = async (email: string, password: string) => {
    const { access_token } = await authApi.login(email, password)
    setLoading(true)
    setUser(null)
    setExperience(null)
    localStorage.setItem('token', access_token)
    setToken(access_token)
  }

  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
    setExperience(null)
  }

  return (
    <AuthContext.Provider
      value={{ user, experience, token, loading, login, logout, refreshExperience }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
