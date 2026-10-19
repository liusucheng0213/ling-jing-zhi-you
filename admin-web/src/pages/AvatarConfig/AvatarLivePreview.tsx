import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Space, Spin, Tag, Typography } from 'antd'
import { CameraOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  acquireAvatarChannel,
  getAdminAvatarOwnerId,
  heartbeatAvatarChannel,
  releaseAvatarChannel,
} from '@/services/avatarChannel'
import { api } from '@/api/client'

const { Text } = Typography

export interface AvatarPreviewPayload {
  avatar_id: string
  avatar_name: string
  image_url?: string | null
  preview_text: string
  sdk_config: Record<string, any>
}

interface Props {
  payload: AvatarPreviewPayload
  saving: boolean
  onCapture: (imageData: string) => void
}

function releasePlatform(platform: any) {
  if (!platform) return
  try {
    platform?.stop?.()
  } catch (reason) {
    console.warn('后台角色预览 stop 失败，继续销毁实例:', reason)
  }
  try {
    platform?.destroy?.()
  } catch (reason) {
    console.warn('后台角色预览 destroy 失败:', reason)
  }
}

function capturePreview(container: HTMLDivElement): string {
  const sourceCanvas = container.querySelector('canvas')
  if (sourceCanvas?.width && sourceCanvas.height) {
    return sourceCanvas.toDataURL('image/jpeg', 0.9)
  }

  const video = container.querySelector('video')
  if (video?.videoWidth && video.videoHeight) {
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器无法创建截图画布')
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.9)
  }

  throw new Error('数字人画面尚未开始，请等待画面出现后再截图')
}

function recordPreviewTelemetry(
  payload: AvatarPreviewPayload,
  eventType: 'connection' | 'first_frame' | 'disconnected' | 'authentication_failed',
  startedAtEpochMs: number,
  eventData: Record<string, unknown> = {},
) {
  void api.post('/avatar/telemetry', {
    event_type: eventType,
    relative_ms: Math.max(0, Date.now() - startedAtEpochMs),
    event_epoch_ms: Date.now(),
    input_mode: 'session',
    evidence_kind: 'browser_sdk',
    event_data: { owner: 'avatar_config_preview', avatar_id: payload.avatar_id, ...eventData },
  }, { skipErrorToast: true }).catch((reason) => console.warn('角色预览遥测写入失败:', reason))
}

