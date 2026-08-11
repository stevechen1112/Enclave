/**
 * 訪談模式：同意 → 貼上／語音轉寫 → 提取步驟／風險 → 建立知識卡草稿。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import PageHeader from '../../components/PageHeader'
import api from '../../api'

export default function InterviewPage() {
  const navigate = useNavigate()
  const [consent, setConsent] = useState(false)
  const [title, setTitle] = useState('')
  const [equipmentId, setEquipmentId] = useState('')
  const [transcript, setTranscript] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [extracted, setExtracted] = useState<Record<string, unknown> | null>(null)

  const handleExtract = async () => {
    if (!consent) {
      toast.error('請先取得受訪者錄音／使用同意')
      return
    }
    if (!transcript.trim()) {
      toast.error('請先輸入訪談內容')
      return
    }
    setSubmitting(true)
    try {
      const { data } = await api.post('/knowhow/interview/extract', {
        transcript,
        title: title || undefined,
        equipment_id: equipmentId || undefined,
        consent: true,
      })
      setExtracted(data.extracted || null)
      toast.success('已建立草稿知識卡')
      if (data.card_id) {
        navigate(`/knowhow/${data.card_id}`)
      }
    } catch {
      toast.error('提取失敗')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto max-w-2xl space-y-4">
        <PageHeader
          variant="section"
          title="訪談建卡"
          subtitle="錄音同意 → 轉寫 → 主題分段 → 步驟／條件／風險／例外提取 → 人工編輯 → 送審。"
        />
        <label className="flex items-start gap-3 rounded-xl border border-line bg-surface p-4">
          <input
            type="checkbox"
            checked={consent}
            onChange={e => setConsent(e.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span className="text-sm text-ink">
            已取得受訪者同意（錄音／轉寫用於知識傳承，並依租戶保留政策處理）。未勾選不得建卡。
          </span>
        </label>
        <input
          className="w-full rounded-xl border border-line px-3 py-2"
          placeholder="標題（可留空自動取第一句）"
          value={title}
          onChange={e => setTitle(e.target.value)}
        />
        <input
          className="w-full rounded-xl border border-line px-3 py-2"
          placeholder="適用設備編號（選填）"
          value={equipmentId}
          onChange={e => setEquipmentId(e.target.value)}
        />
        <textarea
          className="min-h-48 w-full rounded-xl border border-line px-3 py-2"
          placeholder="貼上訪談轉寫或分段描述…"
          value={transcript}
          onChange={e => setTranscript(e.target.value)}
        />
        <button
          type="button"
          disabled={submitting}
          onClick={handleExtract}
          className="rounded-xl bg-accent px-5 py-3 font-semibold text-white disabled:opacity-50"
        >
          {submitting ? '處理中…' : '提取並建立草稿'}
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