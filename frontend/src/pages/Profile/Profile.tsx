import { useEffect, useRef, useState, useCallback } from 'react'
import {
  Card,
  Switch,
  List,
  Toast,
  Modal,
  Dialog,
  Space,
  Tag,
  Empty,
  Skeleton,
  Slider,
} from 'antd-mobile'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { EditSOutline, RightOutline, DeleteOutline } from 'antd-mobile-icons'
import { getOrCreateUserId, normalizeBadgeId, useUserStore } from '../../stores/user'
import { useChatStore } from '../../stores/chat'
import { getJourneyProgress, useJourneyStore } from '../../stores/journey'
import { api } from '../../api/client'
import './Profile.css'

interface CreativeWork {
  id: string
  content_type: string
  title: string
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

interface StoryProgress {
  storyline_id: string
  title: string
  avatar_code: string
  current_node: string
  is_completed: boolean
  progress_percent: number
  unlocked_hidden: boolean
}

interface BadgeItem {
  id: string
  name: string
  icon: string
  description: string
  condition: string
  color: string
}

const BADGE_LIST: BadgeItem[] = [
  { id: 'newbie', name: '新手游客', icon: '🌱', description: '初次踏入灵境', condition: '首次使用灵境智游', color: '#2d5a87' },
  { id: 'zen', name: '禅心徽章', icon: '🧘', description: '心静如水，禅意盎然', condition: '完成一次完整的景点对话', color: '#8B7355' },
  { id: 'walker', name: '行者徽章', icon: '🚶', description: '千里之行，始于足下', condition: '游览3个以上景点', color: '#C8874A' },
  { id: 'lingyun', name: '灵韵徽章', icon: '✨', description: '灵气汇聚，韵味无穷', condition: '创作5件以上文创作品', color: '#A64272' },
  { id: 'storyteller', name: '说书人', icon: '📖', description: '故事大王，娓娓道来', condition: '完成一条故事线', color: '#315F91' },
  { id: 'explorer', name: '探索者', icon: '🔍', description: '好奇心驱动，探索未知', condition: '触发隐藏故事节点', color: '#8B6914' },
]

function getCreativeTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    community_post: '游记',
    journal: '游记',
    poem: '诗词',
    postcard: '明信片',
    badge: '徽章',
    painting: '画作',
  }
  return labels[type] || type
}