export default function AvatarLivePreview({ payload, saving, onCapture }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const platformRef = useRef<any>(null)
  const leaseTokenRef = useRef('')
  const heartbeatTimerRef = useRef<number | null>(null)
  const maxPreviewTimerRef = useRef<number | null>(null)
  const releasePromiseRef = useRef<Promise<void> | null>(null)
  const ownerIdRef = useRef(getAdminAvatarOwnerId('avatar-config'))
  const [loading, setLoading] = useState(true)
  const [frameReady, setFrameReady] = useState(false)
  const [error, setError] = useState('')
  const [channelNotice, setChannelNotice] = useState('正在申请唯一数字人通道')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false

    const clearTimers = () => {
      if (heartbeatTimerRef.current !== null) {
        window.clearInterval(heartbeatTimerRef.current)
        heartbeatTimerRef.current = null
      }
      if (maxPreviewTimerRef.current !== null) {
        window.clearTimeout(maxPreviewTimerRef.current)
        maxPreviewTimerRef.current = null
      }
    }

    const releaseCurrent = () => {
      clearTimers()
      const platform = platformRef.current
      platformRef.current = null
      releasePlatform(platform)
      const token = leaseTokenRef.current
      leaseTokenRef.current = ''
      if (!token) return Promise.resolve()
      const request = releaseAvatarChannel(token)
        .then(() => undefined)
        .catch((reason) => console.warn('后台数字人租约释放失败:', reason))
      releasePromiseRef.current = request
      void request.finally(() => {
        if (releasePromiseRef.current === request) releasePromiseRef.current = null
      })
      return request
    }

    const stopForVisitor = async (message: string) => {
      await releaseCurrent()
      if (cancelled) return
      setLoading(false)
      setFrameReady(false)
      setChannelNotice(message)
    }

    const connect = async () => {
      if (!containerRef.current) return
      if (releasePromiseRef.current) await releasePromiseRef.current
      setLoading(true)
      setFrameReady(false)
      setError('')
      setChannelNotice('正在申请唯一数字人通道')
      try {
        const lease = await acquireAvatarChannel(ownerIdRef.current)
        if (cancelled) {
          if (lease.lease_token) await releaseAvatarChannel(lease.lease_token)
          return
        }
        if (lease.status !== 'acquired' || !lease.lease_token) {
          setLoading(false)
          setChannelNotice(lease.message || '游客端正在使用数字人，实时预览暂不可用')
          return
        }

        leaseTokenRef.current = lease.lease_token
        setChannelNotice('已取得后台预览通道，最长展示 60 秒')
        heartbeatTimerRef.current = window.setInterval(() => {
          const token = leaseTokenRef.current
          if (!token) return
          void heartbeatAvatarChannel(token)
            .then((heartbeat) => {
              if (heartbeat.status === 'acquired') return
              void stopForVisitor(heartbeat.message || '游客端已请求通道，后台预览已自动释放')
            })
            .catch((reason) => console.warn('后台数字人租约心跳失败:', reason))
        }, 3_000)
        maxPreviewTimerRef.current = window.setTimeout(() => {
          void stopForVisitor('后台实时预览已达到 60 秒上限，通道已自动释放')
        }, 60_000)

        const mod = await import('../../vendor/avatar-sdk-web/esm/index.js')
        if (cancelled || !containerRef.current) return
        const AvatarPlatform = mod.default
        const startedAtEpochMs = Date.now()
        const platform = new AvatarPlatform({ useInlinePlayer: true, logLevel: 3 })
        platformRef.current = platform
        platform.setApiInfo(payload.sdk_config.api_info)
        platform.setGlobalParams(payload.sdk_config.global_params)
        platform
          .on(mod.SDKEvents.connected, () => {
            if (!cancelled) {
              setLoading(false)
              recordPreviewTelemetry(payload, 'connection', startedAtEpochMs)
            }
          })
          .on(mod.SDKEvents.frame_start, () => {
            if (!cancelled) {
              setLoading(false)
              setFrameReady(true)
              recordPreviewTelemetry(payload, 'first_frame', startedAtEpochMs)
            }
          })
          .on(mod.SDKEvents.disconnected, (reason: unknown) => {
            if (cancelled || platformRef.current !== platform) return
            recordPreviewTelemetry(payload, 'disconnected', startedAtEpochMs, {
              message: reason instanceof Error ? reason.message : String(reason || ''),
            })
            void releaseCurrent()
            setLoading(false)
            setFrameReady(false)
            if (reason) setError(reason instanceof Error ? reason.message : '讯飞 WebSDK 连接已断开')
          })
          .on(mod.SDKEvents.error, (reason: unknown) => {
            if (cancelled) return
            const message = reason instanceof Error ? reason.message : String(reason || '')
            if (/authentication failed|unauthorized|鉴权失败/i.test(message)) {
              recordPreviewTelemetry(payload, 'authentication_failed', startedAtEpochMs, { message })
            }
            void releaseCurrent()
            setLoading(false)
            setError(reason instanceof Error ? reason.message : '讯飞 WebSDK 返回错误，请核对该形象 ID 的授权')
          })

        await platform.start({
          ...(payload.sdk_config.start_options || {}),
          wrapper: containerRef.current,
        })
        if (cancelled || platformRef.current !== platform) return
        await platform.writeText(payload.preview_text, {
          ...(payload.sdk_config.text_driver || {}),
          nlp: false,
        })
      } catch (reason) {
        await releaseCurrent()
        if (!cancelled) {
          setLoading(false)
          setFrameReady(false)
          setError(reason instanceof Error ? reason.message : String(reason || '实时预览启动失败'))
        }
      }
    }

    void connect()
    return () => {
      cancelled = true
      void releaseCurrent()
    }
  }, [attempt, payload])

  const handleCapture = () => {
    if (!containerRef.current) return
    try {
      onCapture(capturePreview(containerRef.current))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '截图失败')
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <div className="avatar-preview-toolbar">
        <Space wrap>
          <Tag color="blue">Avatar ID {payload.avatar_id}</Tag>
          <Tag color={frameReady ? 'green' : loading ? 'processing' : 'gold'}>
            {frameReady ? '画面已就绪' : loading ? '正在建连' : '通道未取得'}
          </Tag>
        </Space>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={() => setAttempt((value) => value + 1)}>
            重新申请并连接
          </Button>
          <Button
            type="primary"
            icon={<CameraOutlined />}
            disabled={!frameReady}
            loading={saving}
            onClick={handleCapture}
          >
            截图并设为头像
          </Button>
        </Space>
      </div>

      {channelNotice && !error && (
        <Alert type={frameReady ? 'success' : 'info'} showIcon message={channelNotice} />
      )}
      {error && <Alert type="error" showIcon message="实时预览失败" description={error} />}
      <div
        className="avatar-preview-stage"
        style={{
          position: 'relative',
          height: 500,
          overflow: 'hidden',
          border: '1px solid #d0d5dd',
          borderRadius: 8,
          background: '#101828',
        }}
      >
        <div ref={containerRef} className="avatar-preview-player" style={{ width: '100%', height: '100%' }} />
        {loading && (
          <div
            className="avatar-preview-loading"
            style={{
              position: 'absolute',
              inset: 0,
              display: 'grid',
              placeItems: 'center',
              background: 'rgba(16,24,40,0.78)',
            }}
          >
            <Space direction="vertical" align="center">
              <Spin size="large" />
              <Text style={{ color: '#fff' }}>正在连接讯飞数字人服务</Text>
            </Space>
          </div>
        )}
      </div>
    </Space>
  )
}
