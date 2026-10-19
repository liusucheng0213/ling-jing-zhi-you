import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, List, message, Rate, Row, Segmented, Space, Statistic, Table, Tag, Typography } from 'antd'
import {
  BulbOutlined,
  CalendarOutlined,
  DownloadOutlined,
  FileWordOutlined,
  FrownOutlined,
  MessageOutlined,
  SaveOutlined,
  SmileOutlined,
  StarOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { api } from '@/api/client'

const { Title, Text, Paragraph } = Typography

type DailyItem = {
  date: string
  total_visitors: number
  satisfaction: number | null
  positive_rate: number
  negative_rate: number
  top_concern: string
  avg_session_time: number
}

type ConcernItem = {
  topic: string
  mention_count: number
  sentiment: 'positive' | 'neutral' | 'negative'
  trend: 'up' | 'down' | 'stable'
}

type AnalyticsSummary = {
  is_sample: boolean
  overview: {
    total_visitors: number
    avg_satisfaction: number | null
    positive_rate: number
    negative_rate: number
    total_qa: number
    feedback_count: number
    has_feedback: boolean
  }
  daily: DailyItem[]
  concerns: ConcernItem[]
  feedback: {
    summary: string
    low_rating_count: number
    rating_distribution: Record<string, number>
    recent_low_feedback: Array<{ created_at?: string; rating: number; feedback_text?: string; tags?: string[] }>
  }
  suggestions: string[]
}

type MonthlyReportArchive = {
  id: string
  label: string
  period_days: number
  period_start: string
  period_end: string
  generated_at: string
  generated_by?: string
  archive_mode?: 'automatic' | 'manual'
  is_sample: boolean
  total_qa: number
  feedback_count: number
  avg_satisfaction: number | null
}

const emptySummary: AnalyticsSummary = {
  is_sample: false,
  overview: {
    total_visitors: 0,
    avg_satisfaction: null,
    positive_rate: 0,
    negative_rate: 0,
    total_qa: 0,
    feedback_count: 0,
    has_feedback: false,
  },
  daily: [],
  concerns: [],
  feedback: {
    summary: '暂无真实反馈数据。',
    low_rating_count: 0,
    rating_distribution: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
    recent_low_feedback: [],
  },
  suggestions: [],
}

const sentimentConfig = {
  positive: { color: 'success', icon: <SmileOutlined />, text: '正面' },
  neutral: { color: 'default', icon: null, text: '中性' },
  negative: { color: 'error', icon: <FrownOutlined />, text: '负面' },
}

export default function Analytics() {
  const [data, setData] = useState<AnalyticsSummary>(emptySummary)
  const [periodDays, setPeriodDays] = useState<7 | 30>(7)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const [archiveDownloadingId, setArchiveDownloadingId] = useState('')
  const [monthlyReports, setMonthlyReports] = useState<MonthlyReportArchive[]>([])
  const [loadError, setLoadError] = useState('')

  const loadData = useCallback(async (days: 7 | 30) => {
    setLoading(true)
    try {
      const response = await api.get<AnalyticsSummary>(`/admin/analytics/summary?days=${days}`)
      setData(response)
      setLoadError('')
    } catch (error) {
      console.error('加载分析数据失败:', error)
      setData(emptySummary)
      setLoadError('分析接口不可用，当前只显示空态数据。')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadMonthlyReports = useCallback(async () => {
    try {
      const response = await api.get<{ items: MonthlyReportArchive[] }>('/admin/analytics/monthly-reports?limit=12')
      setMonthlyReports(response.items || [])
    } catch (error) {
      console.error('读取月报归档失败:', error)
    }
  }, [])

  useEffect(() => {
    loadData(periodDays)
  }, [loadData, periodDays])

  useEffect(() => {
    loadMonthlyReports()
  }, [loadMonthlyReports])

  const exportReport = async () => {
    setExporting(true)
    try {
      const blob = await api.get<Blob>(`/admin/analytics/report.pdf?days=${periodDays}`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `灵境智游游客感受度报告-${periodDays}天-${new Date().toISOString().slice(0, 10)}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      message.success('报告已导出')
    } catch (error) {
      console.error('导出游客感受度报告失败:', error)
      message.error('报告导出失败')
    } finally {
      setExporting(false)
    }
  }

  const archiveMonthlyReport = async () => {
    setArchiving(true)
    try {
      const report = await api.post<MonthlyReportArchive>('/admin/analytics/monthly-reports', {})
      setMonthlyReports((current) => [report, ...current.filter((item) => item.id !== report.id)].slice(0, 12))
      message.success('近30天月报快照已归档')
    } catch (error) {
      console.error('归档月报失败:', error)
      message.error('月报归档失败')
    } finally {
      setArchiving(false)
    }
  }

  const downloadArchivedReport = async (report: MonthlyReportArchive) => {
    setArchiveDownloadingId(report.id)
    try {
      const blob = await api.get<Blob>(`/admin/analytics/monthly-reports/${report.id}/report.docx`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `灵境智游运营月报-${report.period_end}.docx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      message.success('归档月报已导出')
    } catch (error) {
      console.error('导出归档月报失败:', error)
      message.error('归档月报导出失败')
    } finally {
      setArchiveDownloadingId('')
    }
  }

  const trendOption: EChartsOption = useMemo(() => ({
    tooltip: { trigger: 'axis' },
    legend: { data: ['满意度', '正面率', '负面率'], top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '16%', containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.daily.map((item) => item.date.slice(5)),
    },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: '满意度',
        type: 'line',
        smooth: true,
        data: data.daily.map((item) => {
          const score = item.satisfaction ?? data.overview.avg_satisfaction
          return score == null ? null : Math.round(score * 20)
        }),
        lineStyle: { color: '#2d5a87', width: 3 },
      },
      {
        name: '正面率',
        type: 'line',
        smooth: true,
        data: data.daily.map((item) => item.positive_rate),
        lineStyle: { color: '#4e7fa6', width: 2 },
      },
      {
        name: '负面率',
        type: 'line',
        smooth: true,
        data: data.daily.map((item) => item.negative_rate),
        lineStyle: { color: '#d4a574', width: 2 },
      },
    ],
  }), [data])

  const concernOption: EChartsOption = useMemo(() => ({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '3%', containLabel: true },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: data.concerns.map((item) => item.topic).reverse(),
    },
    series: [{
      type: 'bar',
      data: data.concerns.map((item) => ({
        value: item.mention_count,
        itemStyle: {
          color: item.sentiment === 'positive' ? '#2d5a87' : item.sentiment === 'negative' ? '#d4a574' : '#8aacc6',
        },
      })).reverse(),
      barWidth: '60%',
      label: { show: true, position: 'right' },
    }],
  }), [data])

  const dailyColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 120 },
    { title: '服务/问答', dataIndex: 'total_visitors', key: 'total_visitors', width: 100 },
    {
      title: '平均时长',
      dataIndex: 'avg_session_time',
      key: 'avg_session_time',
      width: 100,
      render: (minutes: number) => minutes ? `${minutes} 分钟` : <Text type="secondary">暂无</Text>,
    },
    {
      title: '满意度',
      dataIndex: 'satisfaction',
      key: 'satisfaction',
      width: 140,
      render: (score: number | null) => {
        const value = score ?? data.overview.avg_satisfaction
        return value == null
          ? <Text type="secondary">暂无评价</Text>
          : <Rate disabled value={value} allowHalf style={{ fontSize: 14 }} />
      },
    },
    { title: '正面率', dataIndex: 'positive_rate', key: 'positive_rate', width: 90, render: (rate: number) => <Tag color="success">{rate}%</Tag> },
    { title: '负面率', dataIndex: 'negative_rate', key: 'negative_rate', width: 90, render: (rate: number) => <Tag color={rate > 10 ? 'error' : 'warning'}>{rate}%</Tag> },
    { title: '主要关注点', dataIndex: 'top_concern', key: 'top_concern', width: 120 },
  ]

  const concernColumns = [
    { title: '话题', dataIndex: 'topic', key: 'topic', render: (text: string) => <Text strong>{text}</Text> },
    { title: '提及次数', dataIndex: 'mention_count', key: 'mention_count', sorter: (a: ConcernItem, b: ConcernItem) => a.mention_count - b.mention_count },
    {
      title: '情感倾向',
      dataIndex: 'sentiment',
      key: 'sentiment',
      render: (value: keyof typeof sentimentConfig) => {
        const config = sentimentConfig[value] || sentimentConfig.neutral
        return <Tag color={config.color} icon={config.icon}>{config.text}</Tag>
      },
    },
    { title: '趋势', dataIndex: 'trend', key: 'trend', render: (value: string) => <Tag>{value === 'up' ? '上升' : value === 'down' ? '下降' : '平稳'}</Tag> },
  ]

  const monthlyReportColumns = [
    {
      title: '归档周期',
      dataIndex: 'label',
      key: 'label',
      width: 260,
      render: (label: string, record: MonthlyReportArchive) => (
        <Space>
          <Text strong>{label}</Text>
          <Tag color={record.archive_mode === 'automatic' ? 'green' : 'blue'}>
            {record.archive_mode === 'automatic' ? '自动' : '手动'}
          </Tag>
          {record.is_sample && <Tag color="orange">样例</Tag>}
        </Space>
      ),
    },
    { title: '问答量', dataIndex: 'total_qa', key: 'total_qa', width: 90 },
    { title: '反馈数', dataIndex: 'feedback_count', key: 'feedback_count', width: 90 },
    {
      title: '满意度',
      dataIndex: 'avg_satisfaction',
      key: 'avg_satisfaction',
      width: 100,
      render: (value: number | null) => value == null ? <Text type="secondary">暂无</Text> : `${value} / 5`,
    },
    {
      title: '归档时间',
      dataIndex: 'generated_at',
      key: 'generated_at',
      width: 180,
      render: (value: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: MonthlyReportArchive) => (
        <Button
          type="link"
          icon={<FileWordOutlined />}
          loading={archiveDownloadingId === record.id}
          onClick={() => downloadArchivedReport(record)}
        >
          导出DOCX
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Space align="center" wrap style={{ width: '100%', justifyContent: 'space-between', marginBottom: 20 }}>
        <Title level={3} style={{ margin: 0 }}>数据分析</Title>
        <Space wrap>
          <Segmented
            value={periodDays}
            onChange={(value) => setPeriodDays(Number(value) as 7 | 30)}
            options={[
              { label: '近7天', value: 7 },
              { label: '近30天月报', value: 30, icon: <CalendarOutlined /> },
            ]}
          />
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={exportReport}>
            导出PDF报告
          </Button>
          {periodDays === 30 && (
            <Button type="primary" icon={<SaveOutlined />} loading={archiving} onClick={archiveMonthlyReport}>
              归档本期月报
            </Button>
          )}
        </Space>
      </Space>

      {loadError && (
        <Alert
          type="error"
          showIcon
          message={loadError}
          style={{ marginBottom: 16 }}
        />
      )}

      {data.is_sample && (
        <Alert
          type="warning"
          showIcon
          message="当前为演示样例数据，不作为真实运营指标。"
          style={{ marginBottom: 16 }}
        />
      )}

      {periodDays === 30 && (
        <Card
          title="近30天月报归档"
          style={{ marginBottom: 20 }}
          extra={<Tag color="green">每6小时自动归档</Tag>}
        >
          <Table
            size="small"
            rowKey="id"
            columns={monthlyReportColumns}
            dataSource={monthlyReports}
            pagination={false}
            locale={{ emptyText: '暂无已归档月报' }}
            scroll={{ x: 860 }}
          />
        </Card>
      )}

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}><Statistic title="总服务/问答" value={data.overview.total_visitors} prefix={<TeamOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic
              title="平均满意度"
              value={data.overview.has_feedback ? data.overview.avg_satisfaction ?? 0 : '暂无'}
              precision={data.overview.has_feedback ? 1 : undefined}
              suffix={data.overview.has_feedback ? '/ 5.0' : undefined}
              prefix={<StarOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}><Statistic title="正面评价率" value={data.overview.positive_rate} suffix="%" prefix={<SmileOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}><Statistic title="反馈数" value={data.overview.feedback_count} prefix={<MessageOutlined />} /></Card>
        </Col>
      </Row>

      {!loading && !data.overview.has_feedback && (
        <Alert
          type="info"
          showIcon
          message="当前周期尚未收集到满意度评价，问答量与关注点仍来自真实会话；满意度不以 0 分代替。"
          style={{ marginBottom: 16 }}
        />
      )}

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={16}>
          <Card title="情感与满意度趋势" loading={loading}>
            <ReactECharts option={trendOption} style={{ height: 320 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="游客反馈总结" loading={loading}>
            <Paragraph>{data.feedback.summary}</Paragraph>
            <Tag color={data.feedback.low_rating_count > 0 ? 'red' : 'green'}>
              低分反馈 {data.feedback.low_rating_count}
            </Tag>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="游客关注点分析" loading={loading}>
            <ReactECharts option={concernOption} style={{ height: 360 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="服务建议" loading={loading}>
            <List
              dataSource={data.suggestions}
              renderItem={(item) => (
                <List.Item>
                  <Space align="start">
                    <BulbOutlined style={{ color: '#d4a574', marginTop: 4 }} />
                    <Text>{item}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title={periodDays === 30 ? '近30天每日明细' : '游客感受度日报'} loading={loading}>
            <Table columns={dailyColumns} dataSource={data.daily} rowKey="date" pagination={false} size="small" scroll={{ x: 760 }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="关注点详细数据" loading={loading}>
            <Table columns={concernColumns} dataSource={data.concerns} rowKey="topic" pagination={{ pageSize: 8 }} size="small" />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
