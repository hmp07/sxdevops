import axios from 'axios'
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'agdevops_token'
const USER_KEY = 'agdevops_user'
let isHandlingSessionExpired = false

const request = axios.create({
    baseURL: '/api',
    timeout: 15000,
})

function redirectToLogin() {
    if (window.location.pathname.startsWith('/login')) return
    const redirect = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.href = `/login?redirect=${redirect}`
}

function handleSessionExpired() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)

    if (isHandlingSessionExpired) return
    isHandlingSessionExpired = true
    ElMessage.error('登录状态已过期，请重新登录')
    window.setTimeout(() => {
        redirectToLogin()
        isHandlingSessionExpired = false
    }, 700)
}

request.interceptors.request.use((config) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
        config.headers = config.headers || {}
        config.headers.Authorization = `Token ${token}`
    }
    return config
})

request.interceptors.response.use(
    (response) => response.data,
    (error) => {
        const status = error.response?.status
        const requestUrl = String(error.config?.url || '')
        const isProfileRequest = requestUrl.includes('/auth/me/')
        const msg = error.response?.data?.detail || error.message || '请求失败'

        if (status === 401 && !isProfileRequest) {
            handleSessionExpired()
        } else if (!(status === 401 && isProfileRequest)) {
            ElMessage.error(msg)
        }

        return Promise.reject(error)
    }
)

export default request
