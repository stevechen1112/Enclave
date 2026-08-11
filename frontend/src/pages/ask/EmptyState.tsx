import { MessageSquare, FlaskConical, ArrowRight } from 'lucide-react'

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
    <div className="flex h-full animate-rise-in flex-col items-center justify-center px-4 py-8">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft">
        {testMode ? (
          <FlaskConical className="h-7 w-7 text-accent" aria-hidden />
        ) : (
          <MessageSquare className="h-7 w-7 text-accent" aria-hidden />
        )}
      </div>
      <h3 className="mt-4 font-display text-xl font-semibold text-ink">
        {testMode
          ? '測試知識'
          : userName
            ? `${userName}，開始提問`
            : '開始提問'}
      </h3>
      <p className="mt-2 max-w-md text-center text-sm leading-relaxed text-muted">
        {testMode
          ? '用範例驗證證據鏈與生命週期是否正確；答案仍須附上可核對來源。'
          : '用自然語言詢問企業知識。每則答案會附上可核對的證據來源。'}
      </p>
      <p className="mt-8 text-xs font-semibold text-muted">範例問題（非依你的企業知識動態產生）</p>
      <div className="mt-3 grid w-full max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
        {examples.map(q => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="card-interactive group flex min-h-11 items-center justify-between gap-2 px-4 py-3 text-left text-sm text-ink"
          >
            <span>{q}</span>
            <ArrowRight
              className="h-4 w-4 shrink-0 text-muted transition-colors group-hover:text-accent"
              aria-hidden
            />
          </button>
        ))}
      </div>
    </div>
  )
}
