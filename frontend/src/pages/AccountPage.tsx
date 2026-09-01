import { useState, type FormEvent } from 'react'
import { Building2, KeyRound, ShieldCheck, UserRound } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api'
import { useAuth } from '../auth'
import PageHeader from '../components/PageHeader'
import { parseApiError } from '../lib/apiError'
import { ROLE_LABELS } from '../navigation/capabilities'

export default function AccountPage() {
  const { user, experience, logout } = useAuth()
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const organization = experience?.organization
  const isDemo = experience?.demo_mode === true
  const roleLabel = ROLE_LABELS[user?.role ?? ''] || user?.role || '使用者'

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (newPassword !== confirmPassword) {
      setError('兩次輸入的新密碼不一致。')
      return
    }
    setBusy(true)
    try {
      await authApi.changePassword(currentPassword, newPassword)
      logout()
      navigate('/login?mode=enterprise&password=changed', { replace: true })
    } catch (reason) {
      setError(parseApiError(reason, '密碼更新失敗，請稍後再試。').message)
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 p-5 md:p-8">
      <PageHeader title="我的帳號" subtitle="確認目前登入的公司環境、身分與帳號安全。" />

      <section className="grid gap-4 md:grid-cols-2" aria-label="登入環境">
        <article className="card p-5">
          <div className="flex items-start gap-3">
            <span className="rounded-xl bg-accent-soft p-2.5 text-accent"><Building2 className="h-5 w-5" aria-hidden /></span>
            <div>
              <p className="text-xs font-semibold tracking-wide text-muted">目前公司</p>
              <h2 className="mt-1 text-lg font-semibold text-ink">{organization?.name || 'Enclave'}</h2>
              <p className="mt-1 text-sm text-muted">{organization?.department_name || '尚未指定部門'}</p>
              <span className="mt-3 inline-flex rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">
                {organization?.environment_label || '正式企業工作區'}
              </span>
            </div>
          </div>
        </article>
        <article className="card p-5">
          <div className="flex items-start gap-3">
            <span className="rounded-xl bg-highlight-soft p-2.5 text-highlight"><UserRound className="h-5 w-5" aria-hidden /></span>
            <div className="min-w-0">
              <p className="text-xs font-semibold tracking-wide text-muted">帳號與權限</p>
              <h2 className="mt-1 truncate text-lg font-semibold text-ink">{user?.full_name || user?.email}</h2>
              <p className="mt-1 break-all text-sm text-muted">{user?.email}</p>
              <p className="mt-2 text-sm font-medium text-ink">權限層級：{roleLabel}</p>
            </div>
          </div>
        </article>
      </section>

      <section className="card p-5 md:p-6" aria-labelledby="change-password-title">
        <div className="flex items-start gap-3">
          <span className="rounded-xl bg-wash p-2.5 text-ink"><KeyRound className="h-5 w-5" aria-hidden /></span>
          <div>
            <h2 id="change-password-title" className="text-lg font-semibold text-ink">變更密碼</h2>
            <p className="mt-1 text-sm leading-6 text-muted">{isDemo ? 'Demo 使用合成帳號，不能變更密碼。' : '第一次登入後建議換成只有本人知道的密碼。更新完成後，系統會要求重新登入。'}</p>
          </div>
        </div>

        {!isDemo && <form onSubmit={event => void submit(event)} className="mt-5 max-w-xl space-y-4">
          <label htmlFor="current-password" className="block text-sm font-semibold text-ink">
            目前密碼
            <input id="current-password" className="input mt-2 w-full" type="password" autoComplete="current-password" required value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} />
          </label>
          <div>
          <label htmlFor="new-password" className="block text-sm font-semibold text-ink">
            新密碼
            <input id="new-password" aria-describedby="new-password-help" className="input mt-2 w-full" type="password" autoComplete="new-password" required minLength={12} value={newPassword} onChange={event => setNewPassword(event.target.value)} />
          </label>
          <span id="new-password-help" className="mt-1 block text-xs font-normal text-muted">至少 12 字元，包含英文大寫、小寫與數字。</span>
          </div>
          <label htmlFor="confirm-password" className="block text-sm font-semibold text-ink">
            再輸入一次新密碼
            <input id="confirm-password" className="input mt-2 w-full" type="password" autoComplete="new-password" required minLength={12} value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} />
          </label>
          {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
          <button type="submit" className="btn-primary" disabled={busy || !currentPassword || !newPassword || !confirmPassword}>
            <ShieldCheck className="h-4 w-4" aria-hidden />
            {busy ? '更新中…' : '更新密碼'}
          </button>
        </form>}
      </section>
    </div>
  )
}
