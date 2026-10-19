import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Button, Tag, Toast, SpinLoading } from 'antd-mobile'
import { BookOutlined, TrophyOutlined } from '@ant-design/icons'
import { motion } from 'framer-motion'
import { getOrCreateUserId } from '../../stores/user'
import { AVATAR_COLOR_MAP, AVATAR_COVER_MAP, AVATAR_NAME_MAP } from '../../constants/avatars'
import './Story.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

interface StoryLineItem {
  id: string
  avatar_code: string
  title: string
  description: string
  reward_badge: string
  is_active: boolean
}

interface StoryProgressResponse {
  storyline_id: string
  title: string
  current_node: string
  current_node_title: string
  current_node_description: string
  completed_nodes: string[]
  is_completed: boolean
  unlocked_hidden: boolean
  choices: unknown[]
  progress_percent: number
}

interface UserStoryProgressItem {
  storyline_id: string
  current_node: string
  is_completed: boolean
  progress_percent: number
}

interface StoryLineUI {
  id: string
  title: string
  avatar: string
  description: string
  cover: string
  progress: number
  reward: string
  color: string
  isCompleted: boolean
}


// 自定义进度条组件
function CustomProgress({ percent, color }: { percent: number; color: string }) {
  return (
    <div className="custom-progress">
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${percent}%`, background: color }}
        />
      </div>
      <span className="progress-text" style={{ color }}>{Math.round(percent)}%</span>
    </div>
  )
}

export default function Story() {
  const navigate = useNavigate()
  const [storyLines, setStoryLines] = useState<StoryLineUI[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchStoryList()
  }, [])

  const fetchStoryList = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/story/list`)
      if (!res.ok) throw new Error(`请求失败: ${res.status}`)
      const data: StoryLineItem[] = await res.json()
      const progressRes = await fetch(`${API_BASE}/api/v1/story/progress/${getOrCreateUserId()}`)
      const progressData: UserStoryProgressItem[] = progressRes.ok ? await progressRes.json() : []
      const progressMap = new Map(progressData.map((item) => [item.storyline_id, item]))
      const uiData: StoryLineUI[] = data.map((item) => ({
        id: item.id,
        title: item.title,
        avatar: AVATAR_NAME_MAP[item.avatar_code] || item.avatar_code,
        description: item.description || '跟随数字人线索，解锁灵山胜境的文化剧情。',
        cover: AVATAR_COVER_MAP[item.avatar_code] || '/assets/scenery/lingshan-scenic.jpg',
        progress: progressMap.get(item.id)?.progress_percent || 0,
        reward: item.reward_badge || '灵山故事徽章',
        color: AVATAR_COLOR_MAP[item.avatar_code] || '#8B4513',
        isCompleted: progressMap.get(item.id)?.is_completed || false,
      }))
      setStoryLines(uiData)
    } catch (err) {
      Toast.show({ content: '获取故事线失败', duration: 2000 })
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const startStory = async (storyId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/story/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storyline_id: storyId, user_id: getOrCreateUserId() }),
      })
      if (!res.ok) {
        const errorData = await res.json().catch(() => null)
        throw new Error(errorData?.detail || `请求失败: ${res.status}`)
      }
      const data: StoryProgressResponse = await res.json()
      setStoryLines((prev) =>
        prev.map((item) =>
          item.id === storyId
            ? { ...item, progress: data.progress_percent, isCompleted: data.is_completed }
            : item
        )
      )
      navigate(`/story/${storyId}`)
    } catch (err) {
      Toast.show({ content: err instanceof Error ? err.message : '开始故事线失败', duration: 2000 })
      console.error(err)
    }
  }

  return (
    <div className="story-page">
      <div className="story-header">
        <h1><BookOutlined /> 沉浸式故事线</h1>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <SpinLoading color="primary" />
          <p style={{ marginTop: 12, color: '#999' }}>加载中...</p>
        </div>
      )}

      <div className="story-list">
        {storyLines.map((story, index) => (
          <motion.div
            key={story.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
          >
            <Card className="story-card" style={{ borderLeft: `4px solid ${story.color}` }}>
              <div className="story-card-content">
                <div className="story-cover" style={{ background: story.color + '15' }}>
                  <img
                    src={story.cover}
                    alt={story.avatar}
                    onError={(event) => {
                      event.currentTarget.src = '/assets/scenery/lingshan-scenic.jpg'
                    }}
                  />
                </div>
                <div className="story-info">
                  <h3>{story.title}</h3>
                  <Tag color={story.color}>讲述人 {story.avatar}</Tag>
                  <p className="story-desc">{story.description}</p>

                  {story.progress > 0 || story.isCompleted ? (
                    <div className="story-progress-bar">
                      <CustomProgress percent={story.progress} color={story.color} />
                    </div>
                  ) : (
                    <div className="story-reward">
                      <TrophyOutlined /> 奖励: {story.reward}
                    </div>
                  )}

                  <Button
                    color="primary"
                    fill="solid"
                    size="small"
                    onClick={() => startStory(story.id)}
                    disabled={story.isCompleted || story.progress >= 100}
                    style={{ background: story.color, borderColor: story.color }}
                  >
                    {story.isCompleted || story.progress >= 100 ? '已完成' : story.progress > 0 ? '继续' : '开始'}
                  </Button>
                </div>
              </div>
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
