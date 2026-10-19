import { useRef, useState, useCallback, useEffect } from 'react'
import { motion } from 'framer-motion'
import { AudioOutlined } from '@ant-design/icons'
import { Toast } from 'antd-mobile'
import './VoiceInput.css'

interface Props {
  onResult?: (text: string) => void
  onAudioResult?: (audioBlob: Blob, transcriptHint?: string) => void
  onRecordingChange?: (recording: boolean) => void
  disabled?: boolean
}

type SpeechRecognitionCtor = new () => SpeechRecognition

interface SpeechRecognition extends EventTarget {
  lang: string
  interimResults: boolean
  continuous: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: Event) => void) | null
}

interface SpeechRecognitionEvent {
  results: ArrayLike<{
    isFinal: boolean
    0: { transcript: string }
  }>
}

export default function VoiceInput({ onResult, onAudioResult, onRecordingChange, disabled = false }: Props) {
  const [recording, setRecording] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const transcriptRef = useRef('')
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const stopTimerRef = useRef<number | null>(null)

  const updateRecording = useCallback((value: boolean) => {
    setRecording(value)
    onRecordingChange?.(value)
  }, [onRecordingChange])

  const stopRecording = useCallback(() => {
    if (stopTimerRef.current) {
      window.clearTimeout(stopTimerRef.current)
      stopTimerRef.current = null
    }
    recognitionRef.current?.stop()
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') recorder.stop()
  }, [])

  const startBrowserRecognition = useCallback(() => {
    const Recognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition as SpeechRecognitionCtor | undefined

    if (!Recognition) return

    const recognition = new Recognition()
    recognition.lang = 'zh-CN'
    recognition.interimResults = true
    recognition.continuous = true
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const text = Array.from(event.results)
        .map((result) => result[0]?.transcript || '')
        .join('')
        .trim()
      transcriptRef.current = text
    }
    recognition.onerror = () => {
      recognitionRef.current = null
    }
    recognitionRef.current = recognition
    recognition.start()
  }, [])

  const startRecording = useCallback(async () => {
    if (disabled) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      Toast.show({ content: '当前浏览器不支持录音，请改用文字输入', icon: 'fail' })
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
        .find((type) => MediaRecorder.isTypeSupported(type))
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      const outputType = recorder.mimeType || mimeType || 'audio/webm'

      chunksRef.current = []
      transcriptRef.current = ''
      streamRef.current = stream
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const audioBlob = new Blob(chunksRef.current, { type: outputType })
        stream.getTracks().forEach((track) => track.stop())
        streamRef.current = null
        mediaRecorderRef.current = null
        recognitionRef.current = null
        updateRecording(false)
        if (audioBlob.size < 256) {
          Toast.show({ content: '没有录到有效声音，请重试', icon: 'fail' })
          return
        }
        Toast.show({ content: '录音完成，正在识别', position: 'center' })
        onAudioResult?.(audioBlob, transcriptRef.current)
        if (!onAudioResult && transcriptRef.current) onResult?.(transcriptRef.current)
      }

      updateRecording(true)
      startBrowserRecognition()
      recorder.start()
      stopTimerRef.current = window.setTimeout(() => stopRecording(), 8000)
    } catch (error) {
      console.error('无法启动麦克风:', error)
      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null
      updateRecording(false)
      const denied = error instanceof DOMException && error.name === 'NotAllowedError'
      Toast.show({
        content: denied ? '未获得麦克风权限，请在浏览器地址栏中允许后重试' : '麦克风不可用，请检查设备后重试',
        icon: 'fail',
      })
    }
  }, [disabled, onAudioResult, onResult, startBrowserRecognition, stopRecording, updateRecording])

  useEffect(() => () => {
    if (stopTimerRef.current) window.clearTimeout(stopTimerRef.current)
    recognitionRef.current?.abort()
    const recorder = mediaRecorderRef.current
    if (recorder) recorder.onstop = null
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    streamRef.current?.getTracks().forEach((track) => track.stop())
    onRecordingChange?.(false)
  }, [onRecordingChange])

  return (
    <motion.button
      className={`voice-input-btn ${recording ? 'recording' : ''}`}
      onClick={recording ? stopRecording : startRecording}
      type="button"
      disabled={disabled && !recording}
      aria-pressed={recording}
      aria-label={recording ? '停止并发送录音' : '开始语音输入'}
      whileTap={{ scale: 0.92 }}
      whileHover={{ scale: recording ? 1 : 1.05 }}
      title={recording ? '停止录音' : '语音输入'}
    >
      <motion.div
        animate={recording ? { scale: [1, 1.2, 1] } : {}}
        transition={{ repeat: Infinity, duration: 0.8 }}
      >
        <AudioOutlined style={{ fontSize: 24, color: recording ? '#fff' : '#2d5a87' }} />
      </motion.div>
      {recording && <span className="recording-text">正在聆听...</span>}
    </motion.button>
  )
}
