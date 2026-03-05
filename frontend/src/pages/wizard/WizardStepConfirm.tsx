import { FolderOpen, Plus } from 'lucide-react'
import clsx from 'clsx'

import type { SubfolderRow, SkippedInfo } from './types'

const SUMMARY_THRESHOLD = 100 // chars before showing expand toggle

interface Props {
  subfolders: SubfolderRow[]
  setSubfolders: React.Dispatch<React.SetStateAction<SubfolderRow[]>>
  selectedFileCount: number
  skippedInfo: SkippedInfo
  onImport: () => void
  onBack: () => void
}

export default function WizardStepConfirm({
  subfolders, setSubfolders, selectedFileCount, skippedInfo, onImport, onBack,
}: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[92vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">確認要匯入的子資料夾</h2>
            <p className="text-sm text-gray-500">勾選後將批次上傳至知識庫（不勾選的資料夾將略過）</p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <button
              onClick={() => setSubfolders(p => p.map(s => ({ ...s, selected: true })))}
              className="text-blue-600 hover:underline"
            >全選</button>
            <span className="text-gray-300">|</span>
            <button
              onClick={() => setSubfolders(p => p.map(s => ({ ...s, selected: false })))}
              className="text-gray-500 hover:underline"
            >取消全選</button>
            <span className="text-gray-300">|</span>
            <button
              onClick={() => setSubfolders(p => p.map(s => ({ ...s, expanded: true })))}
              className="text-gray-500 hover:underline"
            >展開全部</button>
            <span className="text-gray-300">|</span>
            <button
              onClick={() => setSubfolders(p => p.map(s => ({ ...s, expanded: false })))}
              className="text-gray-500 hover:underline"
            >收合全部</button>
          </div>
        </div>

        {/* Subfolder list */}
        <div className="flex-1 space-y-2 overflow-y-auto px-6 py-3">
          {subfolders.map(sf => {
            const isLong = sf.summary.length > SUMMARY_THRESHOLD
            const showFull = sf.expanded || !isLong
            return (
              <div
                key={sf.path}
                style={{ marginLeft: `${sf.depth * 16}px` }}
                className={clsx(
                  'rounded-lg border transition',
                  sf.selected ? 'border-blue-200 bg-blue-50' : 'border-gray-100 bg-white hover:bg-gray-50'
                )}
              >
                {/* Row header — checkbox + name */}
                <label className="flex cursor-pointer items-start gap-3 p-3">
                  <input
                    type="checkbox"
                    checked={sf.selected}
                    onChange={() => setSubfolders(p => p.map(s => s.path === sf.path ? { ...s, selected: !s.selected } : s))}
                    className="mt-0.5 shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <FolderOpen className="h-4 w-4 shrink-0 text-amber-500" />
                      <span className="truncate text-sm font-medium text-gray-900">{sf.name}</span>
                      <span className="shrink-0 text-xs text-gray-400">{sf.fileCount} 個檔案</span>
                      {sf.hasContentSamples && (
                        <span className="shrink-0 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                          內容取樣
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 font-mono text-xs text-gray-400">{sf.path}</p>
                  </div>
                </label>

                {/* Summary section below */}
                {sf.summary && (
                  <div className="border-t border-gray-100 px-3 pb-3 pt-2">
                    <p className={clsx(
                      'text-sm leading-relaxed text-gray-700',
                      !showFull && 'line-clamp-2'
                    )}>
                      {sf.summary}
                    </p>
                    {isLong && (
                      <button
                        onClick={() => setSubfolders(p => p.map(s => s.path === sf.path ? { ...s, expanded: !s.expanded } : s))}
                        className="mt-1 text-xs text-blue-500 hover:underline"
                      >
                        {sf.expanded ? '▲ 收合' : '▼ 展開完整摘要'}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div className="flex shrink-0 flex-col gap-2 border-t px-6 py-4">
          {skippedInfo.count > 0 && (
            <p className="text-xs text-amber-600">
              ⚠️ 已略過 <span className="font-semibold">{skippedInfo.count}</span> 個後端不支援格式的檔案
              {skippedInfo.exts.length > 0 && (
                <span className="ml-1 text-amber-500">
                  （{skippedInfo.exts.join('、')}）
                </span>
              )}
            </p>
          )}
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-500">
              已選 <span className="font-semibold text-blue-600">{subfolders.filter(s => s.selected).length}</span> 個資料夾，
              共 <span className="font-semibold text-blue-600">{selectedFileCount}</span> 個檔案
            </p>
            <div className="flex gap-2">
              <button onClick={onBack} className="rounded-lg border px-4 py-2 text-sm hover:bg-gray-50">
                返回
              </button>
              <button
                onClick={onImport}
                disabled={selectedFileCount === 0}
                className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                <Plus className="h-4 w-4" /> 確認匯入（{selectedFileCount} 個檔案）
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
