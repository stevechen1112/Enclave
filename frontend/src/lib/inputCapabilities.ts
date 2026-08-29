import type { Accept } from 'react-dropzone'
import type { InputCapabilityContract, InputFormatCapability } from '../types'

export type FilePreflight = {
  capability?: InputFormatCapability
  error?: string
  warning?: string
}

export function fileExtension(name: string): string {
  const match = /(?:^|\/)([^/]+?)(\.[^./]+)$/.exec(name)
  return match?.[2]?.toLowerCase() || ''
}

export function buildDropAccept(contract?: InputCapabilityContract): Accept {
  const accept: Accept = {}
  for (const format of contract?.formats || []) {
    if (format.processing_status === 'disabled' || !format.ui_default) continue
    const mediaType = format.media_type || 'application/octet-stream'
    accept[mediaType] = [...new Set([...(accept[mediaType] || []), format.extension])]
  }
  return accept
}

export function findFileCapability(
  file: Pick<File, 'name'>,
  contract?: InputCapabilityContract,
): InputFormatCapability | undefined {
  const extension = fileExtension(file.name)
  return contract?.formats.find(format => format.extension === extension)
}

export function preflightFile(
  file: Pick<File, 'name' | 'size'>,
  contract?: InputCapabilityContract,
  remainingBytes?: number | null,
): FilePreflight {
  const capability = findFileCapability(file, contract)
  if (!capability) return { error: `不支援 ${fileExtension(file.name) || '此'} 檔案格式` }
  if (capability.processing_status === 'disabled') {
    return { capability, error: capability.degradation_reasons[0] || '目前環境未啟用此格式' }
  }
  if (file.size <= 0) return { capability, error: '檔案內容為空' }
  if (file.size > capability.max_bytes) {
    return { capability, error: `檔案超過 ${formatBytes(capability.max_bytes)} 上限` }
  }
  if (remainingBytes != null && file.size > remainingBytes) {
    return { capability, error: '檔案超過目前租戶剩餘儲存空間' }
  }
  return {
    capability,
    warning: capability.processing_status === 'degraded'
      ? capability.degradation_reasons.join('；')
      : undefined,
  }
}

export function capabilitySummary(capability?: InputFormatCapability): string {
  if (!capability) return '等待能力檢查'
  const labels: Record<string, string> = {
    extract_text: '文字擷取',
    layout: '版面理解',
    ocr: 'OCR',
    tables: '表格解析',
    transcribe: '語音轉寫',
    diarize: '說話者',
    timecode: '時間碼',
    keyframes: '關鍵畫面',
    scene_detection: '鏡頭切分',
  }
  const values = capability.capabilities.map(value => labels[value] || value)
  const quality = capability.quality_gate
    ? `品質門檻 ${Math.round(capability.quality_gate.min_content_accuracy * 100)}%`
    : ''
  return [values.join('、') || capability.parser_kind, quality].filter(Boolean).join(' · ')
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`
  return `${Math.round(bytes / 1024 / 1024)} MB`
}
