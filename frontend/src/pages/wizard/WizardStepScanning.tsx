import { Loader2 } from 'lucide-react'

interface Props {
  scanStatus: { current: string; done: number; total: number }
}

export default function WizardStepScanning({ scanStatus }: Props) {
  return (
    <div className="fixed bottom-6 right-6 z-50 w-80 rounded-xl border border-blue-100 bg-white p-4 shadow-2xl">
      <div className="flex items-start gap-3">
        <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-blue-500" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-gray-900">AI 正在分析資料夾…</p>
          {scanStatus.total > 0 && (
            <p className="mt-0.5 text-xs text-gray-500">
              {scanStatus.done + 1} / {scanStatus.total}
              {scanStatus.current && (
                <span className="ml-1 font-medium text-blue-600 truncate">{scanStatus.current}</span>
              )}
            </p>
          )}
          {/* progress bar */}
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100">
            <div
              className="h-full bg-blue-500 transition-all duration-500"
              style={{ width: `${scanStatus.total ? ((scanStatus.done) / scanStatus.total) * 100 : 5}%` }}
            />
          </div>
          <p className="mt-1.5 text-xs text-gray-400">您可以繼續在其他頁面工作，完成後將自動彈出確認視窗</p>
        </div>
      </div>
    </div>
  )
}
