import axios from 'axios'
import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react'
import { authApi } from './api'
import type { DemoPersona } from './api'
import type { ExperienceBootstrap, User } from './types'

interface AuthState {
  user: User | null
  experience: ExperienceBootstrap | null
  token: string | null
  loading: boolean
  experienceStatus: 'idle' | 'loading' | 'ready' | 'error'
  login: (email: string, password: string) => Promise<void>
  demoLogin: (persona: DemoPersona) => Promise<void>
  logout: () => void
  refreshExperience: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [experience, setExperience] = useState<ExperienceBootstrap | null>(null)
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [loading, setLoading] = useState(true)
  const [experienceStatus, setExperienceStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')

  const refreshExperience = useCallback(async () => {
    setExperienceStatus('loading')
    try {
      if (!user) {
        setUser(await authApi.me())
      }
      const exp = await authApi.experience()
      setExperience(exp)
      setExperienceStatus('ready')
    } catch {
      setExperience(null)
      setExperienceStatus('error')
    }
  }, [user])

  const fetchUser = useCallback(async () => {
    try {
      const u = await authApi.me()
      setUser(u)
      setExperienceStatus('loading')
      try {
        const exp = await authApi.experience()
        setExperience(exp)
        setExperienceStatus('ready')
      } catch {
        setExperience(null)
        setExperienceStatus('error')
      }
    } catch (error) {
      setUser(null)
      setExperience(null)
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        setToken(null)
        setExperienceStatus('idle')
        localStorage.removeItem('token')
      } else {
        // A transient gateway/network failure must not destroy a valid session.
        setExperienceStatus('error')
      }
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
    setExperienceStatus('loading')
    localStorage.setItem('token', access_token)
    setToken(access_token)
  }

  const demoLogin = async (persona: DemoPersona) => {
    const { access_token } = await authApi.demoLogin(persona)
    setLoading(true)
    setUser(null)
    setExperience(null)
    setExperienceStatus('loading')
    localStorage.setItem('token', access_token)
    setToken(access_token)
  }

  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
    setExperience(null)
    setExperienceStatus('idle')
  }

  return (
    <AuthContext.Provider
      value={{ user, experience, token, loading, experienceStatus, login, demoLogin, logout, refreshExperience }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// AuthProvider and its hook intentionally share this context module.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
