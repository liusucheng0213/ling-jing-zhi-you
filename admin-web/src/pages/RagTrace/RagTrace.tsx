import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Progress,
  Row,
  Segmented,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'

const { Title, Text, Paragraph } = Typography

type RagSource = {
  rank?: number
  document_id?: string
  chunk_id?: string
  title?: string
  doc_title?: string
  doc_type?: string
  chunk_index?: number
  score?: number
  vector_score?: number
  text_score?: number
  snippet?: string
  content?: string
  mode?: string
  cache_hit?: boolean
  fast_reply?: boolean
  rag_ms?: number
}

type RagTrace = {
  timings?: Record<string, number>
  rag?: Record<string, unknown>
  fast_reply?: boolean
  digital_human_ms?: number | null
}

type ImprovementResult = 'draft' | 'ready_to_retest' | 'improved' | 'hit_without_gain' | 'not_hit'

type ImprovementSummary = {
  document_id: string
  document_status: 'draft' | 'published' | 'archived'
  retest_count: number
  last_retested_at?: string | null
  result: ImprovementResult
}

type RagSnapshot = {
  answer: string
  confidence?: number | null
  mode?: string | null
  source_count: number
  rag_ms?: number | null
  total_ms?: number | null
  fast_reply: boolean
  sources: RagSource[]
}

type ImprovementDetail = {
  message_id: string
  document_id: string
  document_status: 'draft' | 'published' | 'archived'
  question: string
  retrieval_query: string
  before: RagSnapshot
  after?: RagSnapshot | null
  confidence_delta?: number | null
  source_count_delta: number
  new_document_hit: boolean
  improved: boolean
  result: ImprovementResult
  retest_count: number
  last_retested_at?: string | null
}

type RagTraceItem = {
  id: string
  session_id?: string | null
  created_at: string
  question?: string | null
  answer: string
  latency_ms?: number | null
  rag_ms?: number | null
  mode?: string | null
  confidence?: number | null
  low_confidence: boolean
  no_hit: boolean
  fast_reply: boolean
  source_count: number
  sources: RagSource[]
  trace: RagTrace
  improvable: boolean
  improvement?: ImprovementSummary | null
}

type ListResponse = {
  items: RagTraceItem[]
  total: number
}

type StatsResponse = {
  total: number
  success_count: number
  no_hit_count: number
  low_confidence_count: number
  avg_latency_ms?: number | null
  avg_rag_ms?: number | null
  fast_reply_count: number
}

const VIEW_OPTIONS = [
  { label: '最近命中', value: 'recent' },
  { label: '低置信/无命中', value: 'low' },
  { label: '慢查询', value: 'slow' },
]

const endpointByView: Record<string, string> = {
  recent: '/admin/rag-trace/recent?limit=50&days=90',
  low: '/admin/rag-trace/low-confidence?limit=50&days=90',
  slow: '/admin/rag-trace/slow?limit=50&days=90',
}

const formatMs = (value?: number | null) => {
  if (value === undefined || value === null) return '-'
  return `${Math.round(value)}ms`
}

const formatScore = (value?: number | null) => {
  if (value === undefined || value === null) return '-'
  return value.toFixed(3)
}

