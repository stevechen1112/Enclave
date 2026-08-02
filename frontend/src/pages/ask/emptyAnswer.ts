/**
 * Map retrieval / sources / error signals → UIUX §9.4 empty-answer categories.
 * Only use structured signals — never scan LLM answer body (false positives).
 */
import type { ChatSource, RetrievalInfo } from '../../types'

export type EmptyAnswerKind =
  | 'no_evidence'
  | 'no_permission'
  | 'source_processing'
  | 'system_unavailable'

export const EMPTY_ANSWER_LABEL: Record<EmptyAnswerKind, { title: string; description: string }> = {
  no_evidence: {
    title: '無相關證據',
    description: '目前可存取知識中找不到足以支撐回答的證據。請改問法，或確認文件是否已入庫。',
  },
  no_permission: {
    title: '無權限',
    description: '相關內容可能存在，但你目前的角色／部門看不到。請向管理員申請存取。',
  },
  source_processing: {
    title: '來源處理中',
    description: '文件可能仍在解析、嵌入或審核中，稍後再問或到知識頁查看生命週期。',
  },
  system_unavailable: {
    title: '系統暫時不可用',
    description: '檢索或回答服務異常。請稍後重試；若持續發生，請查看系統健康。',
  },
}

export function classifyEmptyAnswer(opts: {
  sources?: ChatSource[] | null
  retrieval?: RetrievalInfo | null
  hadError?: boolean
}): EmptyAnswerKind | null {
  if ((opts.sources?.length ?? 0) > 0) return null

  if (opts.hadError || opts.retrieval?.mode === 'error') {
    return 'system_unavailable'
  }

  const signal = `${opts.retrieval?.mode || ''} ${opts.retrieval?.label || ''}`

  if (/權限|無權|permission|forbidden|403|不可見|不可存取/i.test(signal)) {
    return 'no_permission'
  }

  if (/處理中|審核中|indexing|embedding|parsing|pending|同步中/i.test(signal)) {
    return 'source_processing'
  }

  return 'no_evidence'
}
