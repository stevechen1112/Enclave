import { Loader2, CheckCircle, AlertCircle } from 'lucide-react'

import type { ImportResult } from './types'

interface ImportingProps {
  progress: { done: number; total: number }
}

export function WizardStepImporting({ progress }: ImportingProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-sm rounded-xl bg-white p-8 shadow-xl text-center">
        <Loader2 className="mx-auto mb-4 h-10 w-10 animate-spin text-blue-500" />
        <h3 className="mb-2 text-base font-semibold text-gray-900">匯入中，請稍候…</h3>
        <p className="mb-3 text-2xl font-bold text-blue-600">
          {progress.done} / {progress.total}
        </p>
        <div className="h-2 overflow-hidden rounded-full bg-gray-100">
          <div
            className="h-full bg-blue-500 transition-all duration-300"
            style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }}
          />
        </div>
        <p className="mt-3 text-xs text-gray-400">請勿關閉此視窗</p>
      </div>
    </div>
  )
}

interface DoneProps {
  result: ImportResult | null
  onClose: () => void
}

export function WizardStepDone({ result, onClose }: DoneProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-sm rounded-xl bg-white p-8 shadow-xl text-center">
        {result && result.failed === 0 ? (
          <>
            <CheckCircle className="mx-auto mb-4 h-12 w-12 text-green-500" />
            <h3 className="mb-2 text-base font-semibold text-gray-900">匯入完成！</h3>
            <p className="mb-5 text-2xl font-bold text-green-600">
              {result.succeeded} 個檔案成功上傳
            </p>
          </>
        ) : (
          <>
            <AlertCircle className="mx-auto mb-4 h-12 w-12 text-amber-500" />
            <h3 className="mb-2 text-base font-semibold text-gray-900">匯入完成（部分失敗）</h3>
            <div className="mb-5 space-y-0.5">
              <p className="text-lg font-bold text-green-600">✓ 成功 {result?.succeeded ?? 0} 個</p>
              <p className="text-lg font-bold text-red-500">✗ 失敗 {result?.failed ?? 0} 個</p>
            </div>
            {result && result.failedFiles.length > 0 && (
              <details className="mb-4 rounded-lg border border-red-100 bg-red-50 p-3 text-left">
                <summary className="cursor-pointer text-xs font-medium text-red-600">查看失敗檔案清單</summary>
                <ul className="mt-2 max-h-36 space-y-0.5 overflow-y-auto">
                  {result.failedFiles.map((f, i) => (
                    <li key={i} className="truncate text-xs text-red-500" title={f.reason}>
                      {f.name}{f.reason ? ` — ${f.reason}` : ''}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
        <button
          onClick={onClose}
          className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          關閉
        </button>
      </div>
    </div>
  )
}
