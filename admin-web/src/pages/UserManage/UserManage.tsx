import { useEffect, useState } from 'react'
import { Table, Card, Input, Button, Tag, Space, Modal, Descriptions, Avatar, Select } from 'antd'
import { SearchOutlined, EyeOutlined } from '@ant-design/icons'
import { api } from '../../api/client'

interface UserItem {
  id: string
  nickname: string
  avatar?: string
  phone?: string
  status: 'active' | 'inactive'
  created_at: string
  last_active: string
  total_sessions: number
  total_qa: number
  visit_count: number
  age_group?: string
  tags: string[]
  is_sample: boolean
}

interface UserListResponse {
  items: UserItem[]
  total: number
  page: number
  page_size: number
}

const formatDateTime = (value?: string) => (
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无记录'
)

export default function UserManage() {
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [selectedUser, setSelectedUser] = useState<UserItem | null>(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      setLoading(true)
      try {
        const data = await api.get<UserListResponse>('/admin/users', {
          params: { q: searchText.trim() || undefined, status: statusFilter, page, page_size: 10 },
        })
        setUsers(data.items)
        setTotal(data.total)
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [page, searchText, statusFilter])

  const columns = [
    {
      title: '用户',
      dataIndex: 'nickname',
      key: 'nickname',
      render: (_: string, record: UserItem) => (
        <Space>
          <Avatar style={{ background: '#2d5a87' }}>{record.nickname.charAt(0)}</Avatar>
          <span>{record.nickname}</span>
          {record.is_sample && <Tag color="blue">演示样本</Tag>}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={status === 'active' ? 'success' : 'default'}>
          {status === 'active' ? '活跃' : '离线'}
        </Tag>
      ),
    },
    {
      title: '对话次数',
      dataIndex: 'total_sessions',
      key: 'total_sessions',
    },
    {
      title: '问答数',
      dataIndex: 'total_qa',
      key: 'total_qa',
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      render: (tags: string[]) => (
        <Space wrap>
          {tags.map((tag) => (
            <Tag key={tag}>{tag}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: UserItem) => (
        <Button
          type="link"
          icon={<EyeOutlined />}
          onClick={() => {
            setSelectedUser(record)
            setDetailVisible(true)
          }}
        >
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Card title="用户管理">
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder="搜索用户昵称/ID"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value)
              setPage(1)
            }}
            style={{ width: 240 }}
            allowClear
          />
          <Select
            value={statusFilter}
            onChange={(value) => {
              setStatusFilter(value)
              setPage(1)
            }}
            style={{ width: 120 }}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '活跃', value: 'active' },
              { label: '离线', value: 'inactive' },
            ]}
          />
        </Space>

        <Table
          columns={columns}
          dataSource={users}
          rowKey="id"
          loading={loading}
          locale={{ emptyText: '没有符合条件的用户记录' }}
          pagination={{ current: page, pageSize: 10, total, showTotal: (value) => `共 ${value} 位用户` }}
          onChange={(pagination) => setPage(pagination.current || 1)}
          scroll={{ x: 720 }}
        />
      </Card>

      <Modal
        title="用户详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={600}
      >
        {selectedUser && (
          <Descriptions column={2} bordered>
            <Descriptions.Item label="用户ID">{selectedUser.id}</Descriptions.Item>
            <Descriptions.Item label="昵称">{selectedUser.nickname}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={selectedUser.status === 'active' ? 'success' : 'default'}>
                {selectedUser.status === 'active' ? '活跃' : '离线'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="手机号">{selectedUser.phone || '未绑定'}</Descriptions.Item>
            <Descriptions.Item label="年龄段">{selectedUser.age_group || '未填写'}</Descriptions.Item>
            <Descriptions.Item label="注册时间">{formatDateTime(selectedUser.created_at)}</Descriptions.Item>
            <Descriptions.Item label="最后活跃">{formatDateTime(selectedUser.last_active)}</Descriptions.Item>
            <Descriptions.Item label="对话次数">{selectedUser.total_sessions}</Descriptions.Item>
            <Descriptions.Item label="问答数">{selectedUser.total_qa}</Descriptions.Item>
            <Descriptions.Item label="到访次数">{selectedUser.visit_count}</Descriptions.Item>
            <Descriptions.Item label="标签">
              {selectedUser.tags.map((t) => (
                <Tag key={t}>{t}</Tag>
              ))}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}
