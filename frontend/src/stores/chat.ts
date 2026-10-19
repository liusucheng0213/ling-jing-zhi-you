import { create } from 'zustand'
import { useUserStore } from './user'
import type { AvatarTelemetryContext } from '../services/avatarTelemetry'

/**
 * API 基础地址
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
let avatarConnectionRefreshPromise: Promise<void> | null = null

/**
 * 角色名称到编码映射
 */
export const AVATAR_NAME_TO_CODE: Record<string, string> = {
  '舒窈': 'lingxiaochan',
  '明朗': 'wuchanshi',
  '风屿': 'xuanzang',
  '明泽': 'zhaopuchu',
  '雨桐': 'xiaowan',
  '聆小璇': 'lingxiaochan',
  '明哥': 'wuchanshi',
  '聆飞哲': 'xuanzang',
  '聆伯松': 'zhaopuchu',
  '聆小玥': 'xiaowan',
  '灵小禅': 'lingxiaochan',
  '悟禅师': 'wuchanshi',
  '玄奘法师': 'xuanzang',
  '赵朴初先生': 'zhaopuchu',
  '小宛': 'xiaowan',
}

const LEGACY_AVATAR_NAMES: Record<string, string> = {
  '灵小禅': '舒窈',
  '聆小璇': '舒窈',
  '悟禅师': '明朗',
  '明哥': '明朗',
  '玄奘法师': '风屿',
  '聆飞哲': '风屿',
  '林延': '风屿',
  '知夏': '风屿',
  '赵朴初先生': '明泽',
  '聆伯松': '明泽',
  '林靖': '明泽',
  '小宛': '雨桐',
  '聆小玥': '雨桐',
  '舒然': '雨桐',
}

const readInitialAvatar = () => {
  const stored = localStorage.getItem('lingjing_selected_avatar') || '舒窈'
  return LEGACY_AVATAR_NAMES[stored] || stored
}

/**
 * 消息类型定义
 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  emotion?: string // 情感状态：happy, calm, excited, thoughtful 等
  timestamp: number
  isVoice?: boolean // 是否为语音消息
  voiceUrl?: string // 语音URL
  videoUrl?: string // 数字人视频URL
  imageUrl?: string
  retrievedDocs?: Array<Record<string, any>>
  confidence?: number | null
  answerType?: string | null
  traceId?: string | null
  multimodalEvidence?: Record<string, any> | null
}

/**
 * 数字人状态
 */
export interface AvatarState {
  isSpeaking: boolean
  avatarCode: string
  currentEmotion: string
  isVideoMode: boolean
  audioUrl: string | null
  videoUrl: string | null
  speechText: string | null
  speechRequestId: number
  speechStopRequestId: number
  expression: string
  lipSyncMode: string
  visemeSequence: Array<{ t: number; open: number }>
  actionSequence: Array<{ id: string; name?: string; timing?: string; delay_ms?: number }>
  sdkConfig: Record<string, any> | null
  errorMessage: string | null
}

export interface ImageJourneyResult {
  sessionId: string | null
  answer: string
  sceneDescription: string
  visualFacts: string[]
  recognizedSpots: string[]
  spotCandidates: string[]
  compositionSuggestions: string[]
  safetyTips: string[]
  publishTip?: string
  confidence: number | null
  provider?: string
  model?: string
  latencyMs?: number
  knowledgeSourceCount: number
}

export interface ImageMessageOptions {
  creativeMode?: boolean
  narrate?: boolean
}

/**
 * 游客与数字人的实时交互阶段。
 *
 * 文本问答由后端 SSE stage 驱动，播报阶段只由真实播放器事件确认。
 */
export type ChatInteractionState =
  | 'idle'
  | 'listening'
  | 'emotion'
  | 'retrieving'
  | 'generating'
  | 'avatar_preparing'
  | 'speaking'

export type ResponseMode = 'auto' | 'brief' | 'normal' | 'detail'

const SSE_STAGE_TO_INTERACTION: Record<string, ChatInteractionState> = {
  emotion: 'emotion',
  intent: 'emotion',
  rag: 'retrieving',
  llm: 'generating',
  digital_human: 'avatar_preparing',
}

/**
 * 聊天状态接口
 */
interface ChatStore {
  // 消息列表
  messages: ChatMessage[]
  // 输入框内容
  inputText: string
  // 是否正在发送
  isSending: boolean
  // 数字人状态
  avatarState: AvatarState
  // 是否正在录音
  isRecording: boolean
  // 当前交互阶段
  interactionState: ChatInteractionState
  // 是否正在初始化会话和数字人
  isSessionInitializing: boolean
  // 会话ID（用于保持上下文）
  sessionId: string | null
  // 建议问题列表
  suggestedQuestions: string[]
  selectedAvatar: string
  activeAvatar: string
  muteCurrentTurn: boolean
  avatarTelemetryContext: AvatarTelemetryContext

