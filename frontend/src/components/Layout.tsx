import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { MessageSquare, FileText, BarChart3, BarChart2, LogOut, Shield, ClipboardList, Building2, Menu, X, FolderSearch, CheckSquare, Wand2, HeartPulse, FileStack, Settings } from 'lucide-react'
import clsx from 'clsx'

type NavItem =
  | { type: 'link'; to: string; icon: typeof MessageSquare; label: string; roles?: string[] }
  | { type: 'section'; label: string; roles?: string[] }

const navItems: NavItem[] = [
  // ── 工作 ──
  { type: 'section', label: '工作' },
  { type: 'link', to: '/', icon: MessageSquare, label: 'AI 問答' },
  { type: 'link', to: '/generate', icon: Wand2, label: '內容生成' },
  { type: 'link', to: '/reports', icon: FileStack, label: '我的報告' },
  { type: 'link', to: '/documents', icon: FileText, label: '文件管理' },
  { type: 'link', to: '/usage', icon: BarChart3, label: '用量統計' },
  // ── 管理 ──
  { type: 'section', label: '管理', roles: ['owner', 'admin', 'manager'] },
  { type: 'link', to: '/agent', icon: FolderSearch, label: 'Agent 設定', roles: ['owner', 'admin'] },
  { type: 'link', to: '/agent/review', icon: CheckSquare, label: '審核佇列', roles: ['owner', 'admin', 'manager'] },
  // ── 分析 ──
  { type: 'section', label: '分析', roles: ['owner', 'admin'] },
  { type: 'link', to: '/query-analytics', icon: BarChart2, label: '問答分析', roles: ['owner', 'admin'] },

  { type: 'link', to: '/audit', icon: ClipboardList, label: '稽核日誌', roles: ['owner', 'admin'] },
  { type: 'link', to: '/kb-health', icon: HeartPulse, label: 'KB 健康度', roles: ['owner', 'admin'] },
  // ── 設定 ──
  { type: 'section', label: '設定', roles: ['owner', 'admin'] },
  { type: 'link', to: '/departments', icon: Building2, label: '部門管理', roles: ['owner', 'admin'] },
  { type: 'link', to: '/company', icon: Settings, label: '組織設定', roles: ['owner', 'admin'] },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const visibleNav = navItems.filter(item => {
    return !item.roles || item.roles.includes(user?.role ?? '')
  })

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-gray-200 px-4">
        <Shield className="h-6 w-6 text-blue-600" />
        <span className="text-lg font-bold text-gray-900">Enclave</span>
        {/* Mobile close button */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="ml-auto md:hidden rounded-lg p-1 text-gray-400 hover:text-gray-600"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-3 py-4 overflow-y-auto">
        {visibleNav.map((item, idx) => {
          if (item.type === 'section') {
            return (
              <div key={`sec-${idx}`} className={clsx('px-3 pt-4 pb-1', idx === 0 && 'pt-0')}>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">{item.label}</p>
              </div>
            )
          }
          const { to, icon: Icon, label } = item
          return (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                )
              }
            >
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          )
        })}
      </nav>

      {/* User info */}
      <div className="border-t border-gray-200 p-4">
        <div className="mb-2">
          <p className="text-sm font-medium text-gray-900 truncate">{user?.full_name || user?.email}</p>
          <p className="text-xs text-gray-500">{user?.role?.toUpperCase()}</p>
        </div>
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors"
        >
          <LogOut className="h-4 w-4" />
          登出
        </button>
      </div>
    </>
  )

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-60 flex-col border-r border-gray-200 bg-white">
        {sidebarContent}
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-gray-200 bg-white transition-transform duration-200 md:hidden',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {sidebarContent}
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Mobile top bar */}
        <header className="flex md:hidden items-center gap-3 border-b border-gray-200 bg-white px-4 h-14">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-lg p-1.5 text-gray-600 hover:bg-gray-100"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="font-semibold text-gray-800">Enclave</span>
        </header>

        <main className="flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
