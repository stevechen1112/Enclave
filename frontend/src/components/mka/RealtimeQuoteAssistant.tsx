import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Volume2 } from 'lucide-react'
import type { FormFieldSpec } from '../../services/mka'
import { tasksApi, type TaskRun } from '../../services/tasks'

type Props = {
  run: TaskRun
  fields: FormFieldSpec[]
  disabled?: boolean
  onRunUpdated: (run: TaskRun) => void
  onError: (message: string) => void
}

type Line = { id: string; role: 'assistant' | 'user' | 'system'; text: string }

function eventText(event: Record<string, unknown>): { role: 'assistant' | 'user'; text: string } | null {
  if (event.type === 'conversation.item.input_audio_transcription.completed') {
    return { role: 'user', text: String(event.transcript ?? '').trim() }
  }
  if (
    event.type === 'response.output_audio_transcript.done' ||
    event.type === 'response.audio_transcript.done'
  ) {
    return { role: 'assistant', text: String(event.transcript ?? '').trim() }
  }
  return null
}

export default function RealtimeQuoteAssistant({
  run,
  fields,
  disabled,
  onRunUpdated,
  onError,
}: Props) {
  const [state, setState] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle')
  const [lines, setLines] = useState<Line[]>([])
  const peerRef = useRef<RTCPeerConnection | null>(null)
  const channelRef = useRef<RTCDataChannel | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const handledCalls = useRef(new Set<string>())
  const mountedRef = useRef(true)
  const sessionLimitRef = useRef<number | null>(null)

  const appendLine = useCallback((role: Line['role'], text: string) => {
    if (!text) return
    setLines(previous => [
      ...previous.slice(-11),
      { id: `${Date.now()}-${Math.random()}`, role, text },
    ])
  }, [])

  const stop = useCallback(() => {
    if (sessionLimitRef.current !== null) window.clearTimeout(sessionLimitRef.current)
    sessionLimitRef.current = null
    channelRef.current?.close()
    channelRef.current = null
    peerRef.current?.close()
    peerRef.current = null
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
    if (audioRef.current) audioRef.current.srcObject = null
    if (mountedRef.current) setState('idle')
  }, [])

  const send = useCallback((event: Record<string, unknown>) => {
    const channel = channelRef.current
    if (channel?.readyState === 'open') channel.send(JSON.stringify(event))
  }, [])

  const handleToolCall = useCallback(async (item: Record<string, unknown>) => {
    const callId = String(item.call_id ?? '')
    const name = String(item.name ?? '')
    if (!callId || handledCalls.current.has(callId)) return
    handledCalls.current.add(callId)
    let args: Record<string, unknown> = {}
    try {
      args = JSON.parse(String(item.arguments ?? '{}')) as Record<string, unknown>
      const result = await tasksApi.callQuoteRealtimeTool({
        run_id: run.id,
        call_id: callId,
        name,
        arguments: args,
      })
      const updated = await tasksApi.getRun(run.id)
      if (mountedRef.current) onRunUpdated(updated)
      send({
        type: 'conversation.item.create',
        item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(result) },
      })
      send({ type: 'response.create' })
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      send({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: callId,
          output: JSON.stringify({ error: detail ?? '工具執行失敗，請重新確認欄位。' }),
        },
      })
      send({ type: 'response.create' })
    }
  }, [onRunUpdated, run.id, send])

  const handleMessage = useCallback((message: MessageEvent<string>) => {
    let event: Record<string, unknown>
    try {
      event = JSON.parse(message.data) as Record<string, unknown>
    } catch {
      return
    }
    const line = eventText(event)
    if (line) appendLine(line.role, line.text)
    if (event.type === 'error') {
      appendLine('system', '語音服務發生錯誤，請停止後重試。')
      return
    }
    if (event.type !== 'response.done') return
    const response = event.response as { output?: Array<Record<string, unknown>> } | undefined
    response?.output?.filter(item => item.type === 'function_call').forEach(item => {
      void handleToolCall(item)
    })
  }, [appendLine, handleToolCall])

  const start = useCallback(async () => {
    if (disabled || state === 'connecting' || state === 'connected') return
    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === 'undefined') {
      onError('此瀏覽器不支援即時語音，請改用最新版 Chrome、Edge 或 Safari。')
      return
    }
    setState('connecting')
    setLines([])
    handledCalls.current.clear()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream
      const peer = new RTCPeerConnection()
      peerRef.current = peer
      stream.getAudioTracks().forEach(track => peer.addTrack(track, stream))

      const audio = new Audio()
      audio.autoplay = true
      audioRef.current = audio
      peer.ontrack = event => {
        audio.srcObject = event.streams[0]
        void audio.play().catch(() => undefined)
      }
      peer.onconnectionstatechange = () => {
        if (peer.connectionState === 'failed' || peer.connectionState === 'disconnected') {
          appendLine('system', '語音連線已中斷。')
          stop()
        }
      }

      const channel = peer.createDataChannel('oai-events')
      channelRef.current = channel
      channel.addEventListener('message', handleMessage)
      channel.addEventListener('open', () => {
        if (!mountedRef.current) return
        setState('connected')
        appendLine('system', '已連線，直接說出報價內容即可。')
        sessionLimitRef.current = window.setTimeout(() => {
          appendLine('system', '本次語音對話已達 15 分鐘上限；需要時可重新開始。')
          stop()
        }, 15 * 60 * 1000)
        send({
          type: 'response.create',
          response: {
            instructions: '先簡短問候，說明你會逐欄協助完成報價，接著詢問第一個缺少欄位。',
          },
        })
      })

      const offer = await peer.createOffer()
      await peer.setLocalDescription(offer)
      if (!offer.sdp) throw new Error('瀏覽器未建立語音連線資訊')
      const answerSdp = await tasksApi.createQuoteRealtimeSession(run.id, offer.sdp)
      await peer.setRemoteDescription({ type: 'answer', sdp: answerSdp })
    } catch (error) {
      stop()
      setState('error')
      const status = (error as { response?: { status?: number } })?.response?.status
      const message = status === 503
        ? '即時 AI 語音助理尚未啟用，仍可使用下方文字輸入。'
        : status === 502
          ? '目前無法連上 AI 語音服務，請稍後重試。'
          : '無法啟動麥克風；請確認瀏覽器已允許麥克風權限。'
      onError(message)
    }
  }, [appendLine, disabled, handleMessage, onError, run.id, send, state, stop])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      stop()
    }
  }, [stop])

  useEffect(() => {
    if (disabled && state === 'connected') stop()
  }, [disabled, state, stop])

  const fieldLabels = Object.fromEntries(fields.map(field => [field.name, field.label || field.name]))
  const missing = fields
    .filter(field => field.required && !field.calculated)
    .filter(field => (run.input_snapshot.values ?? {})[field.name] === undefined || (run.input_snapshot.values ?? {})[field.name] === '')
    .map(field => fieldLabels[field.name])

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl border border-line bg-canvas/60 p-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-bold text-ink">AI 語音助理</p>
            <p className="text-sm text-muted">
              {state === 'connected' ? '正在聆聽，可自然對話或打斷助理' : '多輪詢問、即時帶入、逐欄核對'}
            </p>
          </div>
          {state === 'connected' || state === 'connecting' ? (
            <button type="button" onClick={stop} className="flex min-h-11 items-center gap-2 rounded-xl bg-red-600 px-4 font-bold text-white">
              <MicOff className="h-5 w-5" /> 結束對話
            </button>
          ) : (
            <button type="button" onClick={start} disabled={disabled} className="flex min-h-11 items-center gap-2 rounded-xl bg-accent px-4 font-bold text-white disabled:opacity-40">
              <Mic className="h-5 w-5" /> 開始語音對話
            </button>
          )}
        </div>
        {missing.length > 0 ? (
          <p className="mt-2 text-sm text-amber-800">尚缺：{missing.join('、')}</p>
        ) : (
          <p className="mt-2 text-sm font-medium text-green-700">必填資料已齊，請核對右側欄位後親自送審。</p>
        )}
      </div>
      {lines.length > 0 && (
        <div aria-live="polite" className="max-h-52 space-y-2 overflow-y-auto rounded-xl border border-line p-3 text-sm">
          {lines.map(line => (
            <p key={line.id} className={line.role === 'system' ? 'text-muted' : 'text-ink'}>
              <span className="mr-2 font-bold">
                {line.role === 'assistant' ? <Volume2 className="inline h-4 w-4" /> : line.role === 'user' ? '你' : '系統'}
              </span>
              {line.text}
            </p>
          ))}
        </div>
      )}
      <p className="text-xs text-muted">助理只會更新草稿，不會自行送審或產生正式文件；送審前請逐欄核對。</p>
    </div>
  )
}
