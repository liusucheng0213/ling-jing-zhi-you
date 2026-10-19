import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type JourneyMobility = 'low' | 'normal' | 'high'

export interface JourneyPlanNode {
  id: string
  spot_id: string
  spot_name: string
  original_order: number
  planned_order: number
  stay_time: number
  description?: string | null
  is_current?: boolean
}

export interface JourneyPlan {
  nodes: JourneyPlanNode[]
  estimated_duration: number
  requested_duration?: number | null
  is_trimmed: boolean
  reasons: string[]
}

export interface JourneyNode {
  id: string
  spotId: string
  spotName: string
  originalOrder: number
  plannedOrder: number
  stayTime: number
  description?: string | null
  phase: 'pending' | 'arrived'
}

export interface VisitRecord {
  spotId: string
  spotName: string
  recordedAt: number
}

export interface ActiveJourney {
  journeyId: string
  routeId: string
  routeName: string
  startedAt: number
  updatedAt: number
  currentSpot: { id: string; name: string } | null
  remainingNodes: JourneyNode[]
  visited: VisitRecord[]
  skipped: VisitRecord[]
  initialNodeCount: number
  plannedTotal: number
  estimatedRemainingMinutes: number
  requestedDuration: number | null
  mobility: JourneyMobility
  accessibilityRequired: boolean
  latestReasons: string[]
  status: 'active'
}

export interface JourneyHistory {
  journeyId: string
  routeId: string
  routeName: string
  startedAt: number
  endedAt: number
  visited: VisitRecord[]
  skipped: VisitRecord[]
  initialNodeCount: number
  completionPercent: number
  result: 'completed' | 'ended'
}

interface StartJourneyInput {
  routeId: string
  routeName: string
  plan: JourneyPlan
  currentSpot?: { id: string; name: string } | null
  mobility?: JourneyMobility
  accessibilityRequired?: boolean
}

interface JourneyStore {
  activeJourney: ActiveJourney | null
  history: JourneyHistory[]
  visitedSpotIds: string[]
  startJourney: (input: StartJourneyInput) => ActiveJourney
  arriveAtNext: (spotId?: string, spotName?: string) => JourneyNode | null
  completeCurrentSpot: () => { spot: VisitRecord | null; completedJourney: JourneyHistory | null }
  skipNextSpot: () => { spot: VisitRecord | null; completedJourney: JourneyHistory | null }
  applyReplan: (
    plan: JourneyPlan,
    settings?: { mobility?: JourneyMobility; requestedDuration?: number | null },
  ) => void
  finishJourney: (result: 'completed' | 'ended') => JourneyHistory | null
  clearHistory: () => void
}

const mapPlanNodes = (plan: JourneyPlan): JourneyNode[] => plan.nodes.map((node) => ({
  id: node.id,
  spotId: node.spot_id,
  spotName: node.spot_name,
  originalOrder: node.original_order,
  plannedOrder: node.planned_order,
  stayTime: node.stay_time,
  description: node.description,
  phase: node.is_current ? 'arrived' : 'pending',
}))

const syncLegacyVisitedSpots = (spotIds: string[]) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem('lingjing_visited_spots', JSON.stringify(spotIds))
  }
}

