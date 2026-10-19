export type AvatarChannelOwnerType = 'visitor' | 'admin_preview' | 'showcase_probe'
export type AvatarChannelStatus = 'idle' | 'occupied' | 'cooldown' | 'revoking' | 'revoked' | 'acquired'

export interface AvatarChannelResponse {
  status: AvatarChannelStatus
  owner_type?: AvatarChannelOwnerType | null
  lease_token?: string | null
  retry_after_ms: number
  message: string
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''
const CHANNEL_URL = `${API_BASE}/api/v1/avatar/channel`

async function channelRequest(
  path: string,
  body?: Record<string, string>,
): Promise<AvatarChannelResponse> {
  const response = await fetch(`${CHANNEL_URL}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    keepalive: path === '/release',
  })
  if (!response.ok) throw new Error(`数字人通道协调请求失败（${response.status}）`)
  return response.json() as Promise<AvatarChannelResponse>
}

export const acquireAvatarChannel = (ownerId: string, ownerType: AvatarChannelOwnerType) => (
  channelRequest('/acquire', { owner_id: ownerId, owner_type: ownerType })
)

export const heartbeatAvatarChannel = (leaseToken: string) => (
  channelRequest('/heartbeat', { lease_token: leaseToken })
)

export const releaseAvatarChannel = (leaseToken: string) => (
  channelRequest('/release', { lease_token: leaseToken })
)

export const getAvatarChannel = () => channelRequest('')

export function releaseAvatarChannelBeacon(leaseToken: string): boolean {
  if (!leaseToken || !navigator.sendBeacon) return false
  const payload = new Blob(
    [JSON.stringify({ lease_token: leaseToken })],
    { type: 'application/json' },
  )
  return navigator.sendBeacon(`${CHANNEL_URL}/release`, payload)
}