const formatDelta = (value?: number | null, digits = 3) => {
  if (value === undefined || value === null) return '-'
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

const modeTag = (mode?: string | null) => {
  if (!mode) return <Tag>unknown</Tag>
  const color = mode.includes('hybrid') ? 'blue' : mode.includes('lexical') ? 'green' : mode.includes('vector') ? 'purple' : 'default'
  return <Tag color={color}>{mode}</Tag>
}

const improvementTag = (summary?: ImprovementSummary | null) => {
  if (!summary) return <Tag>未处理</Tag>
  const map: Record<ImprovementResult, { text: string; color: string }> = {
    draft: { text: '知识草稿', color: 'default' },
    ready_to_retest: { text: '待复测', color: 'processing' },
    improved: { text: '已改善', color: 'success' },
    hit_without_gain: { text: '已命中', color: 'cyan' },
    not_hit: { text: '需继续优化', color: 'warning' },
  }
  const current = map[summary.result]
  return <Tag color={current.color}>{current.text}</Tag>
}

function SnapshotPanel({ title, snapshot, accent }: { title: string; snapshot: RagSnapshot; accent: string }) {
  return (
    <Card
      title={title}
      size="small"
      styles={{ header: { borderTop: `3px solid ${accent}` } }}
      style={{ height: '100%' }}
    >
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col span={8}><Statistic title="置信度" value={formatScore(snapshot.confidence)} /></Col>
        <Col span={8}><Statistic title="知识来源" value={snapshot.source_count} suffix="条" /></Col>
        <Col span={8}><Statistic title="总耗时" value={formatMs(snapshot.total_ms)} /></Col>
      </Row>
      <Space wrap style={{ marginBottom: 12 }}>
        {modeTag(snapshot.mode)}
        <Tag>RAG {formatMs(snapshot.rag_ms)}</Tag>
        {snapshot.fast_reply && <Tag color="green">快答</Tag>}
      </Space>
      <Paragraph style={{ minHeight: 88, whiteSpace: 'pre-wrap' }}>{snapshot.answer}</Paragraph>
      <Table
        rowKey={(source) => source.chunk_id || source.document_id || `${title}-${source.rank}`}
        size="small"
        pagination={false}
        dataSource={snapshot.sources || []}
        locale={{ emptyText: '无知识来源' }}
        columns={[
          { title: '来源', ellipsis: true, render: (_, source) => source.doc_title || source.title || '-' },
          { title: '分值', dataIndex: 'score', width: 76, render: formatScore },
        ]}
      />
    </Card>
  )
}

export default function RagTrace() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [view, setView] = useState<string>('recent')
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<RagTraceItem[]>([])
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [comparisonOpen, setComparisonOpen] = useState(false)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparison, setComparison] = useState<ImprovementDetail | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [listResponse, statsResponse] = await Promise.all([
        api.get<ListResponse>(endpointByView[view]),
        api.get<StatsResponse>('/admin/rag-trace/stats?days=90'),
      ])
      setItems(listResponse.items || [])
      setStats(statsResponse)
    } catch (err) {
      console.error('加载RAG溯源失败:', err)
      setError('RAG溯源数据加载失败，请确认后端服务和管理员登录态正常。')
    } finally {
      setLoading(false)
    }
  }, [view])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const openComparison = useCallback(async (messageId: string, documentId: string) => {
    setComparisonOpen(true)
    setComparisonLoading(true)
    try {
      const result = await api.get<ImprovementDetail>(
        `/admin/rag-trace/${messageId}/improvement?document_id=${encodeURIComponent(documentId)}`,
      )
      setComparison(result)
    } catch {
      message.error('读取知识改进对比失败')
      setComparisonOpen(false)
    } finally {
      setComparisonLoading(false)
    }
  }, [])

  useEffect(() => {
    const messageId = searchParams.get('case')
    const documentId = searchParams.get('document')
    if (messageId && documentId) {
      void openComparison(messageId, documentId)
    }
  }, [openComparison, searchParams])

  const closeComparison = () => {
    setComparisonOpen(false)
    const next = new URLSearchParams(searchParams)
    next.delete('case')
    next.delete('document')
    setSearchParams(next, { replace: true })
  }

  const runRetest = async (messageId: string, documentId: string) => {
    setActionLoading(messageId)
    try {
      const result = await api.post<ImprovementDetail>(`/admin/rag-trace/${messageId}/retest`, {
        document_id: documentId,
      })
      setComparison(result)
      setComparisonOpen(true)
      message.success(result.new_document_hit ? '复测完成，新知识已进入回答来源' : '复测完成，请查看对比结果')
      await loadData()
    } catch (err) {
      const detail = (err as { message?: string }).message
      message.error(detail || '原问题复测失败')
    } finally {
      setActionLoading(null)
    }
  }

  const handleImprovementAction = async (record: RagTraceItem) => {
    const summary = record.improvement
    if (summary?.result === 'draft') {
      navigate(`/knowledge?edit=${summary.document_id}&trace=${record.id}`)
      return
    }
    if (summary?.result === 'ready_to_retest' || summary?.result === 'not_hit') {
      await runRetest(record.id, summary.document_id)
      return
    }
    if (summary) {
      await openComparison(record.id, summary.document_id)
      return
    }

    setActionLoading(record.id)
    try {
      const created = await api.post<{ id: string }>(`/admin/rag-trace/${record.id}/draft-knowledge`, {
        title: record.question ? `待补问答：${record.question.slice(0, 32)}` : undefined,
        doc_type: '待补充问答',
      })
      message.success('知识草稿已创建，请补充标准答案')
      navigate(`/knowledge?edit=${created.id}&trace=${record.id}`)
    } catch (err) {
      const detail = (err as { message?: string }).message
      message.error(detail || '创建知识草稿失败')
    } finally {
      setActionLoading(null)
    }
  }

  const hitRate = useMemo(() => {
    if (!stats?.total) return 0
    return Math.round((stats.success_count / stats.total) * 100)
  }, [stats])

  const columns: ColumnsType<RagTraceItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '问题',
      dataIndex: 'question',
      ellipsis: true,
      render: (value?: string) => value || <Text type="secondary">未找到上一轮问题</Text>,
    },
    {
      title: '检索模式',
      dataIndex: 'mode',
      width: 130,
      render: modeTag,
    },
    {
      title: '来源',
      dataIndex: 'source_count',
      width: 120,
      render: (value: number, record) => (
        <Space size={4} wrap>
          <Text>{value}</Text>
          {record.no_hit && <Tag color="red">无命中</Tag>}
          {record.fast_reply && <Tag color="green">快答</Tag>}
        </Space>
      ),
    },
    {
      title: '回答置信度',
      dataIndex: 'confidence',
      width: 120,
      render: (value: number | null | undefined, record) => (
        <Tag color={record.low_confidence ? 'orange' : 'blue'}>{formatScore(value)}</Tag>
      ),
    },
    {
      title: '改进状态',
      key: 'improvement',
      width: 120,
      render: (_, record) => improvementTag(record.improvement),
    },
    {
      title: 'RAG耗时',
      dataIndex: 'rag_ms',
      width: 100,
      render: formatMs,
    },
    {
      title: '总耗时',
      dataIndex: 'latency_ms',
      width: 100,
      render: formatMs,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right',
      render: (_, record) => {
        const summary = record.improvement
        const config = !summary
          ? { label: '转知识草稿', icon: <PlusOutlined /> }
          : summary.result === 'draft'
            ? { label: '继续编辑', icon: <EditOutlined /> }
            : summary.result === 'ready_to_retest' || summary.result === 'not_hit'
              ? { label: '复测原问题', icon: <ExperimentOutlined /> }
              : { label: '查看对比', icon: <EyeOutlined /> }
        const needsImprovement = record.low_confidence || record.no_hit
        const disabled = !summary && (!needsImprovement || !record.improvable)
        const disabledLabel = needsImprovement ? '不适用' : '无需补充'
        const disabledReason = needsImprovement
          ? '图片观察等问题不能通过文本知识补全'
          : '当前回答置信度正常'
        return (
          <Tooltip title={disabled ? disabledReason : undefined}>
            <Button
              size="small"
              type={summary?.result === 'ready_to_retest' ? 'primary' : 'default'}
              icon={config.icon}
              disabled={disabled}
              loading={actionLoading === record.id}
              onClick={() => void handleImprovementAction(record)}
            >
              {disabled ? disabledLabel : config.label}
            </Button>
          </Tooltip>
        )
      },
    },
  ]

  const comparisonAlert = comparison?.result === 'improved'
    ? { type: 'success' as const, text: '复测通过：新发布知识已命中，回答置信度得到提升。' }
    : comparison?.result === 'hit_without_gain'
      ? { type: 'info' as const, text: '新发布知识已进入回答来源，置信度暂未提升，可继续调整内容。' }
      : comparison?.result === 'not_hit'
        ? { type: 'warning' as const, text: '本次复测尚未命中新文档，建议调整标题、景点关联或标准答案措辞。' }
        : comparison?.result === 'ready_to_retest'
          ? { type: 'info' as const, text: '知识已发布，可以立即用原问题执行真实问答复测。' }
          : { type: 'warning' as const, text: '知识仍是草稿，请先完成编辑和发布。' }

  return (
    <div>
      <Space align="center" style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>RAG 可信溯源</Title>
        <Button icon={<ReloadOutlined />} onClick={() => void loadData()} loading={loading}>刷新</Button>
      </Space>

      {error && <Alert type="warning" message={error} showIcon style={{ marginBottom: 16 }} />}

      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: '16px 20px' } }} loading={loading && !stats}>
        <Row gutter={[16, 12]} align="middle">
          <Col xs={24} lg={8}>
            <Text strong>命中率</Text>
            <Progress percent={hitRate} status={hitRate >= 70 ? 'active' : 'exception'} />
          </Col>
          <Col xs={12} lg={4}><Statistic title="追踪记录" value={stats?.total || 0} /></Col>
          <Col xs={12} lg={4}><Statistic title="低置信（低于 0.65）" value={stats?.low_confidence_count || 0} /></Col>
          <Col xs={12} lg={4}><Statistic title="无命中" value={stats?.no_hit_count || 0} /></Col>
          <Col xs={12} lg={4}><Statistic title="平均总耗时 / RAG" value={`${formatMs(stats?.avg_latency_ms)} / ${formatMs(stats?.avg_rag_ms)}`} valueStyle={{ fontSize: 20 }} /></Col>
        </Row>
      </Card>

      <Space style={{ marginBottom: 16 }}>
        <Segmented options={VIEW_OPTIONS} value={view} onChange={(value) => setView(String(value))} />
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1320 }}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: <Empty description="暂无RAG溯源记录" /> }}
        expandable={{
          expandedRowRender: (record) => (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
                <Descriptions.Item label="Session">{record.session_id || '-'}</Descriptions.Item>
                <Descriptions.Item label="数字人耗时">{formatMs(record.trace?.digital_human_ms)}</Descriptions.Item>
                <Descriptions.Item label="缓存命中">{record.trace?.rag?.cache_hit ? '是' : '否'}</Descriptions.Item>
              </Descriptions>
              <Paragraph style={{ marginBottom: 0 }}><Text strong>回答：</Text>{record.answer}</Paragraph>
              <Table
                rowKey={(source) => source.chunk_id || `${record.id}-${source.rank}`}
                size="small"
                pagination={false}
                dataSource={record.sources || []}
                scroll={{ x: 850 }}
                columns={[
                  { title: 'Rank', dataIndex: 'rank', width: 70 },
                  { title: '标题', width: 180, render: (_, source) => source.doc_title || source.title || '-' },
                  { title: '类型', dataIndex: 'doc_type', width: 100, render: (value) => value || '-' },
                  { title: '综合分', dataIndex: 'score', width: 90, render: formatScore },
                  { title: '向量分', dataIndex: 'vector_score', width: 90, render: formatScore },
                  { title: '词面分', dataIndex: 'text_score', width: 90, render: formatScore },
                  { title: '片段摘要', ellipsis: true, render: (_, source) => source.content || source.snippet || '-' },
                ]}
              />
            </Space>
          ),
        }}
      />

      <Drawer
        title="知识改进前后对比"
        open={comparisonOpen}
        onClose={closeComparison}
        width="min(980px, calc(100vw - 24px))"
        loading={comparisonLoading}
        extra={comparison?.document_status === 'published' && (
          <Button
            icon={<ExperimentOutlined />}
            loading={actionLoading === comparison.message_id}
            onClick={() => void runRetest(comparison.message_id, comparison.document_id)}
          >
            重新复测
          </Button>
        )}
      >
        {comparison && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Alert showIcon type={comparisonAlert.type} message={comparisonAlert.text} />
            <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
              <Descriptions.Item label="游客原问题">{comparison.question}</Descriptions.Item>
              <Descriptions.Item label="实际复测问题">{comparison.retrieval_query}</Descriptions.Item>
              <Descriptions.Item label="新知识命中">
                <Tag color={comparison.new_document_hit ? 'green' : 'orange'}>{comparison.new_document_hit ? '是' : '否'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="复测次数">{comparison.retest_count}</Descriptions.Item>
              <Descriptions.Item label="置信度变化">{formatDelta(comparison.confidence_delta)}</Descriptions.Item>
              <Descriptions.Item label="来源数变化">
                {comparison.source_count_delta > 0 ? '+' : ''}{comparison.source_count_delta}
              </Descriptions.Item>
            </Descriptions>
            {comparison.after ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
                <SnapshotPanel title="改进前" snapshot={comparison.before} accent="#d4a574" />
                <SnapshotPanel title="改进后" snapshot={comparison.after} accent="#2d5a87" />
              </div>
            ) : (
              <Card><Empty description="尚未执行复测" /></Card>
            )}
          </Space>
        )}
      </Drawer>
    </div>
  )
}
