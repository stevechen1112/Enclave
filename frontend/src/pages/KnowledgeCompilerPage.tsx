/** Legacy — redirected to system modules (UIUX §7). */
import { Navigate } from 'react-router-dom'

export default function KnowledgeCompilerPage() {
  return <Navigate to="/system/modules" replace />
}
