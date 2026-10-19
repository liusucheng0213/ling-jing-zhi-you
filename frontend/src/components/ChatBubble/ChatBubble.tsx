import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { useChatStore } from '../../stores/chat'
import { getAvatarImage } from '../../config/avatarAssets'
import './ChatBubble.css'

interface Props {
  message: {
    id: string
    role: 'user' | 'assistant'
    content: string
    emotion?: string
    timestamp: number
    imageUrl?: string
    retrievedDocs?: Array<Record<string, any>>
    confidence?: number | null
    answerType?: string | null
    traceId?: string | null
    multimodalEvidence?: Record<string, any> | null
  }
}

export default function ChatBubble({ message }: Props) {
  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'
  const { playMessageTTS, stopTTS, selectedAvatar, avatarState } = useChatStore()
  const [isPlaying, setIsPlaying] = useState(false)

  const timeStr = new Date(message.timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
  const evidence = message.multimodalEvidence
  const imageCandidates = evidence?.candidates || []

  useEffect(() => {
    if (!avatarState.isSpeaking) setIsPlaying(false)
  }, [avatarState.isSpeaking])

  // 播放当前消息的TTS
  const handlePlayVoice = () => {
    if (isPlaying) {
      stopTTS()
      setIsPlaying(false)
      return
    }
    setIsPlaying(true)
    playMessageTTS(message.content)
  }

  return (
    <motion.div
      className={`chat-bubble ${isUser ? 'user' : 'assistant'}`}
      initial={{ opacity: 0, y: 10, x: isUser ? 20 : -20 }}
      animate={{ opacity: 1, y: 0, x: 0 }}
      transition={{ type: 'spring', stiffness: 500, damping: 40 }}
    >
      {isAssistant && (
        <div className="bubble-avatar assistant-mark" data-emotion={message.emotion || 'calm'}>
          <img src={getAvatarImage(selectedAvatar)} alt={`${selectedAvatar}头像`} />
        </div>
      )}
      <div className={`bubble-content ${isUser ? 'bg-golden' : 'bg-white'}`}>
        {message.imageUrl && (
          <img className="bubble-image" src={message.imageUrl} alt="上传的景区图片" />
        )}
        <p>{message.content}</p>
        {isAssistant && typeof message.confidence === 'number' && (
          <div className="answer-meta">
            <span>可信度 {Math.round(message.confidence * 100)}%</span>
            {message.answerType && <span>{message.answerType}</span>}
          </div>
        )}
        {isAssistant && imageCandidates.length > 0 && (
          <details className="evidence-details">
            <summary>图片识别候选 · {Math.min(imageCandidates.length, 3)} 条</summary>
            {imageCandidates.slice(0, 3).map((item: any, index: number) => (
              <div className="evidence-row" key={`${item.spot_name}-${index}`}>
                <span>{item.spot_name}</span>
                <strong>{Math.round((item.confidence || 0) * 100)}%</strong>
              </div>
            ))}
          </details>
        )}
        {isAssistant && evidence?.type === 'voice' && (
          <details className="evidence-details">
            <summary>语音识别</summary>
            <div className="evidence-row">
              <span>{evidence.asr_provider}</span>
              <strong>
                {typeof evidence.asr_confidence === 'number'
                  ? `${Math.round(evidence.asr_confidence * 100)}%`
                  : '未提供置信度'}
              </strong>
            </div>
          </details>
        )}
        {isAssistant && message.retrievedDocs && message.retrievedDocs.length > 0 && (
          <details className="source-details">
            <summary>答案依据 · {message.retrievedDocs.length} 条</summary>
            {message.retrievedDocs.slice(0, 3).map((doc, index) => (
              <div className="source-item" key={`${doc.chunk_id || index}`}>
                <div className="source-title">{doc.doc_title || '景区资料'}</div>
                <div className="source-content">{doc.content}</div>
              </div>
            ))}
          </details>
        )}
        <div className="bubble-footer">
          <span className="bubble-time">{timeStr}</span>
          {/* AI消息添加语音播放按钮 */}
          {isAssistant && (
            <button
              className={`voice-play-btn ${isPlaying ? 'playing' : ''}`}
              onClick={handlePlayVoice}
              title={isPlaying ? '停止朗读' : '播放语音'}
              aria-label={isPlaying ? '停止朗读这条回复' : '朗读这条回复'}
            >
              {isPlaying ? (
                <span className="voice-wave">
                  <span />
                  <span />
                  <span />
                </span>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M11 5L6 9H2v6h4l5 4V5z"
                    fill="currentColor"
                  />
                  <path
                    d="M15.54 8.46a5 5 0 010 7.07M19.07 4.93a10 10 0 010 14.14"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                </svg>
              )}
            </button>
          )}
        </div>
      </div>
      {isUser && (
        <div className="bubble-avatar user">游</div>
      )}
    </motion.div>
  )
}
