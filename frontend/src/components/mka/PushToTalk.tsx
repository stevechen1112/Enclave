/**
 * PushToTalk — 現場語音輸入大按鈕。
 *
 * 設計對象：傳產製造業現場人員（可能戴手套、年齡層偏高、環境嘈雜）。
 * - 點一下開始、再點一下停止（toggle，不需持續按壓）
 * - 96px+ 大觸控目標、錄音中紅色脈動、計時顯示
 * - 達到後端上限（預設 120 秒）自動停止
 * - 麥克風權限被拒時給出具體排除步驟
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, Square, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { voiceApi, type SceneContext, type TranscribeResponse } from '../../services/mka'

const MAX_SECONDS = 120

type PttState = 'idle' | 'recording' | 'processing'

export default function PushToTalk({
  moduleKey,
  sceneContext,
  onResult,
  onError,
  disabled,
}: {
  moduleKey?: string
  sceneContext?: SceneContext | null
  onResult: (result: TranscribeResponse) => void
  onError?: (message: string) => void
  disabled?: boolean
}) {
  const [state, setState] = useState<PttState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  const cleanup = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
    recorderRef.current = null
  }, [])

  useEffect(() => cleanup, [cleanup])

  const fail = useCallback(
    (message: string) => {
      setState('idle')
      setElapsed(0)
      cleanup()
      onError?.(message)
    },
    [cleanup, onError],
  )

  const stopAndSend = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') return
    recorder.stop() // onstop 裡送出
  }, [])

  const start = useCallback(async () => {
    if (state !== 'idle' || disabled) return
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      fail('這個瀏覽器不支援錄音，請改用 Chrome 或 Edge，或改用打字輸入。')
      return
    }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      fail(
        '無法使用麥克風。請點網址列左邊的鎖頭圖示，把麥克風權限改成「允許」，再試一次。',
      )
      return
    }
    streamRef.current = stream
    chunksRef.current = []

    const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : ''
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    recorderRef.current = recorder

    recorder.ondataavailable = e => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }
    recorder.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      cleanup()
      if (blob.size === 0) {
        fail('沒有錄到聲音，請靠近麥克風再試一次。')
        return
      }
      setState('processing')
      try {
        const ext = blob.type.includes('webm') ? 'webm' : 'm4a'
        const result = await voiceApi.transcribe(blob, `voice.${ext}`, {
          module_key: moduleKey,
          scene_context: sceneContext,
        })
        setState('idle')
        setElapsed(0)
        onResult(result)
      } catch (err) {
        const detail =
          (err as { apiError?: { message?: string } })?.apiError?.message ||
          '語音辨識失敗，請檢查網路後再試一次。'
        fail(detail)
      }
    }

    recorder.start(500)
    setElapsed(0)
    setState('recording')
    timerRef.current = setInterval(() => {
      setElapsed(prev => {
        if (prev + 1 >= MAX_SECONDS) {
          stopAndSend()
          return prev
        }
        return prev + 1
      })
    }, 1000)
  }, [state, disabled, moduleKey, sceneContext, onResult, fail, cleanup, stopAndSend])

  const handleClick = () => {
    if (state === 'idle') void start()
    else if (state === 'recording') stopAndSend()
  }

  const mm = String(Math.floor(elapsed / 60)).padStart(1, '0')
  const ss = String(elapsed % 60).padStart(2, '0')

  return (
    <div className="flex flex-col items-center gap-3">
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || state === 'processing'}
        aria-label={
          state === 'recording' ? '停止錄音並送出' : state === 'processing' ? '辨識中' : '開始語音輸入'
        }
        aria-pressed={state === 'recording'}
        className={clsx(
          'flex h-24 w-24 items-center justify-center rounded-full text-white shadow-lg transition-all',
          'focus-visible:outline-4 active:scale-95 disabled:opacity-60',
          state === 'idle' && 'bg-accent hover:bg-accent-hover',
          state === 'recording' && 'animate-pulse bg-danger scale-110',
          state === 'processing' && 'bg-muted',
        )}
      >
        {state === 'idle' && <Mic className="h-10 w-10" aria-hidden />}
        {state === 'recording' && <Square className="h-9 w-9" aria-hidden />}
        {state === 'processing' && <Loader2 className="h-10 w-10 animate-spin" aria-hidden />}
      </button>
      <p className="text-lg font-medium text-ink" aria-live="polite">
        {state === 'idle' && '點一下開始說話'}
        {state === 'recording' && (
          <>
            說話中 <span className="font-mono text-danger">{mm}:{ss}</span>，說完再點一下
          </>
        )}
        {state === 'processing' && '辨識中，請稍候…'}
      </p>
    </div>
  )
}
