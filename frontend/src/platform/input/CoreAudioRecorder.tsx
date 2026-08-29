import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Mic, Pause, Play, Square, UploadCloud, WifiOff } from 'lucide-react'
import clsx from 'clsx'
import { captureApi, type CapturePolicy, type CaptureSessionInfo } from './captureApi'
import {
  listPendingCaptureChunks,
  removePendingCaptureChunk,
  savePendingCaptureChunk,
  type PendingCaptureChunk,
} from './captureQueue'

const ACTIVE_SESSION_KEY = 'enclave:long-interview:active-session'

type RecorderState = 'ready' | 'starting' | 'recording' | 'paused' | 'uploading' | 'queued' | 'error'

function formatDuration(ms: number) {
  const seconds = Math.floor(ms / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

async function sha256(blob: Blob): Promise<string> {
  const bytes = await blob.arrayBuffer()
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(hash)).map(value => value.toString(16).padStart(2, '0')).join('')
}

export default function CoreAudioRecorder({
  title,
  equipmentId,
  disabled,
  captureStatus,
  onQueued,
  onError,
  sourceModule = 'core',
  purpose = 'knowledge_capture',
  departmentId,
  dataClassification = 'confidential',
  contextMetadata = {},
  heading = '直接開始錄音',
}: {
  title: string
  equipmentId?: string
  disabled?: boolean
  captureStatus?: CaptureSessionInfo['status']
  onQueued: (session: CaptureSessionInfo) => void
  onError?: (message: string) => void
  sourceModule?: string
  purpose?: string
  departmentId?: string
  dataClassification?: string
  contextMetadata?: Record<string, string | string[]>
  heading?: string
}) {
  const [state, setState] = useState<RecorderState>('ready')
  const [elapsedMs, setElapsedMs] = useState(0)
  const [safeMs, setSafeMs] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
  const [session, setSession] = useState<CaptureSessionInfo | null>(null)
  const [policy, setPolicy] = useState<CapturePolicy | null>(null)
  const [storageAvailable, setStorageAvailable] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const timerRef = useRef<number | null>(null)
  const segmentTimerRef = useRef<number | null>(null)
  const lastChunkAtRef = useRef(0)
  const nextSequenceRef = useRef(0)
  const nextOffsetRef = useRef(0)
  const sessionRef = useRef<CaptureSessionInfo | null>(null)
  const drainingRef = useRef(false)
  const drainPromiseRef = useRef<Promise<boolean> | null>(null)
  const pendingChunkWritesRef = useRef(new Set<Promise<void>>())
  const stoppingRef = useRef(false)
  const pausingRef = useRef(false)
  const mimeTypeRef = useRef('')
  const beginSegmentRef = useRef<(() => void) | null>(null)

  const fail = useCallback((text: string) => {
    setState('error')
    setMessage(text)
    onError?.(text)
  }, [onError])

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current)
    timerRef.current = null
    if (segmentTimerRef.current !== null) window.clearTimeout(segmentTimerRef.current)
    segmentTimerRef.current = null
  }, [])

  const releaseMicrophone = useCallback(() => {
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
  }, [])

  const refreshPendingCount = useCallback(async (sessionId: string) => {
    const items = await listPendingCaptureChunks(sessionId)
    setPendingCount(items.length)
    return items
  }, [])

  const drain = useCallback(async (capture: CaptureSessionInfo): Promise<boolean> => {
    if (drainPromiseRef.current) return drainPromiseRef.current
    const run = async () => {
      drainingRef.current = true
      try {
        const items = await refreshPendingCount(capture.id)
        for (const item of items) {
          await captureApi.uploadChunk(capture.id, item)
          await removePendingCaptureChunk(item.key)
          setSafeMs(previous => Math.max(previous, item.offsetMs + item.durationMs))
          await refreshPendingCount(capture.id)
        }
        return true
      } catch {
        setMessage('網路暫時無法上傳；錄音片段已保存在本機，恢復網路後可重試。')
        setState('uploading')
        return false
      } finally {
        drainingRef.current = false
      }
    }
    const promise = run()
    drainPromiseRef.current = promise
    try {
      return await promise
    } finally {
      drainPromiseRef.current = null
    }
  }, [refreshPendingCount])

  const finishIfUploaded = useCallback(async (capture: CaptureSessionInfo) => {
    const pending = await refreshPendingCount(capture.id)
    if (pending.length) {
      setState('uploading')
      return
    }
    const finalSequence = nextSequenceRef.current - 1
    if (finalSequence < 0) {
      fail('尚未錄到任何音訊，請確認麥克風後再試一次。')
      return
    }
    try {
      const completed = await captureApi.complete(capture.id, finalSequence, nextOffsetRef.current)
      localStorage.removeItem(ACTIVE_SESSION_KEY)
      setSession(completed)
      setState('queued')
      setMessage(completed.queue_enqueued ? '錄音已安全上傳，正在轉寫。您可離開本頁，完成後再回來查看。' : '錄音已安全上傳，轉寫工作將在背景服務恢復後自動繼續。')
      onQueued(completed)
    } catch (error) {
      const detail = (error as { apiError?: { message?: string } })?.apiError?.message || '無法完成錄音，請重試上傳。'
      setState('uploading')
      setMessage(detail)
    }
  }, [fail, onQueued, refreshPendingCount])

  const saveChunk = useCallback(async (blob: Blob) => {
    const capture = sessionRef.current
    if (!capture || blob.size === 0) return
    const now = Date.now()
    const durationMs = Math.max(1, now - lastChunkAtRef.current)
    const sequence = nextSequenceRef.current
    const item: PendingCaptureChunk = {
      key: `${capture.id}:${sequence}`,
      sessionId: capture.id,
      sequence,
      offsetMs: nextOffsetRef.current,
      durationMs,
      sha256: await sha256(blob),
      blob,
    }
    nextSequenceRef.current += 1
    nextOffsetRef.current += durationMs
    lastChunkAtRef.current = now
    try {
      await savePendingCaptureChunk(item)
      await refreshPendingCount(capture.id)
      void drain(capture)
    } catch {
      fail('裝置沒有足夠空間保存錄音片段，已停止錄音以避免遺失資料。')
      recorderRef.current?.stop()
    }
  }, [drain, fail, refreshPendingCount])

  const stopRecording = useCallback(() => {
    stoppingRef.current = true
    pausingRef.current = false
    clearTimer()
    setState('uploading')
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
      return
    }
    const capture = sessionRef.current
    releaseMicrophone()
    if (capture) {
      void (async () => {
        await Promise.all([...pendingChunkWritesRef.current])
        const uploaded = await drain(capture)
        if (uploaded) await finishIfUploaded(capture)
      })()
    }
  }, [clearTimer, drain, finishIfUploaded, releaseMicrophone])

  const beginSegment = useCallback(() => {
    const stream = streamRef.current
    const capture = sessionRef.current
    if (!stream || !capture || stoppingRef.current || pausingRef.current) return
    const recorder = new MediaRecorder(
      stream,
      mimeTypeRef.current ? { mimeType: mimeTypeRef.current } : undefined,
    )
    recorderRef.current = recorder
    lastChunkAtRef.current = Date.now()
    recorder.ondataavailable = event => {
      const write = saveChunk(event.data)
      pendingChunkWritesRef.current.add(write)
      void write.finally(() => pendingChunkWritesRef.current.delete(write))
    }
    recorder.onstop = () => {
      void (async () => {
        await Promise.all([...pendingChunkWritesRef.current])
        if (stoppingRef.current) {
          releaseMicrophone()
          const uploaded = await drain(capture)
          if (uploaded) await finishIfUploaded(capture)
          return
        }
        if (!pausingRef.current) beginSegmentRef.current?.()
      })()
    }
    recorder.start()
    segmentTimerRef.current = window.setTimeout(() => {
      if (recorder.state === 'recording' && !stoppingRef.current && !pausingRef.current) recorder.stop()
    }, 30_000)
  }, [drain, finishIfUploaded, releaseMicrophone, saveChunk])

  useEffect(() => {
    beginSegmentRef.current = beginSegment
  }, [beginSegment])

  const startRecording = useCallback(async () => {
    if (disabled || state === 'starting' || state === 'recording') return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      fail('此瀏覽器不支援瀏覽器錄音，請改用最新版 Chrome、Safari 或 Edge。')
      return
    }
    setState('starting')
    setMessage('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream
      const capture = await captureApi.create({
        title: title.trim() || '未命名師傅訪談',
        equipment_id: equipmentId || undefined,
        consent: true,
        consent_version: policy?.consent_version,
        source_module: sourceModule,
        purpose,
        department_id: departmentId,
        data_classification: dataClassification,
        context_metadata: contextMetadata,
      })
      setSession(capture)
      sessionRef.current = capture
      localStorage.setItem(ACTIVE_SESSION_KEY, capture.id)
      nextSequenceRef.current = 0
      nextOffsetRef.current = 0
      setSafeMs(0)
      setPendingCount(0)
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
      mimeTypeRef.current = mimeType
      stoppingRef.current = false
      pausingRef.current = false
      beginSegment()
      setState('recording')
      timerRef.current = window.setInterval(() => {
        const elapsed = nextOffsetRef.current + Math.max(0, Date.now() - lastChunkAtRef.current)
        setElapsedMs(elapsed)
        if (elapsed >= (policy?.max_duration_seconds || 3600) * 1000) stopRecording()
      }, 500)
    } catch (error) {
      releaseMicrophone()
      const detail = (error as { name?: string })?.name === 'NotAllowedError'
        ? '沒有取得麥克風權限，請在瀏覽器設定中允許後再試。'
        : '無法啟動訪談錄音，請確認網路與麥克風後再試。'
      fail(detail)
    }
  }, [beginSegment, contextMetadata, dataClassification, departmentId, disabled, equipmentId, fail, policy, purpose, releaseMicrophone, sourceModule, state, stopRecording, title])

  const togglePause = useCallback(() => {
    const recorder = recorderRef.current
    if (!recorder) return
    if (recorder.state === 'recording') {
      pausingRef.current = true
      clearTimer()
      setState('paused')
      recorder.stop()
      setMessage('錄音已暫停。')
    } else if (state === 'paused' || recorder.state === 'inactive') {
      pausingRef.current = false
      beginSegment()
      setState('recording')
      timerRef.current = window.setInterval(() => {
        const elapsed = nextOffsetRef.current + Math.max(0, Date.now() - lastChunkAtRef.current)
        setElapsedMs(elapsed)
        if (elapsed >= (policy?.max_duration_seconds || 3600) * 1000) stopRecording()
      }, 500)
    }
  }, [beginSegment, clearTimer, policy?.max_duration_seconds, state, stopRecording])

  const retryUpload = useCallback(async () => {
    if (!session) return
    setState('uploading')
    const uploaded = await drain(session)
    if (uploaded && stoppingRef.current) await finishIfUploaded(session)
  }, [drain, finishIfUploaded, session])

  useEffect(() => {
    const storedSessionId = localStorage.getItem(ACTIVE_SESSION_KEY)
    if (!storedSessionId) return
    void (async () => {
      try {
        const capture = await captureApi.get(storedSessionId)
        const pending = await refreshPendingCount(storedSessionId)
        setSession(capture)
        sessionRef.current = capture
        // A restored recording has no live MediaRecorder, so "retry upload"
        // must finalize it once every locally persisted chunk is acknowledged.
        stoppingRef.current = capture.status === 'recording' || capture.status === 'uploading'
        nextSequenceRef.current = Math.max(capture.received_chunks, ...pending.map(item => item.sequence + 1), 0)
        nextOffsetRef.current = Math.max(capture.total_duration_ms, ...pending.map(item => item.offsetMs + item.durationMs), 0)
        setElapsedMs(nextOffsetRef.current)
        setSafeMs(capture.total_duration_ms)
        setState(
          capture.status === 'recording' || capture.status === 'uploading'
            ? 'uploading'
            : capture.status === 'failed'
              ? 'error'
              : 'queued',
        )
        if (['queued', 'transcribing', 'ready_for_review', 'failed'].includes(capture.status)) {
          onQueued(capture)
        }
        if (pending.length) setMessage('已找到未上傳的訪談片段；恢復網路後請按「重試上傳」。')
      } catch {
        localStorage.removeItem(ACTIVE_SESSION_KEY)
      }
    })()
    return () => {
      clearTimer()
    }
  }, [clearTimer, onQueued, refreshPendingCount])

  useEffect(() => {
    void captureApi.policy().then(setPolicy).catch(() => {
      fail('無法取得此租戶的錄音政策，請重新整理後再試。')
    })
    if (navigator.storage?.estimate) {
      void navigator.storage.estimate().then(estimate => {
        if (estimate.quota != null && estimate.usage != null) {
          setStorageAvailable(Math.max(0, estimate.quota - estimate.usage))
        }
      }).catch(() => undefined)
    }
  }, [fail])

  useEffect(() => {
    const retryWhenOnline = () => {
      const capture = sessionRef.current
      if (capture && state === 'uploading') void drain(capture)
    }
    const warnWhenHidden = () => {
      if (document.visibilityState !== 'hidden' || state !== 'recording') return
      recorderRef.current?.requestData?.()
      setMessage('已嘗試先保存目前片段；鎖屏或切換 App 仍可能中斷瀏覽器錄音，請回到此頁確認狀態。')
    }
    window.addEventListener('online', retryWhenOnline)
    document.addEventListener('visibilitychange', warnWhenHidden)
    return () => {
      window.removeEventListener('online', retryWhenOnline)
      document.removeEventListener('visibilitychange', warnWhenHidden)
    }
  }, [drain, state])

  useEffect(() => () => {
    clearTimer()
    releaseMicrophone()
  }, [clearTimer, releaseMicrophone])

  useEffect(() => {
    if (captureStatus === 'ready_for_review') {
      setMessage('逐字稿已完成，請在下方校正後建立知識卡草稿。')
    } else if (captureStatus === 'failed') {
      setMessage('轉寫失敗；錄音已安全保存，請使用下方的重新排入轉寫。')
    } else if (captureStatus === 'transcribing') {
      setMessage('錄音已安全上傳，正在轉寫。您可離開本頁，完成後再回來查看。')
    }
  }, [captureStatus])

  const isRecording = state === 'recording' || state === 'paused'
  useEffect(() => {
    if (!isRecording) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [isRecording])
  return (
    <section className="rounded-2xl border border-teal-200 bg-teal-50 p-4 text-ink">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{heading}</h2>
          <p className="mt-1 text-sm text-muted">錄音每 30 秒安全保存一次。錄音時請保持頁面開啟；鎖屏或切換 App 可能會中斷手機瀏覽器錄音。</p>
        </div>
        {pendingCount > 0 && <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 text-xs text-amber-800"><WifiOff className="h-3.5 w-3.5" />待上傳 {pendingCount} 段</span>}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-white p-3 text-sm sm:grid-cols-3">
        <div><p className="text-muted">錄製時間</p><p className="font-mono text-lg">{formatDuration(elapsedMs)}</p></div>
        <div><p className="text-muted">安全上傳</p><p className="font-mono text-lg">{formatDuration(safeMs)}</p></div>
        <div className="col-span-2 sm:col-span-1"><p className="text-muted">上限</p><p className="font-mono text-lg">{formatDuration((policy?.max_duration_seconds || 3600) * 1000)}</p></div>
      </div>
      <p className="mt-2 text-xs text-muted">{storageAvailable == null ? '裝置可用空間由瀏覽器管理，錄音前請確認空間充足。' : `瀏覽器估計可用空間約 ${Math.max(0, Math.floor(storageAvailable / 1024 / 1024))} MB。`} 術語表：{policy ? `${policy.terminology_count} 筆` : '載入中'}；音訊保留 {policy?.audio_retention_days ?? '—'} 天。</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {!isRecording && state !== 'uploading' && state !== 'queued' && (
          <button type="button" disabled={disabled || state === 'starting'} onClick={() => void startRecording()} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 font-semibold text-white disabled:opacity-50">
            {state === 'starting' ? <Loader2 className="h-5 w-5 animate-spin" /> : <Mic className="h-5 w-5" />}開始訪談
          </button>
        )}
        {isRecording && <button type="button" onClick={togglePause} className="inline-flex items-center gap-2 rounded-xl border border-line bg-white px-4 py-2.5 font-semibold">{state === 'paused' ? <Play className="h-5 w-5" /> : <Pause className="h-5 w-5" />}{state === 'paused' ? '繼續' : '暫停'}</button>}
        {isRecording && <button type="button" onClick={stopRecording} className="inline-flex items-center gap-2 rounded-xl bg-danger px-4 py-2.5 font-semibold text-white"><Square className="h-5 w-5" />結束訪談</button>}
        {state === 'uploading' && <button type="button" onClick={() => void retryUpload()} className="inline-flex items-center gap-2 rounded-xl border border-teal-700 bg-white px-4 py-2.5 font-semibold text-teal-800"><UploadCloud className="h-5 w-5" />重試上傳</button>}
      </div>
      {message && <p className={clsx('mt-3 text-sm', state === 'error' ? 'text-danger' : 'text-muted')} role="status">{message}</p>}
    </section>
  )
}