const readLegacyVisitedSpots = () => {
  if (typeof window === 'undefined') return []
  try {
    const value = JSON.parse(localStorage.getItem('lingjing_visited_spots') || '[]')
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

const estimateRemainingMinutes = (
  nodes: JourneyNode[],
  currentSpot: ActiveJourney['currentSpot'],
) => {
  if (!nodes.length) return 0
  const stayMinutes = nodes.reduce((total, node) => total + Math.max(1, node.stayTime), 0)
  const isAlreadyAtFirst = nodes[0].phase === 'arrived' && currentSpot?.id === nodes[0].spotId
  const transitionCount = isAlreadyAtFirst
    ? Math.max(0, nodes.length - 1)
    : currentSpot
      ? nodes.length
      : Math.max(0, nodes.length - 1)
  return stayMinutes + transitionCount * 10
}

export const getJourneyProgress = (journey: ActiveJourney | null) => {
  if (!journey) return 0
  const completed = journey.visited.length + journey.skipped.length
  const total = Math.max(1, journey.plannedTotal, completed + journey.remainingNodes.length)
  return Math.min(100, Math.round(completed / total * 100))
}

const buildHistory = (journey: ActiveJourney, result: 'completed' | 'ended'): JourneyHistory => ({
  journeyId: journey.journeyId,
  routeId: journey.routeId,
  routeName: journey.routeName,
  startedAt: journey.startedAt,
  endedAt: Date.now(),
  visited: journey.visited,
  skipped: journey.skipped,
  initialNodeCount: journey.initialNodeCount,
  completionPercent: result === 'completed' ? 100 : getJourneyProgress(journey),
  result,
})

export const useJourneyStore = create<JourneyStore>()(
  persist(
    (set, get) => ({
      activeJourney: null,
      history: [],
      visitedSpotIds: readLegacyVisitedSpots(),

      startJourney: (input) => {
        const now = Date.now()
        const nodes = mapPlanNodes(input.plan)
        const firstCurrent = nodes.find((node) => node.phase === 'arrived')
        const currentSpot = input.currentSpot
          || (firstCurrent ? { id: firstCurrent.spotId, name: firstCurrent.spotName } : null)
        const journey: ActiveJourney = {
          journeyId: `${input.routeId}-${now}`,
          routeId: input.routeId,
          routeName: input.routeName,
          startedAt: now,
          updatedAt: now,
          currentSpot,
          remainingNodes: nodes,
          visited: [],
          skipped: [],
          initialNodeCount: nodes.length,
          plannedTotal: nodes.length,
          estimatedRemainingMinutes: input.plan.estimated_duration,
          requestedDuration: input.plan.requested_duration ?? null,
          mobility: input.mobility || 'normal',
          accessibilityRequired: Boolean(input.accessibilityRequired),
          latestReasons: input.plan.reasons || [],
          status: 'active',
        }
        set({ activeJourney: journey })
        return journey
      },

      arriveAtNext: (spotId, spotName) => {
        const journey = get().activeJourney
        const next = journey?.remainingNodes[0]
        if (!journey || !next || next.phase === 'arrived' || (spotId && next.spotId !== spotId)) return null
        const arrived = { ...next, phase: 'arrived' as const }
        const currentSpot = { id: arrived.spotId, name: spotName || arrived.spotName }
        const remainingNodes = [arrived, ...journey.remainingNodes.slice(1)]
        set({
          activeJourney: {
            ...journey,
            currentSpot,
            remainingNodes,
            estimatedRemainingMinutes: estimateRemainingMinutes(remainingNodes, currentSpot),
            updatedAt: Date.now(),
          },
        })
        return arrived
      },

      completeCurrentSpot: () => {
        const journey = get().activeJourney
        const current = journey?.remainingNodes[0]
        if (!journey || !current || current.phase !== 'arrived') {
          return { spot: null, completedJourney: null }
        }
        const spot: VisitRecord = {
          spotId: current.spotId,
          spotName: current.spotName,
          recordedAt: Date.now(),
        }
        const remainingNodes = journey.remainingNodes.slice(1)
        const visited = [...journey.visited, spot]
        const visitedSpotIds = [...new Set([...get().visitedSpotIds, spot.spotId])]
        const nextJourney: ActiveJourney = {
          ...journey,
          visited,
          remainingNodes,
          estimatedRemainingMinutes: estimateRemainingMinutes(remainingNodes, journey.currentSpot),
          updatedAt: Date.now(),
        }
        syncLegacyVisitedSpots(visitedSpotIds)
        if (!remainingNodes.length) {
          const completedJourney = buildHistory(nextJourney, 'completed')
          set((state) => ({
            activeJourney: null,
            visitedSpotIds,
            history: [completedJourney, ...state.history],
          }))
          return { spot, completedJourney }
        }
        set({ activeJourney: nextJourney, visitedSpotIds })
        return { spot, completedJourney: null }
      },

      skipNextSpot: () => {
        const journey = get().activeJourney
        const current = journey?.remainingNodes[0]
        if (!journey || !current) return { spot: null, completedJourney: null }
        const spot: VisitRecord = {
          spotId: current.spotId,
          spotName: current.spotName,
          recordedAt: Date.now(),
        }
        const remainingNodes = journey.remainingNodes.slice(1)
        const nextJourney: ActiveJourney = {
          ...journey,
          skipped: [...journey.skipped, spot],
          remainingNodes,
          estimatedRemainingMinutes: estimateRemainingMinutes(remainingNodes, journey.currentSpot),
          updatedAt: Date.now(),
        }
        if (!remainingNodes.length) {
          const completedJourney = buildHistory(nextJourney, 'completed')
          set((state) => ({
            activeJourney: null,
            history: [completedJourney, ...state.history],
          }))
          return { spot, completedJourney }
        }
        set({ activeJourney: nextJourney })
        return { spot, completedJourney: null }
      },

      applyReplan: (plan, settings) => {
        const journey = get().activeJourney
        if (!journey) return
        const previousFirst = journey.remainingNodes[0]
        const remainingNodes = mapPlanNodes(plan).map((node, index) => (
          index === 0 && previousFirst?.phase === 'arrived' && previousFirst.spotId === node.spotId
            ? { ...node, phase: 'arrived' as const }
            : node
        ))
        const completed = journey.visited.length + journey.skipped.length
        const replannedCurrent = remainingNodes.find((node) => node.phase === 'arrived')
        const currentSpot = replannedCurrent
          ? { id: replannedCurrent.spotId, name: replannedCurrent.spotName }
          : journey.currentSpot
        set({
          activeJourney: {
            ...journey,
            currentSpot,
            remainingNodes,
            plannedTotal: completed + remainingNodes.length,
            estimatedRemainingMinutes: plan.estimated_duration,
            requestedDuration: settings?.requestedDuration ?? plan.requested_duration ?? journey.requestedDuration,
            mobility: settings?.mobility || journey.mobility,
            latestReasons: plan.reasons || [],
            updatedAt: Date.now(),
          },
        })
      },

      finishJourney: (result) => {
        const journey = get().activeJourney
        if (!journey) return null
        const historyItem = buildHistory(journey, result)
        set((state) => ({
          activeJourney: null,
          history: [historyItem, ...state.history],
        }))
        return historyItem
      },

      clearHistory: () => set({ history: [] }),
    }),
    {
      name: 'lingjing-route-journey',
      version: 1,
      partialize: (state) => ({
        activeJourney: state.activeJourney,
        history: state.history,
        visitedSpotIds: state.visitedSpotIds,
      }),
    },
  ),
)
