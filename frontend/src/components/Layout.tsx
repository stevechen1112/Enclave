import { useState } from 'react'
import { Outlet, NavLink, useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../auth'
import { Shield, LogOut, Menu, X, BarChart3, ChevronDown, PenLine } from 'lucide-react'
import clsx from 'clsx'
import {
  primaryNavFor,
  ROLE_LABELS,
  defaultHomePath,
  hasCapability,
} from '../navigation/capabilities'
import ReadinessBanner from './ReadinessBanner'
import InferenceBanner from './InferenceBanner'

export default function Layout() {
  const { user, experience, logout } = useAuth()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)

  const nav = primaryNavFor(user?.role, user?.is_superuser)
  const home = defaultHomePath(user?.role, user?.is_superuser)
  const roleLabel = ROLE_LABELS[user?.role ?? ''] || user?.role || '使用者'
  const orgLabel =
    experience?.product?.name ||
    (import.meta.env.VITE_ORG_NAME as string | undefined) ||
    'Enclave'

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const sidebarContent = (
    <>
      <div className="flex h-14 items-center gap-2.5 border-b border-sidebar-line px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent">
          <Shield className="h-4.5 w-4.5 text-white" aria-hidden />
        </div>
        <Link to={home} className="min-w-0 text-lg font-semibold tracking-tight text-sidebar-fg" onClick={() => setSidebarOpen(false)}>
          <span className="block truncate">{orgLabel}</span>
          {orgLabel !== 'Enclave' && (
            <span className="block text-[10px] font-normal text-sidebar-muted">Enclave</span>
          )}
        </Link>
        <button
          type="button"
          onClick={() => setSidebarOpen(false)}
          className="ml-auto rounded-lg p-1.5 text-sidebar-muted hover:text-sidebar-fg md:hidden"
          aria-label="關閉選單"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <nav className="flex-1 space-y-0.5 px-3 py-4 overflow-y-auto" aria-label="主要導覽">
        {nav.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={() => setSidebarOpen(false)}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors duration-150',
                isActive
                  ? 'bg-sidebar-active text-white'
                  : 'text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg',
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-sidebar-line p-3">
        <div className="relative">
          <button
            type="button"
            onClick={() => setUserMenuOpen(v => !v)}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-sidebar-hover"
            aria-expanded={userMenuOpen}
            aria-haspopup="menu"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-sidebar-fg">
                {user?.full_name || user?.email}
              </p>
              <p className="text-xs text-sidebar-muted">{roleLabel}</p>
            </div>
            <ChevronDown className={clsx('h-4 w-4 text-sidebar-muted transition', userMenuOpen && 'rotate-180')} />
          </button>
          {userMenuOpen && (
            <div
              role="menu"
              className="mt-1 rounded-lg border border-sidebar-line bg-sidebar-elevated py-1 shadow-lg"
            >
              {hasCapability(user?.role, 'create_content', user?.is_superuser) && (
                <Link
                  to="/create"
                  role="menuitem"
                  onClick={() => { setUserMenuOpen(false); setSidebarOpen(false) }}
                  className="flex items-center gap-2 px-3 py-2 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg"
                >
                  <PenLine className="h-4 w-4" aria-hidden />
                  創作
                </Link>
              )}
              <Link
                to="/me/usage"
                role="menuitem"
                onClick={() => { setUserMenuOpen(false); setSidebarOpen(false) }}
                className="flex items-center gap-2 px-3 py-2 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg"
              >
                <BarChart3 className="h-4 w-4" aria-hidden />
                我的用量
              </Link>
              <button
                type="button"
                role="menuitem"
                onClick={handleLogout}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg"
              >
                <LogOut className="h-4 w-4" aria-hidden />
                登出
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )

  return (
    <div className="flex h-screen bg-wash">
      <aside className="hidden w-56 flex-col border-r border-sidebar-line bg-sidebar md:flex">
        {sidebarContent}
      </aside>

      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-ink/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden
        />
      )}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-50 flex w-56 flex-col border-r border-sidebar-line bg-sidebar transition-transform duration-200 md:hidden',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
        aria-hidden={!sidebarOpen}
      >
        {sidebarContent}
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center gap-3 border-b border-line bg-surface px-4 md:hidden">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="rounded-lg p-1.5 text-ink hover:bg-wash"
            aria-label="開啟選單"
            aria-expanded={sidebarOpen}
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="font-semibold text-ink">Enclave</span>
        </header>

        <InferenceBanner />
        <ReadinessBanner />
        <main className="flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
