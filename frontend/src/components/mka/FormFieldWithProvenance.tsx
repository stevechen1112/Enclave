/**
 * FormFieldWithProvenance — 表單欄位含來源標示（§4.7）。
 *
 * 每個欄位顯示：值 + 來源類型（rule/document/user_input）+ 證據引用。
 */
import { Calculator, FileText, User, HelpCircle } from 'lucide-react'
import clsx from 'clsx'

export interface FieldProvenance {
  source_type: 'rule' | 'document' | 'user_input' | 'unknown'
  source_ref?: string
  evidence?: string[]
  confirmed_by?: string
  confirmed_at?: string
}

interface FormFieldWithProvenanceProps {
  label: string
  value: string | number
  type?: string
  provenance?: FieldProvenance
  required?: boolean
  error?: string
}

const SOURCE_ICONS: Record<string, typeof Calculator> = {
  rule: Calculator,
  document: FileText,
  user_input: User,
  unknown: HelpCircle,
}

const SOURCE_LABELS: Record<string, string> = {
  rule: '規則計算',
  document: '文件引用',
  user_input: '人工輸入',
  unknown: '未知來源',
}

export default function FormFieldWithProvenance({
  label,
  value,
  type,
  provenance,
  required,
  error,
}: FormFieldWithProvenanceProps) {
  const sourceType = provenance?.source_type || 'unknown'
  const SourceIcon = SOURCE_ICONS[sourceType] || HelpCircle

  return (
    <div className={clsx('rounded-xl border-2 p-4', error ? 'border-danger bg-red-50' : 'border-line bg-surface')}>
      <div className="flex items-center justify-between">
        <p className="text-base font-bold text-ink">
          {label}
          {required && <span className="ml-1 text-danger">*</span>}
        </p>
        {provenance && (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-wash px-2 py-0.5 text-xs font-bold text-muted"
            title={`來源：${SOURCE_LABELS[sourceType]}${provenance.source_ref ? `（${provenance.source_ref}）` : ''}`}
          >
            <SourceIcon className="h-3.5 w-3.5" aria-hidden />
            {SOURCE_LABELS[sourceType]}
          </span>
        )}
      </div>
      <p className={clsx(
        'mt-1 text-xl font-bold',
        type === 'amount' && 'font-mono text-2xl',
        error ? 'text-danger' : 'text-ink',
      )}>
        {type === 'amount' && typeof value === 'number'
          ? value.toLocaleString('zh-TW', { style: 'currency', currency: 'TWD' })
          : String(value || '—')}
      </p>
      {error && <p className="mt-1 text-sm font-bold text-danger">{error}</p>}
    </div>
  )
}
