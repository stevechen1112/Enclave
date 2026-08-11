/**
 * QrScanner — 掃描設備/工單 QR 碼帶入作業場景。
 *
 * 優先使用瀏覽器內建 BarcodeDetector（Android Chrome）；不支援時
 * 降級為手動輸入代碼——現場裝置規格不一，不能假設相機 API 可用。
 * 掃描字串一律視為 opaque token 送後端解析，不直接拼入任何 prompt（§5.3）。
 */
import { useEffect, useRef, useState } from 'react'
import { QrCode, Camera, Keyboard, X } from 'lucide-react'
import clsx from 'clsx'
import { sceneApi, type SceneContext } from '../../services/mka'

type BarcodeDetectorLike = {
  detect: (source: CanvasImageSource) => Promise<Array<{ rawValue: string }>>
}

declare global {
  interface Window {
    BarcodeDetector?: new (opts?: { formats?: string[] }) => BarcodeDetectorLike
  }
}

export default function QrScanner({
  onResolved,
  onError,
}: {
  onResolved: (scene: SceneContext) => void
  onError?: (message: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [manualMode, setManualMode] = useState(false)
  const [manualToken, setManualToken] = useState('')
  const [busy, setBusy] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const scanningRef = useRef(false)

  const cameraSupported =
    typeof window !== 'undefined' &&
    !!window.BarcodeDetector &&
    !!navigator.mediaDevices?.getUserMedia

  const stopCamera = () => {
    scanningRef.current = false
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
  }

  useEffect(() => stopCamera, [])

  const resolveToken = async (token: string) => {
    if (!token.trim() || busy) return
    setBusy(true)
    try {
      const scene = await sceneApi.resolve({ qr_token: token.trim() })
      stopCamera()
      setOpen(false)
      setManualToken('')
      onResolved(scene)
    } catch {
      onError?.('找不到這個代碼對應的設備或工單，請確認 QR 碼是否正確，或回報主管建檔。')
    } finally {
      setBusy(false)
    }
  }

  const startCamera = async () => {
    setOpen(true)
    setManualMode(false)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      })
      streamRef.current = stream
      const video = videoRef.current
      if (!video) return
      video.srcObject = stream
      await video.play()
      const detector = new window.BarcodeDetector!({ formats: ['qr_code'] })
      scanningRef.current = true
      const tick = async () => {
        if (!scanningRef.current) return
        try {
          const codes = await detector.detect(video)
          if (codes.length > 0 && codes[0].rawValue) {
            await resolveToken(codes[0].rawValue)
            return
          }
        } catch {
          // 單幀辨識失敗繼續掃
        }
        if (scanningRef.current) setTimeout(tick, 400)
      }
      void tick()
    } catch {
      stopCamera()
      setManualMode(true)
      onError?.('相機無法使用，已切換為手動輸入代碼。')
    }
  }

  if (!open) {
    return (
      <div className="flex flex-col gap-3">
        <button
          type="button"
          onClick={cameraSupported ? startCamera : () => { setOpen(true); setManualMode(true) }}
          className="flex min-h-16 w-full items-center justify-center gap-3 rounded-xl border-2 border-accent bg-surface text-xl font-bold text-accent hover:bg-accent/10 active:scale-[0.98]"
        >
          {cameraSupported ? (
            <Camera className="h-7 w-7" aria-hidden />
          ) : (
            <QrCode className="h-7 w-7" aria-hidden />
          )}
          掃描設備 / 工單 QR 碼
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border-2 border-line bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-lg font-bold text-ink">
          <QrCode className="h-6 w-6 text-accent" aria-hidden />
          {manualMode ? '手動輸入代碼' : '對準 QR 碼'}
        </h3>
        <button
          type="button"
          aria-label="關閉掃描"
          onClick={() => { stopCamera(); setOpen(false) }}
          className="rounded-lg p-2 text-muted hover:bg-wash"
        >
          <X className="h-6 w-6" aria-hidden />
        </button>
      </div>

      {!manualMode && (
        <video
          ref={videoRef}
          className="aspect-video w-full rounded-xl bg-ink"
          muted
          playsInline
          aria-label="相機預覽"
        />
      )}

      {manualMode && (
        <div className="flex flex-col gap-3">
          <label htmlFor="manual-token" className="text-base font-medium text-muted">
            請輸入 QR 碼下方印的代碼：
          </label>
          <input
            id="manual-token"
            value={manualToken}
            onChange={e => setManualToken(e.target.value)}
            inputMode="text"
            autoComplete="off"
            placeholder="例如 EQ-A01-2024"
            className="min-h-16 w-full rounded-xl border-2 border-line px-4 text-xl text-ink focus:border-accent focus:outline-none"
          />
          <button
            type="button"
            disabled={busy || !manualToken.trim()}
            onClick={() => void resolveToken(manualToken)}
            className={clsx(
              'flex min-h-16 items-center justify-center gap-2 rounded-xl text-xl font-bold text-white',
              'bg-accent hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50',
            )}
          >
            <Keyboard className="h-6 w-6" aria-hidden />
            {busy ? '查詢中…' : '帶入這個代碼'}
          </button>
        </div>
      )}

      {!manualMode && (
        <button
          type="button"
          onClick={() => { stopCamera(); setManualMode(true) }}
          className="mt-3 min-h-12 w-full rounded-xl border-2 border-line text-lg font-medium text-muted hover:bg-wash"
        >
          掃不到？改用手動輸入
        </button>
      )}
    </div>
  )
}
