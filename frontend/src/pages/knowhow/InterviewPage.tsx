import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import PageHeader from '../../components/PageHeader'
import LongInterviewRecorder from '../../components/mka/LongInterviewRecorder'
import api from '../../api'
import { captureApi, type CaptureSessionInfo } from '../../platform/input/captureApi'

const CAPTURE_STATUS_LABEL: Record<string, string> = {
  recording: '錄音中',
  uploading: '安全上傳中',
  queued: '等待轉寫',
  transcribing: '正在轉寫',
  ready_for_review: '逐字稿待校正',
  failed: '轉寫失敗',
}

export default function InterviewPage() {
  const navigate = useNavigate()
  const [consent, setConsent] = useState(false)
  const [title, setTitle] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [transcript, setTranscript] = useState('')
  const [capture, setCapture] = useState<CaptureSessionInfo | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [extracted, setExtracted] = useState<Record<string, unknown> | null>(null)
  const notifiedReadyRef = useRef(false)

  useEffect(() => {
    if (!capture || !['queued', 'transcribing'].includes(capture.status)) return
    const check = async () => {
      try {
        const latest = await captureApi.get(capture.id)
        setCapture(latest)
        if (latest.status === 'ready_for_review') {
          const result = await captureApi.transcript(latest.id)
          const completedTranscript = result.transcript || ''
          setTranscript(completedTranscript)
          if (!notifiedReadyRef.current) {
            notifiedReadyRef.current = true
            if (completedTranscript.trim()) {
              toast.success('逐字稿已完成，請校正後建立知識草稿。')
            } else {
              toast('轉寫已完成，但未辨識到語音內容；請重新錄音或貼上逐字稿。', { icon: '⚠️', duration: 6000 })
            }
          }
        }
        if (latest.status === 'failed') toast.error('訪談轉寫失敗，請按重試或聯絡管理員。')
      } catch {
        // Keep the durable capture visible. The next polling cycle can recover.
      }
    }
    void check()
    const timer = window.setInterval(() => { void check() }, 5000)
    return () => window.clearInterval(timer)
  }, [capture])

  const handleExtract = async () => {
    if (!consent) {
      toast.error('請先確認已取得受訪者錄音與知識整理同意。')
      return
    }
    if (!transcript.trim()) {
      toast.error('請先完成訪談轉寫，或貼上既有逐字稿。')
      return
    }
    setSubmitting(true)
    try {
      const { data } = await api.post('/knowhow/interview/extract', {
        transcript,
        title: title || undefined,
        equipment_id: equipmentId || undefined,
        consent: true,
        session_id: capture?.id,
      })
      setExtracted(data.extracted || null)
      toast.success('已建立知識卡草稿，接著請檢查內容並送審。')
      if (data.card_id) navigate(`/knowhow/${data.card_id}`)
    } catch {
      toast.error('建立知識草稿失敗，請稍後再試。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-2xl space-y-4">
        <PageHeader
          title="師傅訪談與知識傳承"
          subtitle="可直接在手機錄音；系統會安全上傳、轉寫並建立可送審的知識草稿。"
        />

        <label className="flex items-start gap-3 rounded-xl border border-line bg-surface p-4">
          <input
            type="checkbox"
            checked={consent}
            onChange={event => setConsent(event.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span className="text-sm text-ink">
            我已取得受訪者同意錄音，並了解錄音會用於逐字稿、知識草稿及後續審核；音訊與逐字稿將依本租戶的資料保留政策處理。
          </span>
        </label>

        <div className="grid gap-3 sm:grid-cols-2">
          <input
            className="w-full rounded-xl border border-line px-3 py-2"
            placeholder="訪談主題，例如：換模設定與異常判斷"
            value={title}
            onChange={event => setTitle(event.target.value)}
          />
          <input
            className="w-full rounded-xl border border-line px-3 py-2"
            placeholder="設備 ID（選填）"
            value={equipmentId}
            onChange={event => setEquipmentId(event.target.value)}
          />
        </div>

        <LongInterviewRecorder
          title={title}
          equipmentId={equipmentId}
          disabled={!consent}
          captureStatus={capture?.status}
          onQueued={session => {
            notifiedReadyRef.current = false
            setCapture(session)
          }}
          onError={message => toast.error(message)}
        />

        {capture && (
          <div className="rounded-xl border border-line bg-surface p-3 text-sm text-muted">
            訪談狀態：<span className="font-medium text-ink">{CAPTURE_STATUS_LABEL[capture.status] || '處理中'}</span>
            {capture.status === 'failed' && (
              <button type="button" className="ml-3 text-accent underline" onClick={() => void captureApi.retry(capture.id).then(setCapture).catch(() => toast.error('無法重新排入轉寫'))}>
                重新排入轉寫
              </button>
            )}
          </div>
        )}

        <div>
          <label className="mb-2 block text-sm font-medium text-ink">逐字稿（可直接校正，也可貼上既有逐字稿）</label>
          <textarea
            className="min-h-56 w-full rounded-xl border border-line px-3 py-2"
            placeholder="完成訪談後，逐字稿會自動帶入這裡。"
            value={transcript}
            onChange={event => setTranscript(event.target.value)}
          />
        </div>

        <button
          type="button"
          disabled={submitting || !consent || !transcript.trim()}
          onClick={handleExtract}
          className="rounded-xl bg-accent px-5 py-3 font-semibold text-white disabled:opacity-50"
        >
          {submitting ? '正在建立草稿…' : '建立知識卡草稿'}
        </button>

        {extracted && (
          <pre className="overflow-x-auto rounded-xl border border-line bg-surface p-3 text-xs text-muted">
            {JSON.stringify(extracted, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}
