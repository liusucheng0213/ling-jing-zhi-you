import axios, { AxiosInstance, AxiosError } from 'axios'

/**
 * axios 实例配置
 * 封装了请求拦截器、响应拦截器和错误处理
 */

// 创建 axios 实例
const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器 - 添加认证token等
apiClient.interceptors.request.use(
  (config) => {
    // 从本地存储获取token
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 添加设备信息
    config.headers['X-Device-Type'] = 'mobile'
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 统一错误处理
apiClient.interceptors.response.use(
  (response) => {
    return response
  },
  (error: AxiosError) => {
    if (error.response) {
      const status = error.response.status
      switch (status) {
        case 401:
          // 未授权，清除token并跳转登录
          localStorage.removeItem('access_token')
          window.location.href = '/login'
          break
        case 403:
          console.error('权限不足')
          break
        case 404:
          console.error('请求资源不存在')
          break
        case 500:
          console.error('服务器内部错误')
          break
        default:
          console.error(`请求失败: ${status}`)
      }
    } else if (error.request) {
      console.error('网络请求失败，请检查网络连接')
    } else {
      console.error('请求配置错误:', error.message)
    }
    return Promise.reject(error)
  }
)

// 封装常用请求方法
export const api = {
  get: <T>(url: string, params?: object) =>
    apiClient.get<T>(url, { params }).then((res) => res.data),

  post: <T>(url: string, data?: object) =>
    apiClient.post<T>(url, data).then((res) => res.data),

  put: <T>(url: string, data?: object) =>
    apiClient.put<T>(url, data).then((res) => res.data),

  delete: <T>(url: string) =>
    apiClient.delete<T>(url).then((res) => res.data),
}

export default apiClient
