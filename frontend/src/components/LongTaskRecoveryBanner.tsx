import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock3, X } from 'lucide-react'

import {
  forgetKnowledgeTask,
  recoverableKnowledgeTasks,
  type RecoverableKnowledgeTask,
} from '../lib/longTaskRecovery'

export default function LongTaskRecoveryBanner() {
  const [task, setTask] = useState<RecoverableKnowledgeTask | null>(() =>
    recoverableKnowledgeTasks()[0] || null,
  )

  useEffect(() => {
    const refresh = () => setTask(recoverableKnowledgeTasks()[0] || null)
    window.addEventListener('storage', refresh)
    window.addEventListener('enclave:long-task', refresh)
    return () => {
      window.removeEventListener('storage', refresh)
      window.removeEventListener('enclave:long-task', refresh)
    }
  }, [])

  if (!task) return null
  return (
    <div role="status" className="flex min-h-11 items-center gap-2 border-b border-accent/20 bg-accent-soft px-4 py-2 text-sm text-accent-ink">
      <Clock3 className="h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate">
        背景處理可繼續追蹤：<strong>{task.title}</strong>
      </span>
      <Link className="shrink-0 font-semibold underline underline-offset-2" to={`/knowledge/assets/${task.assetId}`}>
        查看進度
      </Link>
      <button
        type="button"
        className="icon-btn min-h-9 min-w-9"
        aria-label="關閉背景處理提示"
        onClick={() => forgetKnowledgeTask(task.assetId)}
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  )
}
