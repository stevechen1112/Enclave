import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import { useAuth } from '../auth'
import { hasCapability, type Capability } from '../navigation/capabilities'

type Item = { to: string; label: string; capability: Capability; end?: boolean }

export default function SubNav({ items }: { items: Item[] }) {
  const { user } = useAuth()
  const visible = items.filter(i => hasCapability(user?.role, i.capability, user?.is_superuser))

  if (visible.length === 0) return null

  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line/80 bg-surface/90 px-4 md:px-8">
      {visible.map(item => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            clsx(
              'shrink-0 border-b-2 px-3.5 py-3 text-sm font-medium transition-colors',
              isActive
                ? 'border-accent text-accent'
                : 'border-transparent text-muted hover:border-line hover:text-ink',
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </div>
  )
}
