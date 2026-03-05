import { useState, useEffect, useMemo } from 'react'
import { Building2, Plus, Loader2, Trash2, ChevronRight, ChevronDown, FolderTree, Pencil, Check, X } from 'lucide-react'
import api from '../api'
import toast from 'react-hot-toast'

interface Department {
  id: string
  tenant_id: string
  name: string
  description: string | null
  parent_id: string | null
  is_active: boolean
  created_at: string | null
}

// Build tree structure from flat list
interface DeptNode extends Department {
  children: DeptNode[]
  depth: number
}

function buildTree(departments: Department[]): DeptNode[] {
  const map = new Map<string, DeptNode>()
  const roots: DeptNode[] = []

  // Create nodes
  for (const dept of departments) {
    map.set(dept.id, { ...dept, children: [], depth: 0 })
  }

  // Build hierarchy
  for (const node of map.values()) {
    if (node.parent_id && map.has(node.parent_id)) {
      const parent = map.get(node.parent_id)!
      node.depth = parent.depth + 1
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  }

  return roots
}

// Flatten tree for rendering with depth info
function flattenTree(nodes: DeptNode[], collapsed: Set<string>): DeptNode[] {
  const result: DeptNode[] = []
  for (const node of nodes) {
    result.push(node)
    if (!collapsed.has(node.id) && node.children.length > 0) {
      result.push(...flattenTree(node.children, collapsed))
    }
  }
  return result
}

function DeptRow({ dept, collapsed, onToggle, onDelete, onUpdate }: {
  dept: DeptNode
  collapsed: Set<string>
  onToggle: (id: string) => void
  onDelete: (id: string) => void
  onUpdate: (id: string, data: { name: string; description: string | null }) => Promise<void>
}) {
  const hasChildren = dept.children.length > 0
  const isCollapsed = collapsed.has(dept.id)
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState(dept.name)
  const [editDesc, setEditDesc] = useState(dept.description || '')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!editName.trim()) return
    setSaving(true)
    try {
      await onUpdate(dept.id, { name: editName.trim(), description: editDesc.trim() || null })
      setEditing(false)
    } catch { /* handled by parent */ }
    finally { setSaving(false) }
  }

  const handleCancel = () => {
    setEditName(dept.name)
    setEditDesc(dept.description || '')
    setEditing(false)
  }

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-5 py-3">
        <div className="flex items-center" style={{ paddingLeft: `${dept.depth * 24}px` }}>
          {hasChildren ? (
            <button
              onClick={() => onToggle(dept.id)}
              className="mr-1.5 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-600 transition-colors"
            >
              {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
          ) : (
            <span className="mr-1.5 w-5" />
          )}
          <Building2 className={`h-4 w-4 mr-2 shrink-0 ${dept.depth === 0 ? 'text-blue-500' : dept.depth === 1 ? 'text-indigo-400' : 'text-gray-400'}`} />
          {editing ? (
            <input value={editName} onChange={e => setEditName(e.target.value)}
              className="rounded border border-blue-300 px-2 py-0.5 text-sm font-medium text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-500 w-36"
              autoFocus onKeyDown={e => e.key === 'Enter' && handleSave()} />
          ) : (
            <span className="text-sm font-medium text-gray-900">{dept.name}</span>
          )}
          {hasChildren && !editing && (
            <span className="ml-2 rounded-full bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
              {dept.children.length}
            </span>
          )}
        </div>
      </td>
      <td className="px-5 py-3">
        {editing ? (
          <input value={editDesc} onChange={e => setEditDesc(e.target.value)}
            className="rounded border border-gray-300 px-2 py-0.5 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500 w-full"
            placeholder="描述（選填）"
            onKeyDown={e => e.key === 'Enter' && handleSave()} />
        ) : (
          <span className="text-sm text-gray-500">{dept.description || '—'}</span>
        )}
      </td>
      <td className="px-5 py-3 text-sm text-gray-500">
        {dept.created_at ? new Date(dept.created_at).toLocaleDateString('zh-TW') : '—'}
      </td>
      <td className="px-5 py-3 text-right">
        <div className="flex items-center justify-end gap-1">
          {editing ? (
            <>
              <button onClick={handleSave} disabled={saving || !editName.trim()}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-green-600 hover:bg-green-50 disabled:opacity-50">
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} 儲存
              </button>
              <button onClick={handleCancel}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-gray-500 hover:bg-gray-100">
                <X className="h-3.5 w-3.5" /> 取消
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 transition-colors">
                <Pencil className="h-3.5 w-3.5" /> 編輯
              </button>
              <button onClick={() => onDelete(dept.id)}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-red-600 hover:bg-red-50 transition-colors">
                <Trash2 className="h-3.5 w-3.5" /> 停用
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}

export default function DepartmentsPage() {
  const [departments, setDepartments] = useState<Department[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [parentId, setParentId] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const tree = useMemo(() => buildTree(departments), [departments])
  const flatList = useMemo(() => flattenTree(tree, collapsed), [tree, collapsed])

  const load = () => {
    setLoading(true)
    api.get<Department[]>('/departments/')
      .then(r => setDepartments(r.data))
      .catch(() => setDepartments([]))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const toggleCollapse = (id: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      await api.post('/departments/', {
        name,
        description: description || null,
        parent_id: parentId || null,
      })
      setName('')
      setDescription('')
      setParentId('')
      load()
    } catch {
      alert('建立失敗')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('確定要停用此部門嗎？')) return
    try {
      await api.delete(`/departments/${id}`)
      load()
    } catch {
      toast.error('停用失敗')
    }
  }

  const handleUpdate = async (id: string, data: { name: string; description: string | null }) => {
    try {
      await api.put(`/departments/${id}`, data)
      toast.success('已更新')
      load()
    } catch {
      toast.error('更新失敗')
      throw new Error('update failed')
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center gap-2">
          <FolderTree className="h-5 w-5 text-blue-600" />
          <h1 className="text-lg font-semibold text-gray-900">部門管理</h1>
        </div>
        <p className="text-sm text-gray-500">管理組織架構與部門層級</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Create form */}
        <form onSubmit={handleCreate} className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">新增部門</h2>
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex-1 min-w-[160px]">
              <label className="block text-xs font-medium text-gray-500 mb-1">部門名稱 *</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="例：人力資源部"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                required
              />
            </div>
            <div className="flex-1 min-w-[160px]">
              <label className="block text-xs font-medium text-gray-500 mb-1">上層部門</label>
              <select
                value={parentId}
                onChange={e => setParentId(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="">（頂層部門）</option>
                {departments.map(d => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>
            <div className="flex-1 min-w-[160px]">
              <label className="block text-xs font-medium text-gray-500 mb-1">描述</label>
              <input
                type="text"
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="選填"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit"
              disabled={creating || !name.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              新增
            </button>
          </div>
        </form>

        {/* Department tree */}
        {departments.length === 0 ? (
          <div className="flex flex-col items-center py-16 text-gray-400">
            <Building2 className="mb-3 h-10 w-10" />
            <p className="text-sm">尚未建立部門</p>
          </div>
        ) : (
          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  <th className="px-5 py-3">部門名稱</th>
                  <th className="px-5 py-3">描述</th>
                  <th className="px-5 py-3">建立時間</th>
                  <th className="px-5 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {flatList.map(dept => (
                  <DeptRow
                    key={dept.id}
                    dept={dept}
                    collapsed={collapsed}
                    onToggle={toggleCollapse}
                    onDelete={handleDelete}
                    onUpdate={handleUpdate}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
