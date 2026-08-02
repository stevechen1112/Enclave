import { useState } from 'react'
import { useAuth } from '../auth'
import { Shield, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'

/**
 * 地端版登入 — 僅本機帳號 + JWT（無 SSO 產品入口）
 */
export default function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      await login(email, password)
      toast.success('登入成功')
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '登入失敗'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-sidebar p-4">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            'radial-gradient(ellipse 80% 50% at 20% 20%, rgba(15,118,110,0.35), transparent), radial-gradient(ellipse 60% 40% at 80% 80%, rgba(51,65,85,0.8), transparent)',
        }}
        aria-hidden
      />

      <div className="relative w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-accent shadow-lg">
            <Shield className="h-8 w-8 text-white" aria-hidden />
          </div>
          <h1 className="font-display text-3xl font-bold tracking-tight text-sidebar-fg">
            Enclave
          </h1>
          <p className="mt-2 text-sm text-sidebar-muted">
            企業知識控制面 · 地端 Pilot
          </p>
          <p className="mt-1 text-xs text-sidebar-muted/80">
            問得到、證據找得到、權限守得住、內容撤得掉
          </p>
          <p className="mt-3 text-sm font-medium text-sidebar-fg/90">
            {(import.meta.env.VITE_ORG_NAME as string | undefined) || '組織登入'}
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-sidebar-line bg-surface p-8 shadow-xl"
        >
          <h2 className="mb-6 text-lg font-semibold text-ink">登入</h2>

          <div className="space-y-4">
            <div>
              <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-ink">
                電子郵件
              </label>
              <input
                id="email"
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="name@company.com"
                className="w-full rounded-lg border border-line px-4 py-2.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-ink">
                密碼
              </label>
              <input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-lg border border-line px-4 py-2.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {loading ? '登入中…' : '登入'}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-sidebar-muted">
          帳號問題請聯繫系統管理員 · 本環境為受控 Pilot 部署
        </p>
      </div>
    </div>
  )
}
