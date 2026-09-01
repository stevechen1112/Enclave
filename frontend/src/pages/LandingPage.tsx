import {
  ArrowDown,
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Factory,
  Mic,
  Quote,
  ScanLine,
  Shield,
  ShieldCheck,
  Wrench,
} from 'lucide-react'
import DemoDoors from '../components/DemoDoors'

const PAIN_POINTS = [
  {
    number: '01',
    title: '規格明明有，臨時就是找不到',
    body: '資料散在紙本、LINE、電腦資料夾和不同同事手上。客戶或現場一問，只能四處找人。',
  },
  {
    number: '02',
    title: '同一份資料，一填再填',
    body: '報價、工單、異常紀錄各填一次，還要人工複製。忙的時候容易漏，也容易抄錯。',
  },
  {
    number: '03',
    title: '老師傅一退休，做法也跟著走',
    body: '關鍵眉角多半靠口頭交代。新人遇到問題，還是只能等那位最懂的人有空。',
  },
  {
    number: '04',
    title: '問了 AI，還是不敢直接用',
    body: '不知道答案從哪裡來，也不知道是不是最新版。內容說得再順，現場仍不敢照著做。',
  },
]

const WORKFLOWS = [
  {
    label: '業務報價',
    icon: Quote,
    title: '客戶講完需求，資料跟著帶進報價單',
    body: '用說的或打字都可以。系統協助找料號、規格與舊報價，缺少的欄位再請人補齊。',
    example: '例如：「P-100 兩百個，交期月底。」',
  },
  {
    label: '現場作業',
    icon: ScanLine,
    title: '掃設備 QR 碼，就看到該看的資料',
    body: '設備說明、保養步驟、維修紀錄與交接事項放在一起，不用再回辦公室翻資料夾。',
    example: '有異常就直接留下照片、說明與處理結果。',
  },
  {
    label: '師傅經驗',
    icon: Mic,
    title: '按下開始訪談，把做法好好留下來',
    body: '師傅照平常說法分享，系統整理成逐字內容與工作重點，再交給負責人確認。',
    example: '人的經驗先留下，整理工作交給系統幫忙。',
  },
  {
    label: '新人學習',
    icon: BookOpenCheck,
    title: '不懂就問，也看得到原始資料',
    body: '新人查 SOP、規格與師傅做法；答案會附上資料來源，找不到可靠內容就直接說找不到。',
    example: '少一點「我以為」，多一點有根據的做法。',
  },
]

const KEEP_KNOWLEDGE = [
  ['收進來', '公司文件、現場紀錄與師傅說法，集中放在同一個地方。'],
  ['找得到', '需要時用一句話查詢，也能看出資料來源和目前版本。'],
  ['用得上', '確認過的內容可帶入報價、工單、異常紀錄與新人訓練。'],
]

const TRUST_POINTS = [
  ['答案有根據', '每個回答都能回頭查看原始文件，不把猜測當成公司規定。'],
  ['最新版優先', '已核准、仍在使用的 SOP 與規格排在前面，過期資料不混在一起。'],
  ['重要內容有人確認', 'AI 可以協助整理；報價送出、經驗發布與正式資料變更，仍由人員確認。'],
  ['誰做過都有紀錄', '誰建立、誰核准、何時更新，都能回頭查，不再只靠口頭交代。'],
]

