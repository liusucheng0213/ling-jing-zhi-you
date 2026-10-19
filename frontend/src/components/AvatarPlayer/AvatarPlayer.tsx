import { useEffect, useRef, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { SoundOutlined } from '@ant-design/icons'
import {
  acquireAvatarChannel,
  heartbeatAvatarChannel,
  releaseAvatarChannel,
  releaseAvatarChannelBeacon,
  type AvatarChannelResponse,
  type AvatarChannelStatus,
} from '../../services/avatarChannel'
import {
  recordAvatarTelemetry,
  type AvatarTelemetryContext,
  type AvatarTelemetryEvent,
} from '../../services/avatarTelemetry'
import './AvatarPlayer.css'

interface Props {
  avatarCode?: string
  avatarName?: string
  speechRate?: number
  emotion?: string
  isSpeaking?: boolean
  audioUrl?: string
  videoUrl?: string
  speechText?: string
  speechRequestId?: number
  speechStopRequestId?: number
  connectionResetId?: number
  expression?: string
  lipSyncMode?: string
  visemeSequence?: Array<{ t: number; open: number }>
  actionSequence?: AvatarActionInput[]
  sdkConfig?: Record<string, any>
  errorMessage?: string | null
  telemetryContext?: AvatarTelemetryContext
  telemetrySessionId?: string | null
  onSpeakStart?: () => void
  onSpeakEnd?: () => void
  onConnectionRecovery?: () => Promise<void> | void
}

export type AvatarActionInput = string | {
  id?: string
  action_id?: string
  value?: string
  name?: string
  timing?: string
  delay_ms?: number
}

interface NormalizedAvatarAction {
  id: string
  name: string
  timing: string
  delayMs: number
}

const AVATAR_CONFIG: Record<string, { name: string; accent: string }>
= {
  lingxiaochan: { name: '舒窈', accent: '#c9a87c' },
  wuchanshi: { name: '明朗', accent: '#8a7a6a' },
  xuanzang: { name: '风屿', accent: '#b89858' },
  xiaowan: { name: '雨桐', accent: '#b898a8' },
  zhaopuchu: { name: '明泽', accent: '#315F91' },
}

// 与后端 EmotionEngine.EMOTION_TYPES 保持一致；chip 展示的是实时感知到的游客情绪，
// 数字人的语气、动作与温度会基于该情绪自适应调整。
const EMOTION_CONFIG: Record<string, { icon: string; label: string; color: string }>
= {
  happy: { icon: '✨', label: '愉悦', color: '#e6a817' },
  curious: { icon: '🌟', label: '好奇', color: '#5b9bd5' },
  calm: { icon: '🍃', label: '平静', color: '#70ad47' },
  tired: { icon: '💤', label: '疲惫', color: '#9e9e9e' },
  frustrated: { icon: '💭', label: '沮丧', color: '#c55a11' },
  anxious: { icon: '⏳', label: '焦虑', color: '#d4880f' },
  neutral: { icon: '😊', label: '平静', color: '#70ad47' },
  excited: { icon: '🔥', label: '兴奋', color: '#ff6b6b' },
}

declare global {
  interface Window {
    __xfyunAvatarSdkModule?: any
    __xfyunAvatarSdkPromise?: Promise<any>
  }
}

const destroyXfyunPlatform = (platform: any) => {
  if (!platform) return
  platform?.stop?.()
  platform?.destroy?.()
}

const getVisitorChannelOwnerId = () => {
  const storageKey = 'lingjing_avatar_channel_owner'
  const stored = sessionStorage.getItem(storageKey)
  if (stored) return stored
  const suffix = crypto.randomUUID?.() || Math.random().toString(36).slice(2)
  const ownerId = `visitor-${suffix}`
  sessionStorage.setItem(storageKey, ownerId)
  return ownerId
}

const isAvatarAuthenticationError = (message: string) => (
  /avatar authentication failed|authentication failed|鉴权失败|unauthorized/i.test(message)
)

const restoreXfyunAudio = async (platform: any) => {
  const player = platform?.player
  if (!player) return
  try {
    player.volume = 1
    player.muted = false
    await player.resume?.()
  } catch (error) {
    console.warn('讯飞数字人音频恢复失败:', error)
  }
}

const describeSdkError = (error: unknown) => {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  if (error && typeof error === 'object') {
    const payload = error as Record<string, unknown>
    const code = payload.code ?? payload.errorCode
    const message = payload.message ?? payload.msg ?? payload.error
    if (code || message) {
      return [code ? `code=${code}` : '', message ? String(message) : ''].filter(Boolean).join(' ')
    }
  }
  return '讯飞数字人服务返回未知错误。'
}

const readSdkRecord = (value: unknown): Record<string, unknown> | null => (
  value && typeof value === 'object' ? value as Record<string, unknown> : null
)

const cleanSdkSubtitle = (value: string) => value
  .replace(/\[\[[^\]]+\]\]/g, '')
  .replace(/\[=[^\]]+\]/g, '')
  .replace(/\s+/g, ' ')
  .trim()

/** 仅解析讯飞 subtitle_info 事件载荷，不使用回答正文伪造字幕。 */
export const extractSdkSubtitleText = (payload: unknown): string => {
  if (typeof payload === 'string') return cleanSdkSubtitle(payload)
  const record = readSdkRecord(payload)
  if (!record) return ''
  const nestedText = readSdkRecord(record.text)
  const nestedSubtitle = readSdkRecord(record.subtitle)
  const candidates = [
    record.content,
    record.text,
    record.sentence,
    record.value,
    nestedText?.content,
    nestedText?.text,
    nestedSubtitle?.content,
    nestedSubtitle?.text,
  ]
  const matched = candidates.find((item) => typeof item === 'string' && item.trim())
  return typeof matched === 'string' ? cleanSdkSubtitle(matched) : ''
}

