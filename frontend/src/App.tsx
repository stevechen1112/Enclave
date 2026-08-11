import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import Layout from './components/Layout'
import type { Capability } from './navigation/capabilities'
import { useDefaultHomePath, useHasCapability } from './navigation/useCapabilities'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const OverviewPage = lazy(() => import('./pages/OverviewPage'))
const ChatPage = lazy(() => import('./pages/ChatPage'))
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'))
const UsagePage = lazy(() => import('./pages/UsagePage'))
const AuditLogsPage = lazy(() => import('./pages/AuditLogsPage'))
const DepartmentsPage = lazy(() => import('./pages/DepartmentsPage'))
const CompanyPage = lazy(() => import('./pages/CompanyPage'))
const AgentPage = lazy(() => import('./pages/AgentPage'))
const ReviewQueuePage = lazy(() => import('./pages/ReviewQueuePage'))
const GeneratePage = lazy(() => import('./pages/GeneratePage'))
const QueryAnalyticsPage = lazy(() => import('./pages/QueryAnalyticsPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const ReportDetailPage = lazy(() => import('./pages/ReportDetailPage'))
const KnowledgeLayout = lazy(() => import('./pages/knowledge/KnowledgeLayout'))
const SourcesPage = lazy(() => import('./pages/knowledge/SourcesPage'))
const QualityPage = lazy(() => import('./pages/knowledge/QualityPage'))
const DocumentDetailPage = lazy(() => import('./pages/knowledge/DocumentDetailPage'))
const WikiListPage = lazy(() => import('./pages/knowledge/WikiListPage'))
const WikiDetailPage = lazy(() => import('./pages/knowledge/WikiDetailPage'))
const GovernanceLayout = lazy(() => import('./pages/governance/GovernanceLayout'))
const SystemLayout = lazy(() => import('./pages/system/SystemLayout'))
const ModulesPage = lazy(() => import('./pages/system/ModulesPage'))
const HealthPage = lazy(() => import('./pages/system/HealthPage'))
const BackupPage = lazy(() => import('./pages/system/BackupPage'))
const DeployPage = lazy(() => import('./pages/system/DeployPage'))
const CreateLayout = lazy(() => import('./pages/create/CreateLayout'))
const JobHomePage = lazy(() => import('./pages/job/JobHomePage'))
const TaskWorkspacePage = lazy(() => import('./pages/job/TaskWorkspacePage'))
const TenantAdminPage = lazy(() => import('./pages/system/TenantAdminPage'))
const FormPage = lazy(() => import('./pages/forms/FormPage'))
const FormInstancesPage = lazy(() => import('./pages/forms/FormInstancesPage'))
const FormInstanceDetailPage = lazy(() => import('./pages/forms/FormInstanceDetailPage'))
const ApprovalsPage = lazy(() => import('./pages/approvals/ApprovalsPage'))
const KnowhowListPage = lazy(() => import('./pages/knowhow/KnowhowListPage'))
const KnowhowDetailPage = lazy(() => import('./pages/knowhow/KnowhowDetailPage'))
const InterviewPage = lazy(() => import('./pages/knowhow/InterviewPage'))

function PageLoader() {
  return (
    <div className="flex h-full min-h-[40vh] items-center justify-center">
      <div
        className="h-8 w-8 animate-spin rounded-full border-4 border-accent border-t-transparent"
        role="status"
        aria-label="載入中"
      />
    </div>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth()
  if (loading) return <PageLoader />
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function CapGuard({
  children,
  capability,
}: {
  children: React.ReactNode
  capability: Capability
}) {
  const allowed = useHasCapability(capability)
  const home = useDefaultHomePath()
  if (!allowed) {
    return <Navigate to={home} replace />
  }
  return <>{children}</>
}

function HomeRedirect() {
  const { user, loading } = useAuth()
  const home = useDefaultHomePath()
  if (loading || !user) return <PageLoader />
  return <Navigate to={home} replace />
}

function LegacyReportDetailRedirect() {
  const { id } = useParams<{ id: string }>()
  return <Navigate to={`/create/reports/${id}`} replace />
}

function AppRoutes() {
  const { token, user, loading } = useAuth()
  const home = useDefaultHomePath()

  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route
          path="/login"
          element={
            token
              ? (loading || !user
                ? <PageLoader />
                : <Navigate to={home} replace />)
              : <LoginPage />
          }
        />

        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<HomeRedirect />} />
          <Route path="ask" element={<ChatPage />} />
          <Route
            path="overview"
            element={<CapGuard capability="admin_home"><OverviewPage /></CapGuard>}
          />

          <Route path="knowledge" element={<KnowledgeLayout />}>
            <Route index element={<Navigate to="documents" replace />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="documents/:id" element={<DocumentDetailPage />} />
            <Route path="wiki" element={<WikiListPage />} />
            <Route path="wiki/:id" element={<WikiDetailPage />} />
            <Route
              path="sources"
              element={<CapGuard capability="manage_sources"><SourcesPage /></CapGuard>}
            />
            <Route
              path="review"
              element={<CapGuard capability="review_queue"><ReviewQueuePage /></CapGuard>}
            />
            <Route
              path="quality"
              element={<CapGuard capability="governance"><QualityPage /></CapGuard>}
            />
          </Route>

          <Route
            path="governance"
            element={<CapGuard capability="governance"><GovernanceLayout /></CapGuard>}
          >
            <Route index element={<Navigate to="organization" replace />} />
            <Route path="organization" element={<CompanyPage />} />
            <Route path="departments" element={<DepartmentsPage />} />
            <Route path="audit" element={<AuditLogsPage />} />
            <Route path="insights" element={<QueryAnalyticsPage />} />
          </Route>

          <Route
            path="system"
            element={<CapGuard capability="system_ops"><SystemLayout /></CapGuard>}
          >
            <Route index element={<Navigate to="modules" replace />} />
            <Route path="modules" element={<ModulesPage />} />
            <Route path="tenant-admin" element={<TenantAdminPage />} />
            <Route path="health" element={<HealthPage />} />
            <Route path="backup" element={<BackupPage />} />
            <Route path="deploy" element={<DeployPage />} />
            <Route path="operations" element={<Navigate to="/system/health" replace />} />
          </Route>

          <Route path="me/usage" element={<UsagePage />} />

          {/* MKA 現場作業（製造業 PWA）：職務入口／報價／審核／師傅經驗庫 */}
          <Route
            path="job"
            element={<CapGuard capability="field_work"><JobHomePage /></CapGuard>}
          />
          <Route
            path="job/tasks/:taskKey"
            element={<CapGuard capability="field_work"><TaskWorkspacePage /></CapGuard>}
          />
          <Route
            path="quote"
            element={<Navigate to="/forms/quote" replace />}
          />
          <Route
            path="forms/mine"
            element={<CapGuard capability="field_work"><FormInstancesPage /></CapGuard>}
          />
          <Route
            path="forms/instances/:instanceId"
            element={<CapGuard capability="field_work"><FormInstanceDetailPage /></CapGuard>}
          />
          <Route
            path="forms/:formKey"
            element={<CapGuard capability="field_work"><FormPage /></CapGuard>}
          />
          <Route
            path="approvals"
            element={<CapGuard capability="field_work"><ApprovalsPage /></CapGuard>}
          />
          <Route
            path="knowhow"
            element={<CapGuard capability="field_work"><KnowhowListPage /></CapGuard>}
          />
          <Route
            path="knowhow/interview"
            element={<CapGuard capability="field_work"><InterviewPage /></CapGuard>}
          />
          <Route
            path="knowhow/:id"
            element={<CapGuard capability="field_work"><KnowhowDetailPage /></CapGuard>}
          />

          {/* V1.1 create workspace — user menu, not primary nav */}
          <Route
            path="create"
            element={<CapGuard capability="create_content"><CreateLayout /></CapGuard>}
          >
            <Route index element={<GeneratePage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="reports/:id" element={<ReportDetailPage />} />
          </Route>

          {/* Legacy redirects */}
          <Route path="documents" element={<Navigate to="/knowledge/documents" replace />} />
          <Route path="connectors" element={<Navigate to="/knowledge/sources" replace />} />
          <Route path="agent" element={<Navigate to="/knowledge/sources" replace />} />
          <Route path="agent/review" element={<Navigate to="/knowledge/review" replace />} />
          <Route path="agent/progress" element={<Navigate to="/knowledge/review" replace />} />
          <Route path="kb-health" element={<Navigate to="/knowledge/quality" replace />} />
          <Route path="query-analytics" element={<Navigate to="/governance/insights" replace />} />
          <Route path="audit" element={<Navigate to="/governance/audit" replace />} />
          <Route path="departments" element={<Navigate to="/governance/departments" replace />} />
          <Route path="company" element={<Navigate to="/governance/organization" replace />} />
          <Route path="knowledge-compiler" element={<Navigate to="/system/modules" replace />} />
          <Route path="usage" element={<Navigate to="/me/usage" replace />} />
          <Route path="my-usage" element={<Navigate to="/me/usage" replace />} />
          <Route path="generate" element={<Navigate to="/create" replace />} />
          <Route path="reports" element={<Navigate to="/create/reports" replace />} />
          <Route path="reports/:id" element={<LegacyReportDetailRedirect />} />

          {/* Advanced: full Agent wizard still available via deep link */}
          <Route
            path="advanced/agent-wizard"
            element={<CapGuard capability="manage_sources"><AgentPage /></CapGuard>}
          />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
