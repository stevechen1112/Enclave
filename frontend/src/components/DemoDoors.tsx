import { useState } from 'react'
import {
  ArrowRight,
  BriefcaseBusiness,
  Eye,
  Factory,
  GraduationCap,
  Loader2,
  ShieldCheck,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'
import type { DemoPersona } from '../api'
import { useAuth } from '../auth'

type DemoDoor = {
  key: DemoPersona
  number: string
  role: string
  person: string
  description: string
  hint: string
  icon: LucideIcon
  marker: string
  iconSurface: string
  portraitPosition: string
  readOnly?: boolean
}

const DEMO_DOORS: DemoDoor[] = [
  {
    key: 'sales',
    number: '01',
    role: '業務',
    person: '王小明',
    description: '語音開報價、查產品規格與追蹤單據',
    hint: '業務工作',
    icon: BriefcaseBusiness,
    marker: 'bg-[#b56a2b]',
    iconSurface: 'bg-[#f1e3d3] text-[#85491f]',
    portraitPosition: '0% 0%',
  },
  {
    key: 'field',
    number: '02',
    role: '設備現場',
    person: '李阿明',
    description: '回報異常、交接班與查看設備維修資料',
    hint: '現場工作',
    icon: Factory,
    marker: 'bg-[#26736c]',
    iconSurface: 'bg-[#dceae6] text-[#245d58]',
    portraitPosition: '50% 0%',
  },
  {
    key: 'master',
    number: '03',
    role: '班長／師傅',
    person: '林火旺',
    description: '留下師傅做法、確認經驗內容與協助現場',
    hint: '師傅工作',
    icon: Wrench,
    marker: 'bg-[#8f4938]',
    iconSurface: 'bg-[#efdfd8] text-[#783c30]',
    portraitPosition: '100% 0%',
  },
  {
    key: 'newcomer',
    number: '04',
    role: '新人',
    person: '陳小弟',
    description: '看必讀 SOP、查師傅做法與完成新人訓練',
    hint: '新人工作',
    icon: GraduationCap,
    marker: 'bg-[#567248]',
    iconSurface: 'bg-[#e1e9dc] text-[#47603c]',
    portraitPosition: '0% 100%',
  },
  {
    key: 'viewer',
    number: '05',
    role: '主管檢視',
    person: '主管唯讀展示',
    description: '查看合成知識、師傅經驗與問答，不修改資料',
    hint: '只看不修改',
    icon: Eye,
    marker: 'bg-[#716b63]',
    iconSurface: 'bg-[#e8e5e0] text-[#58534d]',
    portraitPosition: '50% 100%',
    readOnly: true,
  },
  {
    key: 'admin',
    number: '06',
    role: '公司管理',
    person: '公司管理展示',
    description: '查看人員與使用狀況，並核准合成展示單據；系統設定不開放修改',
    hint: '管理與審核',
    icon: ShieldCheck,
    marker: 'bg-[#4d5961]',
    iconSurface: 'bg-[#dfe4e7] text-[#404b52]',
    portraitPosition: '100% 100%',
  },
]

type DemoDoorsProps = {
  compact?: boolean
}

export default function DemoDoors({ compact = false }: DemoDoorsProps) {
  const { demoLogin } = useAuth()
  const navigate = useNavigate()
  const [entering, setEntering] = useState<DemoPersona | null>(null)

  const enterDoor = async (door: DemoDoor) => {
    setEntering(door.key)
    try {
      await demoLogin(door.key)
      toast.success(`已進入${door.role}角色`)
      navigate('/login', { replace: true })
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : '目前無法進入此角色，請稍後再試')
      setEntering(null)
    }
  }

  return (
    <section aria-label="Demo 角色入口" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {DEMO_DOORS.map(door => {
        const Icon = door.icon
        const isEntering = entering === door.key
        return (
          <button
            key={door.key}
            type="button"
            onClick={() => void enterDoor(door)}
            disabled={entering !== null}
            aria-label={`以${door.role}進入 Demo`}
            className="group relative overflow-hidden rounded-[1.25rem] border border-stone-300/90 bg-[#fffdf8] text-left shadow-[0_2px_0_rgba(28,25,23,0.08)] transition duration-200 hover:-translate-y-1 hover:border-stone-500 hover:shadow-[0_7px_0_rgba(28,25,23,0.10)] focus:outline-none focus:ring-4 focus:ring-teal-800/20 disabled:cursor-wait disabled:opacity-70"
          >
            <span className={`absolute inset-x-0 top-0 z-20 h-1 ${door.marker}`} aria-hidden />

            <div
              className="relative aspect-square overflow-hidden border-b border-stone-300 bg-stone-300"
              style={{
                backgroundImage: "url('/images/enclave-demo-personas-v1.webp')",
                backgroundPosition: door.portraitPosition,
                backgroundSize: '300% 200%',
              }}
              aria-hidden
            >
              <span className="absolute inset-0 bg-gradient-to-t from-stone-950/55 via-transparent to-transparent" />
              <span className="absolute bottom-3 left-3 rounded-md border border-white/30 bg-stone-950/75 px-2.5 py-1 font-mono text-xs font-semibold tracking-[0.12em] text-white backdrop-blur-sm">
                第 {door.number} 道門
              </span>
              <div className={`absolute bottom-3 right-3 flex h-10 w-10 items-center justify-center rounded-lg shadow-sm ${door.iconSurface}`}>
                {isEntering ? (
                  <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
                ) : (
                  <Icon className="h-5 w-5" aria-hidden />
                )}
              </div>
            </div>

            <div className={compact ? 'p-5' : 'p-6'}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-stone-500">{door.person}</p>
                  <h3 className="mt-0.5 text-xl font-bold text-stone-900">{door.role}</h3>
                </div>
                <span className="rounded-full border border-stone-200 bg-stone-100/80 px-3 py-1 text-xs font-medium text-stone-600">
                  {door.readOnly ? '只看不修改' : door.hint}
                </span>
              </div>
              <p className="mt-3 min-h-12 text-sm leading-6 text-stone-600">{door.description}</p>

              <div className="mt-4 flex items-center justify-between border-t border-stone-200 pt-3 text-sm font-semibold text-teal-800">
                <span>{isEntering ? '正在開門…' : '免帳號，直接進入'}</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </div>
            </div>
          </button>
        )
      })}
    </section>
  )
}
