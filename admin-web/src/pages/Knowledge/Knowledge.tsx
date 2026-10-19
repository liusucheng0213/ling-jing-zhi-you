import { useState, useEffect, useCallback } from 'react'
import {
  Table,
  Card,
  Button,
  Input,
  Select,
  Tag,
  Space,
  Modal,
  message,
  Upload,
  Popconfirm,
  Row,
  Col,
  Descriptions,
  Alert,
  Form,
} from 'antd'
import {
  SearchOutlined,
  DeleteOutlined,
  UploadOutlined,
  EyeOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  EditOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'

/**
 * 后端返回的知识文档列表项
 */
interface KnowledgeListItem {
  id: string
  title: string
  doc_type: string
  spot_id: string | null
  status: 'draft' | 'published' | 'archived'
  version: number
  lang: string
  created_at: string
  updated_at: string
  published_at: string | null
  content?: string
  content_html?: string
  metadata_json?: Record<string, unknown>
  chunk_count?: number
  source_file?: string
  chunks?: Array<{ id: string; chunk_index: number; content: string; char_count: number; parent_title?: string }>
}

/**
 * 前端展示用的知识文档
 */
interface KnowledgeDoc {
  id: string
  title: string
  doc_type: string
  spot_id: string | null
  status: 'draft' | 'published' | 'archived'
  version: number
  lang: string
  created_at: string
  updated_at: string
  published_at: string | null
  content?: string
  metadata_json?: Record<string, unknown>
  chunk_count?: number
  source_file?: string
  chunks?: Array<{ id: string; chunk_index: number; content: string; char_count: number; parent_title?: string }>
}

interface RecallHit {
  rank: number
  doc_title: string
  score: number
  vector_score: number
  text_score: number
  content: string
  reason: string
}

interface EmbeddingHealth {
  ok: boolean
  active_chain?: string
  runtime: Record<string, unknown>
  service?: Record<string, unknown> | null
  checks: Array<{ name: string; ok: boolean; value: unknown; status?: 'pass' | 'fail' | 'skip' }>
  probe?: { ok: boolean; via?: string; dimension?: number; non_zero?: boolean; loaded_backend?: string; loaded_device?: string; error?: string }
}

interface KnowledgeEditorValues {
  title: string
  doc_type: string
  spot_id?: string
  content: string
  lang: string
  status: 'draft' | 'published' | 'archived'
}

interface TraceBaseline {
  answer?: string
  confidence?: number | null
  mode?: string | null
  source_count?: number
}

interface TraceImprovementMetadata {
  question?: string
  retrieval_query?: string
  baseline?: TraceBaseline
}

function getTraceContext(document: KnowledgeDoc | null) {
  const metadata = document?.metadata_json
  if (!metadata || metadata.source !== 'rag_trace') return null
  const rawImprovement = metadata.improvement
  const improvement = rawImprovement && typeof rawImprovement === 'object'
    ? rawImprovement as TraceImprovementMetadata
    : undefined
  const messageId = typeof metadata.message_id === 'string' ? metadata.message_id : undefined
  if (!messageId) return null
  return { messageId, improvement }
}

/**
 * 文档状态对应的标签配置
 */
const statusMap = {
  draft: { text: '草稿', color: 'default' as const },
  published: { text: '已发布', color: 'success' as const },
  archived: { text: '已归档', color: 'warning' as const },
}

/**
 * 文档类型选项
 */
const docTypeOptions = [
  '景点介绍',
  '历史故事',
  'FAQ',
  '待补充问答',
  '路线指南',
  '餐饮住宿',
  '其他',
]

/**
 * 景点列表（16个灵山胜境景点）
 */
const spotOptions = [
  { id: 'LS-001', name: '灵山大照壁' },
  { id: 'LS-002', name: '五明桥' },
  { id: 'LS-003', name: '佛足坛' },
  { id: 'LS-004', name: '五智门' },
  { id: 'LS-005', name: '菩提大道' },
  { id: 'LS-006', name: '九龙灌浴' },
  { id: 'LS-007', name: '降魔浮雕' },
  { id: 'LS-008', name: '阿育王柱' },
  { id: 'LS-009', name: '百子戏弥勒' },
  { id: 'LS-010', name: '祥符禅寺' },
  { id: 'LS-011', name: '灵山大佛' },
  { id: 'LS-012', name: '佛教文化博览馆' },
  { id: 'LS-013', name: '灵山梵宫' },
  { id: 'LS-014', name: '五印坛城' },
  { id: 'LS-015', name: '曼飞龙塔' },
  { id: 'LS-016', name: '无尽意斋' },
]

/**
 * 格式化ISO时间字符串为本地时间
 */
function formatDateTime(isoString: string | null): string {
  if (!isoString) return '-'
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return isoString
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function metadataText(metadata: Record<string, unknown> | undefined, key: string): string {
  const value = metadata?.[key]
  return typeof value === 'string' ? value : ''
}

/**
 * 知识库管理页面
 */
export default function Knowledge() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedEditDocumentId = searchParams.get('edit')
  const requestedTraceMessageId = searchParams.get('trace')
  const [data, setData] = useState<KnowledgeDoc[]>([])
  const [loading, setLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [docTypeFilter, setDocTypeFilter] = useState<string>('')
  const [detailVisible, setDetailVisible] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [viewingDoc, setViewingDoc] = useState<KnowledgeDoc | null>(null)
  const [recallQuery, setRecallQuery] = useState('')
  const [recallLoading, setRecallLoading] = useState(false)
  const [recallResult, setRecallResult] = useState<{ confidence: number; mode: string; hits: RecallHit[] } | null>(null)
  const [embeddingHealth, setEmbeddingHealth] = useState<EmbeddingHealth | null>(null)
  const [embeddingLoading, setEmbeddingLoading] = useState(false)
  const [editorVisible, setEditorVisible] = useState(false)
  const [editorLoading, setEditorLoading] = useState(false)
  const [editorSaving, setEditorSaving] = useState(false)
  const [editingDoc, setEditingDoc] = useState<KnowledgeDoc | null>(null)
  const [editorForm] = Form.useForm<KnowledgeEditorValues>()
  const editorDocType = Form.useWatch('doc_type', editorForm)
  const traceContext = getTraceContext(editingDoc)
  const activeTraceMessageId = requestedTraceMessageId || traceContext?.messageId || null

  /**
   * 获取知识文档列表
   */
  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.append('limit', '100')
      if (statusFilter) params.append('status', statusFilter)
      if (docTypeFilter) params.append('doc_type', docTypeFilter)
      if (searchText) params.append('search', searchText)

      const response = await api.get(`/admin/knowledge?${params.toString()}`)
      const list: KnowledgeListItem[] = Array.isArray(response) ? response : []
      const mapped = list.map((item) => ({
        id: item.id,
        title: item.title,
        doc_type: item.doc_type,
        spot_id: item.spot_id,
        status: item.status,
        version: item.version,
        lang: item.lang,
        created_at: item.created_at,
        updated_at: item.updated_at,
        published_at: item.published_at,
        content: item.content,
        metadata_json: item.metadata_json,
        chunk_count: item.chunk_count,
        source_file: item.source_file,
      }))
      setData(mapped)
    } catch (error: unknown) {
      const err = error as { status?: number; message?: string }
      if (err.status === 401) {
        message.error('登录已过期，请重新登录')
        window.location.href = '/login'
      } else {
        message.error(err.message || '获取知识文档列表失败')
      }
    } finally {
      setLoading(false)
    }
  }, [statusFilter, docTypeFilter, searchText])

  /**
   * 组件挂载及筛选条件变化时获取数据
   */
  useEffect(() => {
    fetchData()
  }, [fetchData])

  useEffect(() => {
    const documentId = requestedEditDocumentId
    if (!documentId) return
    let cancelled = false
    setEditorVisible(true)
    setEditorLoading(true)
    void api.get<KnowledgeListItem>(`/admin/knowledge/${documentId}`)
      .then((detail) => {
        if (cancelled) return
        const document = detail as KnowledgeDoc
        setEditingDoc(document)
        editorForm.setFieldsValue({
          title: document.title,
          doc_type: document.doc_type,
          spot_id: document.spot_id || undefined,
          content: document.content || '',
          lang: document.lang || 'zh',
          status: document.status,
        })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const detail = (error as { message?: string }).message
        message.error(detail || '读取知识草稿失败')
        setEditorVisible(false)
        navigate('/knowledge', { replace: true })
      })
      .finally(() => {
        if (!cancelled) setEditorLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [editorForm, navigate, requestedEditDocumentId])

  /**
   * 表格列定义
   */
  const columns: ColumnsType<KnowledgeDoc> = [
    {
      title: '文档标题',
      dataIndex: 'title',
      key: 'title',
      width: 280,
      ellipsis: true,
      render: (text: string) => (
        <Space>
          <FileTextOutlined style={{ color: '#2d5a87' }} />
          <span style={{ fontWeight: 500 }}>{text}</span>
        </Space>
      ),
    },
    {
      title: '文档类型',
      dataIndex: 'doc_type',
      key: 'doc_type',
      width: 140,
    },
    {
      title: '关联景点',
      dataIndex: 'spot_id',
      key: 'spot_id',
      width: 150,
      render: (spotId: string) => {
        const spot = spotOptions.find((s) => s.id === spotId)
        return spot ? spot.name : spotId
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: keyof typeof statusMap) => (
        <Tag color={statusMap[status].color}>{statusMap[status].text}</Tag>
      ),
    },
    {
      title: '来源范围',
      key: 'source_scope',
      width: 190,
      render: (_, record) => {
        const scenicArea = metadataText(record.metadata_json, 'scenic_area')
        const sourcePackage = metadataText(record.metadata_json, 'source_package')
        const conflict = metadataText(record.metadata_json, 'conflict_status')
        return (
          <Space wrap size={[4, 4]}>
            {scenicArea && <Tag color={scenicArea === '拈花湾' ? 'purple' : 'green'}>{scenicArea}</Tag>}
            {sourcePackage && <Tag color="blue">官方资料包</Tag>}
            {conflict && conflict !== 'none' && (
              <Tag color={conflict === 'unresolved' ? 'red' : 'gold'}>
                {conflict === 'unresolved' ? '冲突待核实' : conflict}
              </Tag>
            )}
            {!scenicArea && !sourcePackage && <Tag>后台维护</Tag>}
          </Space>
        )
      },
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 80,
    },
    {
      title: '分块',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 90,
      render: (value: number) => <Tag color="blue">{value || 0} 块</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '操作',
      key: 'action',
      width: 250,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleView(record)}
          >
            查看
          </Button>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          {record.status === 'draft' && (
            <Button
              type="text"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handlePublish(record.id)}
            >
              发布
            </Button>
          )}
          <Popconfirm
            title="确认删除"
            description="删除后无法恢复，是否继续？"
            onConfirm={() => handleDelete(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  /**
   * 查看文档详情
   */
  const handleView = async (record: KnowledgeDoc) => {
    setDetailVisible(true)
    setDetailLoading(true)
    try {
      const detail = await api.get<KnowledgeListItem>(`/admin/knowledge/${record.id}`)
      setViewingDoc({ ...record, ...detail })
    } catch {
      setViewingDoc(record)
      message.error('读取文档详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  /**
   * 删除文档
   */
  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/admin/knowledge/${id}`)
      message.success('删除成功')
      fetchData()
    } catch (error: unknown) {
      const err = error as { status?: number; message?: string }
      if (err.status === 401) {
        message.error('登录已过期，请重新登录')
        window.location.href = '/login'
      } else {
        message.error(err.message || '删除失败')
      }
    }
  }

  /**
   * 发布文档
   */
  const handlePublish = async (id: string) => {
    try {
      await api.post(`/admin/knowledge/${id}/publish`, {})
      message.success('发布成功')
      fetchData()
    } catch (error: unknown) {
      const err = error as { status?: number; message?: string }
      if (err.status === 401) {
        message.error('登录已过期，请重新登录')
        window.location.href = '/login'
      } else {
        message.error(err.message || '发布失败')
      }
    }
  }

  const handleCreate = () => {
    setEditingDoc(null)
    editorForm.resetFields()
    editorForm.setFieldsValue({
      doc_type: 'FAQ',
      lang: 'zh',
      status: 'draft',
      content: '',
      title: '',
    })
    setEditorVisible(true)
  }

  const handleEdit = async (record: KnowledgeDoc) => {
    setEditingDoc(record)
    setEditorVisible(true)
    setEditorLoading(true)
    try {
      const detail = await api.get<KnowledgeListItem>(`/admin/knowledge/${record.id}`)
      const document = { ...record, ...detail }
      setEditingDoc(document)
      editorForm.setFieldsValue({
        title: document.title,
        doc_type: document.doc_type,
        spot_id: document.spot_id || undefined,
        content: document.content || '',
        lang: document.lang || 'zh',
        status: document.status,
      })
    } catch (error: unknown) {
      const err = error as { message?: string }
      message.error(err.message || '读取编辑内容失败')
      setEditorVisible(false)
    } finally {
      setEditorLoading(false)
    }
  }

  const closeEditor = () => {
    setEditorVisible(false)
    setEditingDoc(null)
    editorForm.resetFields()
    if (searchParams.get('edit') || searchParams.get('trace')) {
      navigate('/knowledge', { replace: true })
    }
  }

  const handleSave = async (
    statusOverride?: 'draft' | 'published' | 'archived',
    retestAfterPublish = false,
  ) => {
    const values = await editorForm.validateFields()
    const targetStatus = statusOverride || values.status
    setEditorSaving(true)
    let savedDocumentId = editingDoc?.id
    try {
      if (editingDoc) {
        const saved = await api.put<KnowledgeListItem>(`/admin/knowledge/${editingDoc.id}`, {
          title: values.title.trim(),
          doc_type: values.doc_type,
          spot_id: values.spot_id || null,
          content: values.content.trim(),
          lang: values.lang,
          status: targetStatus,
        })
        savedDocumentId = saved.id
      } else {
        const created = await api.post<KnowledgeListItem>('/admin/knowledge', {
          title: values.title.trim(),
          doc_type: values.doc_type,
          spot_id: values.spot_id || null,
          content: values.content.trim(),
          lang: values.lang,
          metadata_json: {
            ingestion_method: 'admin_editor',
            knowledge_kind: values.doc_type === 'FAQ' ? 'qa' : 'document',
          },
        })
        savedDocumentId = created.id
        if (targetStatus === 'published') {
          await api.post(`/admin/knowledge/${created.id}/publish`, {})
        }
      }

      if (retestAfterPublish && activeTraceMessageId && savedDocumentId) {
        try {
          await api.post(`/admin/rag-trace/${activeTraceMessageId}/retest`, {
            document_id: savedDocumentId,
          })
          message.success('标准答案已发布，原问题复测完成')
          navigate(`/rag-trace?case=${activeTraceMessageId}&document=${savedDocumentId}`)
        } catch (error: unknown) {
          const detail = (error as { message?: string }).message
          message.warning(`知识已发布，复测暂未完成：${detail || '可在RAG溯源页重试'}`)
          navigate('/rag-trace')
        }
      } else if (activeTraceMessageId) {
        message.success('知识草稿已保存')
        navigate('/rag-trace')
      } else {
        message.success(editingDoc ? '知识内容已更新' : '知识内容已创建')
      }
      setEditorVisible(false)
      setDetailVisible(false)
      setEditingDoc(null)
      editorForm.resetFields()
      await fetchData()
    } catch (error: unknown) {
      const err = error as { message?: string }
      message.error(err.message || '保存知识内容失败')
    } finally {
      setEditorSaving(false)
    }
  }


  /**
   * 上传文件配置
   */
  const uploadProps: UploadProps = {
    name: 'file',
    accept: '.txt,.md,.markdown,.csv,.json,.pdf,.docx,.xlsx',
    maxCount: 1,
    customRequest: async ({ file, onSuccess, onError }) => {
      const uploadFile = file as File
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('doc_type', '景点介绍')
      formData.append('publish', 'true')
      formData.append('title', uploadFile.name.replace(/\.[^.]+$/, ''))

      try {
        await api.post('/admin/knowledge/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        message.success(`${uploadFile.name} 已上传并发布到知识库`)
        onSuccess?.({}, uploadFile)
        fetchData()
      } catch (error) {
        message.error(`${uploadFile.name} 上传失败`)
        onError?.(error as Error)
      }
    },
  }

  const handleRecallTest = async () => {
    if (!recallQuery.trim()) {
      message.warning('请输入要测试的问题')
      return
    }
    setRecallLoading(true)
    try {
      const result = await api.post<{ confidence: number; mode: string; hits: RecallHit[] }>('/admin/knowledge/recall-test', {
        query: recallQuery.trim(),
        top_k: 5,
      })
      setRecallResult(result)
    } catch (error) {
      message.error('召回测试失败')
    } finally {
      setRecallLoading(false)
    }
  }

  const handleEmbeddingHealth = useCallback(async (showToast = true) => {
    setEmbeddingLoading(true)
    try {
      const result = await api.get<EmbeddingHealth>('/admin/knowledge-embedding-health?probe=true')
      setEmbeddingHealth(result)
      if (showToast && result.probe?.ok) {
        message.success(`Embedding可用，维度 ${result.probe.dimension}`)
      } else if (showToast) {
        message.warning('Embedding探测未通过，请查看检查项')
      }
    } catch {
      if (showToast) message.error('Embedding健康检查失败')
    } finally {
      setEmbeddingLoading(false)
    }
  }, [])

  useEffect(() => {
    void handleEmbeddingHealth(false)
  }, [handleEmbeddingHealth])

  return (
    <div>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>知识库管理</h2>
      </div>

      {/* 搜索和操作栏 */}
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} sm={8} lg={6}>
            <Input
              placeholder="搜索文档标题"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={fetchData}
              allowClear
            />
          </Col>
          <Col xs={24} sm={6} lg={4}>
            <Select
              placeholder="状态筛选"
              value={statusFilter || undefined}
              onChange={setStatusFilter}
              allowClear
              style={{ width: '100%' }}
            >
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="published">已发布</Select.Option>
              <Select.Option value="archived">已归档</Select.Option>
            </Select>
          </Col>
          <Col xs={24} sm={6} lg={4}>
            <Select
              placeholder="文档类型筛选"
              value={docTypeFilter || undefined}
              onChange={setDocTypeFilter}
              allowClear
              style={{ width: '100%' }}
            >
              {docTypeOptions.map((type) => (
                <Select.Option key={type} value={type}>
                  {type}
                </Select.Option>
              ))}
            </Select>
          </Col>
          <Col xs={24} sm={24} lg={10}>
            <Space style={{ float: 'right' }} wrap>
              <Button icon={<PlusOutlined />} onClick={handleCreate}>新建知识/问答</Button>
              <Upload {...uploadProps}>
                <Button type="primary" icon={<UploadOutlined />}>上传并发布</Button>
              </Upload>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card
        title="Embedding 健康检查"
        style={{ marginBottom: 24 }}
        extra={
          <Button loading={embeddingLoading} onClick={() => handleEmbeddingHealth(true)}>
            重新探测
          </Button>
        }
      >
        {!embeddingHealth ? (
          <Alert
            type="info"
            showIcon
            message="正在自动检查嵌入服务并生成测试向量…"
          />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space wrap>
              <Tag color={embeddingHealth.ok ? 'green' : 'orange'}>{embeddingHealth.ok ? '链路可用' : '链路待修复'}</Tag>
              {embeddingHealth.active_chain && <Tag color="geekblue">{embeddingHealth.active_chain}</Tag>}
              <Tag color={embeddingHealth.probe?.ok ? 'green' : 'red'}>
                探测 {embeddingHealth.probe?.ok ? '通过' : '未通过'}
              </Tag>
              {embeddingHealth.probe?.dimension && <Tag color="blue">维度 {embeddingHealth.probe.dimension}</Tag>}
              {embeddingHealth.probe?.loaded_backend && <Tag>{embeddingHealth.probe.loaded_backend}</Tag>}
              {embeddingHealth.probe?.loaded_device && <Tag>{embeddingHealth.probe.loaded_device}</Tag>}
            </Space>
            {embeddingHealth.probe?.error && (
              <Alert type="error" showIcon message={embeddingHealth.probe.error} />
            )}
            <Table
              size="small"
              rowKey="name"
              pagination={false}
              dataSource={embeddingHealth.checks}
              columns={[
                { title: '检查项', dataIndex: 'name', width: 180 },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 90,
                  render: (status: 'pass' | 'fail' | 'skip' | undefined, row: { ok: boolean }) => {
                    const effective = status || (row.ok ? 'pass' : 'fail')
                    if (effective === 'skip') return <Tag>无需</Tag>
                    return <Tag color={effective === 'pass' ? 'green' : 'red'}>{effective === 'pass' ? '通过' : '失败'}</Tag>
                  },
                },
                { title: '值', dataIndex: 'value', render: (value: unknown) => String(value ?? '-') },
              ]}
            />
          </Space>
        )}
      </Card>

      <Card
        title="知识库召回测试"
        style={{ marginBottom: 24 }}
        extra={recallResult && <Tag color={recallResult.confidence >= 0.35 ? 'green' : 'orange'}>{recallResult.mode}</Tag>}
      >
        <Space.Compact style={{ width: '100%', marginBottom: recallResult ? 16 : 0 }}>
          <Input
            placeholder="输入游客问题，查看RAG命中片段"
            value={recallQuery}
            onChange={(event) => setRecallQuery(event.target.value)}
            onPressEnter={handleRecallTest}
          />
          <Button type="primary" loading={recallLoading} onClick={handleRecallTest}>
            测试召回
          </Button>
        </Space.Compact>
        {recallResult && (
          <Table
            size="small"
            rowKey="rank"
            pagination={false}
            dataSource={recallResult.hits}
            columns={[
              { title: '排名', dataIndex: 'rank', width: 70 },
              { title: '文档', dataIndex: 'doc_title', width: 180 },
              { title: '分数', dataIndex: 'score', width: 90, render: (value: number) => value.toFixed(3) },
              { title: '原因', dataIndex: 'reason', width: 160 },
              { title: '片段', dataIndex: 'content', ellipsis: true },
            ]}
          />
        )}
      </Card>

      {/* 文档列表 */}
      <Card>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
          scroll={{ x: 1220 }}
        />
      </Card>

      {/* 查看详情弹窗 */}
      <Modal
        title="文档详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={[
          viewingDoc && (
            <Button key="edit" type="primary" icon={<EditOutlined />} onClick={() => handleEdit(viewingDoc)}>
              编辑内容
            </Button>
          ),
          <Button key="close" onClick={() => setDetailVisible(false)}>
            关闭
          </Button>,
        ].filter(Boolean)}
        width={700}
        loading={detailLoading}
      >
        {viewingDoc && (
          <div>
            <h3 style={{ marginBottom: 16 }}>{viewingDoc.title}</h3>
            <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="状态"><Tag color={statusMap[viewingDoc.status].color}>{statusMap[viewingDoc.status].text}</Tag></Descriptions.Item>
              <Descriptions.Item label="文档类型">{viewingDoc.doc_type}</Descriptions.Item>
              <Descriptions.Item label="关联景点">{spotOptions.find((s) => s.id === viewingDoc.spot_id)?.name || viewingDoc.spot_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="分块数量">{viewingDoc.chunk_count || viewingDoc.chunks?.length || 0}</Descriptions.Item>
              <Descriptions.Item label="源文件">{viewingDoc.source_file || String(viewingDoc.metadata_json?.source_file || '-')}</Descriptions.Item>
              <Descriptions.Item label="RAG策略">{String(viewingDoc.metadata_json?.rag_strategy || 'parent_child')}</Descriptions.Item>
              <Descriptions.Item label="景区范围">{metadataText(viewingDoc.metadata_json, 'scenic_area') || '未限定'}</Descriptions.Item>
              <Descriptions.Item label="资料包">{metadataText(viewingDoc.metadata_json, 'source_package') || '-'}</Descriptions.Item>
              <Descriptions.Item label="冲突状态" span={2}>
                <Tag color={metadataText(viewingDoc.metadata_json, 'conflict_status') === 'unresolved' ? 'red' : 'green'}>
                  {metadataText(viewingDoc.metadata_json, 'conflict_status') || 'none'}
                </Tag>
                {Array.isArray(viewingDoc.metadata_json?.conflicts) && viewingDoc.metadata_json.conflicts.length > 0 && (
                  <span style={{ marginLeft: 8 }}>
                    {viewingDoc.metadata_json.conflicts.map((item) => String(item)).join('；')}
                  </span>
                )}
              </Descriptions.Item>
            </Descriptions>
            <div
              style={{
                padding: 16,
                background: '#f5f5f5',
                borderRadius: 8,
                lineHeight: 1.8,
                color: '#333',
              }}
            >
              {viewingDoc.content}
            </div>
            {!!viewingDoc.chunks?.length && (
              <div style={{ marginTop: 16 }}>
                <h4>父子分块结果</h4>
                <Table
                  size="small"
                  rowKey="id"
                  pagination={{ pageSize: 4 }}
                  dataSource={viewingDoc.chunks}
                  columns={[
                    { title: '序号', dataIndex: 'chunk_index', width: 70 },
                    { title: '父块', dataIndex: 'parent_title', width: 180, ellipsis: true },
                    { title: '字数', dataIndex: 'char_count', width: 80 },
                    { title: '检索子块', dataIndex: 'content', ellipsis: true },
                  ]}
                />
              </div>
            )}
            <div style={{ marginTop: 16, color: '#999', fontSize: 12 }}>
              创建时间: {formatDateTime(viewingDoc.created_at)} |
              更新时间: {formatDateTime(viewingDoc.updated_at)} |
              语言: {viewingDoc.lang}
            </div>
          </div>
        )}
      </Modal>

      <Modal
        title={editingDoc ? '编辑知识/问答' : '新建知识/问答'}
        open={editorVisible}
        onCancel={closeEditor}
        onOk={() => void handleSave()}
        okText={editingDoc ? '保存更改' : '创建'}
        cancelText="取消"
        confirmLoading={editorSaving}
        loading={editorLoading}
        maskClosable={false}
        width={760}
        destroyOnHidden
        footer={activeTraceMessageId ? [
          <Button key="cancel" onClick={closeEditor}>取消</Button>,
          <Button
            key="draft"
            loading={editorSaving}
            onClick={() => void handleSave(editingDoc?.status === 'published' ? 'published' : 'draft')}
          >
            {editingDoc?.status === 'published' ? '保存并保持发布' : '保存草稿'}
          </Button>,
          <Button
            key="publish-retest"
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={editorSaving}
            onClick={() => void handleSave('published', true)}
          >
            发布并立即复测
          </Button>,
        ] : undefined}
      >
        {traceContext?.improvement && (
          <Card size="small" style={{ marginBottom: 16, background: '#fffbe6', borderColor: '#ffe58f' }}>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="游客原问题">
                {traceContext.improvement.question || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="原回答置信度">
                {typeof traceContext.improvement.baseline?.confidence === 'number'
                  ? traceContext.improvement.baseline.confidence.toFixed(3)
                  : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="原回答">
                {traceContext.improvement.baseline?.answer || '-'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        )}
        <Form form={editorForm} layout="vertical" requiredMark="optional">
          <Row gutter={16}>
            <Col xs={24} md={15}>
              <Form.Item
                name="title"
                label={editorDocType === 'FAQ' ? '问题/标题' : '标题'}
                rules={[{ required: true, whitespace: true, message: '请输入标题' }]}
              >
                <Input maxLength={500} showCount placeholder={editorDocType === 'FAQ' ? '例如：灵山胜境现在从哪里预约？' : '请输入知识标题'} />
              </Form.Item>
            </Col>
            <Col xs={24} md={9}>
              <Form.Item name="doc_type" label="分类" rules={[{ required: true, message: '请选择分类' }]}>
                <Select options={docTypeOptions.map((value) => ({ value, label: value }))} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={10}>
              <Form.Item name="spot_id" label="关联景点">
                <Select
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="可不关联具体景点"
                  options={spotOptions.map((spot) => ({ value: spot.id, label: `${spot.name}（${spot.id}）` }))}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={7}>
              <Form.Item name="lang" label="语言" rules={[{ required: true }]}>
                <Select options={[{ value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} />
              </Form.Item>
            </Col>
            <Col xs={12} md={7}>
              <Form.Item name="status" label="保存状态" rules={[{ required: true }]}>
                <Select disabled={Boolean(activeTraceMessageId)}>
                  <Select.Option value="draft">草稿</Select.Option>
                  <Select.Option value="published">已发布</Select.Option>
                  {editingDoc && <Select.Option value="archived">已归档</Select.Option>}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="content"
            label={editorDocType === 'FAQ' ? '答案/知识内容' : '正文内容'}
            rules={[{ required: true, whitespace: true, message: '请输入知识内容' }]}
          >
            <Input.TextArea
              rows={12}
              showCount
              placeholder={editorDocType === 'FAQ' ? '填写可核验、可直接回答游客问题的完整答案，并注明时间口径或来源。' : '请输入完整知识正文'}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
