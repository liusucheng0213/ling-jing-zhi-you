import { useEffect, useState } from 'react'
import { Button, Card, Input, Space, Switch, Table, Tag, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { api } from '../../api/client'

interface CommunityPost {
  id: string
  title: string
  content: string
  nickname: string
  visibility: string
  is_hidden: boolean
  like_count: number
  comment_count: number
  favorite_count: number
  report_count: number
  reports: Array<{ reason: string; nickname: string; created_at: string }>
  created_at: string
}

interface CommunityListResponse {
  items: CommunityPost[]
  total: number
}

export default function CommunityModeration() {
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [onlyReported, setOnlyReported] = useState(false)
  const [items, setItems] = useState<CommunityPost[]>([])

  const fetchPosts = async () => {
    setLoading(true)
    try {
      const data = await api.get<CommunityListResponse>('/admin/community/posts', {
        params: { keyword: keyword || undefined, only_reported: onlyReported, include_hidden: true },
      })
      setItems(data.items || [])
    } catch {
      message.error('社区内容加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPosts()
  }, [onlyReported])

  const toggleHidden = async (record: CommunityPost) => {
    try {
      const updated = await api.put<CommunityPost>(`/admin/community/posts/${record.id}/visibility`, {
        is_hidden: !record.is_hidden,
        reason: !record.is_hidden ? '运营管理隐藏' : '恢复展示',
      })
      setItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      message.success(updated.is_hidden ? '已隐藏帖子' : '已恢复帖子')
    } catch {
      message.error('操作失败')
    }
  }

  const columns: ColumnsType<CommunityPost> = [
    {
      title: '帖子',
      dataIndex: 'title',
      render: (_, record) => (
        <div>
          <strong>{record.title}</strong>
          <div style={{ color: '#667085', marginTop: 4, maxWidth: 460 }}>{record.content}</div>
        </div>
      ),
    },
    { title: '作者', dataIndex: 'nickname', width: 120 },
    {
      title: '状态',
      width: 150,
      render: (_, record) => (
        <Space direction="vertical" size={4}>
          <Tag color={record.visibility === 'public' ? 'green' : record.visibility === 'followers' ? 'blue' : 'orange'}>
            {record.visibility === 'public' ? '公开' : record.visibility === 'followers' ? '仅关注' : '私密'}
          </Tag>
          {record.is_hidden && <Tag color="red">已隐藏</Tag>}
        </Space>
      ),
    },
    {
      title: '互动',
      width: 190,
      render: (_, record) => (
        <Space wrap>
          <Tag>赞 {record.like_count}</Tag>
          <Tag>评 {record.comment_count}</Tag>
          <Tag>藏 {record.favorite_count}</Tag>
        </Space>
      ),
    },
    {
      title: '举报',
      width: 220,
      render: (_, record) => (
        <div>
          <Tag color={record.report_count > 0 ? 'red' : 'default'}>{record.report_count}</Tag>
          <div style={{ marginTop: 6, color: '#667085' }}>
            {record.reports?.[record.reports.length - 1]?.reason || '无举报'}
          </div>
        </div>
      ),
    },
    {
      title: '操作',
      width: 120,
      render: (_, record) => (
        <Button danger={!record.is_hidden} onClick={() => toggleHidden(record)}>
          {record.is_hidden ? '恢复' : '隐藏'}
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Card
        title="社区内容管理"
        extra={
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="搜索标题、正文或作者"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onSearch={fetchPosts}
              style={{ width: 240 }}
            />
            <Space size={4}>
              <span style={{ color: '#667085', fontSize: 13 }}>只看举报</span>
              <Switch checked={onlyReported} onChange={setOnlyReported} />
            </Space>
            <Button icon={<ReloadOutlined />} onClick={fetchPosts}>刷新</Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  )
}
