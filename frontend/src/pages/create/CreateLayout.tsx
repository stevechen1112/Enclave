import { Outlet } from 'react-router-dom'
import SubNav from '../../components/SubNav'
import { CREATE_SUBNAV } from '../../navigation/capabilities'

export default function CreateLayout() {
  return (
    <div className="flex h-full flex-col overflow-hidden bg-wash">
      <div className="border-b border-line bg-surface px-4 py-4 md:px-6">
        <h1 className="font-display text-lg font-semibold text-ink">創作</h1>
        <p className="mt-0.5 text-sm text-muted">依可存取知識起草內容，並管理已儲存的報告</p>
      </div>
      <SubNav items={CREATE_SUBNAV} />
      <div className="flex-1 overflow-auto">
        <Outlet />
      </div>
    </div>
  )
}
