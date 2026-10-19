import { useEffect, useState, useCallback } from 'react'
import { RiseOutlined, FallOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import './Dashboard.css'

// ==================== 类型定义 ====================

/**
 * 概览数据响应接口
 */
interface DashboardOverviewResponse {
  total_users: number
  total_sessions: number
  total_qa: number
  today_active: number
  today_service: number
  week_service: number
  avg_satisfaction: number
  avg_latency_ms: number
  registered_users: number
  anonymous_visitors: number
  satisfaction_count: number
}

/**
 * 日统计项接口
 */
interface DailyStatItem {
  date: string
  service_count: number
  unique_users: number
  qa_count: number
  avg_latency_ms: number
  satisfaction_avg: number
}

/**
 * 日统计数据响应接口
 */
interface DailyStatsResponse {
  items: DailyStatItem[]
  total_days: number
}

/**
 * 热门问答项接口
 */
interface HotQuestionItem {
  question: string
  count: number
  category: string
}

/**
 * 热门问答响应接口
 */
interface HotQuestionsResponse {
  items: HotQuestionItem[]
  period: string
}

/**
 * 情感趋势项接口
 */
interface EmotionTrendItem {
  date: string
  happy: number
  neutral: number
  sad: number
  angry: number
  surprised: number
}

/**
 * 情感趋势响应接口
 */
interface EmotionTrendResponse {
  items: EmotionTrendItem[]
  period: string
}

/**
 * KPI数据接口
 */
interface KPIData {
  todayVisitors: number
  todayService: number
  weekService: number
  satisfaction: number
  activeSessions: number
  totalQA: number
  avgLatency: number
  totalUsers: number
  visitorsTrend: number
  satisfactionTrend: number
  sessionsTrend: number
  qaTrend: number
  registeredUsers: number
  anonymousVisitors: number
  satisfactionCount: number
}

/**
 * 趋势图表数据接口
 */
interface TrendChartData {
  dates: string[]
  data: number[]
}

/**
 * 情感分布数据项接口
 */
interface SentimentDataItem {
  value: number
  name: string
}

/**
 * 热门问答图表数据接口
 */
interface HotQAChartData {
  questions: string[]
  counts: number[]
}

/**
 * 热门景点数据项接口
 */
interface HotSpotItem {
  name: string
  count: number
  trend: 'up' | 'down'
}

interface AnalyticsSummaryResponse {
  is_sample: boolean
  concerns: Array<{
    topic: string
    mention_count: number
    trend: 'up' | 'down' | 'stable'
  }>
}

interface RealtimeDashboardResponse {
  online_sessions: number
  active_sessions_today: number
  hot_spots: Array<{ spot_id: string; count: number }>
  low_confidence_questions: Array<{ message_id: string; answer: string; confidence: number }>
  negative_emotion_alerts: Array<{ emotion: string; count: number }>
  asr_success_rate: number
  tts_success_rate: number
  avatar_success_rate: number
  avg_rag_ms: number
  avg_total_latency_ms: number
  is_sample: boolean
}

interface OptimizationMetricsResponse {
  photo_review_total: number
  photo_review_success: number
  photo_review_failed: number
  community_posts: number
  community_comments: number
  community_favorites: number
  community_reports: number
  hidden_posts: number
  is_sample: boolean
}

// ==================== 默认空态数据 ====================

/**
 * 生成默认KPI数据。接口失败时只显示0，不填充样例数。
 */
function getDefaultKPIData(): KPIData {
  return {
    todayVisitors: 0,
    todayService: 0,
    weekService: 0,
    satisfaction: 0,
    activeSessions: 0,
    totalQA: 0,
    avgLatency: 0,
    totalUsers: 0,
    visitorsTrend: 0,
    satisfactionTrend: 0,
    sessionsTrend: 0,
    qaTrend: 0,
    registeredUsers: 0,
    anonymousVisitors: 0,
    satisfactionCount: 0,
  }
}

/**
 * 生成默认趋势数据。接口失败时为空图，不生成随机曲线。
 */
function getDefaultTrendData(): TrendChartData {
  return { dates: [], data: [] }
}

/**
 * 生成默认情感分布数据。接口失败时不展示样例分布。
 */
function getDefaultSentimentData(): SentimentDataItem[] {
  return []
}

/**
 * 生成默认热门问答数据。接口失败时不展示样例问题。
 */
function getDefaultHotQAData(): HotQAChartData {
  return {
    questions: [],
    counts: [],
  }
}

/**
 * 生成热门关注点空态数据。
 */
function getDefaultHotSpots(): HotSpotItem[] {
  return []
}

// ==================== 辅助函数 ====================

/**
 * 将日期字符串格式化为 MM/DD 格式
 */
function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

/**
 * 将情感数据映射为中文标签
 */
function mapEmotionToChinese(emotion: string): string {
  const map: Record<string, string> = {
    happy: '开心',
    neutral: '平静',
    sad: '悲伤',
    angry: '愤怒',
    surprised: '惊讶',
  }
  return map[emotion] || emotion
}

function formatRate(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '暂无'
}

/**
 * 顶栏实时时钟（秒级）
 */
function formatClock(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} 星期${week} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// ==================== 大屏配色常量 ====================

/** ECharts 统一蓝金系色板 */
const CHART_COLORS = ['#2B5CE6', '#4A7BD9', '#F5C542', '#7BA3E8', '#17377F']
/** 深色底上的坐标轴文字 */
const AXIS_TEXT = 'rgba(159,194,255,0.75)'
/** 深色底上的网格线 */
const GRID_LINE = 'rgba(120,170,255,0.12)'
/** 深色 tooltip 统一样式 */
const DARK_TOOLTIP = {
  backgroundColor: 'rgba(5,15,38,0.92)',
  borderColor: 'rgba(120,170,255,0.35)',
  textStyle: { color: '#CFE0FF' },
}

/** 设计稿尺寸：1920×1080，整体 scale 适配任意分辨率 */
const DESIGN_WIDTH = 1920
const DESIGN_HEIGHT = 1080

// ==================== 主组件 ====================

/**
 * 数据大屏：独立全屏挂墙页
 * 1920×1080 设计稿 + transform scale 适配，一页不滚动；
 * 数据层与原后台页一致：7 接口并行加载，每30秒自动刷新，失败保持空态
 */
export default function Dashboard() {
  const navigate = useNavigate()

  // KPI数据状态
  const [kpiData, setKpiData] = useState<KPIData>(getDefaultKPIData())

  // 趋势图表数据状态
  const [trendData, setTrendData] = useState<TrendChartData>(getDefaultTrendData())

  // 情感分布数据状态
  const [sentimentData, setSentimentData] = useState<SentimentDataItem[]>(getDefaultSentimentData())

  // 热门问答数据状态
  const [hotQAData, setHotQAData] = useState<HotQAChartData>(getDefaultHotQAData())

  // 热门关注点/景点数据：只展示真实接口返回
  const [hotSpots, setHotSpots] = useState<HotSpotItem[]>(getDefaultHotSpots())
  const [isSampleAnalytics, setIsSampleAnalytics] = useState(false)
  const [realtime, setRealtime] = useState<RealtimeDashboardResponse | null>(null)
  const [optimizationMetrics, setOptimizationMetrics] = useState<OptimizationMetricsResponse | null>(null)

  // 加载状态
  const [loading, setLoading] = useState(false)

  // 全屏缩放比例与实时时钟
  const [scale, setScale] = useState(1)
  const [now, setNow] = useState(() => new Date())

  /**
   * 从API获取所有仪表盘数据
   * 并行调用接口，失败项保持空态
   */
  const fetchDashboardData = useCallback(async () => {
    setLoading(true)
    try {
      // 并行调用7个API
      const [
        overviewRes,
        dailyRes,
        hotQuestionsRes,
        emotionRes,
        analyticsRes,
        realtimeRes,
        optimizationRes,
      ] = await Promise.allSettled([
        api.get<DashboardOverviewResponse>('/admin/dashboard/overview'),
        api.get<DailyStatsResponse>('/admin/dashboard/daily?days=7'),
        api.get<HotQuestionsResponse>('/admin/dashboard/hot-questions?period=7d&limit=10'),
        api.get<EmotionTrendResponse>('/admin/dashboard/emotion-trend?days=7'),
        api.get<AnalyticsSummaryResponse>('/admin/analytics/summary?days=7'),
        api.get<RealtimeDashboardResponse>('/admin/dashboard/realtime'),
        api.get<OptimizationMetricsResponse>('/admin/dashboard/optimization-metrics'),
      ])

      // 处理概览数据
      if (overviewRes.status === 'fulfilled' && overviewRes.value) {
        const data = overviewRes.value
        setKpiData((prev) => ({
          ...prev,
          todayVisitors: data.today_active,
          todayService: data.today_service,
          weekService: data.week_service,
          satisfaction: parseFloat((data.avg_satisfaction * 20).toFixed(1)),
          activeSessions: data.total_sessions,
          totalQA: data.total_qa,
          avgLatency: data.avg_latency_ms,
          totalUsers: data.total_users,
          registeredUsers: data.registered_users,
          anonymousVisitors: data.anonymous_visitors,
          satisfactionCount: data.satisfaction_count,
        }))
      } else {
        console.error('获取概览数据失败:', overviewRes.status === 'rejected' ? overviewRes.reason : '无数据')
      }

      // 处理日统计数据（近7日服务人次趋势）
      if (dailyRes.status === 'fulfilled' && dailyRes.value?.items) {
        const items = dailyRes.value.items
        const dates = items.map((item) => formatDateLabel(item.date))
        const data = items.map((item) => item.service_count)
        setTrendData({ dates, data })
        const latest = items[items.length - 1]
        const previous = items[items.length - 2]
        const percentChange = (current = 0, before = 0) => {
          if (before <= 0) return current > 0 ? 100 : 0
          return Math.round(((current - before) / before) * 100)
        }
        setKpiData((prev) => ({
          ...prev,
          visitorsTrend: percentChange(latest?.unique_users, previous?.unique_users),
          sessionsTrend: percentChange(latest?.service_count, previous?.service_count),
          qaTrend: percentChange(latest?.qa_count, previous?.qa_count),
          satisfactionTrend: (
            latest?.satisfaction_avg != null && previous?.satisfaction_avg != null
              ? Math.round((latest.satisfaction_avg - previous.satisfaction_avg) * 20)
              : 0
          ),
        }))
      } else {
        console.error('获取日统计数据失败:', dailyRes.status === 'rejected' ? dailyRes.reason : '无数据')
        setTrendData(getDefaultTrendData())
      }

      // 处理热门问答数据
      if (hotQuestionsRes.status === 'fulfilled' && hotQuestionsRes.value?.items) {
        const items = hotQuestionsRes.value.items
        const questions = items.map((item) => item.question)
        const counts = items.map((item) => item.count)
        setHotQAData({ questions, counts })
      } else {
        console.error('获取热门问答失败:', hotQuestionsRes.status === 'rejected' ? hotQuestionsRes.reason : '无数据')
        setHotQAData(getDefaultHotQAData())
      }

      // 处理情感趋势数据（取最新一天的数据）
      if (emotionRes.status === 'fulfilled' && emotionRes.value?.items) {
        const items = emotionRes.value.items
        if (items.length > 0) {
          const latest = items[items.length - 1]
          const emotions: SentimentDataItem[] = [
            { value: Math.round(latest.happy * 100), name: mapEmotionToChinese('happy') },
            { value: Math.round(latest.neutral * 100), name: mapEmotionToChinese('neutral') },
            { value: Math.round(latest.surprised * 100), name: mapEmotionToChinese('surprised') },
            { value: Math.round(latest.sad * 100), name: mapEmotionToChinese('sad') },
            { value: Math.round(latest.angry * 100), name: mapEmotionToChinese('angry') },
          ]
          setSentimentData(emotions)
        }
      } else {
        console.error('获取情感趋势失败:', emotionRes.status === 'rejected' ? emotionRes.reason : '无数据')
        setSentimentData(getDefaultSentimentData())
      }

      if (analyticsRes.status === 'fulfilled' && analyticsRes.value?.concerns?.length) {
        setIsSampleAnalytics(Boolean(analyticsRes.value.is_sample))
        setHotSpots(analyticsRes.value.concerns.slice(0, 8).map((item) => ({
          name: item.topic,
          count: item.mention_count,
          trend: item.trend === 'down' ? 'down' : 'up',
        })))
      } else {
        setIsSampleAnalytics(false)
        setHotSpots(getDefaultHotSpots())
      }
      if (realtimeRes.status === 'fulfilled') {
        setRealtime(realtimeRes.value)
      }
      if (optimizationRes.status === 'fulfilled') {
        setOptimizationMetrics(optimizationRes.value)
      } else {
        setOptimizationMetrics(null)
      }
    } catch (error) {
      console.error('获取仪表盘数据出错:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  // 组件挂载时获取数据
  useEffect(() => {
    fetchDashboardData()
  }, [fetchDashboardData])

  // 每30秒自动刷新真实接口数据
  useEffect(() => {
    const timer = setInterval(() => {
      fetchDashboardData()
    }, 30000)
    return () => clearInterval(timer)
  }, [fetchDashboardData])

  // 监听窗口尺寸，计算 1920×1080 设计稿的缩放比例
  useEffect(() => {
    const updateScale = () => {
      setScale(Math.min(window.innerWidth / DESIGN_WIDTH, window.innerHeight / DESIGN_HEIGHT))
    }
    updateScale()
    window.addEventListener('resize', updateScale)
    return () => window.removeEventListener('resize', updateScale)
  }, [])

  // 秒级实时时钟
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  // ==================== ECharts配置（深色蓝金系） ====================

  // 近7日服务人次趋势图配置
  const trendOption: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      formatter: '{b}<br/>服务人次: {c}',
      ...DARK_TOOLTIP,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '12%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: trendData.dates,
      axisLine: { lineStyle: { color: 'rgba(120,170,255,0.3)' } },
      axisLabel: { color: AXIS_TEXT },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: GRID_LINE } },
      axisLabel: { color: AXIS_TEXT },
    },
    series: [
      {
        name: '服务人次',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        data: trendData.data,
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(74,123,217,0.38)' },
              { offset: 1, color: 'rgba(38,86,189,0.03)' },
            ],
          },
        },
        lineStyle: { color: '#4A7BD9', width: 3 },
        itemStyle: { color: '#7BA3E8', borderColor: '#081A3E', borderWidth: 2 },
      },
    ],
  }

  // 游客情感分布饼图配置
  const sentimentOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c}%',
      ...DARK_TOOLTIP,
    },
    legend: {
      orient: 'vertical',
      right: '5%',
      top: 'center',
      textStyle: { color: AXIS_TEXT, fontSize: 15 },
      itemWidth: 16,
      itemHeight: 16,
      itemGap: 12,
    },
    series: [
      {
        name: '情感分布',
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 8,
          borderColor: 'rgba(8,26,62,0.9)',
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 16,
            fontWeight: 'bold',
            color: '#CFE0FF',
          },
        },
        data: sentimentData,
        color: CHART_COLORS,
      },
    ],
  }

  // 热门问答TOP10横向条形图配置
  const hotQAOption: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: '{b}<br/>提问次数: {c}',
      ...DARK_TOOLTIP,
    },
    grid: {
      left: '3%',
      right: '8%',
      bottom: '3%',
      top: '3%',
      containLabel: true,
    },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: GRID_LINE } },
      axisLabel: { color: AXIS_TEXT },
    },
    yAxis: {
      type: 'category',
      data: hotQAData.questions,
      axisLine: { lineStyle: { color: 'rgba(120,170,255,0.3)' } },
      axisLabel: { color: AXIS_TEXT, width: 130, overflow: 'truncate' },
      inverse: true,
    },
    series: [
      {
        name: '提问次数',
        type: 'bar',
        data: hotQAData.counts,
        barWidth: '55%',
        itemStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 1,
            y2: 0,
            colorStops: [
              { offset: 0, color: '#17377F' },
              { offset: 1, color: '#4A7BD9' },
            ],
          },
          borderRadius: [0, 4, 4, 0],
        },
        label: {
          show: true,
          position: 'right',
          color: '#9FC2FF',
          fontSize: 12,
        },
      },
    ],
  }

  // ==================== KPI 带（8 项） ====================

  const renderTrend = (trend: number) => (
    <span className={trend >= 0 ? 'trend-up' : 'trend-down'}>
      {trend >= 0 ? <RiseOutlined /> : <FallOutlined />} {trend >= 0 ? '+' : ''}{trend}% 较昨日
    </span>
  )

  const kpiItems: Array<{ title: string; value: string | number; unit?: string; sub?: React.ReactNode }> = [
    { title: '今日服务', value: kpiData.todayService, unit: '次' },
    { title: '本周服务', value: kpiData.weekService, unit: '次' },
    { title: '今日活跃', value: kpiData.todayVisitors, unit: '人', sub: renderTrend(kpiData.visitorsTrend) },
    {
      title: '满意度',
      value: kpiData.satisfactionCount ? kpiData.satisfaction : '暂无',
      unit: kpiData.satisfactionCount ? '%' : undefined,
      sub: kpiData.satisfactionCount > 0 ? renderTrend(kpiData.satisfactionTrend) : '暂无评价样本',
    },
    { title: '总会话', value: kpiData.activeSessions, unit: '个', sub: renderTrend(kpiData.sessionsTrend) },
    { title: '问答总数', value: kpiData.totalQA, unit: '次', sub: renderTrend(kpiData.qaTrend) },
    {
      title: '独立访客',
      value: kpiData.totalUsers,
      unit: '人',
      sub: `注册 ${kpiData.registeredUsers} · 匿名 ${kpiData.anonymousVisitors}`,
    },
    { title: '平均延迟', value: kpiData.avgLatency, unit: 'ms' },
  ]

  // 实时链路状态格
  const linkTiles: Array<{ name: string; value: string | number; plain?: boolean }> = [
    { name: '在线会话', value: realtime?.online_sessions ?? 0, plain: true },
    { name: '今日会话', value: realtime?.active_sessions_today ?? 0, plain: true },
    { name: 'ASR 成功率', value: formatRate(realtime?.asr_success_rate) },
    { name: 'TTS 成功率', value: formatRate(realtime?.tts_success_rate) },
    { name: '数字人成功率', value: formatRate(realtime?.avatar_success_rate) },
    {
      name: 'RAG 平均延迟',
      value: typeof realtime?.avg_rag_ms === 'number' ? `${realtime.avg_rag_ms}ms` : '暂无',
    },
  ]

  const lowConfidenceQuestions = (realtime?.low_confidence_questions || []).slice(0, 4)

  return (
    <div className="dashboard-screen">
      <div className="dashboard-canvas" style={{ transform: `scale(${scale})` }}>
        {/* 顶栏：标题 + 实时徽标 + 秒级时钟 + 返回后台 */}
        <header className="screen-header">
          <div className="screen-title">
            <img className="screen-logo" src="/assets/logo.png" alt="灵境智游" />
            <span className="title-bar" />
            <h1>灵境智游 · 景区运营数据大屏</h1>
            <span className="screen-subtitle">灵山胜境 · AI 数字人智慧导览运营中枢</span>
          </div>
          <div className="screen-header-right">
            {loading && <span className="refresh-hint">数据刷新中…</span>}
            <span className="live-badge">
              <i />
              实时
            </span>
            <span className="screen-clock">{formatClock(now)}</span>
            <button type="button" className="back-btn" onClick={() => navigate('/knowledge')}>
              返回后台
            </button>
          </div>
        </header>

        {/* KPI 带：8 项核心指标，金色大数字 */}
        <section className="kpi-band">
          {kpiItems.map((item) => (
            <div className="kpi-item" key={item.title}>
              <div className="kpi-title">{item.title}</div>
              <div className="kpi-value">
                {item.value}
                {item.unit && <span className="kpi-unit">{item.unit}</span>}
              </div>
              <div className="kpi-sub">{item.sub ?? '每30秒自动刷新'}</div>
            </div>
          ))}
        </section>

        {/* 主区三列 */}
        <main className="screen-main">
          {/* 左列：7日趋势 + 热门问答TOP10 */}
          <div className="screen-col">
            <section className="glass-card flex-5">
              <div className="glass-card-header">
                <span className="glass-card-title">近7日服务人次趋势</span>
              </div>
              <div className="glass-card-body">
                <ReactECharts
                  className="chart-fill"
                  option={trendOption}
                  style={{ height: '100%', width: '100%' }}
                  opts={{ renderer: 'svg' }}
                  notMerge
                />
              </div>
            </section>
            <section className="glass-card flex-6">
              <div className="glass-card-header">
                <span className="glass-card-title">热门问答 TOP10</span>
              </div>
              <div className="glass-card-body">
                <ReactECharts
                  className="chart-fill"
                  option={hotQAOption}
                  style={{ height: '100%', width: '100%' }}
                  opts={{ renderer: 'svg' }}
                  notMerge
                />
              </div>
            </section>
          </div>

          {/* 中列：实时链路状态 + 情感分布 */}
          <div className="screen-col">
            <section className="glass-card flex-5">
              <div className="glass-card-header">
                <span className="glass-card-title">实时链路状态</span>
              </div>
              <div className="glass-card-body">
                <div className="link-grid">
                  {linkTiles.map((tile) => (
                    <div className="link-tile" key={tile.name}>
                      <span className="link-name">{tile.name}</span>
                      <span className={`link-value${tile.plain ? ' plain' : ''}`}>{tile.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>
            <section className="glass-card flex-5">
              <div className="glass-card-header">
                <span className="glass-card-title">游客情感分布</span>
              </div>
              <div className="glass-card-body">
                <ReactECharts
                  className="chart-fill"
                  option={sentimentOption}
                  style={{ height: '100%', width: '100%' }}
                  opts={{ renderer: 'svg' }}
                  notMerge
                />
              </div>
            </section>
          </div>

          {/* 右列：热门关注排行 + 社区与内容 + 低置信预警 */}
          <div className="screen-col">
            <section className="glass-card flex-4">
              <div className="glass-card-header">
                <span className="glass-card-title">热门关注排行</span>
                {isSampleAnalytics && <span className="sample-tag sample">样例</span>}
              </div>
              <div className="glass-card-body">
                {hotSpots.length > 0 ? (
                  <div className="rank-list">
                    {hotSpots.map((item, index) => (
                      <div className="rank-item" key={item.name}>
                        <span className={`rank-index${index < 3 ? ' top' : ''}`}>{index + 1}</span>
                        <span className="rank-name">{item.name}</span>
                        <span className="rank-count">{item.count}次</span>
                        <span className={`rank-trend ${item.trend}`}>
                          {item.trend === 'up' ? <RiseOutlined /> : <FallOutlined />}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-text">暂无关注数据</div>
                )}
              </div>
            </section>
            <section className="glass-card flex-3">
              <div className="glass-card-header">
                <span className="glass-card-title">社区与内容</span>
                {optimizationMetrics && (
                  <span className={`sample-tag ${optimizationMetrics.is_sample ? 'sample' : 'real'}`}>
                    {optimizationMetrics.is_sample ? '演示样例' : '真实数据'}
                  </span>
                )}
              </div>
              <div className="glass-card-body">
                <div className="mini-stat-grid">
                  <div className="mini-stat">
                    <div className="num">{optimizationMetrics?.photo_review_total ?? 0}</div>
                    <div className="label">照片点评</div>
                  </div>
                  <div className="mini-stat">
                    <div className="num">{optimizationMetrics?.photo_review_success ?? 0}</div>
                    <div className="label">成功</div>
                  </div>
                  <div className="mini-stat">
                    <div className="num">{optimizationMetrics?.photo_review_failed ?? 0}</div>
                    <div className="label">失败</div>
                  </div>
                </div>
                <div className="mini-tag-row">
                  <span className="mini-tag">帖子 {optimizationMetrics?.community_posts ?? 0}</span>
                  <span className="mini-tag">评论 {optimizationMetrics?.community_comments ?? 0}</span>
                  <span className="mini-tag">收藏 {optimizationMetrics?.community_favorites ?? 0}</span>
                  <span className={`mini-tag${(optimizationMetrics?.community_reports ?? 0) > 0 ? ' warn' : ''}`}>
                    举报 {optimizationMetrics?.community_reports ?? 0}
                  </span>
                  <span className={`mini-tag${(optimizationMetrics?.hidden_posts ?? 0) > 0 ? ' warn' : ''}`}>
                    隐藏 {optimizationMetrics?.hidden_posts ?? 0}
                  </span>
                </div>
              </div>
            </section>
            <section className="glass-card flex-3">
              <div className="glass-card-header">
                <span className="glass-card-title">低置信预警</span>
                {lowConfidenceQuestions.length > 0 && (
                  <span className="alert-count">{realtime?.low_confidence_questions.length}</span>
                )}
              </div>
              <div className="glass-card-body">
                {lowConfidenceQuestions.length > 0 ? (
                  <div className="alert-list">
                    {lowConfidenceQuestions.map((item) => (
                      <div className="alert-item" key={item.message_id}>
                        <span className="alert-answer">{item.answer}</span>
                        <span className="alert-conf">{Math.round(item.confidence * 100)}%</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-text">暂无低置信问题</div>
                )}
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  )
}
