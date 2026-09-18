import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getCurrentUser, login as loginApi, logout as logoutApi } from '@/api/modules/rbac'

const TOKEN_KEY = 'sxdevops_token'
const USER_KEY = 'sxdevops_user'
// 会话存储：浏览器关闭即清除，重开必须重新登录认证（安全加固）
const sessionStore = window.sessionStorage

function loadStoredUser() {
  try {
    const raw = sessionStore.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    sessionStore.removeItem(USER_KEY)
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(sessionStore.getItem(TOKEN_KEY) || '')
  const currentUser = ref(loadStoredUser())
  const initialized = ref(false)

  const isAuthenticated = computed(() => !!token.value && !!currentUser.value)
  const permissions = computed(() => currentUser.value?.effective_permissions || [])
  // 零权限账号：非超管且没有任何有效权限（用于 403 死循环治理）
  const hasNoAccess = computed(
    () => !!currentUser.value && !currentUser.value.is_superuser && permissions.value.length === 0
  )
  const displayName = computed(() => {
    if (!currentUser.value) return ''
    return currentUser.value.display_name || currentUser.value.username || ''
  })

  function persistToken(value) {
    token.value = value || ''
    if (token.value) {
      sessionStore.setItem(TOKEN_KEY, token.value)
    } else {
      sessionStore.removeItem(TOKEN_KEY)
    }
  }

  function persistUser(user) {
    currentUser.value = user || null
    if (currentUser.value) {
      sessionStore.setItem(USER_KEY, JSON.stringify(currentUser.value))
    } else {
      sessionStore.removeItem(USER_KEY)
    }
  }

  function setUser(user) {
    persistUser(user)
  }

  function clearSession() {
    persistToken('')
    persistUser(null)
  }

  async function bootstrap() {
    if (initialized.value) return currentUser.value
    initialized.value = true

    // 清理历史 localStorage 残留（旧版本持久化登录态，迁移到 sessionStorage 后不再使用）
    try {
      window.localStorage.removeItem(TOKEN_KEY)
      window.localStorage.removeItem(USER_KEY)
    } catch {
      /* ignore */
    }

    if (!token.value) {
      persistUser(null)
      return null
    }

    return reloadProfile({ silent: true, clearOnUnauthorized: true })
  }

  async function reloadProfile(options = {}) {
    const { silent = false, clearOnUnauthorized = true } = options
    initialized.value = true
    if (!token.value) return null
    try {
      const user = await getCurrentUser()
      setUser(user)
      return user
    } catch (error) {
      if (error?.response?.status === 401 && clearOnUnauthorized) {
        clearSession()
        return null
      }
      return silent ? currentUser.value : null
    }
  }

  async function login(payload) {
    const response = await loginApi(payload)
    persistToken(response.token)
    setUser(response.user)
    initialized.value = true
    return response
  }

  async function logout() {
    try {
      if (token.value) {
        await logoutApi()
      }
    } finally {
      clearSession()
      initialized.value = true
    }
  }

  function hasPermission(code) {
    if (!code) return true
    if (currentUser.value?.is_superuser) return true
    if (permissions.value.includes('*')) return true
    return permissions.value.includes(code)
  }

  function hasAnyPermission(codes = []) {
    if (!codes.length) return true
    return codes.some(code => hasPermission(code))
  }

  function hasAllPermissions(codes = []) {
    if (!codes.length) return true
    return codes.every(code => hasPermission(code))
  }

  return {
    token,
    currentUser,
    initialized,
    isAuthenticated,
    permissions,
    hasNoAccess,
    displayName,
    bootstrap,
    login,
    logout,
    clearSession,
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
    reloadProfile,
  }
})
