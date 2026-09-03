import { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import Layout from './components/Layout'
import type { Capability } from './navigation/capabilities'
import { useDefaultHomePath, useHasCapability } from './navigation/useCapabilities'
import { buildModuleRouteElements } from './modules/registry'
import api from './api'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const LandingPage = lazy(() => import('./pages/LandingPage'))
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
const VideoAssetsPage = lazy(() => import('./pages/knowledge/VideoAssetsPage'))
const VideoReviewPage = lazy(() => import('./pages/knowledge/VideoReviewPage'))
const AssetLibraryPage = lazy(() => import('./pages/knowledge/AssetLibraryPage'))
const AddKnowledgePage = lazy(() => import('./pages/knowledge/AddKnowledgePage'))
const AssetDetailPage = lazy(() => import('./pages/knowledge/AssetDetailPage'))
const GovernanceLayout = lazy(() => import('./pages/governance/GovernanceLayout'))
const SystemLayout = lazy(() => import('./pages/system/SystemLayout'))
const ModulesPage = lazy(() => import('./pages/system/ModulesPage'))
const HealthPage = lazy(() => import('./pages/system/HealthPage'))
const BackupPage = lazy(() => import('./pages/system/BackupPage'))
const DeployPage = lazy(() => import('./pages/system/DeployPage'))
const InputPilotPage = lazy(() => import('./pages/system/InputPilotPage'))
const KnowledgeDecisionDiffPage = lazy(() => import('./pages/system/KnowledgeDecisionDiffPage'))
const CreateLayout = lazy(() => import('./pages/create/CreateLayout'))
const TenantAdminPage = lazy(() => import('./pages/system/TenantAdminPage'))
const AccountPage = lazy(() => import('./pages/AccountPage'))

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

function ExperienceUnavailable() {
  const { refreshExperience, logout } = useAuth()
  return (
    <main className="flex min-h-screen items-center justify-center bg-wash p-6">
      <section className="w-full max-w-md rounded-2xl border border-line bg-surface p-6 text-center shadow-card" aria-labelledby="experience-error-title">
        <h1 id="experience-error-title" className="font-display text-xl font-semibold text-ink">無法載入您的工作空間</h1>
        <p className="mt-2 text-sm text-muted">為避免顯示未授權功能，系統已暫停載入導覽與應用。請重試，或重新登入。</p>
        <div className="mt-5 flex justify-center gap-3"><button type="button" className="btn-primary" onClick={() => void refreshExperience()}>重新載入</button><button type="button" className="btn-outline" onClick={logout}>重新登入</button></div>
      </section>
    </main>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, loading, experience, experienceStatus } = useAuth()
  if (loading || experienceStatus === 'loading') return <PageLoader />
  if (!token) return <Navigate to="/login" replace />
  if (!experience) return <ExperienceUnavailable />
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

function LegacyRedirect({ surfaceKey, to }: { surfaceKey: string; to: string }) {
  useEffect(() => {
    void api.post('/deprecations/usage', {
      key: surfaceKey,
      client_path: `${window.location.pathname}${window.location.search}`,
    }).catch(() => undefined)
  }, [surfaceKey])
  return <Navigate to={to} replace />
}

function LegacyReportDetailRedirect() {
  const { id } = useParams<{ id: string }>()
  return <LegacyRedirect surfaceKey="frontend.report_detail" to={`/create/reports/${id}`} />
}

function AppRoutes() {
  const { token, user, loading, experience, experienceStatus } = useAuth()
  const home = useDefaultHomePath()
  const moduleRoutes = buildModuleRouteElements(experience?.ui_modules)

  // Module routes are server-owned. Keep the requested deep link intact until
  // bootstrap has supplied its manifest; otherwise the wildcard route would
  // briefly treat valid module URLs (for example /job) as unknown and send the
  // browser back to the landing page.
  if (token && (loading || experienceStatus === 'loading')) return <PageLoader />
  if (token && experienceStatus === 'error') return <ExperienceUnavailable />

  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route
          path="/demo"
          element={
            token
              ? (loading || !user
                ? <PageLoader />
                : <Navigate to={home} replace />)
              : <LoginPage />
          }
        />
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

        <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route path="ask" element={<ChatPage />} />
          <Route
            path="overview"
            element={<CapGuard capability="home"><OverviewPage /></CapGuard>}
          />

          <Route path="knowledge" element={<KnowledgeLayout />}>
            <Route index element={<Navigate to="assets" replace />} />
            <Route path="assets" element={<AssetLibraryPage />} />
            <Route path="assets/:assetId" element={<AssetDetailPage />} />
            <Route path="new" element={<CapGuard capability="upload_documents"><AddKnowledgePage /></CapGuard>} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="documents/:id" element={<DocumentDetailPage />} />
            <Route path="videos" element={<VideoAssetsPage />} />
            <Route path="videos/:assetId" element={<VideoReviewPage />} />
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
            <Route path="input-pilot" element={<InputPilotPage />} />
            <Route path="decision-diffs" element={<KnowledgeDecisionDiffPage />} />
            <Route path="backup" element={<BackupPage />} />
            <Route path="deploy" element={<DeployPage />} />
            <Route path="operations" element={<Navigate to="/system/health" replace />} />
          </Route>

          <Route path="me/usage" element={<UsagePage />} />
          <Route path="me/account" element={<AccountPage />} />

          {moduleRoutes}

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
          <Route path="documents" element={<LegacyRedirect surfaceKey="frontend.documents" to="/knowledge/assets" />} />
          <Route path="connectors" element={<LegacyRedirect surfaceKey="frontend.connectors" to="/knowledge/sources" />} />
          <Route path="agent" element={<LegacyRedirect surfaceKey="frontend.agent" to="/knowledge/sources" />} />
          <Route path="agent/review" element={<LegacyRedirect surfaceKey="frontend.agent_review" to="/knowledge/review" />} />
          <Route path="agent/progress" element={<LegacyRedirect surfaceKey="frontend.agent_progress" to="/knowledge/review" />} />
          <Route path="kb-health" element={<LegacyRedirect surfaceKey="frontend.kb_health" to="/knowledge/quality" />} />
          <Route path="query-analytics" element={<LegacyRedirect surfaceKey="frontend.query_analytics" to="/governance/insights" />} />
          <Route path="audit" element={<LegacyRedirect surfaceKey="frontend.audit" to="/governance/audit" />} />
          <Route path="departments" element={<LegacyRedirect surfaceKey="frontend.departments" to="/governance/departments" />} />
          <Route path="company" element={<LegacyRedirect surfaceKey="frontend.company" to="/governance/organization" />} />
          <Route path="knowledge-compiler" element={<LegacyRedirect surfaceKey="frontend.knowledge_compiler" to="/system/modules" />} />
          <Route path="usage" element={<LegacyRedirect surfaceKey="frontend.usage" to="/me/usage" />} />
          <Route path="my-usage" element={<LegacyRedirect surfaceKey="frontend.my_usage" to="/me/usage" />} />
          <Route path="generate" element={<LegacyRedirect surfaceKey="frontend.generate" to="/create" />} />
          <Route path="reports" element={<LegacyRedirect surfaceKey="frontend.reports" to="/create/reports" />} />
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
