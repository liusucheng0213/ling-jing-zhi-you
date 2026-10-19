const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export type AvatarTelemetryInputMode = 'text' | 'voice' | 'image' | 'manual_tts' | 'session'
export type AvatarTelemetryEvent =
  | 'voice_stop'
  | 'connection'
  | 'first_frame'
  | 'first_subtitle'
  | 'speech_start'
  | 'action'
  | 'complete'
  | 'interrupted'
  | 'disconnected'
  | 'authentication_failed'

export interface AvatarTelemetryContext {
  traceId?: string | null
  inputMode: AvatarTelemetryInputMode
  startedAtEpochMs?: number | null
  spotId?: string | null
}

interface TelemetryOptions {
  sessionId?: string | null
  avatarCode?: string
  requestId?: string
  eventData?: Record<string, unknown>
  evidenceKind?: 'human_microphone' | 'browser_sdk' | 'media_playback'
  keepalive?: boolean
  eventEpochMs?: number
  relativeMs?: number
}

/** 非阻塞写入真实浏览器事件；回答正文和数字人播报不等待遥测接口。 */
export const recordAvatarTelemetry = (
  context: AvatarTelemetryContext | null | undefined,
  eventType: AvatarTelemetryEvent,
  options: TelemetryOptions = {},
) => {
  if (!context) return
  const now = options.eventEpochMs ?? Date.now()
  const payload = {
    session_id: options.sessionId || undefined,
    trace_id: context.traceId || undefined,
    event_type: eventType,
    relative_ms: options.relativeMs ?? (
      context.startedAtEpochMs ? Math.max(0, now - context.startedAtEpochMs) : undefined
    ),
    event_epoch_ms: now,
    avatar_code: options.avatarCode,
    request_id: options.requestId,
    input_mode: context.inputMode,
    evidence_kind: options.evidenceKind || (context.inputMode === 'voice' ? 'human_microphone' : 'browser_sdk'),
    event_data: options.eventData || {},
    spot_id: context.spotId || undefined,
  }
  void fetch(`${API_BASE}/api/v1/avatar/telemetry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: options.keepalive,
  }).catch((error) => {
    console.warn('数字人遥测写入失败:', error)
  })
}
