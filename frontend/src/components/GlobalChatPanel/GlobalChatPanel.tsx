import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { SpinLoading, Toast } from 'antd-mobile'
import { PictureOutline } from 'antd-mobile-icons'
import { CommentOutlined, ReloadOutlined, StarOutlined, StopOutlined } from '@ant-design/icons'
import { useChatStore } from '../../stores/chat'
import { useJourneyStore } from '../../stores/journey'
import AvatarPlayer, { preloadAvatarRuntime } from '../AvatarPlayer/AvatarPlayer'
import { useUserStore } from '../../stores/user'
import ChatBubble from '../ChatBubble/ChatBubble'
import FeedbackModal from '../FeedbackModal/FeedbackModal'
import VoiceInput from '../VoiceInput/VoiceInput'
import './GlobalChatPanel.css'

const quickPrompts = ['讲讲当前景点', '推荐下一站', '适合长者路线', '拍照机位']

const interactionLabels = {
  idle: '随时可以开始',
  listening: '正在聆听',
  emotion: '正在感知情绪',
  retrieving: '正在检索景区资料',
  generating: '正在组织回答',
  avatar_preparing: '数字人正在准备',
  speaking: '正在为你讲解',
} as const

const prepareVisionImage = async (file: File) => {
  if (!file.type.startsWith('image/')) throw new Error('请选择图片文件')
  if (file.size > 12 * 1024 * 1024) throw new Error('图片不能超过 12MB')
  const sourceUrl = URL.createObjectURL(file)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new Error('无法读取这张图片'))
      element.src = sourceUrl
    })
    const maxDimension = 1600
    const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight))
    if (scale === 1 && file.size <= 3 * 1024 * 1024 && ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      return file
    }
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('当前浏览器无法处理图片')
    context.fillStyle = '#fff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((value) => value ? resolve(value) : reject(new Error('图片压缩失败')), 'image/jpeg', 0.86)
    })
    return new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' })
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

interface Props {
  visible?: boolean
}

