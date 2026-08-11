import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import type { Capability } from '../navigation/capabilities'
import { useCapabilities } from '../navigation/useCapabilities'

type Item = { to: string; label: string; capability: Capability; end?: boolean }

export default function SubNav({ items }: { items: Item[] }) {
  const caps = useCapabilities()
  const visible = items.filter(i => caps.has(i.capability))

  if (visible.length === 0) return null

  return (
    <nav aria-label="子導覽" className="border-b border-line/60 bg-surface/60 px-4 py-2.5 backdrop-blur-sm md:px-8">
      <div className="seg-tabs border-0 bg-wash/80 shadow-none">
        {visible.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              clsx('seg-tab inline-flex items-center justify-center', isActive && 'seg-tab-active')
            }
          >
            {item.label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
