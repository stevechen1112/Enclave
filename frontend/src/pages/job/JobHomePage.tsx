/**
 * JobHomePage — 動態職能工作台（tenant + job role + module binding）。
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BookOpen,
  ClipboardCheck,
  FileText,
  MessageCircleQuestion,
  Wrench,
} from 'lucide-react'
import toast from 'react-hot-toast'
import PushToTalk from '../../components/mka/PushToTalk'
import TranscriptEditor from '../../components/mka/TranscriptEditor'
import QrScanner from '../../components/mka/QrScanner'
import SceneContextBanner from '../../components/mka/SceneContextBanner'
import { useAuth } from '../../auth'
import api from '../../api'
import {
  approvalsApi,
  formsApi,
  voiceApi,
  type SceneContext,
  type TranscribeResponse,
} from '../../services/mka'

type WorkspaceEntry = {
  module_key?: string
  key?: string
  label?: string
  path?: string
  description?: string
}

type JobRoleAssignment = {
  id: string
  job_role_id?: string
  role_key?: string | null
  name?: string | null
  is_primary?: boolean
  default_module_keys?: string[]
}

const FALLBACK_ENTRIES: WorkspaceEntry[] = [
  { label: '開報價單', path: '/job/tasks/quote', description: '語音帶入或手動填寫' },
  { label: '異常回報', path: '/job/tasks/incident', description: '設備／品質／安全' },
  { label: '交接班', path: '/job/tasks/handover', description: '本班狀況與待辦' },
  { label: '師傅經驗庫', path: '/knowhow', description: '知識卡與訪談' },
]

const DEMO_VIEWER_ENTRIES: WorkspaceEntry[] = [
  { label: '查看知識文件', path: '/knowledge/documents', description: '只看合成展示文件與正式發布內容' },
  { label: '查看師傅經驗', path: '/knowhow', description: '只看已核准的做法與注意事項' },
]

export default function JobHomePage() {
  const { user, experience, refreshExperience } = useAuth()
  const navigate = useNavigate()
  const [scene, setScene] = useState<SceneContext | null>(null)
  const [voiceResult, setVoiceResult] = useState<TranscribeResponse | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [pendingApprovals, setPendingApprovals] = useState<number | null>(null)
  const [draftCount, setDraftCount] = useState<number | null>(null)

  const canReview = user?.is_superuser || user?.role === 'owner' || user?.role === 'admin'
  const demoViewer = Boolean(experience?.demo_mode && user?.role === 'viewer')

  const needsJobRoleAssignment = Boolean(
    (experience as { needs_job_role_assignment?: boolean } | null)
      ?.needs_job_role_assignment,
  )
  const assignments = useMemo(
    () => (experience as { job_role_assignments?: JobRoleAssignment[] } | null)?.job_role_assignments || [],
    [experience],
  )
  const workspaceFromBootstrap = useMemo(
    () => (experience as { workspace_entries?: WorkspaceEntry[] } | null)?.workspace_entries || [],
    [experience],
  )

  // active 職能以 bootstrap 為準（後端持久化 users.active_job_role_id）
  const activeAssignment = useMemo(() => {
    if (!assignments.length) return null
    const serverActive = (
      experience as { active_job_role?: { id?: string } | null } | null
    )?.active_job_role
    if (serverActive?.id) {
      const found = assignments.find(a => a.id === serverActive.id)
      if (found) return found
    }
    return assignments.find(a => a.is_primary) || assignments[0]
  }, [assignments, experience])

  const entries = useMemo(() => {
    // 無職能指派 → 空態，禁止回退成全部功能（FALLBACK 僅供 bootstrap 尚未載入）
    if (needsJobRoleAssignment) return demoViewer ? DEMO_VIEWER_ENTRIES : []
    if (!workspaceFromBootstrap.length) return FALLBACK_ENTRIES
    if (!activeAssignment?.default_module_keys?.length) return workspaceFromBootstrap
    const allow = new Set(activeAssignment.default_module_keys)
    const filtered = workspaceFromBootstrap.filter(e => !e.module_key || allow.has(e.module_key))
    return filtered.length ? filtered : workspaceFromBootstrap
  }, [workspaceFromBootstrap, activeAssignment, needsJobRoleAssignment, demoViewer])

  const handleSwitchRole = async (assignmentId: string) => {
    const target = assignments.find(a => a.id === assignmentId)
    if (!target) return
    try {
      await api.post('/job-roles/active', { job_role_id: target.job_role_id })
      await refreshExperience?.()
    } catch {
      toast.error('切換職能失敗，請稍後再試')
    }
  }

  useEffect(() => {
    refreshExperience?.().catch(() => undefined)
  }, [refreshExperience])

  useEffect(() => {
    if (!canReview) return
    approvalsApi
      .inbox()
      .then(rows => setPendingApprovals(rows.length))
      .catch(() => setPendingApprovals(null))
  }, [canReview])

  useEffect(() => {
    formsApi
      .listInstances('draft,changes_requested,rejected,pending_review,pending_approval')
      .then(rows => setDraftCount(rows.length))
      .catch(() => setDraftCount(null))
  }, [])

  const handleVoiceResult = (result: TranscribeResponse) => {
    setVoiceResult(result)
  }

  const handleConfirmTranscript = async (editedText: string) => {
    if (!voiceResult) return
    setConfirming(true)
    try {
      await voiceApi.confirmTranscript(voiceResult.session_id, editedText)
      toast.success('已確認內容')
      const fields = voiceResult.detected_fields || {}
      const looksLikeQuote = Boolean(fields.customer || fields.part_number || fields.unit_price)
      if (looksLikeQuote) {
        navigate('/forms/quote', {
          state: { prefill: fields, transcript: editedText, scene },
        })
      } else {
        const q = new URLSearchParams({ q: editedText })
        if (scene) q.set('scene', JSON.stringify(scene))
        navigate(`/ask?${q.toString()}`)
      }
      setVoiceResult(null)
    } catch {
      toast.error('確認失敗，請檢查網路後再試一次')
    } finally {
      setConfirming(false)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col gap-5 overflow-y-auto p-4 pb-8">
      <header>
        <h1 className="text-2xl font-bold text-ink">
          {user?.full_name || '師傅'}，今天要做什麼？
        </h1>
        <p className="mt-1 text-lg text-muted">
          {demoViewer
            ? '主管檢視模式：只看合成知識與問答，不會修改資料。'
            : activeAssignment?.name
            ? `目前職能：${activeAssignment.name}。說話或掃碼就能開始。`
            : '說話或掃碼就能開始，不用打字。'}
        </p>
      </header>

      {assignments.length > 1 && (
        <label className="flex flex-col gap-1 text-base">
          <span className="font-medium text-ink">切換兼任職能</span>
          <select
            className="min-h-12 rounded-xl border-2 border-line bg-surface px-3 text-lg"
            value={activeAssignment?.id || ''}
            onChange={e => handleSwitchRole(e.target.value)}
          >
            {assignments.map(a => (
              <option key={a.id} value={a.id}>
                {a.name || a.role_key}
              </option>
            ))}
          </select>
        </label>
      )}

      {scene && <SceneContextBanner scene={scene} onClear={() => setScene(null)} />}

      {canReview && pendingApprovals !== null && pendingApprovals > 0 && (
        <button
          type="button"
          onClick={() => navigate('/approvals')}
          className="flex min-h-16 items-center justify-between rounded-xl border-2 border-amber-400 bg-amber-50 px-5 text-left active:scale-[0.99]"
        >
          <span className="flex items-center gap-3 text-xl font-bold text-amber-900">
            <ClipboardCheck className="h-7 w-7" aria-hidden />
            有 {pendingApprovals} 張單據等你審核
          </span>
          <span className="text-lg font-medium text-amber-700">前往 →</span>
        </button>
      )}

      {!demoViewer && draftCount !== null && (
        <button
          type="button"
          onClick={() => navigate('/forms/mine')}
          className="flex min-h-14 items-center justify-between rounded-xl border-2 border-line bg-surface px-5 text-left"
        >
          <span className="flex items-center gap-3 text-lg font-bold text-ink">
            <FileText className="h-6 w-6 text-accent" aria-hidden />
            我的表單
          </span>
          <span className="text-muted">
            {draftCount > 0 ? `${draftCount} 張待處理 · ` : ''}查看 →
          </span>
        </button>
      )}

      {voiceResult ? (
        <TranscriptEditor
          text={voiceResult.text}
          detectedFields={voiceResult.detected_fields}
          confidence={voiceResult.confidence}
          confirming={confirming}
          onConfirm={handleConfirmTranscript}
          onCancel={() => setVoiceResult(null)}
        />
      ) : (
        <section
          aria-label="語音輸入"
          className="flex flex-col items-center gap-2 rounded-2xl border-2 border-line bg-surface p-6 shadow-sm"
        >
          <PushToTalk
            sceneContext={scene}
            onResult={handleVoiceResult}
            onError={msg => toast.error(msg, { duration: 5000 })}
          />
          <p className="text-center text-base text-muted">
            例如：「幫台中精機報價，料號 P-100，兩百個，單價一百二」
          </p>
        </section>
      )}

      <QrScanner
        onResolved={s => {
          setScene(s)
          toast.success('已帶入作業場景')
        }}
        onError={msg => toast.error(msg, { duration: 5000 })}
      />

      {needsJobRoleAssignment && !demoViewer && (
        <section
          aria-label="等待指派職能"
          className="rounded-2xl border-2 border-dashed border-line bg-surface p-6 text-center"
        >
          <p className="text-xl font-bold text-ink">尚未指派職能</p>
          <p className="mt-2 text-base text-muted">
            請聯絡管理員在「職能管理」指派你的工作職能，指派後這裡會顯示你的專屬工作區。
          </p>
        </section>
      )}

      <nav aria-label="我的工作區" className="grid grid-cols-1 gap-3">
        {entries.map(entry => {
          const path = entry.path || '/ask'
          const Icon = path.includes('knowhow')
            ? BookOpen
            : path.includes('incident') || path.includes('repair')
              ? Wrench
              : FileText
          return (
            <button
              key={`${entry.module_key || 'x'}-${entry.key || path}`}
              type="button"
              onClick={() => navigate(path, { state: { scene } })}
              className="flex min-h-20 items-center gap-4 rounded-2xl border-2 border-line bg-surface px-5 text-left shadow-sm hover:border-accent active:scale-[0.99]"
            >
              <Icon className="h-9 w-9 shrink-0 text-accent" aria-hidden />
              <span>
                <span className="block text-xl font-bold text-ink">{entry.label || path}</span>
                <span className="block text-base text-muted">{entry.description || ''}</span>
              </span>
            </button>
          )
        })}

        <button
          type="button"
          onClick={() => navigate(scene ? `/ask?scene=${encodeURIComponent(JSON.stringify(scene))}` : '/ask')}
          className="flex min-h-20 items-center gap-4 rounded-2xl border-2 border-line bg-surface px-5 text-left shadow-sm hover:border-accent active:scale-[0.99]"
        >
          <MessageCircleQuestion className="h-9 w-9 shrink-0 text-accent" aria-hidden />
          <span>
            <span className="block text-xl font-bold text-ink">問知識庫</span>
            <span className="block text-base text-muted">SOP、規格、客戶資料；掃碼後會限定場景</span>
          </span>
        </button>
      </nav>
    </div>
  )
}
