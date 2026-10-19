import { useEffect, useState } from 'react'
import { ListChecks, LocateFixed, MapPin, QrCode } from 'lucide-react'
import { SpinLoading, Toast } from 'antd-mobile'
import { api } from '../../api/client'

const LOCATION_CACHE_KEY = 'lingjing_current_location'

interface LocationSpotOption {
  id: string
  name: string
  scenic_area: string
  has_coordinates: boolean
  coordinate_status: 'verified' | 'estimated' | null
  coordinate_system: string | null
  coordinate_accuracy_meters: number | null
}

interface LocationAttempt {
  source: 'gps' | 'qr' | 'manual'
  status: 'matched' | 'unknown' | 'unavailable' | 'invalid'
  message: string
}

export interface LocationResult {
  source: 'gps' | 'qr' | 'manual' | 'unknown'
  tier: number
  status: 'matched' | 'unknown'
  spot_id: string | null
  spot_name: string | null
  confidence: number
  accuracy_meters: number | null
  distance_meters: number | null
  method: string
  coordinates_available: boolean
  coordinate_status: 'verified' | 'estimated' | null
  coordinate_system: string | null
  coordinate_source: string | null
  coordinate_accuracy_meters: number | null
  coordinate_verified_at: string | null
  message: string
  attempts: LocationAttempt[]
}

interface LocationLocatorProps {
  onSpotChange: (spotId: string | null) => void
  onResolved?: (result: LocationResult, fresh: boolean) => void
}

const sourceLabels: Record<LocationResult['source'], string> = {
  gps: 'GPS',
  qr: '二维码',
  manual: '手动',
  unknown: '未定位',
}

function readCachedLocation(): LocationResult | null {
  try {
    return JSON.parse(localStorage.getItem(LOCATION_CACHE_KEY) || 'null') as LocationResult | null
  } catch {
    return null
  }
}

