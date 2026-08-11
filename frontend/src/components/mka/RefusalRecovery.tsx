/**
 * RefusalRecovery — 拒答後的安全下一步引導（§6.6）。
 *
 * 拒答不可只說「找不到」，應提供安全下一步：
 * - 建議改用哪個場景
 * - 缺哪份文件
 * - 是否可請 owner 補充
 * - 是否建立待辦
 */
import { SearchX, FileQuestion, UserPlus, ListTodo, ArrowRight } from 'lucide-react'

interface RefusalRecoveryProps {
  reason: string
  suggestions?: string[]
  missingDocuments?: string[]
  onSwitchScene?: () => void
  onRequestDocument?: () => void
  onCreateTodo?: () => void
}

export default function RefusalRecovery({
  reason,
  suggestions,
  missingDocuments,
  onSwitchScene,
  onRequestDocument,
  onCreateTodo,
}: RefusalRecoveryProps) {
  return (
    <div className="rounded-2xl border-2 border-line bg-surface p-5" role="alert">
      <div className="mb-3 flex items-center gap-2">
        <SearchX className="h-6 w-6 text-muted" aria-hidden />
        <h3 className="text-xl font-bold text-ink">目前無法回答</h3>
      </div>
      <p className="mb-4 text-base text-muted">{reason}</p>

      {suggestions && suggestions.length > 0 && (
        <div className="mb-3">
          <p className="text-base font-bold text-ink">建議嘗試：</p>
          <ul className="mt-1 space-y-1">
            {suggestions.map((s, i) => (
              <li key={i} className="flex items-center gap-2 text-base text-ink">
                <ArrowRight className="h-4 w-4 text-accent" aria-hidden />
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {missingDocuments && missingDocuments.length > 0 && (
        <div className="mb-4 rounded-xl bg-amber-50 p-3">
          <p className="flex items-center gap-1 text-base font-bold text-amber-900">
            <FileQuestion className="h-5 w-5" aria-hidden />
            缺少以下文件
          </p>
          <ul className="mt-1 list-disc pl-6 text-base text-amber-800">
            {missingDocuments.map((doc, i) => (
              <li key={i}>{doc}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {onSwitchScene && (
          <button
            type="button"
            onClick={onSwitchScene}
            className="rounded-xl border-2 border-accent bg-white px-4 py-2.5 text-base font-bold text-accent hover:bg-accent/5 active:scale-95"
          >
            切換場景再試
          </button>
        )}
        {onRequestDocument && (
          <button
            type="button"
            onClick={onRequestDocument}
            className="rounded-xl border-2 border-line bg-white px-4 py-2.5 text-base font-bold text-ink hover:bg-wash active:scale-95"
          >
            <UserPlus className="mr-1 inline h-5 w-5" aria-hidden />
            請文件 owner 補充
          </button>
        )}
        {onCreateTodo && (
          <button
            type="button"
            onClick={onCreateTodo}
            className="rounded-xl border-2 border-line bg-white px-4 py-2.5 text-base font-bold text-ink hover:bg-wash active:scale-95"
          >
            <ListTodo className="mr-1 inline h-5 w-5" aria-hidden />
            建立待辦追蹤
          </button>
        )}
      </div>
    </div>
  )
}
