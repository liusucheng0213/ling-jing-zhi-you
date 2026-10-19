import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, SpinLoading, Tag, Toast } from 'antd-mobile'
import { motion } from 'framer-motion'
import { BookOutlined, SoundOutlined, TrophyOutlined } from '@ant-design/icons'
import { getOrCreateUserId, useUserStore } from '../../stores/user'
import { AVATAR_COLOR_MAP, AVATAR_NAME_MAP } from '../../constants/avatars'
import { buildAvatarState, useChatStore } from '../../stores/chat'
import './Story.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

interface StoryChoice {
  label: string
  value: string
  next_node?: string
}

interface StoryProgressResponse {
  storyline_id: string
  title: string
  avatar_code?: string
  reward_badge?: string
  current_node: string
  current_node_title?: string
  current_node_description?: string
  current_node_spot_id?: string
  completed_nodes: string[]
  is_completed: boolean
  unlocked_hidden: boolean
  choices: StoryChoice[]
  progress_percent: number
  npc_line?: string
  task?: string
  culture_note?: string
  action_label?: string
  narrator_name?: string
  narration_text?: string
  choice_result?: string
  digital_human?: Record<string, any> | null
}


async function readErrorMessage(res: Response, defaultMessage: string) {
  const data = await res.json().catch(() => null)
  return data?.detail || defaultMessage
}

