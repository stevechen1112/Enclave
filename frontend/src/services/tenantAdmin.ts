/**
 * 租戶設定中心 API client（Phase 5）。
 */
import api from '../api'

export type JobRole = {
  id: string
  tenant_id: string
  role_key: string
  name: string
  description?: string | null
  department_ids: string[]
  default_module_keys: string[]
  active: boolean
}

export type JobRoleAssignment = {
  id: string
  user_id: string
  job_role_id: string
  department_id?: string | null
  is_primary: boolean
  active: boolean
  role?: JobRole | null
}

export type ModuleBindingInfo = {
  module_key: string
  name?: string
  description?: string
  status?: string
  bound: boolean
  enabled: boolean
  license_state?: string | null
  config_version: number
}

export type EffectiveConfig = {
  module_key: string
  config_version: number
  enabled: boolean
  defaults: Record<string, unknown>
  overrides: Record<string, unknown>
  effective: Record<string, unknown>
}

export type TaskDefinitionRow = {
  id: string
  task_key: string
  name: string
  version: string
  status: string
  handler_key: string
  module_key?: string | null
  applicable_job_role_keys: string[]
  required_capabilities: string[]
  risk_level: string
  scope: 'global' | 'tenant'
}

export type ApprovalPolicyRow = {
  id: string
  module_key?: string | null
  object_type: string
  version: string
  status: string
  risk_level: string
  steps: unknown[]
  timeout_policy: Record<string, unknown>
  delegation_policy: Record<string, unknown>
}

export const tenantAdminApi = {
  // 職能
  listJobRoles: () => api.get<JobRole[]>('/job-roles').then(r => r.data),
  createJobRole: (body: {
    role_key: string
    name: string
    description?: string
    default_module_keys?: string[]
  }) => api.post<JobRole>('/job-roles', body).then(r => r.data),
  updateJobRole: (id: string, body: Partial<JobRole>) =>
    api.patch<JobRole>(`/job-roles/${id}`, body).then(r => r.data),
  listAssignments: () =>
    api.get<JobRoleAssignment[]>('/job-roles/assignments').then(r => r.data),
  assign: (body: { user_id: string; job_role_id: string; is_primary?: boolean }) =>
    api.post<JobRoleAssignment>('/job-roles/assignments', body).then(r => r.data),
  deactivateAssignment: (id: string) =>
    api.delete(`/job-roles/assignments/${id}`).then(r => r.data),

  // 模組
  listModules: () => api.get<ModuleBindingInfo[]>('/job-modules').then(r => r.data),
  setBinding: (moduleKey: string, enabled: boolean) =>
    api.put(`/job-modules/${moduleKey}/binding`, { enabled }).then(r => r.data),
  effectiveConfig: (moduleKey: string) =>
    api.get<EffectiveConfig>(`/job-modules/${moduleKey}/effective-config`).then(r => r.data),
  updateConfig: (moduleKey: string, config: Record<string, unknown>) =>
    api.put<EffectiveConfig>(`/job-modules/${moduleKey}/config`, { config }).then(r => r.data),

  // 任務定義
  listTaskDefinitions: () =>
    api.get<TaskDefinitionRow[]>('/tasks/definitions').then(r => r.data),
  overrideTaskDefinition: (taskKey: string, body: Record<string, unknown>) =>
    api.post<TaskDefinitionRow>(`/tasks/definitions/${taskKey}/override`, body).then(r => r.data),
  setTaskDefinitionStatus: (id: string, status: string) =>
    api.patch<TaskDefinitionRow>(`/tasks/definitions/${id}`, { status }).then(r => r.data),

  // 簽核政策
  listApprovalPolicies: () =>
    api.get<ApprovalPolicyRow[]>('/approvals/policies').then(r => r.data),
  upsertApprovalPolicy: (body: {
    object_type: string
    module_key?: string | null
    risk_level?: string
    steps?: unknown[]
  }) => api.post<ApprovalPolicyRow>('/approvals/policies', body).then(r => r.data),

  // 使用者（指派職能用）
  listUsers: () => api.get<Array<{ id: string; email: string; full_name?: string; role: string }>>('/admin/users').then(r => r.data),
}
