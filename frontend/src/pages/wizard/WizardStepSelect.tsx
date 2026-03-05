import { useRef } from 'react'
import { FolderOpen, Trash2, Settings, Loader2 } from 'lucide-react'

import type { AddedFolder, FileWithPath } from './types'

interface Props {
  addedFolders: AddedFolder[]
  setAddedFolders: React.Dispatch<React.SetStateAction<AddedFolder[]>>
  totalFiles: number
  scanError: string
  onScan: () => void
  onClose: () => void
  supportedExtsReady: boolean
}

export default function WizardStepSelect({
  addedFolders, setAddedFolders, totalFiles, scanError, onScan, onClose, supportedExtsReady,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const handleAddFolder = (files: FileList | null) => {
    if (!files || files.length === 0) return
    const arr = Array.from(files) as FileWithPath[]
    const root = arr[0]?.webkitRelativePath?.split('/')[0] || arr[0]?.name || 'folder'
    setAddedFolders(prev => [
      ...prev.filter(f => f.rootName !== root),
      { id: crypto.randomUUID(), rootName: root, files: arr },
    ])
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <h2 className="mb-1 text-lg font-semibold text-gray-900">匯入本機資料夾</h2>
        <p className="mb-4 text-sm text-gray-500">可新增多個資料夾，AI 掃描後產生摘要供您逐一確認</p>

        <input
          ref={fileInputRef} type="file" multiple className="hidden"
          onChange={e => { handleAddFolder(e.target.files); e.currentTarget.value = '' }}
          {...({ webkitdirectory: '', directory: '' } as any)}
        />

        <button
          onClick={() => fileInputRef.current?.click()}
          className="mb-4 flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-blue-300 bg-blue-50 px-4 py-3 text-sm text-blue-600 hover:bg-blue-100"
        >
          <FolderOpen className="h-5 w-5" /> 點擊選擇資料夾（可多次點擊新增不同資料夾）
        </button>

        {addedFolders.length > 0 && (
          <div className="mb-4 max-h-48 space-y-1.5 overflow-y-auto">
            {addedFolders.map(f => (
              <div key={f.id} className="flex items-center justify-between rounded-lg border bg-gray-50 px-3 py-2">
                <div className="flex items-center gap-2 text-sm">
                  <FolderOpen className="h-4 w-4 shrink-0 text-amber-500" />
                  <span className="font-medium text-gray-800">{f.rootName}</span>
                  <span className="text-gray-400">— {f.files.length} 個檔案</span>
                </div>
                <button
                  onClick={() => setAddedFolders(p => p.filter(x => x.id !== f.id))}
                  className="ml-2 text-gray-400 hover:text-red-500"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            <p className="pl-1 text-xs text-gray-400">共 {totalFiles} 個檔案</p>
          </div>
        )}

        {scanError && (
          <p className="mb-3 rounded bg-red-50 px-2 py-1.5 text-xs text-red-600">{scanError}</p>
        )}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border px-4 py-2 text-sm hover:bg-gray-50">
            取消
          </button>
          <button
            onClick={onScan}
            disabled={addedFolders.length === 0 || !supportedExtsReady}
            className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {!supportedExtsReady ? <Loader2 className="h-4 w-4 animate-spin" /> : <Settings className="h-4 w-4" />}
            {!supportedExtsReady ? '載入格式中…' : '開始 AI 掃描'}
          </button>
        </div>
      </div>
    </div>
  )
}
