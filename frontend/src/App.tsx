import { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { TabBar } from 'antd-mobile'
import {
  ForkOutlined,
  BookOutlined,
  GiftOutlined,
  UserOutlined,
} from '@ant-design/icons'
import Home from './pages/Home/Home'
import GlobalChatPanel from './components/GlobalChatPanel/GlobalChatPanel'
import JourneyBar from './components/JourneyBar/JourneyBar'
import { useChatStore } from './stores/chat'
import { useJourneyStore } from './stores/journey'
import { useUserStore } from './stores/user'
import './index.css'

const RoutePage = lazy(() => import('./pages/Route/Route'))
const Story = lazy(() => import('./pages/Story/Story'))
const StoryDetail = lazy(() => import('./pages/Story/StoryDetail'))
const Creative = lazy(() => import('./pages/Creative/Creative'))
const AuthorProfile = lazy(() => import('./pages/Creative/AuthorProfile'))
const Profile = lazy(() => import('./pages/Profile/Profile'))

// 页面切换动画配置（小位移 + 短时长，避免切页跳动感）
const pageVariants = {
  initial: { opacity: 0, x: 14 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -14 },
}

// 底部导航配置
const tabs = [
  { key: '/route', title: '路线', icon: <ForkOutlined /> },
  { key: '/story', title: '故事', icon: <BookOutlined /> },
  { key: '/creative', title: '文创', icon: <GiftOutlined /> },
  { key: '/profile', title: '我的', icon: <UserOutlined /> },
]

/**
 * 主应用组件
 * 包含路由配置和底部导航栏
 */
function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const elderlyMode = useUserStore((state) => state.elderlyMode)
  const fontSizeLevel = useUserStore((state) => state.fontSizeLevel)
  const highContrast = useUserStore((state) => state.highContrast)
  const restoreGuideAvatar = useChatStore((state) => state.restoreGuideAvatar)
  const hasActiveJourney = useJourneyStore((state) => Boolean(state.activeJourney))
  const showGlobalChat = location.pathname !== '/'
  const activeTabKey = location.pathname.startsWith('/story')
    ? '/story'
    : location.pathname.startsWith('/creative')
      ? '/creative'
      : location.pathname

  useEffect(() => {
    document.body.classList.toggle('elderly-mode', elderlyMode)
    document.body.classList.toggle('high-contrast', highContrast || elderlyMode)
    document.body.dataset.fontSize = fontSizeLevel
  }, [elderlyMode, fontSizeLevel, highContrast])

  useEffect(() => {
    if (!/^\/story\/[^/]+/.test(location.pathname)) {
      void restoreGuideAvatar()
    }
  }, [location.pathname, restoreGuideAvatar])

  // 切页后复位滚动位置：消除上一页滚动偏移残留造成的跳动感
  useEffect(() => {
    document.querySelector('.page-content')?.scrollTo(0, 0)
    window.scrollTo(0, 0)
  }, [location.pathname])

  return (
    <div className={`app-container ${showGlobalChat ? 'has-chat-panel' : 'home-shell'} ${hasActiveJourney ? 'has-active-journey' : ''}`}>
      <aside className="desktop-nav" aria-label="桌面导航">
        <button
          type="button"
          className="desktop-brand desktop-home-link"
          onClick={() => navigate('/')}
          aria-label="返回灵境智游主界面"
        >
          <img className="desktop-brand-logo" src="/assets/logo.png" alt="灵境智游" />
          <strong>灵境智游</strong>
          <span>AI 数字人导览</span>
        </button>
        <nav>
          {tabs.map((item) => (
            <button
              key={item.key}
              className={activeTabKey === item.key ? 'active' : ''}
              onClick={() => navigate(item.key)}
              aria-current={activeTabKey === item.key ? 'page' : undefined}
            >
              {item.icon}
              <span>{item.title}</span>
            </button>
          ))}
        </nav>
        <JourneyBar mode="desktop" />
      </aside>

      {/* 页面内容区域 */}
      <div className="page-content">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            variants={pageVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
            style={{ height: '100%' }}
          >
            <Suspense fallback={<div className="page-route-loading">正在加载...</div>}>
              <Routes location={location}>
                <Route path="/" element={<Home />} />
                <Route path="/chat" element={<Navigate to="/route" replace />} />
                <Route path="/route" element={<RoutePage />} />
                <Route path="/story" element={<Story />} />
                <Route path="/story/:storyId" element={<StoryDetail />} />
                <Route path="/creative" element={<Creative />} />
                <Route path="/creative/authors/:nickname" element={<AuthorProfile />} />
                <Route path="/profile" element={<Profile />} />
              </Routes>
            </Suspense>
          </motion.div>
        </AnimatePresence>
      </div>

      <GlobalChatPanel visible={showGlobalChat} />
      <JourneyBar mode="mobile" />

      {/* 底部导航栏 */}
      <div className="tab-bar-wrapper">
        <TabBar
          activeKey={activeTabKey}
          onChange={(key) => {
            navigate(key)
          }}
          safeArea
        >
          {tabs.map((item) => (
            <TabBar.Item key={item.key} icon={item.icon} title={item.title} />
          ))}
        </TabBar>
      </div>
    </div>
  )
}

export default App
