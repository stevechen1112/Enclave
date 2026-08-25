import { Shield } from 'lucide-react'
import DemoDoors from '../components/DemoDoors'

export default function LoginPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#292724] px-4 py-8 sm:px-6 lg:px-8">
      <div
        className="pointer-events-none absolute inset-0 opacity-50"
        style={{
          background:
            'linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
        }}
        aria-hidden
      />

      <div className="relative mx-auto w-full max-w-6xl">
        <header className="mb-7 text-center sm:mb-9">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-accent shadow-lg shadow-black/20">
            <Shield className="h-7 w-7 text-white" aria-hidden />
          </div>
          <p className="text-xs font-semibold tracking-[0.2em] text-[#d0a27f]">
            ENCLAVE 六道門
          </p>
          <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-white sm:text-4xl">
            選一位同事，直接看看他怎麼用
          </h1>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-sidebar-muted sm:text-base">
            業務、現場、師傅、新人、主管檢視與公司管理。免帳號、免密碼，點選人物即可進入他的工作畫面。
          </p>
          <a href="/" className="mt-4 inline-flex text-sm font-medium text-[#d8b08c] underline-offset-4 hover:underline">
            回產品介紹
          </a>
        </header>

        <DemoDoors />

        <footer className="mt-6 flex flex-col items-center justify-center gap-2 text-center text-xs text-sidebar-muted sm:flex-row sm:gap-4">
          <span>合成展示環境，請勿輸入真實客戶資料、個資或公司機密</span>
          <span className="hidden h-1 w-1 rounded-full bg-sidebar-muted sm:block" aria-hidden />
          <span>離開角色後可隨時返回此頁重新選擇</span>
        </footer>
      </div>
    </main>
  )
}
