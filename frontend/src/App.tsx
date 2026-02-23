import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { BrandingProvider } from './contexts/BrandingContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'
import DocumentsPage from './pages/DocumentsPage'
import UsagePage from './pages/UsagePage'
import AuditLogsPage from './pages/AuditLogsPage'
import DepartmentsPage from './pages/DepartmentsPage'
import CompanyPage from './pages/CompanyPage'
import SSOCallbackPage from './pages/SSOCallbackPage'
import SSOSettingsPage from './pages/SSOSettingsPage'
import BrandingPage from './pages/BrandingPage'
import SubscriptionPage from './pages/SubscriptionPage'
import CustomDomainsPage from './pages/CustomDomainsPage'
import RegionsPage from './pages/RegionsPage'
import MyUsagePage from './pages/MyUsagePage'
import RAGDashboardPage from './pages/RAGDashboardPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth()
  if (loading) return <div className="flex h-screen items-center justify-center"><div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" /></div>
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RoleGuard({ children, roles }: { children: React.ReactNode; roles: string[] }) {
  const { user } = useAuth()
  if (!user || !roles.includes(user.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

function AppRoutes() {
  const { token } = useAuth()
  return (
    <Routes>
      <Route path="/login" element={token ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/login/callback" element={<SSOCallbackPage />} />
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<ChatPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="my-usage" element={<MyUsagePage />} />
        <Route path="usage" element={<RoleGuard roles={['owner', 'admin']}><UsagePage /></RoleGuard>} />
        <Route path="audit" element={<RoleGuard roles={['owner', 'admin']}><AuditLogsPage /></RoleGuard>} />
        <Route path="departments" element={<RoleGuard roles={['owner', 'admin', 'hr']}><DepartmentsPage /></RoleGuard>} />
        <Route path="company" element={<RoleGuard roles={['owner', 'admin']}><CompanyPage /></RoleGuard>} />
        <Route path="sso-settings" element={<RoleGuard roles={['owner', 'admin']}><SSOSettingsPage /></RoleGuard>} />
        <Route path="branding" element={<RoleGuard roles={['owner', 'admin']}><BrandingPage /></RoleGuard>} />
        <Route path="subscription" element={<RoleGuard roles={['owner', 'admin']}><SubscriptionPage /></RoleGuard>} />
        <Route path="custom-domains" element={<RoleGuard roles={['owner', 'admin']}><CustomDomainsPage /></RoleGuard>} />
        <Route path="rag-dashboard" element={<RoleGuard roles={['owner', 'admin', 'hr']}><RAGDashboardPage /></RoleGuard>} />
        <Route path="regions" element={<RoleGuard roles={['owner', 'admin']}><RegionsPage /></RoleGuard>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrandingProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrandingProvider>
  )
}