export default function LocationLocator({ onSpotChange, onResolved }: LocationLocatorProps) {
  const [spots, setSpots] = useState<LocationSpotOption[]>([])
  const [result, setResult] = useState<LocationResult | null>(readCachedLocation)
  const [loading, setLoading] = useState<'gps' | 'qr' | 'manual' | null>(null)
  const [mode, setMode] = useState<'qr' | 'manual' | null>(null)
  const [feedback, setFeedback] = useState(
    () => readCachedLocation()?.message || '定位后可优先推荐含当前景点的路线。'
  )
  const [qrValue, setQrValue] = useState('')
  const [manualSpotId, setManualSpotId] = useState('')

  useEffect(() => {
    api.get<LocationSpotOption[]>('/location/spots')
      .then((data) => {
        setSpots(data)
        const cached = readCachedLocation()
        if (cached?.spot_id && data.some((spot) => spot.id === cached.spot_id)) {
          onSpotChange(cached.spot_id)
          onResolved?.(cached, false)
        } else if (cached) {
          localStorage.removeItem(LOCATION_CACHE_KEY)
          setResult(null)
          onSpotChange(null)
        }
      })
      .catch(() => {
        setFeedback('景点列表加载失败，请稍后重试。')
        Toast.show({ content: '景点列表加载失败，定位功能暂不可用', position: 'center' })
      })
  }, [onResolved, onSpotChange])

  const applyResult = (next: LocationResult, fresh = true) => {
    setResult(next)
    setFeedback(next.message)
    onResolved?.(next, fresh)
    if (next.status === 'matched' && next.spot_id) {
      localStorage.setItem(LOCATION_CACHE_KEY, JSON.stringify(next))
      onSpotChange(next.spot_id)
      setMode(null)
      return
    }
    localStorage.removeItem(LOCATION_CACHE_KEY)
    onSpotChange(null)
  }

  const resolveLocation = async (
    source: 'gps' | 'qr' | 'manual',
    payload: Record<string, unknown>,
  ) => {
    setLoading(source)
    setFeedback(source === 'gps' ? '正在匹配附近景点…' : source === 'qr' ? '正在识别二维码信息…' : '正在确认当前景点…')
    try {
      const next = await api.post<LocationResult>('/location/resolve', payload)
      applyResult(next)
      if (next.status !== 'matched') {
        setMode(source === 'qr' ? 'qr' : 'manual')
      }
    } catch {
      setFeedback('定位请求失败，请改用二维码或手动选择。')
      Toast.show({ content: '定位请求失败，请使用二维码或手动选择', position: 'center' })
    } finally {
      setLoading(null)
    }
  }

  const locateByGps = () => {
    if (!navigator.geolocation) {
      applyResult({
        source: 'unknown',
        tier: 0,
        status: 'unknown',
        spot_id: null,
        spot_name: null,
        confidence: 0,
        accuracy_meters: null,
        distance_meters: null,
        method: 'browser_unavailable',
        coordinates_available: false,
        coordinate_status: null,
        coordinate_system: null,
        coordinate_source: null,
        coordinate_accuracy_meters: null,
        coordinate_verified_at: null,
        message: '当前浏览器不支持 GPS，请使用二维码或手动选择',
        attempts: [],
      })
      setMode('manual')
      return
    }

    setLoading('gps')
    setFeedback('正在请求浏览器定位权限，请在地址栏提示中选择“允许”。')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        void resolveLocation('gps', {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
        })
      },
      (error) => {
        const denied = error.code === error.PERMISSION_DENIED
        applyResult({
          source: 'unknown',
          tier: 0,
          status: 'unknown',
          spot_id: null,
          spot_name: null,
          confidence: 0,
          accuracy_meters: null,
          distance_meters: null,
          method: 'browser_geolocation_error',
          coordinates_available: false,
          coordinate_status: null,
          coordinate_system: null,
          coordinate_source: null,
          coordinate_accuracy_meters: null,
          coordinate_verified_at: null,
          message: denied ? 'GPS 权限未开启，请使用二维码或手动选择' : 'GPS 暂时不可用，请使用二维码或手动选择',
          attempts: [],
        })
        setLoading(null)
        setMode('manual')
        Toast.show({ content: denied ? '未获得 GPS 权限，已展开手动选择' : 'GPS 暂不可用，已展开手动选择', position: 'center' })
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 30_000 },
    )
  }

  const clearLocation = () => {
    localStorage.removeItem(LOCATION_CACHE_KEY)
    setResult(null)
    setManualSpotId('')
    setQrValue('')
    setFeedback('已清除当前位置，可重新定位。')
    onSpotChange(null)
  }

  const accuracyText = [
    result?.accuracy_meters != null ? `GPS 精度约 ${Math.round(result.accuracy_meters)} 米` : null,
    result?.distance_meters != null ? `距景点约 ${Math.round(result.distance_meters)} 米` : null,
  ].filter(Boolean).join(' · ')
  const coordinateLabel = result?.coordinate_status === 'verified'
    ? '地图精确点'
    : result?.coordinate_status === 'estimated'
      ? '演示估算点'
      : null

  return (
    <section className="route-location" aria-labelledby="route-location-title">
      <div className="location-summary">
        <div className={`location-pin ${result?.status === 'matched' ? 'matched' : ''}`}>
          <MapPin size={20} aria-hidden="true" />
        </div>
        <div className="location-copy">
          <div className="location-title-row">
            <h2 id="route-location-title">当前位置</h2>
            {result && (
              <span className={`location-source source-${result.source}`}>
                {sourceLabels[result.source]}
              </span>
            )}
          </div>
          <strong>{result?.spot_name || '尚未匹配景点'}</strong>
          <p role="status" aria-live="polite">{feedback}</p>
          {accuracyText && <small>{accuracyText}</small>}
          {coordinateLabel && (
            <small className={`coordinate-quality ${result?.coordinate_status || ''}`}>
              {coordinateLabel}
              {result?.coordinate_accuracy_meters != null ? ` · 误差约 ${Math.round(result.coordinate_accuracy_meters)} 米` : ''}
            </small>
          )}
        </div>
        {result?.status === 'matched' && (
          <button className="location-clear" type="button" onClick={clearLocation}>清除</button>
        )}
      </div>

      <div className="location-actions" aria-label="选择定位方式">
        <button type="button" data-testid="location-gps" onClick={locateByGps} disabled={loading !== null}>
          {loading === 'gps' ? <SpinLoading color="currentColor" /> : <LocateFixed size={18} />}
          <span>GPS</span>
        </button>
        <button
          type="button"
          data-testid="location-qr-toggle"
          onClick={() => {
            const nextMode = mode === 'qr' ? null : 'qr'
            setMode(nextMode)
            setFeedback(nextMode ? '请粘贴二维码识别码或链接。' : '定位后可优先推荐含当前景点的路线。')
          }}
          aria-expanded={mode === 'qr'}
        >
          <QrCode size={18} />
          <span>扫码定位</span>
        </button>
        <button
          type="button"
          data-testid="location-manual-toggle"
          onClick={() => {
            const nextMode = mode === 'manual' ? null : 'manual'
            setMode(nextMode)
            setFeedback(nextMode ? '请选择当前所在景点。' : '定位后可优先推荐含当前景点的路线。')
          }}
          aria-expanded={mode === 'manual'}
        >
          <ListChecks size={18} />
          <span>选择景点</span>
        </button>
      </div>

      {mode === 'qr' && (
        <form
          className="location-choice-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (qrValue.trim()) void resolveLocation('qr', { qr_value: qrValue.trim() })
          }}
        >
          <label htmlFor="route-qr-value">二维码识别码、链接或景点编号</label>
          <div>
            <input
              id="route-qr-value"
              value={qrValue}
              onChange={(event) => setQrValue(event.target.value)}
              placeholder="例如 LS-013 或二维码链接"
              autoComplete="off"
            />
            <button type="submit" disabled={!qrValue.trim() || loading !== null}>识别</button>
          </div>
        </form>
      )}

      {mode === 'manual' && (
        <form
          className="location-choice-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (manualSpotId) void resolveLocation('manual', { manual_spot_id: manualSpotId })
          }}
        >
          <label htmlFor="route-manual-spot">选择当前所在景点</label>
          <div>
            <select
              id="route-manual-spot"
              value={manualSpotId}
              onChange={(event) => setManualSpotId(event.target.value)}
            >
              <option value="">请选择景点</option>
              {spots.map((spot) => (
                <option key={spot.id} value={spot.id}>{spot.name}（{spot.id}）</option>
              ))}
            </select>
            <button type="submit" disabled={!manualSpotId || loading !== null}>确认</button>
          </div>
        </form>
      )}
    </section>
  )
}