export default function LandingPage() {
  return (
    <main className="min-h-screen overflow-hidden bg-[#f4f0e7] text-stone-900">
      <header className="border-b border-stone-300/80 bg-[#f4f0e7]/95">
        <div className="mx-auto flex h-[72px] max-w-7xl items-center justify-between px-5 sm:px-8 lg:px-10">
          <a href="#top" className="flex items-center gap-3" aria-label="回到 Enclave 首頁頂端">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#1f5f59] shadow-[0_2px_0_#153f3b]">
              <Shield className="h-6 w-6 text-white" aria-hidden />
            </span>
            <span>
              <strong className="block text-lg tracking-tight">Enclave</strong>
              <span className="block text-[11px] tracking-[0.08em] text-stone-500">工廠資料與經驗的工作助手</span>
            </span>
          </a>

          <nav className="hidden items-center gap-7 text-sm font-medium text-stone-600 md:flex" aria-label="首頁導覽">
            <a href="#pain" className="hover:text-stone-950">工廠難題</a>
            <a href="#work" className="hover:text-stone-950">實際怎麼用</a>
            <a href="#trust" className="hover:text-stone-950">如何放心用</a>
          </nav>

          <div className="flex items-center gap-2">
            <a
              href="/login"
              className="inline-flex min-h-11 items-center rounded-lg border border-stone-400 bg-[#faf7f0] px-4 text-sm font-semibold text-stone-900 transition hover:border-[#1f5f59] hover:text-[#1f5f59]"
            >
              企業登入
            </a>
            <a
              href="#demo"
              className="hidden min-h-11 items-center gap-2 rounded-lg bg-stone-900 px-4 text-sm font-semibold text-white transition hover:bg-[#1f5f59] sm:inline-flex"
            >
              試用 Demo <ArrowRight className="h-4 w-4" aria-hidden />
            </a>
          </div>
        </div>
      </header>

      <section id="top" className="relative border-b border-stone-300/80">
        <div
          className="pointer-events-none absolute inset-0 opacity-45"
          style={{
            backgroundImage:
              'linear-gradient(rgba(87,83,78,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(87,83,78,0.08) 1px, transparent 1px)',
            backgroundSize: '32px 32px',
          }}
          aria-hidden
        />
        <div className="relative mx-auto grid max-w-7xl gap-12 px-5 py-16 sm:px-8 sm:py-20 lg:grid-cols-[0.96fr_1.04fr] lg:items-center lg:px-10 lg:py-24">
          <div>
            <div className="mb-6 inline-flex items-center gap-3 border-y border-stone-400 py-2 text-xs font-semibold tracking-[0.13em] text-stone-600">
              <Factory className="h-4 w-4 text-[#1f5f59]" aria-hidden />
              為台灣製造現場而做
            </div>
            <h1 className="max-w-3xl text-balance font-display text-[2.55rem] font-bold leading-[1.16] tracking-tight text-stone-950 sm:text-5xl lg:text-[3.25rem] xl:text-[3.55rem]">
              公司資料找得到，<br />老師傅經驗留得住，<br /><span className="text-[#1f5f59]">現場工作接得起來。</span>
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-stone-700">
              規格、SOP、報價、異常與師傅做法，不再散在紙本、資料夾和人的腦袋裡。需要時找得到，填單時帶得入，重要內容有人確認。
            </p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <a
                href="/login"
                className="inline-flex min-h-14 items-center justify-center gap-2 rounded-xl bg-[#1f5f59] px-7 font-semibold text-white shadow-[0_3px_0_#153f3b] transition hover:-translate-y-0.5 hover:bg-[#184e49]"
              >
                企業帳號登入 <ArrowRight className="h-5 w-5" aria-hidden />
              </a>
              <a
                href="#demo"
                className="inline-flex min-h-14 items-center justify-center gap-2 rounded-xl border border-stone-400 bg-[#faf7f0] px-7 font-semibold text-stone-800 transition hover:bg-white"
              >
                先選角色試用 <ArrowDown className="h-5 w-5" aria-hidden />
              </a>
            </div>
          </div>

          <figure className="relative mx-auto w-full max-w-2xl lg:mx-0">
            <div className="absolute -bottom-4 -right-4 h-full w-full rounded-[1.5rem] border border-[#9c5a32]/40 bg-[#d9c4a8]" aria-hidden />
            <div className="relative overflow-hidden rounded-[1.5rem] border border-stone-500 bg-stone-800 shadow-[0_18px_50px_rgba(54,45,34,0.20)]">
              <img
                src="/images/enclave-factory-knowledge-transfer-v1.webp"
                alt="老師傅與年輕技術人員在工廠設備旁討論設定"
                className="aspect-[3/2] h-auto w-full object-cover"
                width="1600"
                height="1066"
                fetchPriority="high"
              />
              <figcaption className="absolute inset-x-4 bottom-4 flex items-center gap-3 rounded-xl border border-white/25 bg-stone-950/85 px-4 py-3 text-white backdrop-blur-sm sm:inset-x-5 sm:bottom-5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#d8b08c] text-stone-900">
                  <Mic className="h-4 w-4" aria-hidden />
                </span>
                <span>
                  <strong className="block text-sm">把現場做法留下來</strong>
                  <span className="text-xs text-stone-300">師傅照平常說，系統協助整理，再由人員確認</span>
                </span>
              </figcaption>
            </div>
          </figure>
        </div>
      </section>

      <section id="pain" className="bg-stone-900 py-16 text-stone-100 sm:py-20">
        <div className="mx-auto max-w-7xl px-5 sm:px-8 lg:px-10">
          <div className="grid gap-6 border-b border-stone-700 pb-9 lg:grid-cols-[0.8fr_1.2fr] lg:items-end">
            <div>
              <p className="text-sm font-semibold tracking-[0.12em] text-[#d3a27d]">不是缺資料，是資料沒有在需要時出現</p>
              <h2 className="mt-3 font-display text-3xl font-bold sm:text-4xl">工廠每天都在遇到的四件事</h2>
            </div>
            <p className="max-w-2xl text-base leading-7 text-stone-400 lg:justify-self-end">
              問題常常不是員工不認真，而是資料散、交接斷、經驗只在人身上。Enclave 先把這些每天浪費的時間接起來。
            </p>
          </div>

          <div className="mt-3 grid sm:grid-cols-2 lg:grid-cols-4">
            {PAIN_POINTS.map(point => (
              <article key={point.number} className="border-b border-stone-700 py-7 sm:px-5 lg:border-b-0 lg:border-r lg:last:border-r-0">
                <span className="font-mono text-sm text-[#d3a27d]">{point.number}</span>
                <h3 className="mt-5 text-lg font-bold leading-7 text-white">{point.title}</h3>
                <p className="mt-3 text-sm leading-7 text-stone-400">{point.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-stone-300 bg-[#e8e0d2] py-14 sm:py-16" aria-labelledby="keep-heading">
        <div className="mx-auto max-w-7xl px-5 sm:px-8 lg:px-10">
          <div className="grid gap-8 lg:grid-cols-[0.7fr_1.3fr] lg:items-center">
            <div>
              <p className="text-sm font-semibold tracking-[0.12em] text-[#8b4b2c]">從資料散落，到工作用得上</p>
              <h2 id="keep-heading" className="mt-3 font-display text-3xl font-bold text-stone-950">三步，把公司的做法接起來</h2>
            </div>
            <ol className="grid gap-3 sm:grid-cols-3">
              {KEEP_KNOWLEDGE.map(([title, body], index) => (
                <li key={title} className="rounded-xl border border-stone-300 bg-[#fffdf8] p-5">
                  <span className="font-mono text-xs font-semibold text-[#9c5a32]">第 {index + 1} 步</span>
                  <h3 className="mt-2 text-lg font-bold">{title}</h3>
                  <p className="mt-2 text-sm leading-6 text-stone-600">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section id="work" className="border-b border-stone-300 bg-[#f4f0e7] py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-5 sm:px-8 lg:px-10">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold tracking-[0.12em] text-[#8b4b2c]">不是多一套難學的軟體</p>
            <h2 className="mt-3 font-display text-3xl font-bold text-stone-950 sm:text-4xl">每個人打開，就看到自己的工作</h2>
            <p className="mt-5 text-lg leading-8 text-stone-600">
              業務、現場、師傅與新人不必先學系統架構。從每天本來就在做的報價、查資料、回報異常與交接開始。
            </p>
          </div>

          <div className="mt-11 grid gap-px overflow-hidden rounded-2xl border border-stone-300 bg-stone-300 md:grid-cols-2">
            {WORKFLOWS.map(flow => {
              const Icon = flow.icon
              return (
                <article key={flow.label} className="bg-[#fffdf8] p-6 sm:p-8">
                  <div className="flex items-center justify-between">
                    <span className="rounded-full bg-[#e1e9e5] px-3 py-1 text-sm font-semibold text-[#1f5f59]">{flow.label}</span>
                    <Icon className="h-7 w-7 text-[#9c5a32]" aria-hidden />
                  </div>
                  <h3 className="mt-7 text-xl font-bold text-stone-950 sm:text-2xl">{flow.title}</h3>
                  <p className="mt-3 leading-7 text-stone-600">{flow.body}</p>
                  <p className="mt-6 border-l-2 border-[#b96c3d] pl-4 text-sm font-medium leading-6 text-stone-700">{flow.example}</p>
                </article>
              )
            })}
          </div>
        </div>
      </section>

      <section id="trust" className="bg-[#ddd3c2] py-16 sm:py-20">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 sm:px-8 lg:grid-cols-[0.75fr_1.25fr] lg:px-10">
          <div>
            <ShieldCheck className="h-10 w-10 text-[#1f5f59]" aria-hidden />
            <p className="mt-6 text-sm font-semibold tracking-[0.12em] text-[#714329]">工廠要的是能放心使用</p>
            <h2 className="mt-3 font-display text-3xl font-bold text-stone-950 sm:text-4xl">AI 幫忙整理，人員負責確認。</h2>
            <p className="mt-5 leading-8 text-stone-700">
              Enclave 不把電腦說的每句話都當成答案。資料從哪裡來、是不是最新版、誰確認過，畫面上都應該看得出來。
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {TRUST_POINTS.map(([title, body]) => (
              <article key={title} className="rounded-xl border border-stone-400/70 bg-[#f7f2e8] p-5">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-5 w-5 shrink-0 text-[#1f5f59]" aria-hidden />
                  <h3 className="font-bold text-stone-950">{title}</h3>
                </div>
                <p className="mt-3 text-sm leading-6 text-stone-600">{body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="demo" className="border-y border-stone-300 bg-[#f7f3eb] py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-5 sm:px-8 lg:px-10">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold tracking-[0.12em] text-[#8b4b2c]">六位同事，就是六道門</p>
            <h2 className="mt-3 font-display text-3xl font-bold text-stone-950 sm:text-4xl">選一位同事，直接看看他怎麼用</h2>
            <p className="mt-5 text-lg leading-8 text-stone-600">
              不用帳號、不用密碼。從業務、現場、師傅、新人、主管檢視到系統管理，點一位就能進入他的工作畫面。
            </p>
          </div>
          <div className="mt-11">
            <DemoDoors compact />
          </div>
          <p className="mt-6 text-center text-xs leading-6 text-stone-500">
            這是展示環境，內容會定期整理；請勿輸入真實客戶資料、個人資料或公司機密。
          </p>
        </div>
      </section>

      <section className="bg-[#1f5f59] px-5 py-14 text-white sm:px-8">
        <div className="mx-auto flex max-w-5xl flex-col items-center text-center">
          <Wrench className="h-9 w-9 text-[#d8b08c]" aria-hidden />
          <h2 className="mt-5 font-display text-3xl font-bold sm:text-4xl">從一個角色開始，看它能不能解決每天的事。</h2>
          <p className="mt-4 max-w-2xl leading-7 text-teal-50/80">
            不必先聽完整套系統介紹。選一位最接近你公司同事的角色，直接走一次他的工作。
          </p>
          <a href="#demo" className="mt-7 inline-flex min-h-12 items-center gap-2 rounded-xl bg-[#fffaf0] px-6 font-semibold text-[#174742] transition hover:bg-white">
            回到六道門 <ArrowRight className="h-5 w-5" aria-hidden />
          </a>
        </div>
      </section>

      <footer className="bg-stone-950 px-5 py-8 text-stone-400 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 text-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2 text-stone-200">
            <Shield className="h-5 w-5 text-[#67a79f]" aria-hidden />
            <strong>Enclave</strong>
            <span className="text-stone-500">工廠資料與經驗的工作助手</span>
          </div>
          <p>讓資料找得到、經驗留得住、工作接得起來。</p>
        </div>
      </footer>
    </main>
  )
}