  // 操作方法
  setInputText: (text: string) => void
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void
  clearMessages: () => void
  setIsSending: (sending: boolean) => void
  setAvatarState: (state: Partial<AvatarState>) => void
  setIsRecording: (recording: boolean) => void
  setInteractionState: (state: ChatInteractionState) => void
  setAvatarPlaybackState: (speaking: boolean) => void
  setSessionId: (sessionId: string | null) => void
  setSuggestedQuestions: (questions: string[]) => void
  setSelectedAvatar: (avatar: string) => Promise<void>
  setNarrationAvatar: (avatar: string) => void
  restoreGuideAvatar: () => Promise<void>
  refreshAvatarConnection: (avatar?: string) => Promise<void>
  initializeSession: (avatar?: string) => Promise<void>
  // 发送消息（调用后端API）
  sendMessage: (content: string, spotId?: string, avatar?: string, routeId?: string, responseMode?: ResponseMode) => Promise<ChatMessage | null>
  // 发送真实语音消息（MediaRecorder音频 + 可选浏览器识别文本）
  sendVoiceMessage: (audioBlob: Blob, transcriptHint?: string, spotId?: string, avatar?: string, routeId?: string) => Promise<void>
  sendImageMessage: (
    imageFile: File,
    content?: string,
    spotId?: string,
    avatar?: string,
    routeId?: string,
    options?: ImageMessageOptions,
  ) => Promise<ImageJourneyResult>
  // 播放消息语音（TTS）
  playMessageTTS: (text: string, avatar?: string) => void
  // 停止播放
  stopTTS: () => void
}

/**
 * 生成唯一消息ID
 */
