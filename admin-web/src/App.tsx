import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuthStore } from './stores/auth'
import MainLayout from './layouts/MainLayout'
import Login from './pages/Login/Login'

const Dashboard = lazy(() => import('./pages/Dashboard/Dashboard'))
const Knowledge = lazy(() => import('./pages/Knowledge/Knowledge'))
const RagTrace = lazy(() => import('./pages/RagTrace/RagTrace'))
const AvatarConfig = lazy(() => import('./pages/AvatarConfig/AvatarConfig'))
const Analytics = lazy(() => import('./pages/Analytics/Analytics'))
const UserManage = lazy(() => import('./pages/UserManage/UserManage'))
const CommunityModeration = lazy(() => import('./pages/CommunityModeration/CommunityModeration'))

function PageLoading() {
  return (
    <div style={{ minHeight: 320, display: 'grid', placeItems: 'center' }}>
      <Spin size="large" />
    </div>
  )
}

/**
 * 路由守卫组件：未登录时重定向到登录页
 */
function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.token)
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

/**
 * 主应用组件：配置全局路由
 */
function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Suspense fallback={<PageLoading />}>
        <Routes>
        {/* 登录页 */}
        <Route path="/login" element={<Login />} />

        {/* 数据大屏：独立全屏页（挂墙展示），不套后台布局 */}
        <Route
          path="/dashboard"
          element={
            <PrivateRoute>
              <Dashboard />
            </PrivateRoute>
          }
        />

        {/* 受保护路由：需要登录 */}
        <Route
          path="/*"
          element={
            <PrivateRoute>
              <MainLayout />
            </PrivateRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="knowledge" element={<Knowledge />} />
          <Route path="rag-trace" element={<RagTrace />} />
          <Route path="avatar" element={<AvatarConfig />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="community" element={<CommunityModeration />} />
          <Route path="users" element={<UserManage />} />
        </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