export default function StoryDetail() {
  const { storyId } = useParams()
  const navigate = useNavigate()
  const [progress, setProgress] = useState<StoryProgressResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [advancing, setAdvancing] = useState(false)
  const narratedNodeRef = useRef('')
  const addBadge = useUserStore((state) => state.addBadge)
  const activeAvatar = useChatStore((state) => state.activeAvatar)
  const setNarrationAvatar = useChatStore((state) => state.setNarrationAvatar)
  const setAvatarState = useChatStore((state) => state.setAvatarState)
  const addMessage = useChatStore((state) => state.addMessage)

  const color = useMemo(() => {
    return AVATAR_COLOR_MAP[progress?.avatar_code || ''] || '#2d5a87'
  }, [progress?.avatar_code])

  useEffect(() => {
    if (!storyId) {
      Toast.show({ content: '故事不存在', duration: 2000 })
      navigate('/story', { replace: true })
      return
    }
    loadStory()
  }, [storyId])

  useEffect(() => {
    if (progress?.is_completed) {
      addBadge(progress.reward_badge || '灵山故事徽章')
    }
  }, [progress?.is_completed, progress?.reward_badge, addBadge])

  const playNarration = (next: StoryProgressResponse, appendMessage = true) => {
    const narrator = next.narrator_name || AVATAR_NAME_MAP[next.avatar_code || ''] || '舒窈'
    const narrationText = next.narration_text || next.npc_line || next.current_node_description || ''
    if (!next.digital_human || !narrationText) {
      Toast.show({ content: '本章数字人播报配置暂不可用', duration: 1800 })
      return
    }

    if (activeAvatar !== narrator) {
      setNarrationAvatar(narrator)
    }
    setAvatarState({
      ...buildAvatarState({
        digital_human: next.digital_human,
        message: { content: narrationText, emotion: next.digital_human.emotion || 'friendly' },
      }, narrator),
      speechRequestId: Date.now(),
    })

    if (appendMessage && narratedNodeRef.current !== next.current_node) {
      addMessage({
        role: 'assistant',
        content: narrationText,
        emotion: next.digital_human.emotion || 'friendly',
      })
      narratedNodeRef.current = next.current_node
    }
  }

  const acceptProgress = (next: StoryProgressResponse) => {
    setProgress(next)
    window.setTimeout(() => playNarration(next), 0)
  }

  const loadStory = async () => {
    if (!storyId) return
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/story/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storyline_id: storyId, user_id: getOrCreateUserId() }),
      })
      if (!res.ok) {
        throw new Error(await readErrorMessage(res, `请求失败: ${res.status}`))
      }
      acceptProgress(await res.json())
    } catch (err) {
      Toast.show({ content: err instanceof Error ? err.message : '加载故事失败', duration: 2200 })
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const advanceStory = async (choice?: string) => {
    if (!storyId || !progress) return
    if (progress.is_completed) {
      navigate('/story')
      return
    }
    setAdvancing(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/story/progress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storyline_id: storyId, user_id: getOrCreateUserId(), choice }),
      })
      if (!res.ok) {
        throw new Error(await readErrorMessage(res, `推进失败: ${res.status}`))
      }
      acceptProgress(await res.json())
    } catch (err) {
      Toast.show({ content: err instanceof Error ? err.message : '推进故事失败', duration: 2200 })
      console.error(err)
    } finally {
      setAdvancing(false)
    }
  }

  if (loading && !progress) {
    return (
      <div className="story-page story-detail-page">
        <div className="story-detail-loading">
          <SpinLoading color="primary" />
          <p>正在进入故事...</p>
        </div>
      </div>
    )
  }

  if (!progress) {
    return (
      <div className="story-page story-detail-page">
        <button className="story-back-button" onClick={() => navigate('/story')}>返回故事列表</button>
        <div className="story-empty-detail">
          <span className="story-empty-icon">📖</span>
          暂时无法进入这个故事，请稍后再试。
        </div>
      </div>
    )
  }

  const avatarName = progress.narrator_name || AVATAR_NAME_MAP[progress.avatar_code || ''] || '数字人'
  const hasChoices = progress.choices.length > 0 && !progress.is_completed

  return (
    <div className="story-page story-detail-page">
      <button className="story-back-button" onClick={() => navigate('/story')}>返回</button>

      <motion.div
        className="story-detail-hero"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        style={{ borderColor: color }}
      >
        <div className="story-detail-title-row">
          <div>
            <span className="story-detail-kicker">数字人讲述 · {avatarName}</span>
            <h1>{progress.title}</h1>
          </div>
          <Tag color={progress.is_completed ? 'success' : 'primary'}>
            {progress.is_completed ? '已完成' : `节点 ${progress.completed_nodes.length + 1}`}
          </Tag>
        </div>
        <div className="story-detail-progress">
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{ width: `${progress.progress_percent}%`, background: color }}
            />
          </div>
          <span>{progress.progress_percent}%</span>
        </div>
      </motion.div>

      <section className="story-detail-section npc-section">
        <div className="story-detail-heading">
          <BookOutlined />
          <span>{progress.current_node_title || '当前章节'}</span>
        </div>
        <p className="npc-line">{progress.npc_line || progress.current_node_description}</p>
        {progress.choice_result && <p className="story-choice-result">{progress.choice_result}</p>}
        {progress.current_node_spot_id && (
          <span className="spot-pill">关联景点 {progress.current_node_spot_id}</span>
        )}
        <Button className="story-avatar-button" size="small" onClick={() => playNarration(progress, false)}>
          <SoundOutlined /> 重播本章
        </Button>
      </section>

      {progress.task && (
        <section className="story-detail-section task-section">
          <div className="story-detail-heading">当前任务</div>
          <p>{progress.task}</p>
        </section>
      )}

      {progress.culture_note && (
        <section className="story-detail-section culture-section">
          <div className="story-detail-heading">文化线索</div>
          <p>{progress.culture_note}</p>
        </section>
      )}

      {progress.unlocked_hidden && (
        <div className="hidden-story-note">隐藏剧情已触发</div>
      )}

      <div className="story-actions">
        {hasChoices ? (
          progress.choices.map((choice) => (
            <Button
              key={choice.value}
              block
              color="primary"
              loading={advancing}
              disabled={advancing}
              style={{ '--background-color': color, '--border-color': color } as CSSProperties}
              onClick={() => advanceStory(choice.value)}
            >
              {choice.label}
            </Button>
          ))
        ) : progress.is_completed ? (
          <div className="story-complete-panel">
            <TrophyOutlined />
            <strong>{progress.reward_badge || '灵山故事徽章'}</strong>
            <p>故事已完成，奖励已解锁。</p>
            <Button block color="primary" onClick={() => navigate('/story')}>
              {progress.action_label || '返回故事列表'}
            </Button>
          </div>
        ) : (
          <Button
            block
            color="primary"
            loading={advancing}
            disabled={advancing}
            style={{ '--background-color': color, '--border-color': color } as CSSProperties}
            onClick={() => advanceStory()}
          >
            {progress.action_label || '继续剧情'}
          </Button>
        )}
      </div>
    </div>
  )
}
