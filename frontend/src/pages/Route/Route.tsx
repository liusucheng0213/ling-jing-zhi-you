import { useCallback, useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Dialog, Popup, SpinLoading, Steps, Switch, Toast } from 'antd-mobile'
import {
  ClockCircleOutline,
  CompassOutline,
  EnvironmentOutline,
  FlagOutline,
  HeartOutline,
  PictureOutline,
  ShopbagOutline,
  StarOutline,
  TeamOutline,
} from 'antd-mobile-icons'
import { api } from '../../api/client'
import { useChatStore } from '../../stores/chat'
import type { ChatMessage } from '../../stores/chat'
import { getJourneyProgress, useJourneyStore } from '../../stores/journey'
import type { ActiveJourney, JourneyHistory, JourneyMobility, JourneyPlan } from '../../stores/journey'
import { useUserStore } from '../../stores/user'
import LocationLocator from './LocationLocator'
import type { LocationResult } from './LocationLocator'
import './Route.css'

/**
 * 路线推荐页面
 * 兴趣标签选择 + 推荐路线卡片 + 路线详情
 * 数据从后端 API 动态获取
 */

// 兴趣标签配置，包含与后端标签的映射关系
const interestTags = [
  { key: 'history', label: '历史文化', icon: <FlagOutline />, backendTags: ['历史', '文化', '佛教'] },
  { key: 'nature', label: '自然风光', icon: <CompassOutline />, backendTags: ['自然', '风光', '摄影'] },
  { key: 'family', label: '亲子游玩', icon: <TeamOutline />, backendTags: ['亲子', '轻松'] },
  { key: 'zen', label: '禅修体验', icon: <HeartOutline />, backendTags: ['禅修', '深度'] },
  { key: 'food', label: '美食探索', icon: <ShopbagOutline />, backendTags: ['美食'] },
  { key: 'photo', label: '摄影打卡', icon: <PictureOutline />, backendTags: ['摄影', '风光'] },
]

const INTEREST_PROFILE_KEY = 'lingjing_route_interests'

// 后端难度值到中文的映射
const difficultyMap: Record<string, string> = {
  easy: '轻松',
  medium: '适中',
  hard: '困难',
}

// 路线列表项接口（对应后端 RouteListItem）
interface RouteListItem {
  id: string
  name: string
  description: string
  tags: string[]
  total_time: number
  total_distance: number
  difficulty: string
  node_count: number
  match_score?: number | null
  matched_interests?: string[]
  recommend_reason?: string
  explanation_focus?: string[]
  recommend_mode?: 'personalized' | 'default_hot' | 'location'
  dynamic_plan?: JourneyPlan | null
}

interface RouteBranchNode {
  title: string
  type: 'photo' | 'rest' | 'culture' | 'shortcut'
  description: string
  near_spot?: string | null
  extra_time?: number | null
}

// 路线节点接口
interface RouteNode {
  id: string
  spot_id: string
  spot_name: string
  order: number
  stay_time: number
  description: string
}

// 路线详情接口（对应后端 RouteDetailResponse）
interface RouteDetail {
  id: string
  name: string
  description: string
  tags: string[]
  total_time: number
  total_distance: number
  difficulty: string
  nodes: RouteNode[]
  branch_nodes?: RouteBranchNode[]
  rest_tips?: string[]
  route_notes?: string[]
}

type RouteAnswer = Pick<ChatMessage, 'content' | 'confidence' | 'answerType' | 'traceId' | 'retrievedDocs'>

// 将后端标签映射为前端兴趣标签 key
function mapBackendTagsToFrontend(backendTags: string[]): string[] {
  const result: string[] = []
  backendTags.forEach((bTag) => {
    interestTags.forEach((fTag) => {
      if (fTag.backendTags.includes(bTag) && !result.includes(fTag.key)) {
        result.push(fTag.key)
      }
    })
  })
  return result
}

function readSavedInterestTags(): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(INTEREST_PROFILE_KEY) || '[]')
    return Array.isArray(saved) ? mapBackendTagsToFrontend(saved) : []
  } catch {
    return []
  }
}

