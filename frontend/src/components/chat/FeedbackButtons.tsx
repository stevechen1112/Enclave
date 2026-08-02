import { useState } from 'react'
import { ThumbsUp, ThumbsDown } from 'lucide-react'
import { chatApi, parseApiError, formatErrorWithTrace } from '../../api'
import clsx from 'clsx'
import toast from 'react-hot-toast'

interface Props {
  messageId: string
  initialFeedback?: 'up' | 'down' | null
}

const DOWN_CATEGORIES = [
  { id: 'stale_source', label: '來源已過期' },
  { id: 'wrong_answer', label: '答案不正確' },
  { id: 'missing_evidence', label: '證據不足' },
  { id: 'other', label: '其他' },
]

export default function FeedbackButtons({ messageId, initialFeedback = null }: Props) {
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(initialFeedback)
  const [submitting, setSubmitting] = useState(false)
  const [showCats, setShowCats] = useState(false)

  const submit = async (type: 'up' | 'down', category?: string) => {
    if (submitting) return
    setSubmitting(true)
    try {
      await chatApi.submitFeedback({
        message_id: messageId,
        rating: type === 'up' ? 2 : 1,
        category: category || null,
      })
      setFeedback(type)
      setShowCats(false)
      toast.success('已送出回饋')
    } catch (err) {
      toast.error(formatErrorWithTrace(parseApiError(err, '回饋提交失敗')))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mt-1">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => submit('up')}
          disabled={submitting}
          className={clsx(
            'min-h-11 min-w-11 rounded p-2 transition-colors',
            feedback === 'up'
              ? 'bg-green-50 text-green-600'
              : 'text-gray-300 hover:bg-green-50 hover:text-green-500',
          )}
          aria-label="有幫助"
          aria-pressed={feedback === 'up'}
        >
          <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => setShowCats(v => !v)}
          disabled={submitting}
          className={clsx(
            'min-h-11 min-w-11 rounded p-2 transition-colors',
            feedback === 'down'
              ? 'bg-red-50 text-red-500'
              : 'text-gray-300 hover:bg-red-50 hover:text-red-400',
          )}
          aria-label="需要改善"
          aria-pressed={feedback === 'down'}
          aria-expanded={showCats}
        >
          <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      {showCats && (
        <div className="mt-1 flex flex-wrap gap-1" role="group" aria-label="負評原因">
          {DOWN_CATEGORIES.map(c => (
            <button
              key={c.id}
              type="button"
              disabled={submitting}
              onClick={() => submit('down', c.id)}
              className="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted hover:border-accent hover:text-accent"
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
