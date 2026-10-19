import { api } from '@/api/client'

export type AvatarChannelOwnerType = 'visitor' | 'admin_preview' | 'showcase_probe'
export type AvatarChannelStatus = 'idle' | 'occupied' | 'cooldown' | 'revoking' | 'revoked' | 'acquired'

export interface AvatarChannelResponse {
  status: AvatarChannelStatus
  owner_type?: AvatarChannelOwnerType | null
  lease_token?: string | null
  retry_after_ms: number
  message: string
}

export const getAvatarChannel = () => api.get<AvatarChannelResponse>('/avatar/channel')

export const acquireAvatarChannel = (ownerId: string) => api.post<AvatarChannelResponse>(
  '/avatar/channel/acquire',
  { owner_id: ownerId, owner_type: 'admin_preview' },
)

export const heartbeatAvatarChannel = (leaseToken: string) => api.post<AvatarChannelResponse>(
  '/avatar/channel/heartbeat',
  { lease_token: leaseToken },
)

export const releaseAvatarChannel = (leaseToken: string) => api.post<AvatarChannelResponse>(
  '/avatar/channel/release',
  { lease_token: leaseToken },
)

export function getAdminAvatarOwnerId(scope: string): string {
  const key = `lingjing_avatar_channel_owner_${scope}`
  const stored = sessionStorage.getItem(key)
  if (stored) return stored
  const suffix = crypto.randomUUID?.() || Math.random().toString(36).slice(2)
  const ownerId = `admin-${scope}-${suffix}`
  sessionStorage.setItem(key, ownerId)
  return ownerId
}