const generateId = () =>
  `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

const resolveMediaUrl = (url?: string | null) => {
  if (!url) return null
  return url.startsWith('http') ? url : `${API_BASE}${url}`
}

const resolveResponseAvatar = (data: any, fallback?: string) => {
  const returned = data?.avatar || data?.digital_human?.avatar_name || fallback || '舒窈'
  return LEGACY_AVATAR_NAMES[returned] || returned
}

const readStringList = (value: unknown): string[] => (
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : []
)

const buildImageJourneyResult = (data: any): ImageJourneyResult => {
  const evidence = data?.multimodal_evidence || {}
  const sourceList = Array.isArray(data?.retrieved_docs)
    ? data.retrieved_docs
    : Array.isArray(data?.message?.retrieved_docs)
      ? data.message.retrieved_docs
      : []
  const confidence = evidence.confidence ?? data?.confidence
  return {
    sessionId: typeof data?.session_id === 'string' ? data.session_id : null,
    answer: String(data?.message?.content || ''),
    sceneDescription: String(evidence.scene_description || ''),
    visualFacts: readStringList(evidence.visual_facts),
    recognizedSpots: readStringList(evidence.recognized_spots),
    spotCandidates: readStringList(evidence.spot_candidates),
    compositionSuggestions: readStringList(evidence.composition_suggestions),
    safetyTips: readStringList(evidence.safety_tips),
    publishTip: typeof evidence.publish_tip === 'string' ? evidence.publish_tip : undefined,
    confidence: typeof confidence === 'number' ? confidence : null,
    provider: typeof evidence.provider === 'string' ? evidence.provider : undefined,
    model: typeof evidence.model === 'string' ? evidence.model : undefined,
    latencyMs: typeof evidence.latency_ms === 'number' ? evidence.latency_ms : undefined,
    knowledgeSourceCount: sourceList.length,
  }
}

export const buildAvatarState = (data: any, avatar?: string): Partial<AvatarState> => {
  const digitalHuman = data.digital_human
  const emotion = data.message?.emotion || digitalHuman?.emotion || 'calm'
  const hasSdk = Boolean(digitalHuman?.sdk_config)
  const audioUrl = hasSdk
    ? null
    : resolveMediaUrl(digitalHuman?.audio_url || data.message?.audio_url)
  const videoUrl = resolveMediaUrl(digitalHuman?.video_url || data.message?.video_url)

  return {
    isSpeaking: true,
    avatarCode: digitalHuman?.avatar_code || AVATAR_NAME_TO_CODE[avatar || '舒窈'] || 'lingxiaochan',
    currentEmotion: emotion,
    audioUrl,
    videoUrl,
    speechText: data.message?.content || digitalHuman?.speech_text || null,
    speechRequestId: Date.now(),
    isVideoMode: Boolean(videoUrl || hasSdk),
    expression: digitalHuman?.expression || emotion,
    lipSyncMode: digitalHuman?.lip_sync_mode || 'web_audio_energy',
    visemeSequence: digitalHuman?.viseme_sequence || [],
    actionSequence: digitalHuman?.action_sequence || digitalHuman?.sdk_config?.action_sequence || [],
    sdkConfig: digitalHuman?.sdk_config || null,
    errorMessage: hasSdk || videoUrl ? null : '讯飞数字人未连接，请检查讯飞星火数字人配置。',
  }
}

const extractMessageMedia = (data: any) => {
  const digitalHuman = data.digital_human
  const hasSdk = Boolean(digitalHuman?.sdk_config)
  const audioUrl = hasSdk
    ? null
    : resolveMediaUrl(digitalHuman?.audio_url || data.message?.audio_url)
  const videoUrl = resolveMediaUrl(digitalHuman?.video_url || data.message?.video_url)

  return { audioUrl, videoUrl }
}

const buildAssistantMessage = (data: any, defaultContent = '抱歉，我没有理解您的问题。') => {
  const emotion = data.message?.emotion || 'calm'
  const { audioUrl, videoUrl } = extractMessageMedia(data)
  return {
    role: 'assistant' as const,
    content: data.message?.content || defaultContent,
    emotion,
    voiceUrl: audioUrl || undefined,
    videoUrl: videoUrl || undefined,
    retrievedDocs: data.retrieved_docs || data.message?.retrieved_docs || [],
    confidence: data.confidence ?? null,
    answerType: data.answer_type || null,
    traceId: data.trace_id || null,
    multimodalEvidence: data.multimodal_evidence || null,
  }
}

/**
 * 欢迎消息
 */
const welcomeMessage: ChatMessage = {
  id: generateId(),
  role: 'assistant',
  content:
    '欢迎来到灵境智游！我是您的AI导览助手，可以问我景点介绍、路线推荐、历史故事等问题。',
  emotion: 'happy',
  timestamp: Date.now(),
}

/**
 * Zustand 聊天状态管理
 */
export const useChatStore = create<ChatStore>((set, get) => ({
  // 初始状态
  messages: [welcomeMessage],
  inputText: '',
  isSending: false,
  avatarState: {
    isSpeaking: false,
    avatarCode: 'lingxiaochan',
    currentEmotion: 'happy',
    isVideoMode: false,
    audioUrl: null,
    videoUrl: null,
    speechText: null,
    speechRequestId: 0,
    speechStopRequestId: 0,
    expression: 'smile',
    lipSyncMode: 'web_audio_energy',
    visemeSequence: [],
    actionSequence: [],
    sdkConfig: null,
    errorMessage: null,
  },
  isRecording: false,
  interactionState: 'idle',
  isSessionInitializing: false,
  sessionId: null,
  suggestedQuestions: [],
  selectedAvatar: readInitialAvatar(),
  activeAvatar: readInitialAvatar(),
  muteCurrentTurn: false,
  avatarTelemetryContext: { inputMode: 'session', startedAtEpochMs: null },

  // 设置输入文本
  setInputText: (text) => set({ inputText: text }),

  // 添加消息
  addMessage: (message) => {
    const newMessage: ChatMessage = {
      ...message,
      id: generateId(),
      timestamp: Date.now(),
    }
    set((state) => ({
      messages: [...state.messages, newMessage],
    }))
  },

  // 清空消息
  clearMessages: () => set({
    messages: [welcomeMessage],
    sessionId: null,
    suggestedQuestions: [],
    interactionState: 'idle',
    avatarTelemetryContext: { inputMode: 'session', startedAtEpochMs: null },
    avatarState: {
      isSpeaking: false,
      avatarCode: 'lingxiaochan',
      currentEmotion: 'happy',
      isVideoMode: false,
      audioUrl: null,
      videoUrl: null,
      speechText: null,
      speechRequestId: 0,
      speechStopRequestId: 0,
      expression: 'smile',
      lipSyncMode: 'web_audio_energy',
      visemeSequence: [],
      actionSequence: [],
      sdkConfig: null,
      errorMessage: null,
    },
  }),

  // 设置发送状态
  setIsSending: (sending) => set({ isSending: sending }),

  // 设置数字人状态
  setAvatarState: (state) =>
    set((prev) => ({
      avatarState: { ...prev.avatarState, ...state },
    })),

  // 开始录音前先打断上一段播报；interrupt 不销毁 WebSDK 长连接。
  setIsRecording: (recording) => {
    if (recording) get().stopTTS()
    set((state) => ({
      isRecording: recording,
      ...(state.isRecording && !recording ? {
        avatarTelemetryContext: {
          inputMode: 'voice' as const,
          startedAtEpochMs: Date.now(),
        },
      } : {}),
      interactionState: recording
        ? 'listening'
        : state.isSending
          ? state.interactionState
          : 'idle',
    }))
  },

  setInteractionState: (interactionState) => set({ interactionState }),

  // speaking 只由播放器的真实开始/结束事件更新，不依据回答字数估算。
  setAvatarPlaybackState: (speaking) => set((state) => ({
    interactionState: speaking
      ? 'speaking'
      : state.isRecording
        ? 'listening'
        : state.isSending && ['emotion', 'retrieving', 'generating', 'avatar_preparing'].includes(state.interactionState)
          ? state.interactionState
          : 'idle',
    avatarState: {
      ...state.avatarState,
      isSpeaking: speaking,
      ...(speaking ? {} : {
        audioUrl: null,
        videoUrl: null,
        speechText: null,
        actionSequence: [],
      }),
    },
  })),

  // 设置会话ID
  setSessionId: (sessionId) => set({ sessionId }),

  // 设置建议问题
  setSuggestedQuestions: (questions) => set({ suggestedQuestions: questions }),

  setSelectedAvatar: async (avatar) => {
    const canonicalAvatar = LEGACY_AVATAR_NAMES[avatar] || avatar
    localStorage.setItem('lingjing_selected_avatar', canonicalAvatar)
    const current = get()
    if (current.selectedAvatar === canonicalAvatar && current.activeAvatar === canonicalAvatar) return
    current.stopTTS()
    set((state) => ({
      selectedAvatar: canonicalAvatar,
      activeAvatar: canonicalAvatar,
      muteCurrentTurn: false,
      messages: state.messages.some((message) => message.role === 'user')
        ? state.messages
        : [{
            id: generateId(),
            role: 'assistant',
            content: `您好，我是${canonicalAvatar}。接下来我会作为您的常驻数字人导游，陪您规划路线并解答景区问题。`,
            emotion: 'happy',
            timestamp: Date.now(),
          }],
      avatarState: {
        ...state.avatarState,
        isSpeaking: false,
        audioUrl: null,
        videoUrl: null,
        speechText: null,
        sdkConfig: null,
        actionSequence: [],
        avatarCode: AVATAR_NAME_TO_CODE[canonicalAvatar] || 'lingxiaochan',
        errorMessage: null,
      },
    }))
    if (!current.sessionId) return
    try {
      const response = await fetch(`${API_BASE}/api/v1/session/${current.sessionId}/avatar`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ avatar: canonicalAvatar }),
      })
      if (!response.ok) throw new Error(`数字人切换失败: ${response.status}`)
      const data = await response.json()
      const silentState = buildAvatarState(data, canonicalAvatar)
      set((state) => ({
        activeAvatar: canonicalAvatar,
        avatarState: {
          ...state.avatarState,
          ...silentState,
          isSpeaking: false,
          speechText: null,
          speechRequestId: state.avatarState.speechRequestId,
        },
      }))
    } catch (error) {
      console.error('数字人切换失败:', error)
      set((state) => ({
        avatarState: {
          ...state.avatarState,
          errorMessage: error instanceof Error ? error.message : '数字人切换失败',
        },
      }))
    }
  },

  // 故事讲述人仅影响当前播放器，不覆盖游客在首页选择的常驻导游。
  setNarrationAvatar: (avatar) => {
    const canonicalAvatar = LEGACY_AVATAR_NAMES[avatar] || avatar
    get().stopTTS()
    set((state) => ({
      activeAvatar: canonicalAvatar,
      muteCurrentTurn: false,
      avatarState: {
        ...state.avatarState,
        isSpeaking: false,
        avatarCode: AVATAR_NAME_TO_CODE[canonicalAvatar] || 'lingxiaochan',
        audioUrl: null,
        videoUrl: null,
        speechText: null,
        sdkConfig: null,
        actionSequence: [],
        errorMessage: null,
      },
    }))
  },

  restoreGuideAvatar: async () => {
    const { selectedAvatar, activeAvatar, sessionId } = get()
    if (selectedAvatar === activeAvatar) return
    get().stopTTS()
    set({ activeAvatar: selectedAvatar, muteCurrentTurn: false })
    if (!sessionId) return
    try {
      const response = await fetch(`${API_BASE}/api/v1/session/${sessionId}/avatar`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ avatar: selectedAvatar }),
      })
      if (!response.ok) throw new Error(`常驻导游恢复失败: ${response.status}`)
      const data = await response.json()
      const silentState = buildAvatarState(data, selectedAvatar)
      set((state) => ({
        activeAvatar: selectedAvatar,
        avatarState: {
          ...state.avatarState,
          ...silentState,
          isSpeaking: false,
          speechText: null,
          speechRequestId: state.avatarState.speechRequestId,
        },
      }))
    } catch (error) {
      console.error('恢复常驻导游失败:', error)
      set((state) => ({
        avatarState: {
          ...state.avatarState,
          errorMessage: error instanceof Error ? error.message : '常驻导游恢复失败',
        },
      }))
    }
  },

  refreshAvatarConnection: async (avatar?: string) => {
    if (avatarConnectionRefreshPromise) return avatarConnectionRefreshPromise
    const run = async () => {
      const { sessionId, activeAvatar, selectedAvatar } = get()
      const avatarName = avatar || activeAvatar || selectedAvatar || '舒窈'
      if (!sessionId) {
        await get().initializeSession(avatarName)
        return
      }
      const response = await fetch(`${API_BASE}/api/v1/session/${sessionId}/avatar`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ avatar: avatarName }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || `数字人连接凭证刷新失败: ${response.status}`)
      }
      const data = await response.json()
      const responseAvatar = resolveResponseAvatar(data, avatarName)
      const silentState = buildAvatarState(data, responseAvatar)
      set((state) => ({
        activeAvatar: responseAvatar,
        avatarState: {
          ...state.avatarState,
          ...silentState,
          isSpeaking: false,
          speechText: state.avatarState.speechText,
          speechRequestId: state.avatarState.speechRequestId,
          errorMessage: null,
        },
      }))
    }
    avatarConnectionRefreshPromise = run().finally(() => {
      avatarConnectionRefreshPromise = null
    })
    return avatarConnectionRefreshPromise
  },

  initializeSession: async (avatar?: string) => {
    const { sessionId, isSessionInitializing, setSessionId, setAvatarState, selectedAvatar } = get()
    if (sessionId || isSessionInitializing) return

    const avatarName = avatar || selectedAvatar || '舒窈'
    set({ isSessionInitializing: true, interactionState: 'avatar_preparing' })
    try {
      const response = await fetch(`${API_BASE}/api/v1/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          avatar: avatarName,
          user_agent: navigator.userAgent,
        }),
      })

      if (!response.ok) {
        throw new Error(`数字人会话创建失败: ${response.status}`)
      }

      const data = await response.json()
      if (data.session_id) {
        setSessionId(data.session_id)
      }
      set({ activeAvatar: resolveResponseAvatar(data, avatarName) })

      const welcome: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content: data.welcome_message || welcomeMessage.content,
        emotion: data.digital_human?.emotion || 'happy',
        timestamp: Date.now(),
      }
      set({ messages: [welcome] })
      setAvatarState(buildAvatarState({
        digital_human: data.digital_human,
        message: {
          content: welcome.content,
          emotion: data.digital_human?.emotion || 'happy',
        },
      }, data.avatar || avatarName))
    } catch (error) {
      console.error('初始化数字人会话失败:', error)
      setAvatarState({
        isSpeaking: false,
        isVideoMode: false,
        sdkConfig: null,
        audioUrl: null,
        videoUrl: null,
        speechText: null,
        errorMessage: error instanceof Error ? error.message : '讯飞数字人连接失败',
      })
      set({ interactionState: 'idle' })
    } finally {
      set({ isSessionInitializing: false })
    }
  },

  // 发送消息（调用后端API）
  sendMessage: async (content: string, spotId?: string, avatar?: string, routeId?: string, responseMode: ResponseMode = 'auto') => {
    get().stopTTS()
    const { addMessage, setIsSending, setAvatarState, setSessionId, setSuggestedQuestions, sessionId, selectedAvatar } = get()

    // 添加用户消息
    addMessage({
      role: 'user',
      content,
    })

    set({ inputText: '' })
    const requestStartedAt = Date.now()
    set({
      muteCurrentTurn: false,
      interactionState: 'emotion',
      avatarTelemetryContext: { inputMode: 'text', startedAtEpochMs: requestStartedAt, spotId },
    })
    setIsSending(true)

    const payload = {
      message: content,
      spot_id: spotId,
      avatar: avatar || selectedAvatar || '舒窈',
      session_id: sessionId,
      route_id: routeId,
      response_mode: responseMode,
    }

    const sendByJson = async (): Promise<ChatMessage> => {
      const response = await fetch(`${API_BASE}/api/v1/text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        throw new Error(`请求失败: ${response.status}`)
      }

      const data = await response.json()
      set({
        avatarTelemetryContext: {
          inputMode: 'text',
          startedAtEpochMs: requestStartedAt,
          traceId: data.trace_id || null,
          spotId,
        },
      })
      if (data.session_id) {
        setSessionId(data.session_id)
      }
      const responseAvatar = resolveResponseAvatar(data, avatar || selectedAvatar)
      set({ activeAvatar: responseAvatar })
      const nextAvatarState = buildAvatarState(data, responseAvatar)
      const muted = get().muteCurrentTurn
      if (muted) {
        setAvatarState({
          ...nextAvatarState,
          isSpeaking: false,
          speechText: null,
          speechRequestId: get().avatarState.speechRequestId,
        })
      } else {
        setAvatarState(nextAvatarState)
      }
      set({ interactionState: muted ? 'idle' : 'avatar_preparing' })

      const assistantMessage: ChatMessage = {
        ...buildAssistantMessage(data),
        id: generateId(),
        timestamp: Date.now(),
      }
      set((state) => ({ messages: [...state.messages, assistantMessage] }))

      if (data.suggested_questions && Array.isArray(data.suggested_questions)) {
        setSuggestedQuestions(data.suggested_questions)
      }
      return assistantMessage
    }

    let assistantMessageId: string | null = null
    let finalMessage: ChatMessage | null = null
    let finalReceived = false
    let usedJsonDirectly = false

    try {
      const response = await fetch(`${API_BASE}/api/v1/text/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!response.ok || !response.body) {
        usedJsonDirectly = true
        return await sendByJson()
      }

      const streamingMessageId = generateId()
      assistantMessageId = streamingMessageId
      set((state) => ({
        messages: [...state.messages, {
          id: streamingMessageId,
          role: 'assistant',
          content: '',
          emotion: 'calm',
          timestamp: Date.now(),
        }],
      }))

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const handleEvent = (eventData: any) => {
        const eventType = eventData.type
        if (eventType === 'stage') {
          const nextStage = SSE_STAGE_TO_INTERACTION[String(eventData.stage || '')]
          if (nextStage) set({ interactionState: nextStage })
          return
        }
        if (eventType === 'session' && eventData.session_id) {
          setSessionId(eventData.session_id)
          if (eventData.avatar) {
            set({ activeAvatar: resolveResponseAvatar(eventData, avatar || selectedAvatar) })
          }
          return
        }
        const delta = typeof eventData.delta === 'string'
          ? eventData.delta
          : typeof eventData.content === 'string'
            ? eventData.content
            : ''
        if (eventType === 'delta' && delta) {
          set({ interactionState: 'generating' })
          set((state) => ({
            messages: state.messages.map((message) =>
              message.id === assistantMessageId
                ? { ...message, content: `${message.content}${delta}` }
                : message
            ),
          }))
          return
        }
        if (eventType === 'final' && eventData.data) {
          finalReceived = true
          const data = eventData.data
          set({
            avatarTelemetryContext: {
              inputMode: 'text',
              startedAtEpochMs: requestStartedAt,
              traceId: data.trace_id || null,
              spotId,
            },
          })
          if (data.session_id) {
            setSessionId(data.session_id)
          }
          const responseAvatar = resolveResponseAvatar(data, avatar || selectedAvatar)
          set({ activeAvatar: responseAvatar })
          const nextAvatarState = buildAvatarState(data, responseAvatar)
          const muted = get().muteCurrentTurn
          if (muted) {
            setAvatarState({
              ...nextAvatarState,
              isSpeaking: false,
              speechText: null,
              speechRequestId: get().avatarState.speechRequestId,
            })
          } else {
            setAvatarState(nextAvatarState)
          }
          set({ interactionState: muted ? 'idle' : 'avatar_preparing' })

          const completedMessage: ChatMessage = {
            ...buildAssistantMessage(data),
            id: assistantMessageId || generateId(),
            timestamp: Date.now(),
          }
          finalMessage = completedMessage
          set((state) => ({
            messages: state.messages.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...completedMessage,
                    timestamp: message.timestamp,
                  }
                : message
            ),
          }))

          if (data.suggested_questions && Array.isArray(data.suggested_questions)) {
            setSuggestedQuestions(data.suggested_questions)
          }
          return
        }
        if (eventType === 'error') {
          throw new Error(eventData.message || '流式响应失败')
        }
      }

      const processBuffer = (flush = false) => {
        const events = flush ? [buffer] : buffer.split('\n\n')
        buffer = flush ? '' : events.pop() || ''
        events.forEach((eventText) => {
          const dataLine = eventText
            .split('\n')
            .find((line) => line.startsWith('data: '))
          if (!dataLine) return
          handleEvent(JSON.parse(dataLine.slice(6)))
        })
      }

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        processBuffer()
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        processBuffer(true)
      }

      if (!finalReceived) {
        throw new Error('流式响应未返回最终结果')
      }
      return finalMessage
    } catch (error) {
      console.error('发送消息失败:', error)

      if (!usedJsonDirectly && !finalReceived) {
        if (assistantMessageId) {
          set((state) => ({
            messages: state.messages.filter((message) => message.id !== assistantMessageId),
          }))
        }
        try {
          usedJsonDirectly = true
          return await sendByJson()
        } catch (jsonError) {
          console.error('非流式消息重试失败:', jsonError)
        }
      }

      if (assistantMessageId) {
        set((state) => ({
          messages: state.messages.map((message) =>
            message.id === assistantMessageId
              ? { ...message, content: '抱歉，网络出了点问题，请稍后再试。', emotion: 'calm' }
              : message
          ),
        }))
      } else {
        // 添加错误提示消息
        addMessage({
          role: 'assistant',
          content: '抱歉，网络出了点问题，请稍后再试。',
          emotion: 'calm',
        })
      }
      set({ interactionState: 'idle' })
      return null
    } finally {
      setIsSending(false)
    }
  },

  sendVoiceMessage: async (audioBlob: Blob, transcriptHint?: string, spotId?: string, avatar?: string, routeId?: string) => {
    const { addMessage, setIsSending, setAvatarState, setSessionId, setSuggestedQuestions, sessionId, selectedAvatar } = get()
    const recordedStopAt = get().avatarTelemetryContext.inputMode === 'voice'
      ? get().avatarTelemetryContext.startedAtEpochMs || Date.now()
      : Date.now()
    set({
      muteCurrentTurn: false,
      interactionState: 'emotion',
      avatarTelemetryContext: { inputMode: 'voice', startedAtEpochMs: recordedStopAt, spotId },
    })
    setIsSending(true)

    try {
      const formData = new FormData()
      formData.append('audio', audioBlob, 'voice.webm')
      if (sessionId) formData.append('session_id', sessionId)
      if (spotId) formData.append('spot_id', spotId)
      if (routeId) formData.append('route_id', routeId)
      formData.append('avatar', avatar || selectedAvatar || '舒窈')
      formData.append('response_mode', 'brief')
      if (transcriptHint?.trim()) formData.append('transcript_hint', transcriptHint.trim())

      const response = await fetch(`${API_BASE}/api/v1/voice`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        throw new Error(`语音请求失败: ${response.status}`)
      }

      const data = await response.json()
      set({
        avatarTelemetryContext: {
          inputMode: 'voice',
          startedAtEpochMs: recordedStopAt,
          traceId: data.trace_id || null,
          spotId,
        },
      })
      if (data.session_id) setSessionId(data.session_id)
      const responseAvatar = resolveResponseAvatar(data, avatar || selectedAvatar)
      set({ activeAvatar: responseAvatar })

      const recognizedText = data.recognized_text || transcriptHint || '语音消息'
      addMessage({
        role: 'user',
        content: recognizedText,
        isVoice: true,
      })

      const nextAvatarState = buildAvatarState(data, responseAvatar)
      const muted = get().muteCurrentTurn
      setAvatarState(muted ? {
        ...nextAvatarState,
        isSpeaking: false,
        speechText: null,
        speechRequestId: get().avatarState.speechRequestId,
      } : nextAvatarState)
      set({ interactionState: muted ? 'idle' : 'avatar_preparing' })

      addMessage(buildAssistantMessage(data, '抱歉，我没有理解您的语音。'))

      if (data.suggested_questions && Array.isArray(data.suggested_questions)) {
        setSuggestedQuestions(data.suggested_questions)
      }
    } catch (error) {
      console.error('发送语音失败:', error)
      addMessage({
        role: 'assistant',
        content: '抱歉，语音识别暂时不可用，请检查麦克风权限或稍后再试。',
        emotion: 'calm',
      })
      set({ interactionState: 'idle' })
    } finally {
      setIsSending(false)
    }
  },

  sendImageMessage: async (
    imageFile: File,
    content?: string,
    spotId?: string,
    avatar?: string,
    routeId?: string,
    options?: ImageMessageOptions,
  ) => {
    get().stopTTS()
    const { addMessage, setIsSending, setAvatarState, setSessionId, setSuggestedQuestions, sessionId, selectedAvatar } = get()
    const text = content?.trim() || '请识别这张景区图片并介绍相关景点'
    const imageUrl = URL.createObjectURL(imageFile)
    const requestStartedAt = Date.now()

    addMessage({
      role: 'user',
      content: text,
      imageUrl,
    })
    set({ inputText: '' })
    set({
      muteCurrentTurn: false,
      interactionState: 'retrieving',
      avatarTelemetryContext: { inputMode: 'image', startedAtEpochMs: requestStartedAt, spotId },
    })
    setIsSending(true)

    try {
      const formData = new FormData()
      formData.append('image', imageFile)
      formData.append('message', text)
      if (sessionId) formData.append('session_id', sessionId)
      if (spotId) formData.append('spot_id', spotId)
      if (routeId) formData.append('route_id', routeId)
      formData.append('avatar', avatar || selectedAvatar || '舒窈')
      if (options?.creativeMode) formData.append('creative_mode', 'true')

      const response = await fetch(`${API_BASE}/api/v1/image`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || `图片请求失败: ${response.status}`)
      }

      const data = await response.json()
      set({
        avatarTelemetryContext: {
          inputMode: 'image',
          startedAtEpochMs: requestStartedAt,
          traceId: data.trace_id || null,
          spotId,
        },
      })
      if (data.session_id) setSessionId(data.session_id)
      const responseAvatar = resolveResponseAvatar(data, avatar || selectedAvatar)
      set({ activeAvatar: responseAvatar })

      const nextAvatarState = buildAvatarState(data, responseAvatar)
      const muted = get().muteCurrentTurn || options?.narrate === false
      setAvatarState(muted ? {
        ...nextAvatarState,
        isSpeaking: false,
        speechText: null,
        speechRequestId: get().avatarState.speechRequestId,
      } : nextAvatarState)
      set({ interactionState: muted ? 'idle' : 'avatar_preparing' })

      addMessage(buildAssistantMessage(data, '未能识别图片对应的景点。'))

      if (data.suggested_questions && Array.isArray(data.suggested_questions)) {
        setSuggestedQuestions(data.suggested_questions)
      }
      return buildImageJourneyResult(data)
    } catch (error) {
      console.error('发送图片失败:', error)
      addMessage({
        role: 'assistant',
        content: error instanceof Error
          ? `这张图片暂时没有识别成功：${error.message}`
          : '图片识别请求失败，请确认图片格式或稍后再试。',
        emotion: 'calm',
      })
      set({ interactionState: 'idle' })
      throw error
    } finally {
      setIsSending(false)
    }
  },

  // 播放消息TTS
  playMessageTTS: (text: string, avatar?: string) => {
    get().stopTTS()
    const { setAvatarState, avatarState, selectedAvatar } = get()
    const avatarName = avatar || selectedAvatar || '舒窈'
    set({
      muteCurrentTurn: false,
      avatarTelemetryContext: { inputMode: 'manual_tts', startedAtEpochMs: Date.now() },
    })
    if (avatarState.sdkConfig) {
      setAvatarState({
        isSpeaking: true,
        avatarCode: AVATAR_NAME_TO_CODE[avatarName] || avatarState.avatarCode || 'lingxiaochan',
        audioUrl: null,
        videoUrl: null,
        speechText: text,
        speechRequestId: Date.now(),
        isVideoMode: true,
        errorMessage: null,
      })
      set({ interactionState: 'avatar_preparing' })
      return
    }

    const params = new URLSearchParams({
      text,
      avatar: avatarName,
      emotion: 'neutral',
      speed: String(useUserStore.getState().speechRate),
    })
    const audioUrl = `${API_BASE}/api/v1/tts?${params.toString()}`
    setAvatarState({
      isSpeaking: true,
      avatarCode: AVATAR_NAME_TO_CODE[avatarName] || 'lingxiaochan',
      audioUrl,
      videoUrl: null,
      speechText: text,
      speechRequestId: Date.now(),
      isVideoMode: false,
      actionSequence: [],
      sdkConfig: null,
      errorMessage: '讯飞数字人未连接，请检查讯飞星火数字人配置。',
    })
    set({ interactionState: 'avatar_preparing' })
  },

  // 停止TTS播放
  stopTTS: () => {
    const { avatarState, isSending } = get()
    set((state) => ({
      muteCurrentTurn: isSending || avatarState.isSpeaking || state.muteCurrentTurn,
      interactionState: isSending
        && !['avatar_preparing', 'speaking'].includes(state.interactionState)
        ? state.interactionState
        : 'idle',
      avatarState: {
        ...state.avatarState,
        isSpeaking: false,
        audioUrl: null,
        videoUrl: null,
        speechText: null,
        actionSequence: [],
        speechStopRequestId: avatarState.speechStopRequestId + 1,
      },
    }))
  },
}))
