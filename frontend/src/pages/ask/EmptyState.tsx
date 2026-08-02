import { MessageSquare, FlaskConical } from 'lucide-react'

const DEFAULT_EXAMPLES = [
  '這份知識庫裡有哪些政策文件？',
  '請摘要最近更新的規範重點',
  '某某流程的負責單位是誰？',
  '這份文件最後是什麼時候更新的？',
]

const TEST_EXAMPLES = [
  '這份文件的證據來源與版本是什麼？',
  '剛入庫的規範目前是什麼生命週期狀態？',
  '撤銷後這份知識還會出現在問答嗎？',
  '請指出回答所依據的段落與更新時間',
]

type Props = {
  userName?: string | null
  testMode: boolean
  onPick: (q: string) => void
}

export default function EmptyState({ userName, testMode, onPick }: Props) {
  const examples = testMode ? TEST_EXAMPLES : DEFAULT_EXAMPLES
  return (
    <div className="flex h-full flex-col items-center justify-center text-muted px-4">
      {testMode ? (
        <FlaskConical className="mb-4 h-12 w-12 text-accent/50" aria-hidden />
      ) : (
        <MessageSquare className="mb-4 h-12 w-12 text-accent/40" aria-hidden />
      )}
      <h3 className="font-display text-lg font-semibold text-ink">
        {testMode
          ? '測試知識'
          : userName
            ? `${userName}，開始提問`
            : '開始提問'}
      </h3>
      <p className="mt-1 max-w-md text-center text-sm">
        {testMode
          ? '用範例驗證證據鏈與生命週期是否正確；答案仍須附上可核對來源。'
          : '用自然語言詢問企業知識。每則答案會附上可核對的證據來源。'}
      </p>
      <p className="mt-6 text-xs text-muted">範例問題（非依你的企業知識動態產生）</p>
      <div className="mt-2 grid max-w-lg grid-cols-1 gap-3 sm:grid-cols-2">
        {examples.map(q => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="rounded-xl border border-line bg-surface px-4 py-3 text-left text-sm text-ink transition-colors hover:border-accent/40 hover:bg-wash min-h-11"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
