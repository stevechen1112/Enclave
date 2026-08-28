import { useEffect, useState } from 'react'
import { CloudOff } from 'lucide-react'

export default function ConnectivityBanner() {
  const [online, setOnline] = useState(() =>
    typeof navigator === 'undefined' ? true : navigator.onLine,
  )

  useEffect(() => {
    const onOnline = () => setOnline(true)
    const onOffline = () => setOnline(false)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  if (online) return null
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-11 items-center justify-center gap-2 border-b border-highlight/30 bg-highlight-soft px-4 py-2 text-sm font-medium text-highlight"
    >
      <CloudOff className="h-4 w-4 shrink-0" aria-hidden />
      裝置目前離線。已載入內容仍可查看；需要連線的操作會在恢復網路後重試。
    </div>
  )
}
