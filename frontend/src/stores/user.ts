import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const DEFAULT_AVATAR = '/assets/avatars/default-user.webp'

export const BADGE_NAME_TO_ID: Record<string, string> = {
  新手游客: 'newbie',
  禅心徽章: 'zen',
  行者徽章: 'walker',
  灵韵徽章: 'lingyun',
  说书人: 'storyteller',
  探索者: 'explorer',
  灵山故事徽章: 'storyteller',
  '玄奘西行徽章': 'storyteller',
}

export function normalizeBadgeId(badge: string): string {
  return BADGE_NAME_TO_ID[badge] || badge
}

export function getOrCreateUserId(): string {
  const stored = localStorage.getItem('lingjing_user_id')
  if (stored && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(stored)) {
    return stored
  }
  const newId = window.crypto?.randomUUID?.() || '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
    (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c) / 4).toString(16)
  )
  localStorage.setItem('lingjing_user_id', newId)
  return newId
}

/**
 * 用户状态接口
 */
interface UserStore {
  // 用户信息
  userInfo: {
    id: string
    nickname: string
    avatar: string
    bio: string
    visibility: 'public' | 'followers' | 'private'
    phone?: string
  } | null
  // 是否已登录
  isLoggedIn: boolean
  // 长辈模式开关
  elderlyMode: boolean
  // 字体大小级别：normal, large, extra-large
  fontSizeLevel: 'normal' | 'large' | 'extra-large'
  // 全局高对比度
  highContrast: boolean
  speechRate: number
  // 当前游览景点
  currentSpot: string | null
  // 已获得的徽章
  badges: string[]

  // 操作方法
  setUserInfo: (info: UserStore['userInfo']) => void
  updateProfile: (profile: Partial<NonNullable<UserStore['userInfo']>>) => void
  logout: () => void
  toggleElderlyMode: () => void
  setFontSizeLevel: (level: UserStore['fontSizeLevel']) => void
  setHighContrast: (enabled: boolean) => void
  setSpeechRate: (rate: number) => void
  setCurrentSpot: (spot: string | null) => void
  addBadge: (badge: string) => void
}

/**
 * Zustand 用户状态管理
 * 使用 persist 中间件实现状态持久化
 */
export const useUserStore = create<UserStore>()(
  persist(
    (set, get) => ({
      // 初始状态
      userInfo: {
        id: getOrCreateUserId(),
        nickname: localStorage.getItem('lingjing_nickname') || '游客',
        avatar: DEFAULT_AVATAR,
        bio: '把今天的灵山片刻，留给下一次回看。',
        visibility: 'public',
      },
      isLoggedIn: false,
      elderlyMode: false,
      fontSizeLevel: 'normal',
      highContrast: false,
      speechRate: 1,
      currentSpot: null,
      badges: ['newbie'],

      // 设置用户信息
      setUserInfo: (info) =>
        set({
          userInfo: info ? { ...info, bio: info.bio || '', visibility: info.visibility || 'public' } : info,
          isLoggedIn: true,
        }),

      // 更新资料
      updateProfile: (profile) =>
        set((state) => {
          const current = state.userInfo || {
            id: getOrCreateUserId(),
            nickname: '游客',
            avatar: DEFAULT_AVATAR,
            bio: '',
            visibility: 'public',
          }
          const next = { ...current, ...profile }
          localStorage.setItem('lingjing_user_id', next.id)
          localStorage.setItem('lingjing_nickname', next.nickname)
          return {
            userInfo: next,
            isLoggedIn: state.isLoggedIn,
          }
        }),

      // 退出登录
      logout: () =>
        set({
          userInfo: null,
          isLoggedIn: false,
          badges: [],
        }),

      // 切换长辈模式
      toggleElderlyMode: () => {
        const newMode = !get().elderlyMode
        const fontSizeLevel = newMode ? 'large' : 'normal'
        set({ elderlyMode: newMode, fontSizeLevel, speechRate: newMode ? 0.8 : 1 })
        document.body.dataset.fontSize = fontSizeLevel
        // 切换 body 类名以应用长辈模式样式
        if (newMode) {
          document.body.classList.add('elderly-mode')
        } else {
          document.body.classList.remove('elderly-mode')
        }
      },

      // 设置字体大小
      setFontSizeLevel: (level) => {
        set({ fontSizeLevel: level })
        document.body.dataset.fontSize = level
      },

      setHighContrast: (enabled) => {
        set({ highContrast: enabled })
        document.body.classList.toggle('high-contrast', enabled)
      },

      setSpeechRate: (rate) => set({ speechRate: Math.min(2, Math.max(0.5, rate)) }),

      // 设置当前景点
      setCurrentSpot: (spot) => set({ currentSpot: spot }),

      // 添加徽章
      addBadge: (badge) => {
        const { badges } = get()
        const normalized = normalizeBadgeId(badge)
        const normalizedBadges = badges.map(normalizeBadgeId)
        if (!normalizedBadges.includes(normalized)) {
          set({ badges: [...normalizedBadges, normalized] })
        } else if (normalizedBadges.some((item, index) => item !== badges[index])) {
          set({ badges: normalizedBadges })
        }
      },
    }),
    {
      name: 'lingjing-user-storage', // localStorage 键名
      merge: (persistedState, currentState) => {
        const saved = persistedState as Partial<UserStore>
        return {
          ...currentState,
          ...saved,
          userInfo: saved.userInfo
            ? { ...saved.userInfo, avatar: saved.userInfo.avatar || DEFAULT_AVATAR }
            : currentState.userInfo,
        }
      },
      partialize: (state) => ({
        elderlyMode: state.elderlyMode,
        fontSizeLevel: state.fontSizeLevel,
        highContrast: state.highContrast,
        speechRate: state.speechRate,
        badges: state.badges.map(normalizeBadgeId),
        userInfo: state.userInfo
          ? {
              id: state.userInfo.id || getOrCreateUserId(),
              nickname: state.userInfo.nickname || '游客',
              avatar: state.userInfo.avatar || DEFAULT_AVATAR,
              bio: state.userInfo.bio || '',
              visibility: state.userInfo.visibility || 'public',
              phone: state.userInfo.phone,
            }
          : state.userInfo,
        isLoggedIn: state.isLoggedIn,
      }),
    }
  )
)
