import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * 用户信息接口
 */
export interface UserInfo {
  id: number
  username: string
  nickname: string
  avatar?: string
  role: 'admin' | 'operator'
}

/**
 * 认证状态接口
 */
interface AuthState {
  token: string | null
  userInfo: UserInfo | null
  setToken: (token: string) => void
  setUserInfo: (userInfo: UserInfo) => void
  logout: () => void
}

/**
 * Zustand认证状态管理Store
 * 使用persist中间件实现localStorage持久化
 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      userInfo: null,
      setToken: (token: string) => set({ token }),
      setUserInfo: (userInfo: UserInfo) => set({ userInfo }),
      logout: () => {
        set({ token: null, userInfo: null })
        // 清除所有持久化数据
        localStorage.removeItem('auth-storage')
      },
    }),
    {
      name: 'auth-storage',
    }
  )
)
