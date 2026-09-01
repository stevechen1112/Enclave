import { useEffect, useRef, useState } from 'react'
import { Outlet, NavLink, useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../auth'
import {
  Shield, LogOut, Menu, X, BarChart3, ChevronDown, PenLine, Plus, KeyRound,
  LayoutGrid, Blocks, MessageCircle, BookOpen, Scale, Settings2, Search,
} from 'lucide-react'
import clsx from 'clsx'
import { ROLE_LABELS } from '../navigation/capabilities'
import {
  useDefaultHomePath,
  useHasCapability,
  usePrimaryNav,
} from '../navigation/useCapabilities'
import ReadinessBanner from './ReadinessBanner'
import InferenceBanner from './InferenceBanner'
import CommandPalette from './CommandPalette'
import ConnectivityBanner from './ConnectivityBanner'
import LongTaskRecoveryBanner from './LongTaskRecoveryBanner'

const NAV_ICONS: Record<string, typeof LayoutGrid> = {
  '/overview': LayoutGrid,
  '/ask': MessageCircle,
  '/knowledge': BookOpen,
  '/governance': Scale,
  '/system': Settings2,
}

export default function Layout() {
  const { user, experience, logout } = useAuth()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null)
  const mobileDrawerRef = useRef<HTMLElement>(null)
  const userMenuButtonRef = useRef<HTMLButtonElement>(null)

  const nav = usePrimaryNav()
  const home = useDefaultHomePath()
  const canCreate = useHasCapability('create_content')
  const canAddKnowledge = useHasCapability('upload_documents')
  const roleLabel = ROLE_LABELS[user?.role ?? ''] || user?.role || '使用者'
  const orgLabel =
    experience?.organization?.name ||
    experience?.product?.name ||
    (import.meta.env.VITE_ORG_NAME as string | undefined) ||
    'Enclave'

  useEffect(() => {
    if (!userMenuOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setUserMenuOpen(false)
        userMenuButtonRef.current?.focus()
      }
    }
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target
      if (!(target instanceof Element) || !target.closest('[data-user-menu]')) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [userMenuOpen])

  useEffect(() => {
    if (!sidebarOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSidebarOpen(false)
        window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus())
        return
      }
      if (e.key !== 'Tab') return
      const focusable = [...(mobileDrawerRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
      ) || [])].filter(element => element.offsetParent !== null)
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey)
    const frame = window.requestAnimationFrame(() => {
      mobileDrawerRef.current?.querySelector<HTMLElement>('[data-mobile-menu-close]')?.focus()
    })
    return () => {
      window.cancelAnimationFrame(frame)
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKey)
    }
  }, [sidebarOpen])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(open => !open)
      } else if (event.key === 'Escape') {
        setCommandOpen(false)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const closeSidebar = () => {
    const shouldRestore = sidebarOpen
    setSidebarOpen(false)
    if (shouldRestore) {
      window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus())
    }
  }

  const sidebarContent = (
    <>
      <div className="flex h-16 items-center gap-2.5 border-b border-sidebar-line px-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent shadow-sm">
          <Shield className="h-5 w-5 text-white" aria-hidden />
        </div>
        <Link to={home} className="min-w-0 text-lg font-semibold tracking-tight text-sidebar-fg" onClick={closeSidebar}>
          <span className="block truncate">{orgLabel}</span>
          {orgLabel !== 'Enclave' && (
            <span className="block text-xs font-normal text-sidebar-muted">Enclave</span>
          )}
        </Link>
        <button
          type="button"
          onClick={closeSidebar}
          className="ml-auto inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg md:hidden"
          aria-label="關閉選單"
          data-mobile-menu-close
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="主要導覽">
        {canAddKnowledge && (
          <Link
            to="/knowledge/new"
            onClick={closeSidebar}
            className="mb-4 flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accent px-3 text-sm font-semibold text-white shadow-sm hover:brightness-105"
          >
            <Plus className="h-4 w-4" aria-hidden />
            新增知識
          </Link>
        )}
        <button type="button" onClick={() => { closeSidebar(); setCommandOpen(true) }} className="mb-3 flex min-h-11 w-full items-center gap-3 rounded-xl px-3.5 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg" aria-label="搜尋可用功能">
          <Search className="h-5 w-5" aria-hidden />
          <span className="flex-1 text-left">搜尋功能</span><kbd className="rounded border border-sidebar-line px-1.5 py-0.5 text-[10px]">Ctrl K</kbd>
        </button>
        {nav.map(item => {
          const Icon = item.module ? Blocks : NAV_ICONS[item.to]
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={closeSidebar}
              className={({ isActive }) =>
                clsx(
                  'flex min-h-11 items-center gap-3 rounded-xl px-3.5 text-[15px] font-medium transition-colors duration-150',
                  isActive
                    ? 'bg-sidebar-active text-white shadow-sm'
                    : 'text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg',
                )
              }
            >
              {Icon && <Icon className="h-5 w-5 shrink-0" aria-hidden />}
              {item.label}
            </NavLink>
          )
        })}
      </nav>

      <div className="border-t border-sidebar-line p-3">
        <div className="relative" data-user-menu>
          <button
            ref={userMenuButtonRef}
            type="button"
            onClick={() => setUserMenuOpen(v => !v)}
            className="flex min-h-11 w-full items-center gap-2 rounded-xl px-3 py-2 text-left hover:bg-sidebar-hover"
            aria-expanded={userMenuOpen}
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
              // The account control sits at the bottom of the sidebar.  Keep
              // its menu inside the viewport by overlaying it above the
              // trigger instead of expanding the sidebar below the fold.
              className="absolute bottom-full left-0 right-0 z-50 mb-1 rounded-xl border border-sidebar-line bg-sidebar-elevated py-1.5 shadow-lg"
            >
              {canCreate && (
                <Link
                  to="/create"
                  onClick={() => { setUserMenuOpen(false); setSidebarOpen(false) }}
                  className="flex min-h-11 items-center gap-2.5 px-4 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg"
                >
                  <PenLine className="h-4 w-4" aria-hidden />
                  創作
                </Link>
              )}
              <Link
                to="/me/account"
                onClick={() => { setUserMenuOpen(false); setSidebarOpen(false) }}
                className="flex min-h-11 items-center gap-2.5 px-4 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg"
              >
                <KeyRound className="h-4 w-4" aria-hidden />
                我的帳號
              </Link>
              <Link
                to="/me/usage"
                onClick={() => { setUserMenuOpen(false); setSidebarOpen(false) }}
                className="flex min-h-11 items-center gap-2.5 px-4 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg"
              >
                <BarChart3 className="h-4 w-4" aria-hidden />
                我的用量
              </Link>
              <button
                type="button"
                onClick={handleLogout}
                className="flex min-h-11 w-full items-center gap-2.5 px-4 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-fg"
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
      <a href="#main-content" className="skip-link">跳到主要內容</a>
      <aside className="hidden w-60 flex-col border-r border-sidebar-line bg-sidebar md:flex">
        {sidebarContent}
      </aside>

      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-ink/40 md:hidden"
          onClick={closeSidebar}
          aria-hidden
        />
      )}
      {sidebarOpen && (
        <aside
          ref={mobileDrawerRef}
          role="dialog"
          aria-modal="true"
          aria-label="行動版主要選單"
          className="fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-sidebar-line bg-sidebar md:hidden"
        >
          {sidebarContent}
        </aside>
      )}

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center gap-3 border-b border-line bg-surface px-4 md:hidden">
          <button
            ref={mobileMenuButtonRef}
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl text-ink hover:bg-wash"
            aria-label="開啟選單"
            aria-expanded={sidebarOpen}
          >
            <Menu className="h-6 w-6" />
          </button>
          <span className="text-[15px] font-semibold text-ink">{orgLabel}</span>
        </header>

        <InferenceBanner />
        <ReadinessBanner />
        <ConnectivityBanner />
        <LongTaskRecoveryBanner />
        <main id="main-content" tabIndex={-1} className="flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={commandOpen} items={nav} onClose={() => setCommandOpen(false)} />
    </div>
  )
}
