/**
 * Legacy ConnectorsPage — SP/Drive create UI removed (UIUX §9.6).
 * Route redirects to /knowledge/sources; this file exists only to avoid accidental re-import of uncertified flows.
 */
import { Navigate } from 'react-router-dom'

export default function ConnectorsPage() {
  return <Navigate to="/knowledge/sources" replace />
}
