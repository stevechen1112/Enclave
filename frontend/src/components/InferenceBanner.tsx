import { useAuth } from '../auth'
import { AlertTriangle } from 'lucide-react'

/** Shows when deployment uses external model inference */
export default function InferenceBanner() {
  const { experience } = useAuth()
  const inf = experience?.inference
  if (!inf || inf.data_stays_on_prem_for_inference) return null

  return (
    <div className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900 md:px-6">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p>{inf.message}</p>
    </div>
  )
}