export default function GlobalChatPanel({ visible = true }: Props) {
  const speechRate = useUserStore((state) => state.speechRate)
  const location = useLocation()
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const mobileDrawerRef = useRef<HTMLDivElement>(null)
  const mobileFabRef = useRef<HTMLButtonElement>(null)
  const mobileCloseRef = useRef<HTMLButtonElement>(null)
  const mobileWasOpenRef = useRef(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [feedbackVisible, setFeedbackVisible] = useState(false)
  const [isImageSending, setIsImageSending] = useState(false)
  const [avatarRefreshId, setAvatarRefreshId] = useState(0)
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia('(min-width: 1280px)').matches)

  const {
    messages,
    inputText,
    isSending,
    avatarState,
    isRecording,
    interactionState,
    suggestedQuestions,
    sessionId,
    selectedAvatar,
    activeAvatar,
    muteCurrentTurn,
    avatarTelemetryContext,
    setInputText,
    setIsRecording,
    setAvatarPlaybackState,
    initializeSession,
    refreshAvatarConnection,
    sendMessage,
    sendVoiceMessage,
    sendImageMessage,
    playMessageTTS,
    stopTTS,
  } = useChatStore()

  const activeJourney = useJourneyStore((state) => state.activeJourney)
  const isStoryDetail = /^\/story\/[^/]+/.test(location.pathname)
  const routeId = isStoryDetail
    ? undefined
    : activeJourney?.routeId || new URLSearchParams(location.search).get('routeId') || undefined
  const spotId = isStoryDetail ? undefined : activeJourney?.currentSpot?.id
  const requestAvatar = isStoryDetail ? activeAvatar : selectedAvatar
  const displayedPrompts = suggestedQuestions.length > 0 ? suggestedQuestions.slice(0, 4) : quickPrompts

  useEffect(() => {
    preloadAvatarRuntime(avatarState.avatarCode)
  }, [avatarState.avatarCode])

  useEffect(() => {
    if (isStoryDetail) return
    initializeSession(selectedAvatar)
  }, [initializeSession, isStoryDetail, location.pathname, selectedAvatar])

  useEffect(() => {
    if (!visible) setMobileOpen(false)
  }, [visible])

  useEffect(() => {
    const drawer = mobileDrawerRef.current
    if (!drawer) return
    if ((isDesktop || mobileOpen) && visible) drawer.removeAttribute('inert')
    else drawer.setAttribute('inert', '')
  }, [isDesktop, mobileOpen, visible])

  useEffect(() => {
    const wasOpen = mobileWasOpenRef.current
    mobileWasOpenRef.current = mobileOpen
    if (isDesktop) return
    if (mobileOpen) {
      window.requestAnimationFrame(() => mobileCloseRef.current?.focus())
    } else if (wasOpen) {
      window.requestAnimationFrame(() => mobileFabRef.current?.focus())
    }
  }, [isDesktop, mobileOpen])

  useEffect(() => {
    if (isDesktop || !mobileOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [isDesktop, mobileOpen])

  useEffect(() => {
    const container = messagesContainerRef.current
    if (!container) return
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }, [messages, mobileOpen])

  useEffect(() => {
    const query = window.matchMedia('(min-width: 1280px)')
    const handleChange = (event: MediaQueryListEvent) => {
      setIsDesktop(event.matches)
      if (event.matches) setMobileOpen(false)
    }
    query.addEventListener('change', handleChange)
    return () => query.removeEventListener('change', handleChange)
  }, [])

  useEffect(() => {
    if (!isDesktop && /^\/story\/[^/]+/.test(location.pathname) && avatarState.speechRequestId > 0) {
      setMobileOpen(true)
    }
  }, [avatarState.speechRequestId, isDesktop, location.pathname])

  const handleSend = async () => {
    if (!inputText.trim() || isSending) return
    await sendMessage(inputText.trim(), spotId, requestAvatar, routeId)
  }

  const handleVoiceAudio = async (audioBlob: Blob, transcriptHint?: string) => {
    if (audioBlob.size === 0) return
    await sendVoiceMessage(audioBlob, transcriptHint, spotId, requestAvatar, routeId)
  }

  const handleImageChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file || isSending) return
    stopTTS()
    setIsImageSending(true)
    try {
      const prepared = await prepareVisionImage(file)
      await sendImageMessage(prepared, inputText.trim(), spotId, requestAvatar, routeId)
    } catch (error) {
      Toast.show({ content: error instanceof Error ? error.message : '图片处理失败', icon: 'fail' })
    } finally {
      setIsImageSending(false)
      event.target.value = ''
    }
  }

  const reconnectAvatar = async () => {
    stopTTS()
    try {
      await refreshAvatarConnection(requestAvatar)
      setAvatarRefreshId((value) => value + 1)
      Toast.show({ content: '数字人正在重新连接', position: 'center' })
    } catch (error) {
      Toast.show({
        content: error instanceof Error ? error.message : '重新连接失败',
        icon: 'fail',
      })
    }
  }

  // 点击数字人主动打招呼：播报走真实讯飞 WebSDK 链路，不占用会话消息列表。
  const greetingIndexRef = useRef(0)
  const greetWithAvatar = async () => {
    if (isSending || isRecording || avatarState.isSpeaking) return
    if (!sessionId) {
      await initializeSession(requestAvatar)
      return
    }
    if (!avatarState.sdkConfig) {
      await reconnectAvatar()
      return
    }
    const greetingLines = [
      '我在呢，想先了解哪个景点？',
      '欢迎回来，要我继续讲解，还是推荐下一站？',
      '您好呀，想听景点故事，还是看看游览路线？',
    ]
    const line = greetingLines[greetingIndexRef.current % greetingLines.length]
    greetingIndexRef.current += 1
    playMessageTTS(line, requestAvatar)
  }

  const panel = (
    <aside className="global-chat-panel" aria-label="AI数字人实时对话">
      <div className="global-chat-head">
        <div>
          <strong>{activeAvatar}</strong>
          <span className={`chat-live-status is-${interactionState}`} role="status" aria-live="polite">
            <i aria-hidden="true" />
            {interactionLabels[interactionState]}
          </span>
        </div>
        {!isDesktop && (
          <button ref={mobileCloseRef} className="mobile-chat-close" type="button" onClick={() => setMobileOpen(false)}>收起</button>
        )}
      </div>

      <div
        className="global-avatar-slot"
        title="点我和数字人打招呼"
        onClick={(event) => {
          if ((event.target as HTMLElement).closest('button')) return
          void greetWithAvatar()
        }}
      >
        <AvatarPlayer
          avatarCode={avatarState.avatarCode}
          avatarName={activeAvatar}
          speechRate={speechRate}
          emotion={avatarState.currentEmotion}
          isSpeaking={avatarState.isSpeaking}
          audioUrl={avatarState.audioUrl || undefined}
          videoUrl={avatarState.videoUrl || undefined}
          speechText={avatarState.speechText || undefined}
          speechRequestId={avatarState.speechRequestId}
          speechStopRequestId={avatarState.speechStopRequestId}
          connectionResetId={avatarRefreshId}
          expression={avatarState.expression}
          lipSyncMode={avatarState.lipSyncMode}
          visemeSequence={avatarState.visemeSequence}
          actionSequence={avatarState.actionSequence}
          sdkConfig={avatarState.sdkConfig || undefined}
          telemetryContext={avatarTelemetryContext}
          telemetrySessionId={sessionId}
          errorMessage={avatarState.errorMessage}
          onConnectionRecovery={() => refreshAvatarConnection(requestAvatar)}
          onSpeakStart={() => setAvatarPlaybackState(true)}
          onSpeakEnd={() => setAvatarPlaybackState(false)}
        />
      </div>

      <div className="global-chat-tools">
        <button type="button" onClick={() => setFeedbackVisible(true)} title="评价本次讲解">
          <StarOutlined /> 评价
        </button>
        <button type="button" onClick={reconnectAvatar} disabled={!avatarState.sdkConfig} title="重新连接数字人">
          <ReloadOutlined /> 重连
        </button>
        {(avatarState.isSpeaking || isSending) && (
          <button
            type="button"
            className="stop-speaking-btn"
            onClick={stopTTS}
            disabled={muteCurrentTurn && !avatarState.isSpeaking}
            title="停止本轮播报"
          >
            <StopOutlined /> {avatarState.isSpeaking ? '停止朗读' : muteCurrentTurn ? '本轮已静音' : '本轮静音'}
          </button>
        )}
      </div>

      <div ref={messagesContainerRef} className="global-messages">
        {messages.map((msg) => (
          <ChatBubble key={msg.id} message={msg} />
        ))}
        <AnimatePresence>
          {(isSending || isImageSending) && (
            <motion.div className="global-typing" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <SpinLoading color="#2d5a87" style={{ '--size': '16px' } as React.CSSProperties} />
              <span>{isImageSending ? '正在理解画面并核对景点资料...' : interactionLabels[interactionState]}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="global-input-area">
        <div className="global-quick-tags">
          {displayedPrompts.map((prompt) => (
            <button key={prompt} type="button" onClick={() => sendMessage(prompt, spotId, requestAvatar, routeId, 'brief')} disabled={isSending}>
              {prompt}
            </button>
          ))}
        </div>
        <div className="global-input-row">
          <input ref={imageInputRef} type="file" accept="image/*" className="image-input" onChange={handleImageChange} />
          <button className="global-icon-btn" type="button" onClick={() => imageInputRef.current?.click()} disabled={isSending || isImageSending} title="发送图片" aria-label="选择景区图片提问">
            <PictureOutline />
          </button>
          <VoiceInput
            onResult={(text) => text.trim() && sendMessage(text.trim(), spotId, requestAvatar, routeId)}
            onAudioResult={handleVoiceAudio}
            onRecordingChange={setIsRecording}
            disabled={isSending}
          />
          <input
            className="global-chat-input"
            value={inputText}
            onChange={(event) => setInputText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing) void handleSend()
            }}
            placeholder={isRecording ? '正在录音...' : '问数字人...'}
            disabled={isRecording}
          />
          <button className="global-send-btn" type="button" onClick={handleSend} disabled={!inputText.trim() || isSending}>发送</button>
        </div>
      </div>

      <FeedbackModal visible={feedbackVisible} onClose={() => setFeedbackVisible(false)} sessionId={sessionId} />
    </aside>
  )

  return (
    <>
      {!isDesktop && visible && !mobileOpen && (
        <button ref={mobileFabRef} className="mobile-chat-fab" type="button" onClick={() => setMobileOpen(true)} aria-label="打开数字人对话" aria-expanded={mobileOpen}>
          <CommentOutlined />
        </button>
      )}
      <motion.div
        ref={mobileDrawerRef}
        className={`${isDesktop ? 'desktop-chat-panel' : 'mobile-chat-drawer'} ${!isDesktop && mobileOpen && visible ? 'is-open' : ''} ${visible ? '' : 'chat-panel-hidden'}`}
        initial={false}
        animate={{ y: isDesktop || (mobileOpen && visible) ? 0 : '100%' }}
        transition={{ duration: isDesktop ? 0 : 0.24, ease: 'easeOut' }}
        aria-hidden={!visible || (!isDesktop && !mobileOpen)}
        role={isDesktop ? undefined : 'dialog'}
        aria-modal={isDesktop ? undefined : true}
        aria-label={isDesktop ? undefined : '数字人对话面板'}
      >
        {panel}
      </motion.div>
    </>
  )
}
