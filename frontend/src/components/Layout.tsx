import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { useBranding } from '../contexts/BrandingContext'
import { MessageSquare, FileText, BarChart3, LogOut, Shield, ClipboardList, Building2, KeyRound, Palette, CreditCard, Globe, MapPin, Activity, Menu, X, Gauge } from 'lucide-react'
import clsx from 'clsx'

const navItems = [
  { to: '/', icon: MessageSquare, label: 'AI 問答' },
  { to: '/documents', icon: FileText, label: '文件管理' },
  { to: '/my-usage', icon: Activity, label: '我的用量' },
  { to: '/usage', icon: BarChart3, label: '用量統計', roles: ['owner', 'admin'] },
  { to: '/audit', icon: ClipboardList, label: '稽核日誌', roles: ['owner', 'admin'] },
  { to: '/departments', icon: Building2, label: '部門管理', roles: ['owner', 'admin', 'hr'] },
  { to: '/company', icon: Building2, label: '公司管理', roles: ['owner', 'admin'] },
  { to: '/branding', icon: Palette, label: '品牌設定', roles: ['owner', 'admin'] },
  { to: '/subscription', icon: CreditCard, label: '訂閱方案', roles: ['owner', 'admin'] },
  { to: '/custom-domains', icon: Globe, label: '自訂域名', roles: ['owner', 'admin'] },
  { to: '/regions', icon: MapPin, label: '區域資訊', roles: ['owner', 'admin'] },
  { to: '/rag-dashboard', icon: Gauge, label: 'RAG 儀表板', roles: ['owner', 'admin', 'hr'] },
  { to: '/sso-settings', icon: KeyRound, label: 'SSO 設定', roles: ['owner', 'admin'] },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const branding = useBranding()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const displayName = branding.brand_name || branding.tenant_name || 'UniHR'

  const visibleNav = navItems.filter(item => {
    return !item.roles || item.roles.includes(user?.role ?? '')
  })

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-gray-200 px-4">
        {branding.brand_logo_url ? (
          <img src={branding.brand_logo_url} alt={displayName} className="h-6 w-6 object-contain" />
        ) : (
          <Shield className="h-6 w-6" style={{ color: branding.brand_primary_color || '#2563eb' }} />
        )}
        <span className="text-lg font-bold text-gray-900">{displayName}</span>
        {/* Mobile close button */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="ml-auto md:hidden rounded-lg p-1 text-gray-400 hover:text-gray-600"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {visibleNav.map(({ to, icon: Icon, label }) => (
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
        ))}
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
          <span className="font-semibold text-gray-800">{displayName}</span>
        </header>

        <main className="flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
