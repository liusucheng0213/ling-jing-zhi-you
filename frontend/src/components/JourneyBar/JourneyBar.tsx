import { useNavigate } from 'react-router-dom'
import { Clock3, MapPin, Route } from 'lucide-react'
import { getJourneyProgress, useJourneyStore } from '../../stores/journey'
import './JourneyBar.css'

interface JourneyBarProps {
  mode: 'desktop' | 'mobile'
}

export default function JourneyBar({ mode }: JourneyBarProps) {
  const navigate = useNavigate()
  const journey = useJourneyStore((state) => state.activeJourney)
  if (!journey) return null

  const next = journey.remainingNodes[0]
  const progress = getJourneyProgress(journey)
  const locationLabel = next?.phase === 'arrived'
    ? `正在游览 ${next.spotName}`
    : next
      ? `下一站 ${next.spotName}`
      : '即将完成行程'

  return (
    <button
      type="button"
      className={`journey-bar journey-bar-${mode}`}
      onClick={() => navigate('/route')}
      aria-label={`返回当前行程，进度${progress}%`}
    >
      <span className="journey-bar-icon"><Route size={18} /></span>
      <span className="journey-bar-copy">
        <span className="journey-bar-kicker">游览中 · {journey.routeName}</span>
        <strong><MapPin size={13} />{locationLabel}</strong>
        <span className="journey-bar-track" aria-hidden="true">
          <i style={{ width: `${progress}%` }} />
        </span>
      </span>
      <span className="journey-bar-meta">
        <b>{progress}%</b>
        <small><Clock3 size={11} />{journey.estimatedRemainingMinutes}分钟</small>
      </span>
    </button>
  )
}