/** 保留供应商返回的真实时长数值，不推算字幕时间轴。 */
export const extractSdkTtsDuration = (payload: unknown): number | null => {
  if (typeof payload === 'number' && Number.isFinite(payload)) return payload
  const record = readSdkRecord(payload)
  if (!record) return null
  const value = record.duration ?? record.tts_duration ?? record.audio_duration ?? record.value
  const duration = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(duration) && duration >= 0 ? duration : null
}

const getSdkRequestId = (payload: unknown) => {
  const record = readSdkRecord(payload)
  const value = record?.request_id ?? record?.requestId
  return typeof value === 'string' ? value : ''
}

export const normalizeAvatarActions = (actions: AvatarActionInput[]): NormalizedAvatarAction[] => {
  const seen = new Set<string>()
  return actions.flatMap((action) => {
    const item = typeof action === 'string' ? { id: action } : action
    const id = String(item.id || item.action_id || item.value || '').trim()
    if (!id || seen.has(id)) return []
    seen.add(id)
    return [{
      id,
      name: String(item.name || ''),
      timing: String(item.timing || ''),
      delayMs: Number.isFinite(item.delay_ms) ? Math.max(0, Number(item.delay_ms)) : 0,
    }]
  })
}

const SUBTITLE_ACTION_RULES: Array<{ subtitle: RegExp; action: RegExp }> = [
  { subtitle: /你好|您好|欢迎|很高兴/, action: /hello|welcome|招呼|欢迎/i },
  { subtitle: /感谢|谢谢|致敬|敬意/, action: /respect|jingli|感谢|致敬|抚胸/i },
  { subtitle: /再见|下次见|期待再会/, action: /wave|bye|挥手|拜拜/i },
  { subtitle: /左侧|左边|向左|往左/, action: /left|左/i },
  { subtitle: /右侧|右边|向右|往右/, action: /right|右/i },
  { subtitle: /前方|向前|往前|接下来/, action: /forward|show|展示|欢迎/i },
  { subtitle: /可以|没问题|好的|当然/, action: /ok|点赞|加油/i },
  { subtitle: /重点|核心|首先|建议|注意|特别/, action: /emphasize|talk|强调|交流|scratch/i },
]

const GENERAL_ACTION_KEYWORDS = /你好|您好|欢迎|感谢|谢谢|再见|左侧|左边|右侧|右边|前方|向前|接下来|重点|核心|首先|建议|注意|可以|好的|一起|请看/

/** 从本轮后端已授权的动作序列中，按真实字幕语义选择一个尚未使用的动作。 */
export const selectSubtitleAction = (
  subtitle: string,
  actions: NormalizedAvatarAction[],
  usedActionIds: ReadonlySet<string>,
) => {
  const available = actions.filter((action) => !usedActionIds.has(action.id))
  if (!available.length) return null
  for (const rule of SUBTITLE_ACTION_RULES) {
    if (!rule.subtitle.test(subtitle)) continue
    const semanticMatch = available.find((action) => rule.action.test(`${action.id} ${action.name}`))
    if (semanticMatch) return semanticMatch
  }
  return GENERAL_ACTION_KEYWORDS.test(subtitle) ? available[0] : null
}

const loadXfyunAvatarSdk = () => {
  if (window.__xfyunAvatarSdkModule) {
    return Promise.resolve(window.__xfyunAvatarSdkModule)
  }
  if (window.__xfyunAvatarSdkPromise) {
    return window.__xfyunAvatarSdkPromise
  }

  window.__xfyunAvatarSdkPromise = import('../../vendor/avatar-sdk-web/esm/index.js')
    .then((mod) => {
      window.__xfyunAvatarSdkModule = mod
      return mod
    })

  return window.__xfyunAvatarSdkPromise
}

const preloadedAvatarAssets = new Set<string>()

const preloadImageAsset = (src: string) => {
  if (preloadedAvatarAssets.has(src)) return
  preloadedAvatarAssets.add(src)
  const image = new Image()
  image.decoding = 'async'
  image.src = src
}

/**
 * 角色选定后只预加载 SDK 模块与静态资源；这里不会请求签名、租约或建立 WebSocket。
 */
export const preloadAvatarRuntime = (avatarCode = 'lingxiaochan') => {
  if (typeof window === 'undefined') return
  void loadXfyunAvatarSdk().catch((error) => {
    console.warn('讯飞数字人SDK预加载失败:', error)
  })
  const normalizedCode = AVATAR_CONFIG[avatarCode] ? avatarCode : 'lingxiaochan'
  preloadImageAsset(`/assets/avatars/${normalizedCode}.jpg`)
  preloadImageAsset('/assets/avatar-backgrounds/lingjing-avatar-bg-v1.png')
  preloadImageAsset('/assets/avatar-backgrounds/lingjing-avatar-bg-v1-1080x1920.png')
}

