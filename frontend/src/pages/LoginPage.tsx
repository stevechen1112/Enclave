import { useEffect, useState, type FormEvent } from 'react'
import { Loader2, Shield } from 'lucide-react'
import DemoDoors from '../components/DemoDoors'
import { authApi } from '../api'
import { useAuth } from '../auth'
import { parseApiError } from '../lib/apiError'

export default function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [demoEnabled, setDemoEnabled] = useState(false)

  useEffect(() => {
    void authApi.loginOptions()
      .then(options => setDemoEnabled(options.demo_enabled))
      .catch(() => setDemoEnabled(false))
  }, [])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email.trim(), password)
    } catch (reason) {
      const info = parseApiError(reason)
      if (info.status === 401) {
        setError('帳號或密碼不正確，請重新確認。')
      } else if (info.status === 429) {
        setError('登入嘗試過於頻繁，請稍候再試。')
      } else {
        setError('登入服務目前無法使用，請稍後再試。')
      }
      setBusy(false)
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#292724] px-4 py-8 sm:px-6 lg:px-8">
      <div
        className="pointer-events-none absolute inset-0 opacity-50"
        style={{
          background:
            'linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
        }}
        aria-hidden
      />

      <div className="relative mx-auto w-full max-w-6xl">
        <header className="mx-auto mb-7 max-w-md text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-accent shadow-lg shadow-black/20">
            <Shield className="h-7 w-7 text-white" aria-hidden />
          </div>
          <p className="text-xs font-semibold tracking-[0.2em] text-[#d0a27f]">ENCLAVE</p>
          <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-white">登入企業知識平台</h1>
          <p className="mt-3 text-sm leading-6 text-sidebar-muted">使用公司核發的帳號，進入您獲授權的知識與應用。</p>
        </header>

        <form onSubmit={event => void submit(event)} className="mx-auto max-w-md rounded-2xl border border-stone-300 bg-[#fffdf8] p-6 shadow-xl" noValidate>
          <label className="block text-sm font-semibold text-stone-800">
            電子郵件
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={event => setEmail(event.target.value)}
              className="input mt-2 w-full"
            />
          </label>
          <label className="mt-4 block text-sm font-semibold text-stone-800">
            密碼
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={event => setPassword(event.target.value)}
              className="input mt-2 w-full"
            />
          </label>
          {error && <p role="alert" aria-live="polite" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
          <button type="submit" disabled={busy || !email.trim() || !password} className="btn-primary mt-5 w-full justify-center disabled:opacity-50">
            {busy ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden />登入中…</> : '登入'}
          </button>
        </form>

        {demoEnabled && (
          <details className="mt-6 rounded-2xl border border-white/15 bg-white/5 p-4 text-white">
            <summary className="cursor-pointer text-center text-sm font-semibold">查看合成 Demo 角色</summary>
            <div className="mt-5">
              <DemoDoors compact />
              <p className="mt-4 text-center text-xs text-sidebar-muted">合成展示環境，請勿輸入真實客戶資料、個資或公司機密。</p>
            </div>
          </details>
        )}

        <a href="/" className="mx-auto mt-6 block max-w-md text-center text-sm font-medium text-[#d8b08c] underline-offset-4 hover:underline">回產品介紹</a>
      </div>
    </main>
  )
}