export default function Profile() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editNickname, setEditNickname] = useState('')
  const [editBio, setEditBio] = useState('')
  const [editVisibility, setEditVisibility] = useState<Array<'public' | 'followers' | 'private'>>(['public'])

  const { userInfo, elderlyMode, toggleElderlyMode, fontSizeLevel, setFontSizeLevel, highContrast, setHighContrast, speechRate, setSpeechRate, updateProfile } = useUserStore()
  const userId = userInfo?.id || getOrCreateUserId()
  const nickname = userInfo?.nickname || '游客'
  const avatar = userInfo?.avatar || ''
  const bio = userInfo?.bio || '把今天的灵山片刻，留给下一次回看。'
  const visibility = userInfo?.visibility || 'public'

  const chatMessages = useChatStore((s) => s.messages)
  const chatCount = Math.max(0, chatMessages.length - 1)
  const activeJourney = useJourneyStore((state) => state.activeJourney)
  const journeyHistory = useJourneyStore((state) => state.history)
  const visitedSpots = useJourneyStore((state) => state.visitedSpotIds.length)
  const [footprintExpanded, setFootprintExpanded] = useState(true)

  const [creativeWorks, setCreativeWorks] = useState<CreativeWork[]>([])
  const [creativeLoading, setCreativeLoading] = useState(false)
  const [creativeExpanded, setCreativeExpanded] = useState(false)

  const [storyProgress, setStoryProgress] = useState<StoryProgress[]>([])
  const [storyLoading, setStoryLoading] = useState(false)
  const [storyExpanded, setStoryExpanded] = useState(false)

  const [badgeExpanded, setBadgeExpanded] = useState(true)
  const userBadges = useUserStore((s) => s.badges)
  const normalizedBadges = userBadges.map(normalizeBadgeId)
  const earnedBadgeCount = BADGE_LIST.filter((badge) => normalizedBadges.includes(badge.id)).length

  const [aboutVisible, setAboutVisible] = useState(false)
  const [creativeDetail, setCreativeDetail] = useState<CreativeWork | null>(null)

  useEffect(() => {
    const oldNickname = localStorage.getItem('lingjing_nickname')
    if (oldNickname && oldNickname !== nickname) {
      updateProfile({ nickname: oldNickname })
    }
  }, [])

  const fetchCreativeWorks = useCallback(async () => {
    setCreativeLoading(true)
    try {
      const data = await api.get<{ items: CreativeWork[]; total: number }>(`/creative/list/${userId}`)
      setCreativeWorks(data.items || [])
    } catch {
      const local = localStorage.getItem('lingjing_creative_works')
      setCreativeWorks(local ? JSON.parse(local) : [])
    } finally {
      setCreativeLoading(false)
    }
  }, [userId])

  const fetchStoryProgress = useCallback(async () => {
    setStoryLoading(true)
    try {
      const data = await api.get<StoryProgress[]>(`/story/progress/${userId}`)
      setStoryProgress(data || [])
    } catch {
      const local = localStorage.getItem('lingjing_story_progress')
      setStoryProgress(local ? JSON.parse(local) : [])
    } finally {
      setStoryLoading(false)
    }
  }, [userId])

  const toggleCreative = () => {
    const next = !creativeExpanded
    setCreativeExpanded(next)
    if (next) fetchCreativeWorks()
  }

  const toggleStory = () => {
    const next = !storyExpanded
    setStoryExpanded(next)
    if (next) fetchStoryProgress()
  }

  const deleteCreative = (id: string) => {
    Dialog.confirm({
      content: '确定要删除这件文创作品吗？',
      confirmText: '删除',
      cancelText: '取消',
      onConfirm: () => {
        const updated = creativeWorks.filter((w) => w.id !== id)
        setCreativeWorks(updated)
        localStorage.setItem('lingjing_creative_works', JSON.stringify(updated))
        Toast.show({ content: '已删除' })
      },
    })
  }

  const openEditModal = () => {
    setEditNickname(nickname)
    setEditBio(bio)
    setEditVisibility([visibility])
    setEditModalVisible(true)
  }

  const saveProfile = () => {
    const trimmed = editNickname.trim()
    const bioText = editBio.trim()
    if (!trimmed) {
      Toast.show({ content: '昵称不能为空' })
      return
    }
    if (trimmed.length > 12) {
      Toast.show({ content: '昵称最多12个字符' })
      return
    }
    if (bioText.length > 80) {
      Toast.show({ content: '自我介绍最多80个字符' })
      return
    }
    updateProfile({ id: userId, nickname: trimmed, bio: bioText, visibility: editVisibility[0] || 'public' })
    setEditModalVisible(false)
    Toast.show({ content: '资料已保存', icon: 'success' })
  }

  const handleAvatarChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      Toast.show({ content: '请选择图片文件' })
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      Toast.show({ content: '图片不能超过2MB' })
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      if (result) {
        updateProfile({ id: userId, avatar: result })
        Toast.show({ content: '头像已更新', icon: 'success' })
      }
    }
    reader.onerror = () => Toast.show({ content: '头像读取失败' })
    reader.readAsDataURL(file)
  }

  const handleToggleContrast = (checked: boolean) => {
    setHighContrast(checked)
    Toast.show({ content: checked ? '高对比度已开启' : '高对比度已关闭' })
  }

  const fontSizeLabel = fontSizeLevel === 'normal' ? '标准' : fontSizeLevel === 'large' ? '大' : '特大'

  return (
    <div className={`profile-page ${elderlyMode ? 'elderly-mode' : ''} ${highContrast ? 'high-contrast' : ''}`}>
      {/* 用户信息卡片 */}
      <Card className="profile-card user-card">
        <div className="user-header">
          <button className="user-avatar" onClick={() => fileInputRef.current?.click()} aria-label="更换头像">
            {avatar ? <img src={avatar} alt={nickname} /> : <span className="avatar-text">{nickname.charAt(0)}</span>}
          </button>
          <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handleAvatarChange} />
          <div className="user-info">
            <div className="user-name-row">
              <h2 className="user-name">{nickname}</h2>
              <span className="edit-btn" onClick={openEditModal}>
                <EditSOutline />
              </span>
            </div>
            <p className="user-bio">{bio}</p>
            <p className="user-visibility">
              {visibility === 'public' ? '资料公开' : visibility === 'followers' ? '仅关注可见' : '仅自己可见'}
            </p>
          </div>
        </div>
        <div className="user-stats">
          <div className="stat-item">
            <span className="stat-num">{chatCount}</span>
            <span className="stat-label">对话次数</span>
          </div>
          <div className="stat-item">
            <span className="stat-num">{visitedSpots}</span>
            <span className="stat-label">游览景点</span>
          </div>
          <div className="stat-item">
            <span className="stat-num">{creativeWorks.length}</span>
            <span className="stat-label">文创作品</span>
          </div>
        </div>
      </Card>

      {/* 实时行程与游览足迹 */}
      <Card className="profile-card journey-footprint-card">
        <div className="card-header" onClick={() => setFootprintExpanded(!footprintExpanded)}>
          <h3 className="card-title">🧭 我的足迹</h3>
          <span className="footprint-count">{journeyHistory.length} 次行程</span>
          <RightOutline className={`expand-icon ${footprintExpanded ? 'expanded' : ''}`} />
        </div>
        <AnimatePresence>
          {footprintExpanded && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
              {activeJourney && (
                <button type="button" className="active-footprint" onClick={() => navigate('/route')}>
                  <div>
                    <span>正在游览</span>
                    <strong>{activeJourney.routeName}</strong>
                    <small>
                      {activeJourney.remainingNodes[0]?.phase === 'arrived' ? '当前' : '下一站'}：
                      {activeJourney.remainingNodes[0]?.spotName || '即将完成'}
                    </small>
                  </div>
                  <b>{getJourneyProgress(activeJourney)}%</b>
                </button>
              )}

              {journeyHistory.length > 0 ? (
                <div className="footprint-history-list">
                  {journeyHistory.slice(0, 5).map((journey) => (
                    <div key={journey.journeyId} className="footprint-history-item">
                      <div className="footprint-history-head">
                        <div>
                          <strong>{journey.routeName}</strong>
                          <span>{new Date(journey.endedAt).toLocaleDateString('zh-CN')}</span>
                        </div>
                        <Tag
                          className="footprint-result-tag"
                          color={journey.result === 'completed' ? 'success' : 'warning'}
                        >
                          {journey.result === 'completed' ? '已完成' : `完成 ${journey.completionPercent}%`}
                        </Tag>
                      </div>
                      <div className="footprint-spot-tags">
                        {journey.visited.length > 0
                          ? journey.visited.map((spot) => (
                              <span key={`${journey.journeyId}-${spot.spotId}-${spot.recordedAt}`}>{spot.spotName}</span>
                            ))
                          : <small>本次未确认到访景点</small>}
                      </div>
                      <p>
                        到访 {journey.visited.length} 站
                        {journey.skipped.length ? ` · 跳过 ${journey.skipped.length} 站` : ''}
                        {' · '}陪游 {Math.max(1, Math.round((journey.endedAt - journey.startedAt) / 60000))} 分钟
                      </p>
                    </div>
                  ))}
                </div>
              ) : !activeJourney ? (
                <Empty description="开始一条数字人陪游路线后，足迹会保存在这里" />
              ) : null}
            </motion.div>
          )}
        </AnimatePresence>
      </Card>

      {/* 设置 */}
      <Card className="profile-card">
        <h3 className="card-title">⚙️ 设置</h3>
        <List>
          <List.Item
            extra={<Switch checked={elderlyMode} onChange={toggleElderlyMode} />}
            description="大字、慢语速、高对比度"
          >
            <span style={{ fontSize: elderlyMode ? 20 : 16 }}>👴 长辈模式</span>
          </List.Item>
          <List.Item
            extra={<Switch checked={highContrast} onChange={handleToggleContrast} />}
            description="增强文字与背景对比"
          >
            <span style={{ fontSize: elderlyMode ? 20 : 16 }}>🔲 高对比度</span>
          </List.Item>
          <List.Item extra={<span className="font-size-value">{fontSizeLabel}</span>}>
            <span style={{ fontSize: elderlyMode ? 20 : 16 }}>🔤 字体大小</span>
            <div className="font-size-slider">
              <Slider
                min={0}
                max={2}
                step={1}
                value={fontSizeLevel === 'normal' ? 0 : fontSizeLevel === 'large' ? 1 : 2}
                onChange={(v) => {
                  const idx = Array.isArray(v) ? v[0] : v
                  const levels: Array<'normal' | 'large' | 'extra-large'> = ['normal', 'large', 'extra-large']
                  const level = levels[idx]
                  setFontSizeLevel(level)
                }}
              />
            </div>
          </List.Item>
          <List.Item description="调节AI导览语音播放速度">
            <span style={{ fontSize: elderlyMode ? 20 : 16 }}>🗣️ 语音语速</span>
            <div className="speech-rate-slider">
              <span className="rate-label">慢</span>
              <Slider min={0.5} max={2.0} step={0.1} value={speechRate} onChange={(v) => setSpeechRate(Array.isArray(v) ? v[0] : v)} />
              <span className="rate-label">快</span>
              <span className="rate-value">{speechRate.toFixed(1)}x</span>
            </div>
          </List.Item>
        </List>
      </Card>

      {/* 故事线进度 */}
      <Card className="profile-card">
        <div className="card-header" onClick={toggleStory}>
          <h3 className="card-title">📖 故事线进度</h3>
          <RightOutline className={`expand-icon ${storyExpanded ? 'expanded' : ''}`} />
        </div>
        <AnimatePresence>
          {storyExpanded && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
              {storyLoading ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Skeleton.Title animated />
                  <Skeleton.Paragraph lineCount={2} />
                </Space>
              ) : storyProgress.length > 0 ? (
                storyProgress.map((sp) => (
                  <div key={sp.storyline_id} className="story-progress-item">
                    <div className="story-info-row">
                      <span className="story-title">{sp.title}</span>
                      {sp.is_completed && <Tag color="success">已完成</Tag>}
                    </div>
                    <div className="progress-bar">
                      <div className="progress-fill" style={{ width: `${sp.progress_percent}%` }} />
                    </div>
                    <span className="progress-text">{sp.progress_percent}%</span>
                  </div>
                ))
              ) : (
                <Empty description="还没有故事进度 · 去「故事」页开启第一段剧情吧" />
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </Card>

      {/* 文创作品 */}
      <Card className="profile-card">
        <div className="card-header" onClick={toggleCreative}>
          <h3 className="card-title">🎨 我的文创</h3>
          <RightOutline className={`expand-icon ${creativeExpanded ? 'expanded' : ''}`} />
        </div>
        <AnimatePresence>
          {creativeExpanded && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
              {creativeLoading ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Skeleton.Title animated />
                  <Skeleton.Paragraph lineCount={3} />
                </Space>
              ) : creativeWorks.length > 0 ? (
                creativeWorks.map((work) => (
                  <div key={work.id} className="creative-item">
                    <div className="creative-header">
                      <Tag color={work.content_type === 'community_post' || work.content_type === 'journal' ? 'success' : work.content_type === 'poem' ? 'primary' : 'warning'}>
                        {getCreativeTypeLabel(work.content_type)}
                      </Tag>
                      <span className="creative-title">{work.title}</span>
                      <DeleteOutline className="delete-btn" onClick={() => deleteCreative(work.id)} />
                    </div>
                    <p className="creative-content" onClick={() => setCreativeDetail(work)}>{work.content}</p>
                  </div>
                ))
              ) : (
                <Empty description="还没有文创作品 · 去「文创」页留下第一张明信片吧" />
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </Card>

      {/* 徽章 */}
      <Card className="profile-card">
        <div className="card-header" onClick={() => setBadgeExpanded(!badgeExpanded)}>
          <h3 className="card-title">🏆 我的徽章</h3>
          <span className="badge-count">{earnedBadgeCount}/{BADGE_LIST.length}</span>
          <RightOutline className={`expand-icon ${badgeExpanded ? 'expanded' : ''}`} />
        </div>
        <AnimatePresence>
          {badgeExpanded && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
              <div className="badge-grid">
                {BADGE_LIST.map((badge) => {
                  const earned = normalizedBadges.includes(badge.id)
                  return (
                    <div key={badge.id} className={`badge-card ${earned ? 'earned' : 'locked'}`}>
                      <div className="badge-icon" style={{ background: earned ? badge.color : '#ddd' }}>
                        {earned ? badge.icon : '🔒'}
                      </div>
                      <span className="badge-name">{badge.name}</span>
                      <span className="badge-status">{earned ? '已获得' : badge.condition}</span>
                    </div>
                  )
                })}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>

      {/* 关于 */}
      <Card className="profile-card">
        <div className="card-header" onClick={() => setAboutVisible(true)}>
          <h3 className="card-title">ℹ️ 关于灵境智游</h3>
          <RightOutline />
        </div>
      </Card>

      {/* 编辑昵称弹窗 */}
      <Modal
        visible={editModalVisible}
        title="编辑个人资料"
        content={
          <div className="profile-edit-form">
            <label>
              昵称
              <input
                className="nickname-input"
                value={editNickname}
                onChange={(e) => setEditNickname(e.target.value)}
                placeholder="请输入昵称"
                maxLength={12}
              />
            </label>
            <label>
              自我介绍
              <textarea
                className="bio-input"
                value={editBio}
                onChange={(e) => setEditBio(e.target.value)}
                placeholder="写一句介绍自己"
                maxLength={80}
                rows={3}
              />
            </label>
            <label>
              资料可见范围
              <div className="visibility-select">
                {[
                  { label: '公开', value: 'public' },
                  { label: '仅关注可见', value: 'followers' },
                  { label: '仅自己可见', value: 'private' },
                ].map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    className={editVisibility[0] === item.value ? 'active' : ''}
                    onClick={() => setEditVisibility([item.value as 'public' | 'followers' | 'private'])}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </label>
          </div>
        }
        closeOnAction
        onClose={() => setEditModalVisible(false)}
        actions={[
          { key: 'cancel', text: '取消' },
          { key: 'confirm', text: '保存', onClick: saveProfile },
        ]}
      />

      {/* 关于弹窗 */}
      <Modal
        visible={aboutVisible}
        title="关于灵境智游"
        content={
          <div className="about-content">
            <p>灵境智游 v1.1.0</p>
            <p>AI数字人智慧景区导览系统</p>
            <p>示范景区：灵山胜境</p>
            <p style={{ marginTop: 12, color: '#999', fontSize: 12 }}>
              基于DeepSeek大模型 · 多模态交互 · RAG知识增强
            </p>
          </div>
        }
        closeOnAction
        onClose={() => setAboutVisible(false)}
        actions={[{ key: 'ok', text: '知道了' }]}
      />

      {/* 文创详情弹窗 */}
      <Modal
        visible={!!creativeDetail}
        title={creativeDetail?.title || ''}
        content={
          <div className="creative-detail">
            <p>{creativeDetail?.content}</p>
          </div>
        }
        closeOnAction
        onClose={() => setCreativeDetail(null)}
        actions={[{ key: 'close', text: '关闭' }]}
      />
    </div>
  )
}
