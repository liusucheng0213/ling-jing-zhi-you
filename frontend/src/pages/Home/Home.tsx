import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Swiper } from 'antd-mobile'
import { CompassOutlined, BookOutlined, GiftOutlined, UserOutlined } from '@ant-design/icons'
import { api } from '../../api/client'
import { useChatStore } from '../../stores/chat'
import './Home.css'

const bannerImages = [
  {
    url: '/assets/scenery/lingshan-buddha.jpg',
    title: '九龙灌浴',
    subtitle: '动态仪式与文化讲解',
  },
  {
    url: '/assets/scenery/lingshan-scenic.jpg',
    title: '灵山大佛',
    subtitle: '88米青铜释迦牟尼立像',
  },
  {
    url: '/assets/scenery/lingshan-palace.jpg',
    title: '灵山梵宫',
    subtitle: '东方佛教艺术殿堂',
  },
]

const featureEntries = [
  {
    icon: <CompassOutlined />,
    title: '路线推荐',
    path: '/route',
    color: '#D4A574',
  },
  {
    icon: <BookOutlined />,
    title: '故事线',
    path: '/story',
    color: '#8B6914',
  },
  {
    icon: <GiftOutlined />,
    title: 'AI文创',
    path: '/creative',
    color: '#8f5d8d',
  },
  {
    icon: <UserOutlined />,
    title: '我的旅程',
    path: '/profile',
    color: '#315F91',
  },
]

interface AvatarOption {
  name: string
  code: string
  title: string
  desc: string
  cover: string
  tone: string
}

interface PublicAvatarResponse {
  code: string
  name: string
  title: string
  description: string
  enabled: boolean
  image_url?: string | null
}

const avatarVisuals: Record<string, { cover: string; tone: string }> = {
  lingxiaochan: { cover: '/assets/avatars/lingxiaochan.jpg', tone: '#2d5a87' },
  wuchanshi: { cover: '/assets/avatars/wuchanshi.jpg', tone: '#695B45' },
  xuanzang: { cover: '/assets/avatars/xuanzang.jpg', tone: '#8B4513' },
  xiaowan: { cover: '/assets/avatars/xiaowan.jpg', tone: '#A64272' },
  zhaopuchu: { cover: '/assets/avatars/zhaopuchu.jpg', tone: '#315F91' },
}

const defaultAvatarOptions: AvatarOption[] = [
  {
    name: '舒窈',
    code: 'lingxiaochan',
    title: '轻松导览',
    desc: '首次游览 · 亲子问答',
    ...avatarVisuals.lingxiaochan,
  },
  {
    name: '明朗',
    code: 'wuchanshi',
    title: '稳重讲解',
    desc: '梵宫禅寺 · 深度文化',
    ...avatarVisuals.wuchanshi,
  },
  {
    name: '风屿',
    code: 'xuanzang',
    title: '历史故事',
    desc: '剧情体验 · 研学游览',
    ...avatarVisuals.xuanzang,
  },
  {
    name: '雨桐',
    code: 'xiaowan',
    title: '江南美学',
    desc: '拍照机位 · 文创灵感',
    ...avatarVisuals.xiaowan,
  },
  {
    name: '明泽',
    code: 'zhaopuchu',
    title: '艺术导览',
    desc: '佛教艺术 · 文化脉络',
    ...avatarVisuals.zhaopuchu,
  },
]

export default function Home() {
  const navigate = useNavigate()
  const selectedAvatar = useChatStore((state) => state.selectedAvatar)
  const setSelectedAvatar = useChatStore((state) => state.setSelectedAvatar)
  const [remoteAvatars, setRemoteAvatars] = useState<AvatarOption[] | null>(null)

  const avatarOptions = useMemo(() => remoteAvatars?.length ? remoteAvatars : defaultAvatarOptions, [remoteAvatars])

  useEffect(() => {
    let cancelled = false
    api.get<PublicAvatarResponse[]>('/avatars')
      .then((rows) => {
        if (cancelled) return
        const next = rows
          .filter((item) => item.enabled)
          .map((item) => {
            const visual = avatarVisuals[item.code] || avatarVisuals.lingxiaochan
            return {
              name: item.name,
              code: item.code,
              title: item.title || 'AI数字人导游',
              desc: item.description || item.title || '景区智慧导览角色',
              cover: item.image_url || visual.cover,
              tone: visual.tone,
            }
          })
        setRemoteAvatars(next)
        if (next.length && !next.some((item) => item.name === selectedAvatar)) {
          setSelectedAvatar(next[0].name)
        }
      })
      .catch((error) => {
        console.error('加载启用数字人失败:', error)
      })
    return () => {
      cancelled = true
    }
  }, [selectedAvatar, setSelectedAvatar])

  return (
    <div className="home-page">
      <div className="home-header-bg"></div>

      <motion.div
        className="banner-section"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        <Swiper autoplay loop className="banner-swiper">
          {bannerImages.map((item, index) => (
            <Swiper.Item key={index}>
              <div className="banner-item">
                <img src={item.url} alt={item.title} />
                <div className="banner-overlay"></div>
                <div className="banner-text">
                  <h2>{item.title}</h2>
                  <p>{item.subtitle}</p>
                </div>
              </div>
            </Swiper.Item>
          ))}
        </Swiper>
      </motion.div>

      <motion.section
        className="avatar-select-hero"
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, delay: 0.2 }}
      >
        <div className="welcome-text">
          <img className="welcome-logo" src="/assets/logo.png" alt="灵境智游" />
          <h1>灵境智游</h1>
          <p className="welcome-subtitle">灵山胜境 · 数字人伴游</p>
          <div className="welcome-divider"></div>
        </div>

        <div className={`avatar-option-grid ${avatarOptions.length === 1 ? 'single' : ''}`}>
          {avatarOptions.map((avatar) => (
            <button
              key={avatar.code}
              type="button"
              className={`avatar-option-card ${selectedAvatar === avatar.name ? 'active' : ''}`}
              onClick={() => setSelectedAvatar(avatar.name)}
            >
              <img
                src={avatar.cover}
                alt={avatar.name}
                onError={(event) => {
                  event.currentTarget.src = '/assets/scenery/lingshan-scenic.jpg'
                }}
              />
              <span className="avatar-option-mark" style={{ background: avatar.tone }}>{avatar.name.slice(0, 1)}</span>
              <strong>{avatar.name}</strong>
              <em>{avatar.title}</em>
              {avatar.desc && !avatar.desc.includes(avatar.title) && <p>{avatar.desc}</p>}
            </button>
          ))}
        </div>
      </motion.section>

      <motion.div
        className="feature-grid"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.4 }}
      >
        {featureEntries.map((item, index) => (
          <motion.button
            key={item.title}
            type="button"
            className="feature-card"
            whileTap={{ scale: 0.95 }}
            onClick={() => navigate(item.path)}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5 + index * 0.1 }}
          >
            <div
              className="feature-icon"
              style={{ background: `linear-gradient(135deg, ${item.color}, ${item.color}b3)`, color: '#fff' }}
            >
              {item.icon}
            </div>
            <div className="feature-info">
              <h3>{item.title}</h3>
            </div>
          </motion.button>
        ))}
      </motion.div>

    </div>
  )
}
