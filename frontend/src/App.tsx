import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'
import DocumentsPage from './pages/DocumentsPage'
import UsagePage from './pages/UsagePage'
import AuditLogsPage from './pages/AuditLogsPage'
import DepartmentsPage from './pages/DepartmentsPage'
import CompanyPage from './pages/CompanyPage'
import MyUsagePage from './pages/MyUsagePage'
// Phase 10 — 主動索引 Agent
import AgentPage from './pages/AgentPage'
import ReviewQueuePage from './pages/ReviewQueuePage'
import ProgressDashboardPage from './pages/ProgressDashboardPage'
// Phase 11 — 內容生成
import GeneratePage from './pages/GeneratePage'
import QueryAnalyticsPage from './pages/QueryAnalyticsPage'
// Phase 11-2 — 報告管理
import ReportsPage from './pages/ReportsPage'
import ReportDetailPage from './pages/ReportDetailPage'
// Phase 13 — 知識庫主動維護
import KBHealthPage from './pages/KBHealthPage'

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
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<ChatPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="my-usage" element={<MyUsagePage />} />
        <Route path="usage" element={<RoleGuard roles={['owner', 'admin']}><UsagePage /></RoleGuard>} />
        <Route path="audit" element={<RoleGuard roles={['owner', 'admin']}><AuditLogsPage /></RoleGuard>} />
        <Route path="departments" element={<RoleGuard roles={['owner', 'admin']}><DepartmentsPage /></RoleGuard>} />
        <Route path="company" element={<RoleGuard roles={['owner', 'admin']}><CompanyPage /></RoleGuard>} />
        {/* Phase 10 — 主動索引 Agent */}
        <Route path="agent" element={<RoleGuard roles={['owner', 'admin']}><AgentPage /></RoleGuard>} />
        <Route path="agent/review" element={<RoleGuard roles={['owner', 'admin', 'manager']}><ReviewQueuePage /></RoleGuard>} />
        <Route path="agent/progress" element={<RoleGuard roles={['owner', 'admin', 'manager']}><ProgressDashboardPage /></RoleGuard>} />
        <Route path="query-analytics" element={<RoleGuard roles={['owner', 'admin']}><QueryAnalyticsPage /></RoleGuard>} />
        {/* Phase 11 — 內容生成 */}
        <Route path="generate" element={<GeneratePage />} />
        {/* Phase 11-2 — 報告管理 */}
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/:id" element={<ReportDetailPage />} />
        {/* Phase 13 — 知識庫維護 */}
        <Route path="kb-health" element={<RoleGuard roles={['owner', 'admin']}><KBHealthPage /></RoleGuard>} />
        {/* Redirects for merged pages */}
        <Route path="rag-dashboard" element={<Navigate to="/query-analytics" replace />} />
        <Route path="usage-report" element={<Navigate to="/usage" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