export default function AvatarPlayer({
  avatarCode = 'lingxiaochan',
  avatarName,
  speechRate = 1,
  emotion = 'neutral',
  isSpeaking = false,
  audioUrl,
  videoUrl,
  speechText,
  speechRequestId = 0,
  speechStopRequestId = 0,
  connectionResetId = 0,
  visemeSequence = [],
  actionSequence = [],
  sdkConfig,
  errorMessage,
  telemetryContext,
  telemetrySessionId,
  onSpeakStart,
  onSpeakEnd,
  onConnectionRecovery,
}: Props) {
  const config = AVATAR_CONFIG[avatarCode] || AVATAR_CONFIG.lingxiaochan
  const emotionConfig = EMOTION_CONFIG[emotion] || EMOTION_CONFIG.neutral

  const [speaking, setSpeaking] = useState(isSpeaking)
  const [waveData, setWaveData] = useState<number[]>(Array(20).fill(0))
  const [sdkError, setSdkError] = useState<string | null>(null)
  const [sdkVisualReady, setSdkVisualReady] = useState(false)
  const [sdkReconnectRevision, setSdkReconnectRevision] = useState(0)
  const [audioUnlockNeeded, setAudioUnlockNeeded] = useState(false)
  const [playbackError, setPlaybackError] = useState<string | null>(null)
  const [subtitleLines, setSubtitleLines] = useState<string[]>([])
  const [sdkTtsDuration, setSdkTtsDuration] = useState<number | null>(null)
  const [channelStatus, setChannelStatus] = useState<AvatarChannelStatus>('idle')
  const [channelMessage, setChannelMessage] = useState('正在申请数字人通道')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animationRef = useRef<number>(0)
  const audioContextRef = useRef<AudioContext | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const syntheticTimerRef = useRef<number | null>(null)
  const visemeFrameRef = useRef<number>(0)
  const visemeStartRef = useRef<number>(0)
  const sdkContainerRef = useRef<HTMLDivElement | null>(null)
  const sdkPlatformRef = useRef<any>(null)
  const sdkConfigKeyRef = useRef('')
  const lastSdkTextRef = useRef('')
  const actionSequenceRef = useRef<NormalizedAvatarAction[]>(normalizeAvatarActions(actionSequence))
  const sdkActionQueueRef = useRef<NormalizedAvatarAction[]>([])
  const sdkActionTimerRef = useRef<number | null>(null)
  const sdkActionDrainRef = useRef<() => void>(() => undefined)
  const usedSdkActionIdsRef = useRef(new Set<string>())
  const sdkActionCountRef = useRef(0)
  const lastSdkActionAtRef = useRef(0)
  const sdkFrameStartedAtRef = useRef(0)
  const activeSdkSpeechRequestIdRef = useRef('')
  const sdkSpeechActiveRef = useRef(false)
  const sdkOwnerIdRef = useRef(getVisitorChannelOwnerId())
  const channelLeaseTokenRef = useRef('')
  const channelHeartbeatTimerRef = useRef<number | null>(null)
  const channelRetryTimerRef = useRef<number | null>(null)
  const channelReleasePromiseRef = useRef<Promise<void> | null>(null)
  const handleLeaseRevokedRef = useRef<() => void>(() => undefined)
  const sdkAuthenticationFailedRef = useRef(false)
  const sdkRetryKeyRef = useRef('')
  const sdkReconnectTimerRef = useRef<number | null>(null)
  const sdkReconnectAttemptsRef = useRef(0)
  const pageIsUnloadingRef = useRef(false)
  const onConnectionRecoveryRef = useRef(onConnectionRecovery)
  const onSpeakStartRef = useRef(onSpeakStart)
  const onSpeakEndRef = useRef(onSpeakEnd)
  const telemetryContextRef = useRef<AvatarTelemetryContext | undefined>(telemetryContext)
  const telemetrySessionIdRef = useRef<string | null | undefined>(telemetrySessionId)
  const telemetryEventKeysRef = useRef(new Set<string>())
  const voiceStopTraceRef = useRef('')
  const speechRequestIdRef = useRef(speechRequestId)

  useEffect(() => {
    onConnectionRecoveryRef.current = onConnectionRecovery
  }, [onConnectionRecovery])

  useEffect(() => {
    onSpeakStartRef.current = onSpeakStart
    onSpeakEndRef.current = onSpeakEnd
  }, [onSpeakEnd, onSpeakStart])

  useEffect(() => {
    telemetryContextRef.current = telemetryContext
    telemetrySessionIdRef.current = telemetrySessionId
    if (
      telemetryContext?.inputMode === 'voice'
      && telemetryContext.traceId
      && voiceStopTraceRef.current !== telemetryContext.traceId
    ) {
      voiceStopTraceRef.current = telemetryContext.traceId
      recordAvatarTelemetry(telemetryContext, 'voice_stop', {
        sessionId: telemetrySessionId,
        avatarCode,
        requestId: String(speechRequestIdRef.current || ''),
        evidenceKind: 'human_microphone',
        eventEpochMs: telemetryContext.startedAtEpochMs || undefined,
        relativeMs: 0,
      })
    }
  }, [avatarCode, telemetryContext, telemetrySessionId])

  useEffect(() => {
    speechRequestIdRef.current = speechRequestId
    telemetryEventKeysRef.current.clear()
  }, [speechRequestId])

  const emitTelemetry = useCallback((
    eventType: AvatarTelemetryEvent,
    requestId?: string,
    eventData?: Record<string, unknown>,
    allowRepeat = false,
  ) => {
    const key = `${speechRequestIdRef.current}:${eventType}`
    if (!allowRepeat && telemetryEventKeysRef.current.has(key)) return
    telemetryEventKeysRef.current.add(key)
    recordAvatarTelemetry(telemetryContextRef.current, eventType, {
      sessionId: telemetrySessionIdRef.current,
      avatarCode,
      requestId,
      eventData,
      evidenceKind: telemetryContextRef.current?.inputMode === 'voice'
        ? 'human_microphone'
        : 'browser_sdk',
    })
  }, [avatarCode])

  useEffect(() => {
    actionSequenceRef.current = normalizeAvatarActions(actionSequence)
  }, [actionSequence])

  const clearSdkSpeechPresentation = useCallback(() => {
    if (sdkActionTimerRef.current !== null) {
      window.clearTimeout(sdkActionTimerRef.current)
      sdkActionTimerRef.current = null
    }
    sdkActionQueueRef.current = []
    usedSdkActionIdsRef.current.clear()
    sdkActionCountRef.current = 0
    lastSdkActionAtRef.current = 0
    sdkFrameStartedAtRef.current = 0
    activeSdkSpeechRequestIdRef.current = ''
    sdkSpeechActiveRef.current = false
    setSubtitleLines([])
    setSdkTtsDuration(null)
  }, [])

  const isActiveSdkSpeechEvent = useCallback((payload: unknown) => {
    const activeRequestId = activeSdkSpeechRequestIdRef.current
    if (!activeRequestId) return false
    const eventRequestId = getSdkRequestId(payload)
    if (!eventRequestId) return true
    if (activeRequestId === 'pending') {
      activeSdkSpeechRequestIdRef.current = eventRequestId
      return true
    }
    return eventRequestId === activeRequestId
  }, [])

  const clearChannelHeartbeat = useCallback(() => {
    if (channelHeartbeatTimerRef.current !== null) {
      window.clearInterval(channelHeartbeatTimerRef.current)
      channelHeartbeatTimerRef.current = null
    }
  }, [])

  const releaseChannelLease = useCallback((useBeacon = false) => {
    clearChannelHeartbeat()
    const leaseToken = channelLeaseTokenRef.current
    channelLeaseTokenRef.current = ''
    if (!leaseToken) return
    if (useBeacon && releaseAvatarChannelBeacon(leaseToken)) return
    const releasePromise = releaseAvatarChannel(leaseToken)
      .then(() => undefined)
      .catch((error) => {
        if (!useBeacon) console.warn('数字人通道租约释放失败:', error)
      })
    channelReleasePromiseRef.current = releasePromise
    void releasePromise.finally(() => {
      if (channelReleasePromiseRef.current === releasePromise) {
        channelReleasePromiseRef.current = null
      }
    })
  }, [clearChannelHeartbeat])

  const acquireChannelLease = useCallback(async (): Promise<AvatarChannelResponse> => {
    if (channelReleasePromiseRef.current) {
      await channelReleasePromiseRef.current
    }
    const existingToken = channelLeaseTokenRef.current
    if (existingToken) {
      const heartbeat = await heartbeatAvatarChannel(existingToken)
      if (heartbeat.status === 'acquired') return heartbeat
      channelLeaseTokenRef.current = ''
      clearChannelHeartbeat()
    }

    const result = await acquireAvatarChannel(sdkOwnerIdRef.current, 'visitor')
    setChannelStatus(result.status)
    setChannelMessage(result.message)
    if (result.status !== 'acquired' || !result.lease_token) return result

    channelLeaseTokenRef.current = result.lease_token
    clearChannelHeartbeat()
    channelHeartbeatTimerRef.current = window.setInterval(() => {
      const token = channelLeaseTokenRef.current
      if (!token) return
      void heartbeatAvatarChannel(token)
        .then((heartbeat) => {
          if (heartbeat.status === 'acquired') return
          channelLeaseTokenRef.current = ''
          clearChannelHeartbeat()
          setChannelStatus(heartbeat.status)
          setChannelMessage(heartbeat.message)
          handleLeaseRevokedRef.current()
        })
        .catch((error) => {
          console.warn('数字人通道心跳暂时失败:', error)
        })
    }, 15_000)
    return result
  }, [clearChannelHeartbeat])

  const releaseSdkPlatform = useCallback((clearLastText = false, useBeacon = false) => {
    const platform = sdkPlatformRef.current
    sdkPlatformRef.current = null
    destroyXfyunPlatform(platform)
    releaseChannelLease(useBeacon)
    if (clearLastText) lastSdkTextRef.current = ''
    clearSdkSpeechPresentation()
    setSdkVisualReady(false)
  }, [clearSdkSpeechPresentation, releaseChannelLease])

  handleLeaseRevokedRef.current = () => {
    const platform = sdkPlatformRef.current
    sdkPlatformRef.current = null
    destroyXfyunPlatform(platform)
    clearSdkSpeechPresentation()
    setSdkVisualReady(false)
    setSpeaking(false)
  }

  const scheduleSdkReconnect = useCallback((delayMs = 700) => {
    if (pageIsUnloadingRef.current || document.visibilityState === 'hidden' || !navigator.onLine) return
    if (sdkReconnectTimerRef.current !== null) return
    if (sdkReconnectAttemptsRef.current >= 3) {
      setSdkError('数字人自动重连未成功，请点击“重新连接”再试。')
      return
    }
    sdkReconnectAttemptsRef.current += 1
    sdkReconnectTimerRef.current = window.setTimeout(async () => {
      sdkReconnectTimerRef.current = null
      try {
        await onConnectionRecoveryRef.current?.()
        setSdkError(null)
        setSdkReconnectRevision((value) => value + 1)
      } catch (error) {
        setSdkError(error instanceof Error ? error.message : '数字人连接凭证刷新失败')
      }
    }, delayMs)
  }, [])

  const analyzeAudio = useCallback(() => {
    if (!analyserRef.current) return
    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(dataArray)
    const waveBars = Array.from({ length: 20 }, (_, i) => {
      const idx = Math.floor((i / 20) * dataArray.length)
      return dataArray[idx] / 255
    })
    setWaveData(waveBars)
    animationRef.current = requestAnimationFrame(analyzeAudio)
  }, [])

  const stopSyntheticMouth = useCallback(() => {
    if (syntheticTimerRef.current) {
      window.clearInterval(syntheticTimerRef.current)
      syntheticTimerRef.current = null
    }
    cancelAnimationFrame(visemeFrameRef.current)
  }, [])

  const startVisemePlayback = useCallback((estimatedMs?: number) => {
    if (!visemeSequence.length) return
    cancelAnimationFrame(visemeFrameRef.current)
    visemeStartRef.current = performance.now()

    const run = () => {
      const elapsed = (performance.now() - visemeStartRef.current) / 1000
      let frame = visemeSequence[0]
      for (let index = 0; index < visemeSequence.length; index += 1) {
        if (visemeSequence[index].t <= elapsed) {
          frame = visemeSequence[index]
        } else {
          break
        }
      }
      setWaveData((prev) => prev.map((_, index) => {
        const pulse = Math.sin((elapsed * 9) + index * 0.7)
        return Math.max(0.08, frame.open * (0.55 + pulse * 0.25))
      }))

      const lastFrame = visemeSequence[visemeSequence.length - 1]
      const maxDuration = estimatedMs ? estimatedMs / 1000 : lastFrame.t + 0.8
      if (elapsed < maxDuration && !analyserRef.current) {
        visemeFrameRef.current = requestAnimationFrame(run)
      }
    }

    visemeFrameRef.current = requestAnimationFrame(run)
  }, [visemeSequence])

  const drainSdkActionQueue = useCallback(() => {
    if (
      sdkActionTimerRef.current !== null
      || !sdkSpeechActiveRef.current
      || !sdkActionQueueRef.current.length
      || sdkActionCountRef.current >= 3
    ) return

    const nextAction = sdkActionQueueRef.current[0]
    const providerDelay = nextAction.timing === 'during_speech' ? nextAction.delayMs : 0
    const sinceFrameStart = Date.now() - sdkFrameStartedAtRef.current
    const sinceLastAction = Date.now() - lastSdkActionAtRef.current
    const waitMs = Math.max(0, 2500 - sinceLastAction, providerDelay - sinceFrameStart)

    const execute = () => {
      sdkActionTimerRef.current = null
      if (!sdkSpeechActiveRef.current) return
      const action = sdkActionQueueRef.current.shift()
      const platform = sdkPlatformRef.current
      if (!action || !platform || sdkActionCountRef.current >= 3) return
      sdkActionCountRef.current += 1
      lastSdkActionAtRef.current = Date.now()
      const actionPromise = platform.writeCmd?.('action', action.id)
      emitTelemetry('action', activeSdkSpeechRequestIdRef.current, {
        action_id: action.id,
        action_name: action.name,
      }, true)
      actionPromise?.catch((error: unknown) => {
        console.warn('讯飞数字人动作触发失败:', action.id, error)
      })
      sdkActionDrainRef.current()
    }

    if (waitMs > 0) {
      sdkActionTimerRef.current = window.setTimeout(execute, waitMs)
    } else {
      execute()
    }
  }, [emitTelemetry])

  sdkActionDrainRef.current = drainSdkActionQueue

  const enqueueSubtitleAction = useCallback((subtitle: string) => {
    if (!sdkSpeechActiveRef.current) return
    if (sdkActionCountRef.current + sdkActionQueueRef.current.length >= 3) return
    const action = selectSubtitleAction(
      subtitle,
      actionSequenceRef.current,
      usedSdkActionIdsRef.current,
    )
    if (!action) return
    usedSdkActionIdsRef.current.add(action.id)
    sdkActionQueueRef.current.push(action)
    drainSdkActionQueue()
  }, [drainSdkActionQueue])

  const finishSpeaking = useCallback(() => {
    stopSyntheticMouth()
    clearSdkSpeechPresentation()
    setSpeaking(false)
    setWaveData(Array(20).fill(0))
    onSpeakEndRef.current?.()
  }, [clearSdkSpeechPresentation, stopSyntheticMouth])

  const describePlaybackError = useCallback((error: unknown) => {
    if (error instanceof DOMException) {
      if (error.name === 'NotAllowedError') {
        return '浏览器拦截了自动播放。请先点击页面或点击消息气泡的小喇叭播放。'
      }
      if (error.name === 'NotSupportedError') {
        return '浏览器不支持当前音频格式或音频地址不可用。'
      }
      return `${error.name}: ${error.message}`
    }
    if (error instanceof Error) {
      return error.message
    }
    return '音频播放失败，请查看浏览器控制台。'
  }, [])

  const waitForAudioReady = useCallback((audio: HTMLAudioElement) => (
    new Promise<void>((resolve, reject) => {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        cleanup()
        resolve()
      }
      const fail = (error: Event) => {
        if (settled) return
        settled = true
        cleanup()
        reject(error)
      }
      const timeout = window.setTimeout(finish, 1200)
      const cleanup = () => {
        window.clearTimeout(timeout)
        audio.removeEventListener('canplay', finish)
        audio.removeEventListener('loadedmetadata', finish)
        audio.removeEventListener('error', fail)
      }
      audio.addEventListener('canplay', finish, { once: true })
      audio.addEventListener('loadedmetadata', finish, { once: true })
      audio.addEventListener('error', fail, { once: true })
      audio.load()
    })
  ), [])

  const playAudio = useCallback(async (url: string) => {
    try {
      setPlaybackError(null)
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      audioContextRef.current?.close()

      const audio = new Audio(url)
      audio.playbackRate = speechRate
      audio.crossOrigin = 'anonymous'
      audio.preload = 'auto'
      audioRef.current = audio

      await waitForAudioReady(audio)

      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      audioContextRef.current = audioContext

      const source = audioContext.createMediaElementSource(audio)
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 128
      analyser.smoothingTimeConstant = 0.6

      source.connect(analyser)
      analyser.connect(audioContext.destination)
      analyserRef.current = analyser
      cancelAnimationFrame(visemeFrameRef.current)

      audio.addEventListener('ended', () => {
        emitTelemetry('complete')
        finishSpeaking()
        cancelAnimationFrame(animationRef.current)
        audioContextRef.current?.close()
      }, { once: true })

      audio.addEventListener('error', () => {
        finishSpeaking()
      }, { once: true })

      await audio.play()
      emitTelemetry('speech_start')
      setSpeaking(true)
      onSpeakStartRef.current?.()
      startVisemePlayback()
      animationRef.current = requestAnimationFrame(analyzeAudio)
    } catch (e) {
      console.error('音频播放失败:', e)
      setPlaybackError(describePlaybackError(e))
      finishSpeaking()
    }
  }, [analyzeAudio, describePlaybackError, emitTelemetry, finishSpeaking, speechRate, startVisemePlayback, waitForAudioReady])

  useEffect(() => {
    if (audioUrl && !videoUrl && !sdkConfig) {
      playAudio(audioUrl)
    }
    return () => {
      audioRef.current?.pause()
      audioRef.current = null
      cancelAnimationFrame(animationRef.current)
      audioContextRef.current?.close()
      stopSyntheticMouth()
    }
  }, [audioUrl, videoUrl, sdkConfig, playAudio, stopSyntheticMouth])

  useEffect(() => {
    if (!videoUrl || !videoRef.current) return
    const video = videoRef.current
    const handlePlaying = () => {
      emitTelemetry('speech_start')
      setSpeaking(true)
      onSpeakStartRef.current?.()
    }
    const handleEnded = () => {
      emitTelemetry('complete')
      setSpeaking(false)
      onSpeakEndRef.current?.()
    }
    video.addEventListener('playing', handlePlaying, { once: true })
    video.addEventListener('ended', handleEnded)
    video.play().catch((error) => {
      console.error('数字人视频播放失败:', error)
      setSpeaking(false)
      onSpeakEndRef.current?.()
    })
    return () => {
      video.removeEventListener('playing', handlePlaying)
      video.removeEventListener('ended', handleEnded)
    }
  }, [emitTelemetry, videoUrl])

  useEffect(() => {
    if (!sdkConfig || !isSpeaking) setSpeaking(isSpeaking)
  }, [isSpeaking, sdkConfig])

  useEffect(() => {
    setSdkError(null)
    setAudioUnlockNeeded(false)
    setPlaybackError(null)
  }, [sdkConfig, speechRequestId, speechText])

  useEffect(() => {
    if (!speechRequestId) return
    clearSdkSpeechPresentation()
    if (sdkConfig) setSpeaking(false)
  }, [clearSdkSpeechPresentation, sdkConfig, speechRequestId])

  useEffect(() => {
    if (!sdkConfig) return
    void loadXfyunAvatarSdk().catch((error) => {
      console.warn('讯飞数字人SDK预加载失败:', error)
    })
  }, [sdkConfig])

  useEffect(() => {
    if (!speechStopRequestId) return
    clearSdkSpeechPresentation()
    stopSyntheticMouth()
    audioRef.current?.pause()
    videoRef.current?.pause()
    const interruptPromise = sdkPlatformRef.current?.interrupt?.()
    emitTelemetry('interrupted', activeSdkSpeechRequestIdRef.current)
    interruptPromise?.catch((error: unknown) => {
      console.warn('停止讯飞数字人播报失败:', error)
    })
    setSpeaking(false)
    setWaveData(Array(20).fill(0))
  }, [clearSdkSpeechPresentation, emitTelemetry, speechStopRequestId, stopSyntheticMouth])

  useEffect(() => {
    if (!connectionResetId) return
    releaseSdkPlatform(true)
    sdkConfigKeyRef.current = ''
    sdkReconnectAttemptsRef.current = 0
    setSdkError(null)
    setPlaybackError(null)
    setSdkReconnectRevision((value) => value + 1)
  }, [connectionResetId, releaseSdkPlatform])

  useEffect(() => {
    let cancelled = false

    const runXfyunSdk = async () => {
      if (!sdkConfig || !sdkContainerRef.current) return
      const configKey = JSON.stringify({
        serverUrl: sdkConfig.api_info?.serverUrl,
        appId: sdkConfig.api_info?.appId,
        sceneId: sdkConfig.api_info?.sceneId,
        avatarId: sdkConfig.global_params?.avatar?.avatar_id,
        avatarWidth: sdkConfig.global_params?.avatar?.width,
        avatarHeight: sdkConfig.global_params?.avatar?.height,
        stream: sdkConfig.global_params?.stream,
        vcn: sdkConfig.global_params?.tts?.vcn,
        background: sdkConfig.global_params?.background,
        startOptions: sdkConfig.start_options,
      })
      if (sdkConfigKeyRef.current && sdkConfigKeyRef.current !== configKey) {
        releaseSdkPlatform(true)
      }
      sdkConfigKeyRef.current = configKey
      const textKey = `${configKey}:${speechRequestId}:${speechText}`
      console.info('讯飞数字人SDK配置:', {
        appId: sdkConfig.api_info?.appId,
        sceneId: sdkConfig.api_info?.sceneId,
        avatarId: sdkConfig.global_params?.avatar?.avatar_id,
        vcn: sdkConfig.global_params?.tts?.vcn,
        usesSignedUrl: Boolean(sdkConfig.api_info?.signedUrl),
        backgroundConfigured: Boolean(sdkConfig.background_configured),
        backgroundFields: sdkConfig.background_fields || [],
      })

      try {
        const mod = await loadXfyunAvatarSdk()
        const AvatarPlatform = mod.default
        const { SDKEvents } = mod
        if (cancelled) {
          return
        }
        if (!sdkPlatformRef.current) {
          setSdkVisualReady(false)
          const channel = await acquireChannelLease()
          if (channel.status !== 'acquired') {
            setSdkError(null)
            const retryAfter = Math.max(400, Math.min(1_500, channel.retry_after_ms || 800))
            if (channelRetryTimerRef.current === null && !cancelled) {
              channelRetryTimerRef.current = window.setTimeout(() => {
                channelRetryTimerRef.current = null
                setSdkReconnectRevision((value) => value + 1)
              }, retryAfter)
            }
            return
          }
          if (cancelled) return
          sdkAuthenticationFailedRef.current = false
          const platform = new AvatarPlatform({ useInlinePlayer: true, logLevel: 3 })
          const inlinePlayer = platform.createPlayer?.()
          if (inlinePlayer?.on && mod.PlayerEvents) {
            inlinePlayer
              .on(mod.PlayerEvents.playNotAllowed, () => {
                console.warn('讯飞数字人音频自动播放被浏览器拦截')
                setAudioUnlockNeeded(true)
              })
              .on(mod.PlayerEvents.playing, () => {
                setAudioUnlockNeeded(false)
                setSdkVisualReady(true)
                sdkReconnectAttemptsRef.current = 0
                restoreXfyunAudio(platform)
              })
          }
          platform.setApiInfo(sdkConfig.api_info)
          const providerSpeed = Math.round(Math.min(100, Math.max(0, 50 * speechRate)))
          platform.setGlobalParams({
            ...sdkConfig.global_params,
            tts: { ...sdkConfig.global_params?.tts, speed: providerSpeed },
          })
          platform
            .on(SDKEvents.connected, () => {
              console.info('讯飞数字人SDK已连接')
              emitTelemetry('connection')
              sdkReconnectAttemptsRef.current = 0
              setChannelStatus('acquired')
              setChannelMessage('游客端数字人已保持连接')
              setSdkError(null)
            })
            .on(SDKEvents.frame_start, (payload: unknown) => {
              console.info('讯飞数字人SDK画面开始')
              setSdkVisualReady(true)
              if (!isActiveSdkSpeechEvent(payload)) return
              sdkSpeechActiveRef.current = true
              sdkFrameStartedAtRef.current = Date.now()
              const requestId = getSdkRequestId(payload) || activeSdkSpeechRequestIdRef.current
              emitTelemetry('first_frame', requestId)
              emitTelemetry('speech_start', requestId)
              setSpeaking(true)
              onSpeakStartRef.current?.()
            })
            .on(SDKEvents.tts_duration, (payload: unknown) => {
              if (!isActiveSdkSpeechEvent(payload)) return
              setSdkTtsDuration(extractSdkTtsDuration(payload))
            })
            .on(SDKEvents.subtitle_info, (payload: unknown) => {
              if (!isActiveSdkSpeechEvent(payload)) return
              const subtitle = extractSdkSubtitleText(payload)
              if (!subtitle) {
                setSubtitleLines([])
                return
              }
              emitTelemetry('first_subtitle', getSdkRequestId(payload) || activeSdkSpeechRequestIdRef.current, {
                subtitle: subtitle.slice(0, 80),
              })
              setSubtitleLines((current) => {
                const latest = current[current.length - 1]
                if (latest === subtitle) return current
                if (latest && subtitle.startsWith(latest)) {
                  return [...current.slice(0, -1), subtitle].slice(-2)
                }
                return [...current, subtitle].slice(-2)
              })
              enqueueSubtitleAction(subtitle)
            })
            .on(SDKEvents.frame_stop, (payload: unknown) => {
              console.info('讯飞数字人SDK画面结束')
              if (!isActiveSdkSpeechEvent(payload)) return
              emitTelemetry('complete', getSdkRequestId(payload) || activeSdkSpeechRequestIdRef.current)
              finishSpeaking()
            })
            .on(SDKEvents.disconnected, (error: unknown) => {
              console.warn('讯飞数字人SDK已断开:', error)
              if (sdkPlatformRef.current !== platform) return
              emitTelemetry('disconnected', undefined, error ? { message: describeSdkError(error) } : undefined)
              sdkPlatformRef.current = null
              destroyXfyunPlatform(platform)
              releaseChannelLease()
              if (error) {
                const message = describeSdkError(error)
                sdkAuthenticationFailedRef.current = isAvatarAuthenticationError(message)
                if (sdkAuthenticationFailedRef.current) {
                  emitTelemetry('authentication_failed', undefined, { message })
                }
                setSdkError(message)
              }
              setSdkVisualReady(false)
              finishSpeaking()
              if (!sdkAuthenticationFailedRef.current) scheduleSdkReconnect()
            })
            .on(SDKEvents.error, (error: unknown) => {
              console.error('讯飞数字人SDK事件错误:', error)
              const message = describeSdkError(error)
              sdkAuthenticationFailedRef.current = isAvatarAuthenticationError(message)
              if (sdkAuthenticationFailedRef.current) {
                emitTelemetry('authentication_failed', undefined, { message })
              }
              setSdkError(message)
              setSdkVisualReady(false)
              finishSpeaking()
              if (sdkAuthenticationFailedRef.current) releaseSdkPlatform(false)
            })
          sdkPlatformRef.current = platform
          await platform.start({
            ...(sdkConfig.start_options || {}),
            wrapper: sdkContainerRef.current,
          })
          sdkRetryKeyRef.current = ''
          await restoreXfyunAudio(platform)
        }
        if (cancelled) {
          return
        }
        // 先确保连接存在，再判断这段文本是否已经播过。断线恢复时不重复朗读上一条回复。
        if (lastSdkTextRef.current === textKey) {
          setSpeaking(false)
          return
        }
        // WebSDK 连接与播报分离：角色切换时允许只建连，不发送空文本。
        if (!speechText || !speechRequestId) {
          setSpeaking(false)
          return
        }
        lastSdkTextRef.current = textKey
        const platform = sdkPlatformRef.current
        setSpeaking(false)
        activeSdkSpeechRequestIdRef.current = 'pending'
        const sdkRequestId = await platform.writeText(speechText, {
          ...sdkConfig.text_driver,
          tts: {
            ...sdkConfig.text_driver?.tts,
            speed: Math.round(Math.min(100, Math.max(0, 50 * speechRate))),
          },
          nlp: false,
        })
        if (typeof sdkRequestId === 'string' && activeSdkSpeechRequestIdRef.current === 'pending') {
          activeSdkSpeechRequestIdRef.current = sdkRequestId
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error || '')
        const authenticationFailed = isAvatarAuthenticationError(message)
        if (authenticationFailed) {
          emitTelemetry('authentication_failed', undefined, { message })
        }
        const shouldRetry = (
          !authenticationFailed
          &&
          /code\s*=\s*105|invalid param value/i.test(message)
          && sdkRetryKeyRef.current !== configKey
        )
        console.error('讯飞数字人SDK调用失败:', error)
        releaseSdkPlatform(false)
        if (shouldRetry && !cancelled) {
          sdkRetryKeyRef.current = configKey
          setSdkError('数字人通道刚完成释放，系统将按统一租约状态自动重连一次。')
          scheduleSdkReconnect(900)
          return
        }
        setSdkError(message || '讯飞数字人 SDK 调用失败')
        finishSpeaking()
        if (!cancelled && !authenticationFailed) scheduleSdkReconnect(900)
      }
    }

    runXfyunSdk()
    return () => {
      cancelled = true
    }
  }, [acquireChannelLease, connectionResetId, emitTelemetry, enqueueSubtitleAction, finishSpeaking, isActiveSdkSpeechEvent, releaseChannelLease, releaseSdkPlatform, scheduleSdkReconnect, sdkConfig, sdkReconnectRevision, speechRate, speechRequestId, speechText])

  const enableSdkAudio = useCallback(async () => {
    const platform = sdkPlatformRef.current
    if (!platform || !sdkConfig || !speechText) return
    try {
      await restoreXfyunAudio(platform)
      setAudioUnlockNeeded(false)
      clearSdkSpeechPresentation()
      activeSdkSpeechRequestIdRef.current = 'pending'
      const sdkRequestId = await platform.writeText(speechText, {
        ...sdkConfig.text_driver,
        tts: {
          ...sdkConfig.text_driver?.tts,
          speed: Math.round(Math.min(100, Math.max(0, 50 * speechRate))),
        },
        nlp: false,
      })
      if (typeof sdkRequestId === 'string' && activeSdkSpeechRequestIdRef.current === 'pending') {
        activeSdkSpeechRequestIdRef.current = sdkRequestId
      }
    } catch (error) {
      setSdkError(describeSdkError(error))
    }
  }, [clearSdkSpeechPresentation, sdkConfig, speechRate, speechText])

  useEffect(() => {
    const container = sdkContainerRef.current
    if (!container || !sdkConfig) return
    const detectReadyFrame = () => {
      const video = container.querySelector('video')
      const canvas = container.querySelector('canvas')
      if ((video && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) || (canvas && canvas.width > 0 && canvas.height > 0)) {
        setSdkVisualReady(true)
      }
    }
    const observer = new MutationObserver(detectReadyFrame)
    observer.observe(container, { childList: true, subtree: true })
    container.addEventListener('playing', detectReadyFrame, true)
    container.addEventListener('loadeddata', detectReadyFrame, true)
    detectReadyFrame()
    return () => {
      observer.disconnect()
      container.removeEventListener('playing', detectReadyFrame, true)
      container.removeEventListener('loadeddata', detectReadyFrame, true)
    }
  }, [sdkConfig, sdkReconnectRevision])

  useEffect(() => () => {
    if (sdkReconnectTimerRef.current !== null) {
      window.clearTimeout(sdkReconnectTimerRef.current)
      sdkReconnectTimerRef.current = null
    }
    if (channelRetryTimerRef.current !== null) {
      window.clearTimeout(channelRetryTimerRef.current)
      channelRetryTimerRef.current = null
    }
    releaseSdkPlatform(false)
  }, [releaseSdkPlatform])

  useEffect(() => {
    const disconnectSdk = () => {
      pageIsUnloadingRef.current = true
      releaseSdkPlatform(false, true)
    }
    const recoverSdk = () => {
      pageIsUnloadingRef.current = false
      if (document.visibilityState === 'visible') {
        void restoreXfyunAudio(sdkPlatformRef.current)
        if (!sdkPlatformRef.current) scheduleSdkReconnect(120)
      }
    }
    window.addEventListener('pagehide', disconnectSdk)
    window.addEventListener('beforeunload', disconnectSdk)
    window.addEventListener('pageshow', recoverSdk)
    window.addEventListener('online', recoverSdk)
    document.addEventListener('visibilitychange', recoverSdk)
    return () => {
      window.removeEventListener('pagehide', disconnectSdk)
      window.removeEventListener('beforeunload', disconnectSdk)
      window.removeEventListener('pageshow', recoverSdk)
      window.removeEventListener('online', recoverSdk)
      document.removeEventListener('visibilitychange', recoverSdk)
    }
  }, [releaseSdkPlatform, scheduleSdkReconnect])

  return (
    <div className="avatar-player">
      <div className="avatar-wrapper">
        {sdkConfig ? (
          <div
            className={`avatar-stage-screen ${sdkVisualReady ? 'is-ready' : ''}`}
            data-tts-duration={sdkTtsDuration ?? undefined}
          >
            <div className="avatar-stage-placeholder" role="status" aria-live="polite" aria-atomic="true">
              <span>
                {channelStatus === 'occupied' || channelStatus === 'revoking'
                  ? '正在等待唯一数字人通道'
                  : channelStatus === 'cooldown'
                    ? '数字人通道正在快速切换'
                    : '数字人画面准备中'}
              </span>
              {!sdkVisualReady && channelMessage && <small>{channelMessage}</small>}
            </div>
            <div
              ref={sdkContainerRef}
              className={`avatar-sdk-container ${sdkVisualReady ? 'is-ready' : ''}`}
            />
            {!sdkError && subtitleLines.length > 0 && (
              <div className="avatar-subtitle-overlay" aria-live="polite" aria-atomic="true">
                {subtitleLines.map((line, index) => (
                  <span key={`${line}-${index}`}>{line}</span>
                ))}
              </div>
            )}
            {sdkError && (
              <div className="avatar-error-overlay">
                <strong>讯飞数字人连接失败</strong>
                <span>{sdkError}</span>
              </div>
            )}
            {!sdkError && audioUnlockNeeded && (
              <button type="button" className="avatar-audio-unlock" onClick={enableSdkAudio}>
                <SoundOutlined />
                开启数字人声音
              </button>
            )}
          </div>
        ) : videoUrl ? (
          <video
            ref={videoRef}
            className="avatar-video"
            src={videoUrl}
            playsInline
            controls={false}
          />
        ) : (
          <div className="avatar-missing-state">
            <strong>讯飞数字人未连接</strong>
            <span>{playbackError || errorMessage || '数字人连接配置未完成，请检查管理端设置。'}</span>
          </div>
        )}
      </div>

      {/* 角色信息 */}
      <div className="avatar-meta">
        <div className="avatar-name-line">
          <span className="avatar-name">{avatarName || config.name}</span>
        </div>

        <div
          className={`avatar-emotion-chip ${speaking ? 'is-speaking' : ''}`}
          style={{ '--emotion-color': emotionConfig.color } as React.CSSProperties}
          aria-label={`实时感知到游客情绪为${emotionConfig.label}，数字人表达已自适应调整`}
        >
          <span>{emotionConfig.icon} 情绪感知 · {emotionConfig.label}</span>
        </div>
      </div>

      {/* 音频波形 */}
      <div
        className={`voice-visualizer ${speaking && !videoUrl ? 'is-active' : ''}`}
        aria-hidden={!speaking || Boolean(videoUrl)}
      >
        {waveData.map((h, i) => (
          <motion.div
            key={i}
            className="viz-bar"
            animate={{ height: speaking && !videoUrl ? `${3 + h * 22}px` : '3px' }}
            transition={{ duration: 0.06 }}
            style={{ background: config.accent }}
          />
        ))}
      </div>
    </div>
  )
}
