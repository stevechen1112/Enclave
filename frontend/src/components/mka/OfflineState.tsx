/**
 * OfflineState — 離線/弱網狀態提示（§6.7）。
 *
 * 顯示網路狀態、離線時可用的功能、建議動作。
 */
import { Wifi, WifiOff, CloudOff } from 'lucide-react'
import clsx from 'clsx'

interface OfflineStateProps {
  online: boolean
  weakNetwork?: boolean
  lastSyncAt?: string
}

export default function OfflineState({ online, weakNetwork, lastSyncAt }: OfflineStateProps) {
  if (online && !weakNetwork) return null

  return (
    <div
      className={clsx(
        'flex items-center gap-3 rounded-xl border-2 px-4 py-3',
        !online
          ? 'border-amber-400 bg-amber-50'
          : 'border-amber-300 bg-amber-50/50',
      )}
      role="alert"
    >
      {!online ? (
        <WifiOff className="h-6 w-6 shrink-0 text-amber-600" aria-hidden />
      ) : (
        <CloudOff className="h-6 w-6 shrink-0 text-amber-500" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-base font-bold text-amber-900">
          {!online ? '目前離線' : '網路不穩定'}
        </p>
        <p className="text-sm text-amber-700">
          {!online
            ? '語音輸入與表單填寫仍可使用，送出與查詢將在連線恢復後自動處理。'
            : '部分功能可能延遲，請稍候。'}
        </p>
        {lastSyncAt && (
          <p className="mt-0.5 text-xs text-amber-600">
            上次同步：{lastSyncAt}
          </p>
        )}
      </div>
      {!online && (
        <Wifi className="h-5 w-5 shrink-0 animate-pulse text-amber-400" aria-hidden />
      )}
    </div>
  )
}
