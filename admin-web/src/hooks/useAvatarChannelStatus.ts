import { useCallback, useEffect, useState } from 'react'
import { getAvatarChannel, type AvatarChannelResponse } from '@/services/avatarChannel'

const INITIAL_STATUS: AvatarChannelResponse = {
  status: 'idle',
  retry_after_ms: 0,
  message: '正在读取数字人通道状态',
}

export function useAvatarChannelStatus(pollMs = 1_000) {
  const [channel, setChannel] = useState<AvatarChannelResponse>(INITIAL_STATUS)

  const refresh = useCallback(async () => {
    try {
      const result = await getAvatarChannel()
      setChannel(result)
      return result
    } catch (error) {
      console.warn('读取数字人通道状态失败:', error)
      return null
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), pollMs)
    return () => window.clearInterval(timer)
  }, [pollMs, refresh])

  return { channel, refresh }
}