export default function RoutePage() {
  const sessionId = useChatStore((state) => state.sessionId)
  const selectedAvatar = useChatStore((state) => state.selectedAvatar)
  const sendMessage = useChatStore((state) => state.sendMessage)
  const activeJourney = useJourneyStore((state) => state.activeJourney)
  const visitedSpotIds = useJourneyStore((state) => state.visitedSpotIds)
  const startJourney = useJourneyStore((state) => state.startJourney)
  const arriveAtNext = useJourneyStore((state) => state.arriveAtNext)
  const completeCurrentSpot = useJourneyStore((state) => state.completeCurrentSpot)
  const skipNextSpot = useJourneyStore((state) => state.skipNextSpot)
  const applyReplan = useJourneyStore((state) => state.applyReplan)
  const finishJourney = useJourneyStore((state) => state.finishJourney)
  const addBadge = useUserStore((state) => state.addBadge)

  // 选中的兴趣标签
  const [selectedTags, setSelectedTags] = useState<string[]>(readSavedInterestTags)
  // 当前展开的路线 ID
  const [expandedRoute, setExpandedRoute] = useState<string | null>(null)
  // 路线列表数据
  const [routes, setRoutes] = useState<RouteListItem[]>([])
  // 路线详情缓存（key 为 routeId）
  const [routeDetails, setRouteDetails] = useState<Record<string, RouteDetail>>({})
  // 加载状态
  const [loading, setLoading] = useState(false)
  // 详情加载状态
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>({})
  const [spotAskLoading, setSpotAskLoading] = useState<string | null>(null)
  const [spotAnswers, setSpotAnswers] = useState<Record<string, RouteAnswer | undefined>>({})
  const [locatedSpotId, setLocatedSpotId] = useState<string | null>(null)
  const [locatedSpot, setLocatedSpot] = useState<{ id: string; name: string } | null>(null)
  const [startSheetRoute, setStartSheetRoute] = useState<RouteListItem | null>(null)
  const [startDuration, setStartDuration] = useState<number | null>(null)
  const [startMobility, setStartMobility] = useState<JourneyMobility>('normal')
  const [startAccessibility, setStartAccessibility] = useState(false)
  const [startLoading, setStartLoading] = useState(false)
  const [replanLoading, setReplanLoading] = useState<'tired' | 'time' | 'location' | null>(null)
  const [completionSummary, setCompletionSummary] = useState<JourneyHistory | null>(null)
  const [pendingLocation, setPendingLocation] = useState<LocationResult | null>(null)

  // 当选择标签变化时，调用推荐接口
  useEffect(() => {
    fetchRecommendRoutes()
  }, [selectedTags, sessionId, locatedSpotId, visitedSpotIds])

  // 基于兴趣标签获取推荐路线
  const fetchRecommendRoutes = async () => {
    setLoading(true)
    try {
      // 将前端标签 key 转换为后端标签
      const interests: string[] = []
      selectedTags.forEach((tagKey) => {
        const tagConfig = interestTags.find((t) => t.key === tagKey)
        if (tagConfig) {
          interests.push(...tagConfig.backendTags)
        }
      })

      const uniqueInterests = [...new Set(interests)]
      const data = await api.post<RouteListItem[]>('/routes/recommend', {
        interests: uniqueInterests,
        spot_id: locatedSpotId || undefined,
        session_id: uniqueInterests.length ? sessionId : undefined,
        visited_spots: visitedSpotIds,
      })
      setRoutes(data)
    } catch {
      Toast.show({
        content: '获取推荐路线失败，请稍后重试',
        position: 'center',
      })
    } finally {
      setLoading(false)
    }
  }

  const persistInterests = async (interests: string[]) => {
    const unique = [...new Set(interests)]
    localStorage.setItem(INTEREST_PROFILE_KEY, JSON.stringify(unique))
    try {
      await api.post('/routes/interests', {
        interests: unique,
        session_id: sessionId,
        source: 'route_onboarding',
      })
    } catch {
      // 本地画像已保存，接口失败不阻塞游客继续浏览路线。
    }
  }

  // 获取路线详情
  const fetchRouteDetail = async (routeId: string) => {
    // 如果已缓存则直接返回
    if (routeDetails[routeId]) return

    setDetailLoading((prev) => ({ ...prev, [routeId]: true }))
    try {
      const data = await api.get<RouteDetail>(`/routes/${routeId}`)
      setRouteDetails((prev) => ({ ...prev, [routeId]: data }))
    } catch {
      Toast.show({
        content: '获取路线详情失败',
        position: 'center',
      })
    } finally {
      setDetailLoading((prev) => ({ ...prev, [routeId]: false }))
    }
  }

  // 切换标签选择
  const toggleTag = (tagKey: string) => {
    setSelectedTags((prev) => {
      const next = prev.includes(tagKey)
        ? prev.filter((t) => t !== tagKey)
        : [...prev, tagKey]
      const backendInterests = next.flatMap((key) =>
        interestTags.find((tag) => tag.key === key)?.backendTags || []
      )
      persistInterests(backendInterests)
      return next
    })
  }

  const clearInterestProfile = () => {
    setSelectedTags([])
    persistInterests([])
  }

  // 切换路线展开/收起
  const toggleExpand = (routeId: string) => {
    const newExpanded = expandedRoute === routeId ? null : routeId
    setExpandedRoute(newExpanded)
    // 展开时获取详情
    if (newExpanded) {
      fetchRouteDetail(routeId)
    }
  }

  const recordJourneyEvent = useCallback(async (
    eventType: 'started' | 'arrived' | 'spot_completed' | 'spot_skipped' | 'replanned' | 'completed' | 'ended',
    journey: ActiveJourney | JourneyHistory,
    spotId?: string,
    details: Record<string, unknown> = {},
  ) => {
    const isActive = 'status' in journey
    try {
      await api.post('/routes/journey-events', {
        route_id: journey.routeId,
        journey_id: journey.journeyId,
        session_id: sessionId || undefined,
        event_type: eventType,
        spot_id: spotId,
        progress_percent: isActive ? getJourneyProgress(journey) : journey.completionPercent,
        visited_spots: journey.visited.map((spot) => spot.spotId),
        skipped_spots: journey.skipped.map((spot) => spot.spotId),
        estimated_remaining_minutes: isActive ? journey.estimatedRemainingMinutes : 0,
        details,
      })
    } catch (error) {
      console.warn('行程事件记录失败:', error)
    }
  }, [sessionId])

  const openStartRoute = async (route: RouteListItem) => {
    if (activeJourney) {
      const confirmed = await Dialog.confirm({
        title: '切换游览路线？',
        content: `当前正在游览「${activeJourney.routeName}」，切换后会保存本次部分足迹。`,
        confirmText: '结束并切换',
        cancelText: '继续当前路线',
      })
      if (!confirmed) return
      const ended = finishJourney('ended')
      if (ended) void recordJourneyEvent('ended', ended, activeJourney.currentSpot?.id)
    }
    setStartDuration(null)
    setStartMobility('normal')
    setStartAccessibility(false)
    setStartSheetRoute(route)
  }

  const confirmStartRoute = async () => {
    if (!startSheetRoute || startLoading) return
    setStartLoading(true)
    try {
      const plan = await api.post<JourneyPlan>(`/routes/${startSheetRoute.id}/plan`, {
        spot_id: locatedSpotId || undefined,
        visited_spots: visitedSpotIds,
        skipped_spots: [],
        duration: startDuration || undefined,
        mobility: startMobility,
        accessibility_required: startAccessibility,
      })
      if (!plan.nodes.length) {
        Toast.show({ content: plan.reasons[0] || '这条路线已没有可继续游览的节点', icon: 'fail' })
        return
      }
      const journey = startJourney({
        routeId: startSheetRoute.id,
        routeName: startSheetRoute.name,
        plan,
        currentSpot: locatedSpot,
        mobility: startMobility,
        accessibilityRequired: startAccessibility,
      })
      setStartSheetRoute(null)
      void recordJourneyEvent('started', journey, journey.currentSpot?.id, {
        requested_duration: startDuration,
        mobility: startMobility,
        accessibility_required: startAccessibility,
      })
      const first = journey.remainingNodes[0]
      const opening = first.phase === 'arrived'
        ? `我已开始「${journey.routeName}」，现在就在第一站「${first.spotName}」。请用80字以内介绍整体节奏，并告诉我本站先看什么。`
        : `我已开始「${journey.routeName}」。请用80字以内介绍整体节奏，并引导我前往第一站「${first.spotName}」。`
      void sendMessage(opening, journey.currentSpot?.id, selectedAvatar, journey.routeId, 'brief')
      Toast.show({ content: '行程已开始，数字人会全程陪伴', icon: 'success' })
    } catch {
      Toast.show({ content: '行程规划失败，请稍后重试', icon: 'fail' })
    } finally {
      setStartLoading(false)
    }
  }

  const arriveAtCurrent = useCallback((spotId?: string, spotName?: string) => {
    const arrived = arriveAtNext(spotId, spotName)
    const journey = useJourneyStore.getState().activeJourney
    if (!arrived || !journey) return
    setPendingLocation(null)
    void recordJourneyEvent('arrived', journey, arrived.spotId)
    void sendMessage(
      `我已到达路线节点「${arrived.spotName}」。请用80字以内讲最值得看的两点和一条现场游览提醒。`,
      arrived.spotId,
      selectedAvatar,
      journey.routeId,
      'brief',
    )
    Toast.show({ content: `已到达 ${arrived.spotName}，数字人正在讲解`, icon: 'success' })
  }, [arriveAtNext, recordJourneyEvent, selectedAvatar, sendMessage])

  const handleCompleteSpot = () => {
    const before = useJourneyStore.getState().activeJourney
    if (!before) return
    const result = completeCurrentSpot()
    if (!result.spot) return
    const after = useJourneyStore.getState().activeJourney
    void recordJourneyEvent('spot_completed', after || result.completedJourney || before, result.spot.spotId)
    if (useJourneyStore.getState().visitedSpotIds.length >= 3) addBadge('walker')
    if (result.completedJourney) {
      setCompletionSummary(result.completedJourney)
      void recordJourneyEvent('completed', result.completedJourney, result.spot.spotId)
      return
    }
    Toast.show({ content: `已完成 ${result.spot.spotName}，下一站已更新`, icon: 'success' })
  }

  const handleSkipSpot = () => {
    const before = useJourneyStore.getState().activeJourney
    if (!before) return
    const result = skipNextSpot()
    if (!result.spot) return
    const after = useJourneyStore.getState().activeJourney
    void recordJourneyEvent('spot_skipped', after || result.completedJourney || before, result.spot.spotId)
    if (result.completedJourney) {
      setCompletionSummary(result.completedJourney)
      void recordJourneyEvent('completed', result.completedJourney, before.currentSpot?.id)
      return
    }
    Toast.show({ content: `已跳过 ${result.spot.spotName}` })
  }

  const replanJourney = async (
    trigger: 'tired' | 'time' | 'location',
    locationResult?: LocationResult,
  ) => {
    const journey = useJourneyStore.getState().activeJourney
    if (!journey || replanLoading) return
    setReplanLoading(trigger)
    const requestedDuration = trigger === 'time' ? 30 : journey.requestedDuration
    const mobility = trigger === 'tired' ? 'low' : journey.mobility
    try {
      const plan = await api.post<JourneyPlan>(`/routes/${journey.routeId}/plan`, {
        spot_id: locationResult?.spot_id || journey.currentSpot?.id || undefined,
        visited_spots: visitedSpotIds,
        skipped_spots: journey.skipped.map((spot) => spot.spotId),
        duration: requestedDuration || undefined,
        mobility,
        accessibility_required: journey.accessibilityRequired,
      })
      if (!plan.nodes.length) {
        const completed = finishJourney('completed')
        if (completed) {
          setCompletionSummary(completed)
          void recordJourneyEvent('completed', completed, journey.currentSpot?.id, { trigger })
        }
        return
      }
      applyReplan(plan, { mobility, requestedDuration })
      const updated = useJourneyStore.getState().activeJourney
      if (!updated) return
      setPendingLocation(null)
      void recordJourneyEvent('replanned', updated, updated.currentSpot?.id, {
        trigger,
        reasons: plan.reasons,
      })
      if (trigger === 'location' && updated.remainingNodes[0]?.phase === 'arrived') {
        const arrived = updated.remainingNodes[0]
        void recordJourneyEvent('arrived', updated, arrived.spotId, { source: locationResult?.source })
        void sendMessage(
          `我已切换到路线节点「${arrived.spotName}」。请简要介绍两项看点，并告诉我后续怎么走。`,
          arrived.spotId,
          selectedAvatar,
          updated.routeId,
          'brief',
        )
      }
      Toast.show({
        content: trigger === 'tired'
          ? `已按轻松节奏缩短为 ${plan.nodes.length} 站`
          : trigger === 'time'
            ? `已重排为30分钟内的 ${plan.nodes.length} 站`
            : `已从 ${locationResult?.spot_name || '当前位置'} 继续`,
        icon: 'success',
      })
    } catch {
      Toast.show({ content: '路线重规划失败，请稍后重试', icon: 'fail' })
    } finally {
      setReplanLoading(null)
    }
  }

  const handleLocationResolved = useCallback((result: LocationResult, fresh: boolean) => {
    if (result.status === 'matched' && result.spot_id && result.spot_name) {
      setLocatedSpot({ id: result.spot_id, name: result.spot_name })
    } else {
      setLocatedSpot(null)
    }
    if (!fresh || result.status !== 'matched' || !result.spot_id) return
    const journey = useJourneyStore.getState().activeJourney
    if (!journey) return
    const nodeIndex = journey.remainingNodes.findIndex((node) => node.spotId === result.spot_id)
    if (nodeIndex < 0) return
    const canArriveDirectly = nodeIndex === 0 && (result.source !== 'gps' || result.confidence >= 0.7)
    if (canArriveDirectly) {
      arriveAtCurrent(result.spot_id, result.spot_name || undefined)
      return
    }
    setPendingLocation(result)
  }, [arriveAtCurrent])

  const askSpot = async (node: RouteNode, routeId: string) => {
    setSpotAskLoading(node.id)
    setSpotAnswers((prev) => ({ ...prev, [node.id]: undefined }))
    try {
      const answer = await sendMessage(
        `请介绍路线节点「${node.spot_name}」，重点讲它的文化背景、看点和游览提醒。`,
        node.spot_id,
        selectedAvatar,
        routeId
      )
      if (answer?.content.trim()) {
        setSpotAnswers((prev) => ({ ...prev, [node.id]: answer }))
        Toast.show({ content: '数字人已回复', position: 'center' })
      } else {
        Toast.show({ content: '暂未收到回复，请重试', position: 'center' })
      }
    } finally {
      setSpotAskLoading(null)
    }
  }

  // 格式化时间
  const formatDuration = (minutes: number) => {
    if (!minutes) return '待确认'
    if (minutes < 60) return `${minutes}分钟`
    const hours = Math.floor(minutes / 60)
    const rest = minutes % 60
    return rest ? `${hours}小时${rest}分钟` : `${hours}小时`
  }

  // 格式化距离
  const formatDistance = (meters: number) => {
    if (!meters) return '待确认'
    return meters >= 1000 ? `${(meters / 1000).toFixed(1)}公里` : `${meters}米`
  }

  // 获取路线对应的前端标签
  const getRouteFrontendTags = (backendTags: string[]) => {
    return mapBackendTagsToFrontend(backendTags)
  }

  const getRecommendationLabel = (route: RouteListItem) => {
    if (route.recommend_mode === 'default_hot') return '热门推荐'
    if (route.recommend_mode === 'location') return '就近推荐'
    const score = route.match_score ?? 0
    if (score >= 90) return '高度匹配'
    if (score >= 82) return '较匹配'
    return '可参考'
  }

  const getBranchTypeLabel = (type: RouteBranchNode['type']) => {
    const labelMap: Record<RouteBranchNode['type'], string> = {
      photo: '拍照',
      rest: '休息',
      culture: '文化',
      shortcut: '短线',
    }
    return labelMap[type]
  }

  const endActiveJourney = async () => {
    const journey = useJourneyStore.getState().activeJourney
    if (!journey) return
    const confirmed = await Dialog.confirm({
      title: '结束当前行程？',
      content: '已到访景点会保留在“我的足迹”，未完成节点不会计入到访。',
      confirmText: '保存并结束',
      cancelText: '继续游览',
    })
    if (!confirmed) return
    const ended = finishJourney('ended')
    if (ended) {
      setCompletionSummary(ended)
      void recordJourneyEvent('ended', ended, journey.currentSpot?.id)
    }
  }

  const confirmPendingLocation = () => {
    if (!pendingLocation?.spot_id) return
    const journey = useJourneyStore.getState().activeJourney
    const nodeIndex = journey?.remainingNodes.findIndex((node) => node.spotId === pendingLocation.spot_id) ?? -1
    if (nodeIndex === 0) {
      arriveAtCurrent(pendingLocation.spot_id, pendingLocation.spot_name || undefined)
      return
    }
    void replanJourney('location', pendingLocation)
  }

  const journeyProgress = getJourneyProgress(activeJourney)
  const nextJourneyNode = activeJourney?.remainingNodes[0]
  const followingJourneyNode = activeJourney?.remainingNodes[1]

  return (
    <div className="route-page">
      <div className="route-live-status" role="status" aria-live="polite" aria-atomic="true">
        {loading
          ? '正在更新推荐路线'
          : activeJourney && nextJourneyNode
            ? `当前行程下一站 ${nextJourneyNode.spotName}，预计剩余 ${activeJourney.estimatedRemainingMinutes} 分钟`
            : `已显示 ${routes.length} 条推荐路线`}
      </div>
      {/* 页面标题 */}
      <div className="route-header">
        <h1>路线推荐</h1>
      </div>

      {activeJourney && nextJourneyNode && (
        <section className="journey-companion" aria-labelledby="journey-companion-title">
          <div className="journey-companion-head">
            <div>
              <span className="journey-live-badge"><i /> 数字人陪游中</span>
              <h2 id="journey-companion-title">{activeJourney.routeName}</h2>
              <p>
                已完成 {activeJourney.visited.length} 站
                {activeJourney.skipped.length > 0 ? ` · 跳过 ${activeJourney.skipped.length} 站` : ''}
                {' · '}预计还需 {activeJourney.estimatedRemainingMinutes} 分钟
              </p>
            </div>
            <strong className="journey-progress-value">{journeyProgress}%</strong>
          </div>
          <div className="journey-progress-track" aria-label={`行程进度 ${journeyProgress}%`}>
            <span style={{ width: `${journeyProgress}%` }} />
          </div>

          <div className="journey-current-grid">
            <div className={nextJourneyNode.phase === 'arrived' ? 'active' : ''}>
              <span>{nextJourneyNode.phase === 'arrived' ? '当前景点' : '下一站'}</span>
              <strong>{nextJourneyNode.spotName}</strong>
              <small>建议停留 {nextJourneyNode.stayTime} 分钟</small>
            </div>
            <div>
              <span>后续安排</span>
              <strong>{followingJourneyNode?.spotName || '完成本次行程'}</strong>
              <small>剩余 {activeJourney.remainingNodes.length} 个节点</small>
            </div>
          </div>

          {pendingLocation?.spot_id && (
            <div className="journey-location-notice" role="status">
              <div>
                <strong>定位到 {pendingLocation.spot_name}</strong>
                <span>
                  {activeJourney.remainingNodes[0]?.spotId === pendingLocation.spot_id
                    ? 'GPS 匹配置信度较低，请确认是否已经到站。'
                    : '该景点位于本路线后续，可从这里重新编排行程。'}
                </span>
              </div>
              <button type="button" onClick={confirmPendingLocation} disabled={replanLoading !== null}>
                {replanLoading === 'location' ? '重排中...' : '确认并继续'}
              </button>
              <button type="button" className="plain" onClick={() => setPendingLocation(null)}>忽略</button>
            </div>
          )}

          <div className="journey-primary-actions">
            {nextJourneyNode.phase === 'arrived' ? (
              <button type="button" className="primary" onClick={handleCompleteSpot}>完成本站，去下一站</button>
            ) : (
              <button type="button" className="primary" onClick={() => arriveAtCurrent()}>我已到达</button>
            )}
            <button type="button" onClick={handleSkipSpot}>跳过此站</button>
          </div>
          <div className="journey-adjust-actions">
            <button type="button" onClick={() => void replanJourney('tired')} disabled={replanLoading !== null}>
              {replanLoading === 'tired' ? '正在缩短...' : '我有点累'}
            </button>
            <button type="button" onClick={() => void replanJourney('time')} disabled={replanLoading !== null}>
              {replanLoading === 'time' ? '正在重排...' : '只剩30分钟'}
            </button>
            <button type="button" className="journey-end" onClick={() => void endActiveJourney()}>结束行程</button>
          </div>
          {!!activeJourney.latestReasons.length && (
            <p className="journey-plan-reason">{activeJourney.latestReasons[activeJourney.latestReasons.length - 1]}</p>
          )}
        </section>
      )}

      {/* 兴趣标签选择 */}
      <section className="interest-section" aria-labelledby="route-interest-title">
        <div className="interest-section-head">
          <h2 id="route-interest-title">兴趣偏好</h2>
          {selectedTags.length > 0 && (
            <button className="btn-clear-profile" type="button" onClick={clearInterestProfile}>
              清空 {selectedTags.length} 项
            </button>
          )}
        </div>
        <div className="tag-grid">
          {interestTags.map((tag) => (
            <motion.button
              key={tag.key}
              className={`interest-tag ${
                selectedTags.includes(tag.key) ? 'active' : ''
              }`}
              whileTap={{ scale: 0.95 }}
              onClick={() => toggleTag(tag.key)}
              aria-pressed={selectedTags.includes(tag.key)}
            >
              <span className="tag-icon" aria-hidden="true">{tag.icon}</span>
              <span className="tag-label">{tag.label}</span>
            </motion.button>
          ))}
        </div>
      </section>

      <LocationLocator onSpotChange={setLocatedSpotId} onResolved={handleLocationResolved} />

      {/* 路线列表 */}
      <div className="route-list">
        <h2 className="section-label">
          推荐路线
          <span className="route-count">({routes.length}条)</span>
        </h2>

        {/* 加载状态 */}
        {loading && (
          <div className="loading-state">
            <SpinLoading color="primary" />
            <p>正在加载路线...</p>
          </div>
        )}

        {/* 路线卡片 */}
        {!loading && routes.map((route, index) => {
          const frontendTags = getRouteFrontendTags(route.tags)
          const detail = routeDetails[route.id]
          const isExpanded = expandedRoute === route.id

          return (
            <motion.div
              key={route.id}
              className={`route-card ${isExpanded ? 'expanded' : ''}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
            >
              {/* 路线封面 */}
              <div className="route-cover">
                <img
                  src={getCoverImage(route.id, route.name)}
                  alt={route.name}
                />
                <div className="route-cover-overlay" />
                <div className="route-cover-content">
                  <h3>{route.name}</h3>
                  <p>{route.description}</p>
                </div>
              </div>

              {/* 路线基本信息 */}
              <div className="route-info">
                <div className="route-meta">
                  <span className="meta-item">
                    <ClockCircleOutline />
                    {formatDuration(route.total_time)}
                  </span>
                  <span className="meta-item">
                    <EnvironmentOutline />
                    {formatDistance(route.total_distance)}
                  </span>
                  <span className="meta-item">
                    <StarOutline />
                    {difficultyMap[route.difficulty] || route.difficulty}
                  </span>
                </div>
                {(route.recommend_reason || route.recommend_mode || frontendTags.length > 0) && (
                  <div className="route-reason">
                    <div className={`route-score route-score-${route.recommend_mode || 'default'}`}>
                      {getRecommendationLabel(route)}
                    </div>
                    {/* 兴趣标签与推荐理由融合为一行展示，与封面描述去重，超长省略 */}
                    <div className="route-reason-text">
                      {[
                        ...frontendTags
                          .map((tagKey) => interestTags.find((t) => t.key === tagKey)?.label)
                          .filter(Boolean),
                        ...(route.recommend_reason && route.recommend_reason !== route.description
                          ? [route.recommend_reason]
                          : []),
                      ].join(' · ') || '按当前兴趣推荐'}
                    </div>
                  </div>
                )}
                {route.explanation_focus && route.explanation_focus.length > 0 && (
                  <div className="route-focus">
                    {route.explanation_focus.map((focus) => (
                      <span key={focus}>{focus}</span>
                    ))}
                  </div>
                )}
              </div>

              {/* 展开的路线详情 */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    className="route-detail"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3 }}
                  >
                    <div className="detail-divider" />

                    {/* 详情加载中 */}
                    {detailLoading[route.id] && (
                      <div className="detail-loading">
                        <SpinLoading color="primary" />
                        <p>正在加载详情...</p>
                      </div>
                    )}

                    {/* 路线详情 */}
                    {!detailLoading[route.id] && detail && (
                      <>
                        <section className="detail-section">
                          <h4 className="detail-title">主线节点</h4>
                          <Steps direction="vertical">
                            {detail.nodes.map((node, idx) => (
                              <Steps.Step
                                key={node.id}
                                title={node.spot_name}
                                description={
                                  <div className="node-description">
                                    <span>{node.description}</span>
                                    <em>建议停留 {node.stay_time} 分钟</em>
                                    <button
                                      type="button"
                                      onClick={() => askSpot(node, route.id)}
                                      disabled={Boolean(spotAskLoading)}
                                    >
                                      {spotAskLoading === node.id ? '查询中...' : '问数字人'}
                                    </button>
                                    {spotAnswers[node.id] && (
                                      <div className="route-node-answer" aria-live="polite">
                                        <strong>{selectedAvatar}答复</strong>
                                        <p>{spotAnswers[node.id]?.content}</p>
                                        <div className="route-answer-meta">
                                          {typeof spotAnswers[node.id]?.confidence === 'number' && (
                                            <span className={(spotAnswers[node.id]?.confidence || 0) < 0.6 ? 'low' : ''}>
                                              可信度 {Math.round((spotAnswers[node.id]?.confidence || 0) * 100)}%
                                            </span>
                                          )}
                                          {spotAnswers[node.id]?.answerType && <span>{spotAnswers[node.id]?.answerType}</span>}
                                        </div>
                                        {(spotAnswers[node.id]?.retrievedDocs || []).length > 0 && (
                                          <details className="route-answer-sources">
                                            <summary>查看答案依据 · {spotAnswers[node.id]?.retrievedDocs?.length} 条</summary>
                                            {spotAnswers[node.id]?.retrievedDocs?.slice(0, 3).map((doc, sourceIndex) => (
                                              <div key={`${doc.chunk_id || sourceIndex}`}>
                                                <b>{doc.doc_title || '景区资料'}</b>
                                                <span>{doc.content}</span>
                                              </div>
                                            ))}
                                          </details>
                                        )}
                                        {typeof spotAnswers[node.id]?.confidence === 'number'
                                          && (spotAnswers[node.id]?.confidence || 0) < 0.6 && (
                                            <small>当前证据匹配度偏低，建议结合景区当天公告或向工作人员确认。</small>
                                          )}
                                      </div>
                                    )}
                                  </div>
                                }
                                icon={
                                  idx === 0 ? (
                                    <div className="step-icon start">起</div>
                                  ) : idx === detail.nodes.length - 1 ? (
                                    <div className="step-icon end">终</div>
                                  ) : (
                                    <div className="step-icon">{idx + 1}</div>
                                  )
                                }
                              />
                            ))}
                          </Steps>
                        </section>

                        {!!detail.branch_nodes?.length && (
                          <section className="detail-section">
                            <h4 className="detail-title">可选支线</h4>
                            <div className="branch-list">
                              {detail.branch_nodes.map((branch) => (
                                <div key={`${branch.type}-${branch.title}`} className={`branch-item branch-${branch.type}`}>
                                  <div className="branch-item-head">
                                    <span>{getBranchTypeLabel(branch.type)}</span>
                                    <strong>{branch.title}</strong>
                                  </div>
                                  <p>{branch.description}</p>
                                  <div className="branch-meta">
                                    {branch.near_spot && <span>靠近 {branch.near_spot}</span>}
                                    {branch.extra_time !== null && branch.extra_time !== undefined && (
                                      <span>{branch.extra_time > 0 ? `约多 ${branch.extra_time} 分钟` : '可直接缩短行程'}</span>
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </section>
                        )}

                        {!!detail.route_notes?.length && (
                          <section className="detail-section route-notes">
                            <h4 className="detail-title">游览提醒</h4>
                            <ul>
                              {detail.route_notes.map((note) => (
                                <li key={note}>{note}</li>
                              ))}
                            </ul>
                          </section>
                        )}

                        {!!detail.rest_tips?.length && (
                          <section className="detail-section rest-tips">
                            <h4 className="detail-title">休息补给</h4>
                            <ul>
                              {detail.rest_tips.map((tip) => (
                                <li key={tip}>{tip}</li>
                              ))}
                            </ul>
                          </section>
                        )}
                      </>
                    )}

                    {/* 开始路线按钮 */}
                    <motion.button
                      className="btn-start-route"
                      whileTap={{ scale: 0.96 }}
                      onClick={() => void openStartRoute(route)}
                    >
                      {activeJourney?.routeId === route.id ? '当前正在游览' : '开始此路线'}
                    </motion.button>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* 展开/收起按钮 */}
              <button
                className="expand-btn"
                onClick={() => toggleExpand(route.id)}
              >
                {isExpanded ? '收起详情' : '查看详情'}
                <span
                  className={`expand-arrow ${
                    isExpanded ? 'up' : ''
                  }`}
                >
                  ▼
                </span>
              </button>
            </motion.div>
          )
        })}
      </div>

      {/* 空状态 */}
      {!loading && routes.length === 0 && (
        <div className="empty-state">
          <span className="empty-icon">🔍</span>
          <p>没有找到符合条件的路线</p>
          <button
            className="btn-reset"
            onClick={clearInterestProfile}
          >
            重置筛选
          </button>
        </div>
      )}

      <Popup
        visible={Boolean(startSheetRoute)}
        onMaskClick={() => !startLoading && setStartSheetRoute(null)}
        onClose={() => !startLoading && setStartSheetRoute(null)}
        bodyClassName="journey-start-popup"
        position="bottom"
      >
        <div className="journey-start-sheet">
          <span className="journey-sheet-kicker">开始数字人陪游</span>
          <h3>{startSheetRoute?.name}</h3>

          <label>可用时间</label>
          <div className="journey-option-grid duration">
            {[
              { label: '不限', value: null },
              { label: '1小时', value: 60 },
              { label: '2小时', value: 120 },
              { label: '3小时', value: 180 },
            ].map((option) => (
              <button
                key={option.label}
                type="button"
                className={startDuration === option.value ? 'active' : ''}
                onClick={() => setStartDuration(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>

          <label>体力节奏</label>
          <div className="journey-option-grid mobility">
            <button type="button" className={startMobility === 'normal' ? 'active' : ''} onClick={() => setStartMobility('normal')}>
              正常游览
            </button>
            <button type="button" className={startMobility === 'low' ? 'active' : ''} onClick={() => setStartMobility('low')}>
              轻松少走
            </button>
          </div>

          <div className="journey-accessibility-row">
            <div>
              <strong>无障碍优先</strong>
              <span>减少连续步行和高强度节点</span>
            </div>
            <Switch checked={startAccessibility} onChange={setStartAccessibility} />
          </div>

          <button className="journey-start-confirm" type="button" onClick={() => void confirmStartRoute()} disabled={startLoading}>
            {startLoading ? <><SpinLoading color="currentColor" /> 正在生成路线</> : '生成计划并开始陪游'}
          </button>
        </div>
      </Popup>

      <Popup
        visible={Boolean(completionSummary)}
        onMaskClick={() => setCompletionSummary(null)}
        onClose={() => setCompletionSummary(null)}
        bodyClassName="journey-summary-popup"
        position="bottom"
      >
        {completionSummary && (
          <div className="journey-summary-sheet">
            <div className="journey-summary-mark">✓</div>
            <span>{completionSummary.result === 'completed' ? '本次行程已完成' : '本次足迹已保存'}</span>
            <h3>{completionSummary.routeName}</h3>
            <div className="journey-summary-stats">
              <div><strong>{completionSummary.visited.length}</strong><span>到访景点</span></div>
              <div><strong>{completionSummary.skipped.length}</strong><span>跳过节点</span></div>
              <div><strong>{Math.max(1, Math.round((completionSummary.endedAt - completionSummary.startedAt) / 60000))}</strong><span>陪游分钟</span></div>
            </div>
            <div className="journey-summary-spots">
              {completionSummary.visited.length
                ? completionSummary.visited.map((spot) => <span key={`${spot.spotId}-${spot.recordedAt}`}>{spot.spotName}</span>)
                : <p>本次尚未确认到访景点。</p>}
            </div>
            <div className="journey-summary-actions">
              <button
                type="button"
                className="primary"
                onClick={() => {
                  const spotNames = completionSummary.visited.map((spot) => spot.spotName).join('、') || '本次路线'
                  void sendMessage(
                    `请用80字以内总结我刚完成的「${completionSummary.routeName}」行程。我到访了：${spotNames}，结尾鼓励我继续探索。`,
                    completionSummary.visited[completionSummary.visited.length - 1]?.spotId,
                    selectedAvatar,
                    completionSummary.routeId,
                    'brief',
                  )
                  setCompletionSummary(null)
                }}
              >
                让{selectedAvatar}总结
              </button>
              <button type="button" onClick={() => setCompletionSummary(null)}>稍后查看足迹</button>
            </div>
          </div>
        )}
      </Popup>
    </div>
  )
}

function getCoverImage(routeId: string, routeName: string): string {
  const covers: Record<string, string> = {
    'route-history': '/assets/routes/route-history.webp',
    'route-nature': '/assets/routes/route-nature.webp',
    'route-family': '/assets/routes/route-family.webp',
    'route-photo': '/assets/routes/route-photo.webp',
    'route-zen': '/assets/routes/route-zen.webp',
  }
  if (covers[routeId]) return covers[routeId]
  if (routeName.includes('历史') || routeName.includes('文化')) return covers['route-history']
  if (routeName.includes('自然') || routeName.includes('风光')) return covers['route-nature']
  if (routeName.includes('亲子') || routeName.includes('家庭')) return covers['route-family']
  if (routeName.includes('摄影') || routeName.includes('拍照')) return covers['route-photo']
  if (routeName.includes('禅修') || routeName.includes('静心')) return covers['route-zen']
  if (routeName.includes('梵宫') || routeName.includes('艺术')) return '/assets/scenery/lingshan-palace.jpg'
  if (routeName.includes('大佛') || routeName.includes('朝圣')) return '/assets/scenery/lingshan-buddha.jpg'
  return '/assets/scenery/lingshan-scenic.jpg'
}
