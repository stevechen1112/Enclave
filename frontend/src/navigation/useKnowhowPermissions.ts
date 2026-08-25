import { useAuth } from '../auth'

/** Keep know-how authoring UI aligned with the API's master/admin boundary. */
export function useCanAuthorKnowhow(): boolean {
  const { user, experience } = useAuth()
  const activeRoleKey = (experience?.active_job_role as { role_key?: string } | null)?.role_key
  return Boolean(
    user?.is_superuser
      || user?.role === 'owner'
      || user?.role === 'admin'
      || activeRoleKey === 'master',
  )
}

/** Approval and retirement are tenant-administration operations. */
export function useCanAdministerKnowhow(): boolean {
  const { user } = useAuth()
  return Boolean(user?.is_superuser || user?.role === 'owner' || user?.role === 'admin')
}
