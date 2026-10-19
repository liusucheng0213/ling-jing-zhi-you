import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { message } from 'antd'
import { useAuthStore } from '@/stores/auth'

type ApiErrorBody = {
  message?: string
  detail?: string | Array<{ msg?: string }>
}

export function getApiErrorMessage(error: unknown, fallback = '网络请求失败'): string {
  if (!axios.isAxiosError<ApiErrorBody>(error)) return fallback
  const data = error.response?.data
  if (typeof data?.detail === 'string' && data.detail.trim()) return data.detail
  if (Array.isArray(data?.detail)) {
    const details = data.detail.map((item) => item?.msg).filter(Boolean).join('；')
    if (details) return details
  }
  return data?.message || error.message || fallback
}

/**
 * 创建axios实例，配置基础URL和超时时间
 */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// React 开发模式会复挂组件；相同的并发 GET 共享一个请求，避免大屏接口被成倍触发。
const pendingGetRequests = new Map<string, Promise<unknown>>()

function getRequestKey(url: string, config?: any): string {
  return `${url}|${config?.responseType || 'json'}|${JSON.stringify(config?.params || {})}`
}

/**
 * 请求拦截器：自动附加认证Token
 */
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = useAuthStore.getState().token
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: AxiosError) => {
    return Promise.reject(error)
  }
)

/**
 * 响应拦截器：统一错误处理
 */
client.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  (error: AxiosError) => {
    const status = error.response?.status
    const errorMessage = getApiErrorMessage(error)
    const skipErrorToast = Boolean((error.config as InternalAxiosRequestConfig & { skipErrorToast?: boolean })?.skipErrorToast)

    // 即使页面选择自行展示错误，也不能跳过登录失效后的清理与跳转。
    if (status === 401) {
      if (!skipErrorToast) message.error('登录已过期，请重新登录')
      useAuthStore.getState().logout()
      window.location.href = '/login'
      return Promise.reject(error)
    }

    if (skipErrorToast) return Promise.reject(error)

    switch (status) {
      case 403:
        message.error('权限不足')
        break
      case 404:
        message.error('请求的资源不存在')
        break
      case 500:
        message.error(errorMessage || '服务器内部错误')
        break
      default:
        message.error(errorMessage)
    }

    return Promise.reject(error)
  }
)

/**
 * 类型安全的 API 客户端
 * 响应拦截器已转换 response.data，所以返回类型为 T 而非 AxiosResponse<T>
 */
export const api = {
  get: <T = any>(url: string, config?: any): Promise<T> => {
    const key = getRequestKey(url, config)
    const pending = pendingGetRequests.get(key)
    if (pending) return pending as Promise<T>

    const request = client.get(url, config) as Promise<T>
    pendingGetRequests.set(key, request)
    request.finally(() => {
      if (pendingGetRequests.get(key) === request) pendingGetRequests.delete(key)
    })
    return request
  },
  post: <T = any>(url: string, data?: any, config?: any): Promise<T> => client.post(url, data, config) as Promise<T>,
  put: <T = any>(url: string, data?: any, config?: any): Promise<T> => client.put(url, data, config) as Promise<T>,
  delete: <T = any>(url: string, config?: any): Promise<T> => client.delete(url, config) as Promise<T>,
  patch: <T = any>(url: string, data?: any, config?: any): Promise<T> => client.patch(url, data, config) as Promise<T>,
}

export default client
