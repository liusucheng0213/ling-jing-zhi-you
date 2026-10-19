import { useEffect, useState } from 'react'
import { Layout, Menu, Avatar, Button, ConfigProvider, Dropdown, Grid, theme } from 'antd'
import {
  DashboardOutlined,
  BookOutlined,
  RobotOutlined,
  BarChartOutlined,
  UserOutlined,
  FileSearchOutlined,
  CommentOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'

const { Header, Sider, Content } = Layout

/**
 * 侧边栏菜单配置
 */
const menuItems = [
  {
    key: '/dashboard',
    icon: <DashboardOutlined />,
    label: '数据大屏',
  },
  {
    key: '/knowledge',
    icon: <BookOutlined />,
    label: '知识库管理',
  },
  {
    key: '/rag-trace',
    icon: <FileSearchOutlined />,
    label: 'RAG溯源',
  },
  {
    key: '/avatar',
    icon: <RobotOutlined />,
    label: '数字人配置',
  },
  {
    key: '/analytics',
    icon: <BarChartOutlined />,
    label: '数据分析',
  },
  {
    key: '/community',
    icon: <CommentOutlined />,
    label: '社区管理',
  },
  {
    key: '/users',
    icon: <UserOutlined />,
    label: '用户管理',
  },
]

/**
 * 主布局组件：左侧菜单 + 顶部Header + 内容区
 */
export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const screens = Grid.useBreakpoint()
  const isCompact = screens.lg === false
  const navigate = useNavigate()
  const location = useLocation()
  const { userInfo, logout } = useAuthStore()
  const {
    token: { colorBgContainer },
  } = theme.useToken()

  useEffect(() => {
    if (isCompact) setCollapsed(true)
  }, [isCompact])

  // 用户下拉菜单
  const userMenuItems = [
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
    },
  ]

  const handleUserMenuClick = ({ key }: { key: string }) => {
    if (key === 'logout') {
      logout()
      navigate('/login')
    }
  }

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#2d5a87',
          colorLink: '#2d5a87',
          borderRadius: 10,
        },
        components: {
          Menu: {
            darkItemBg: 'transparent',
            darkSubMenuItemBg: 'transparent',
            darkItemSelectedBg: 'transparent',
          },
        },
      }}
    >
    <Layout style={{ minHeight: '100vh' }}>
      {/* 左侧侧边栏 */}
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        collapsedWidth={isCompact ? 56 : 80}
        theme="dark"
        style={{
          background:
            'radial-gradient(340px 220px at 50% -8%, rgba(90, 135, 171, 0.28), transparent 70%), linear-gradient(180deg, #14304a 0%, #0b1e30 100%)',
          boxShadow: '2px 0 20px rgba(6, 15, 44, 0.45)',
          zIndex: 10,
        }}
      >
        {/* Logo区域 */}
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderBottom: '1px solid rgba(212, 165, 116,0.22)',
            padding: collapsed ? '0 8px' : '0 16px',
          }}
        >
          <img
            src="/assets/logo.png"
            alt="灵境智游"
            style={{
              height: 38,
              width: 'auto',
              marginRight: collapsed ? 0 : 12,
              filter: 'drop-shadow(0 3px 8px rgba(0, 0, 0, 0.35))',
            }}
          />
          {!collapsed && (
            <span
              style={{
                fontSize: 18,
                fontWeight: 600,
                color: '#d5e3ec',
                whiteSpace: 'nowrap',
                letterSpacing: 1,
              }}
            >
              灵境智游
            </span>
          )}
        </div>

        {/* 导航菜单 */}
        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => {
            navigate(key)
            if (isCompact) setCollapsed(true)
          }}
          style={{ borderRight: 0, background: 'transparent', padding: '8px 6px' }}
        />
      </Sider>

      <Layout style={{ minWidth: 0, background: 'transparent' }}>
        {/* 顶部Header */}
        <Header
          style={{
            padding: isCompact ? '0 8px' : '0 24px',
            background: 'rgba(255,255,255,0.82)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid rgba(45, 90, 135,0.08)',
            boxShadow: '0 4px 16px rgba(28, 50, 78, 0.05)',
            zIndex: 9,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
              style={{ fontSize: 16, color: '#666' }}
            />
            {!isCompact && (
              <span style={{ color: '#1e4367', fontSize: 14, fontWeight: 600, marginLeft: 8, letterSpacing: 0.5 }}>
                AI数字人导览管理后台
              </span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {/* 用户信息 */}
            <Dropdown
              menu={{ items: userMenuItems, onClick: handleUserMenuClick }}
              placement="bottomRight"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <Avatar
                  size="small"
                  icon={<UserOutlined />}
                  style={{ backgroundColor: '#2d5a87' }}
                />
                {!isCompact && (
                  <span style={{ color: '#333', fontSize: 14 }}>
                    {userInfo?.nickname || '管理员'}
                  </span>
                )}
              </div>
            </Dropdown>
          </div>
        </Header>

        {/* 内容区域 */}
        <Content
          style={{
            margin: isCompact ? 8 : 24,
            padding: isCompact ? 12 : 24,
            background: colorBgContainer,
            borderRadius: 16,
            border: '1px solid rgba(45, 90, 135,0.08)',
            boxShadow: '0 1px 2px rgba(28, 50, 78,0.04), 0 12px 32px rgba(28, 50, 78,0.07)',
            minHeight: 280,
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
    </ConfigProvider>
  )
}
