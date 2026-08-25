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
  { id: 'wrong_entity', label: '對象不對' },
  { id: 'wrong_number', label: '數字不對' },
  { id: 'wrong_version', label: '版本不對' },
  { id: 'wrong_source', label: '來源不對' },
  { id: 'incomplete', label: '回答不完整' },
  { id: 'unclear', label: '看不懂' },
  { id: 'should_abstain', label: '不該回答' },
  { id: 'false_abstain', label: '有資料卻沒回答' },
  { id: 'permission', label: '權限問題' },
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
            'icon-btn',
            feedback === 'up'
              ? 'bg-success-soft text-success hover:bg-success-soft hover:text-success'
              : 'hover:text-success',
          )}
          aria-label="有幫助"
          aria-pressed={feedback === 'up'}
        >
          <ThumbsUp className="h-4 w-4" aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => setShowCats(v => !v)}
          disabled={submitting}
          className={clsx(
            'icon-btn',
            feedback === 'down'
              ? 'bg-danger-soft text-danger hover:bg-danger-soft hover:text-danger'
              : 'hover:text-danger',
          )}
          aria-label="需要改善"
          aria-pressed={feedback === 'down'}
          aria-expanded={showCats}
        >
          <ThumbsDown className="h-4 w-4" aria-hidden />
        </button>
        {feedback && (
          <span className="ml-1 text-xs text-muted">感謝回饋</span>
        )}
      </div>
      {showCats && (
        <div className="mt-2 flex animate-fade-in flex-wrap gap-2" role="group" aria-label="負評原因">
          {DOWN_CATEGORIES.map(c => (
            <button
              key={c.id}
              type="button"
              disabled={submitting}
              onClick={() => submit('down', c.id)}
              className="inline-flex min-h-11 items-center rounded-full border border-line bg-surface px-4 text-sm font-semibold text-muted transition-colors hover:border-accent/50 hover:bg-accent-soft/40 hover:text-accent-ink"
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
