import { useState } from 'react'
import { Form, Input, Button, Card, ConfigProvider, message, Spin } from 'antd'
import { UserOutlined, LockOutlined, SafetyCertificateOutlined, DashboardOutlined, DatabaseOutlined, RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/client'
import './Login.css'

type LoginResponse = {
  token: string
  user: {
    id: number
    username: string
    nickname: string
    role: 'admin' | 'operator'
  }
}

export default function Login() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { setToken, setUserInfo } = useAuthStore()

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const result = await api.post<LoginResponse>('/admin/auth/login', values)
      setToken(result.token)
      setUserInfo(result.user)
      message.success('登录成功')
      navigate('/dashboard')
    } catch {
      message.error('登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <section className="login-visual">
        <div className="login-seal">灵山胜境</div>
        <div className="login-brand">
          <span>灵境智游</span>
          <strong>AI 数字人智慧景区运营平台</strong>
          <p>面向 5A 文化景区的实时导览、知识库、服务质量与游客感受度管理。</p>
        </div>
        <div className="login-metrics">
          <div>
            <DashboardOutlined />
            <strong>实时运营</strong>
            <span>客流、问答、满意度</span>
          </div>
          <div>
            <DatabaseOutlined />
            <strong>RAG 知识库</strong>
            <span>文档导入与溯源</span>
          </div>
          <div>
            <RobotOutlined />
            <strong>讯飞数字人</strong>
            <span>形象、音色、动作编排</span>
          </div>
        </div>
      </section>

      <Spin spinning={loading}>
        <ConfigProvider theme={{ token: { colorPrimary: '#2d5a87' } }}>
        <Card className="login-card" styles={{ body: { padding: '38px 34px' } }}>
          <div className="login-card-head">
            <div className="login-logo">
              <SafetyCertificateOutlined />
            </div>
            <h1>管理后台登录</h1>
            <p>使用管理员账号进入运营控制台</p>
          </div>

          <Form
            name="login"
            onFinish={handleLogin}
            autoComplete="off"
            size="large"
          >
            <Form.Item
              name="username"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder="管理员用户名"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="管理员密码"
              />
            </Form.Item>

            <Form.Item className="login-submit">
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={loading}
              >
                登录运营平台
              </Button>
            </Form.Item>
          </Form>
        </Card>
        </ConfigProvider>
      </Spin>
    </div>
  )
}
