<template>
  <div class="app-layout">
    <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <img src="@/assets/brand-mark.svg" alt="SxDevOps" class="brand-mark" />
        </div>
        <div class="logo-copy">
          <span class="logo-text">SxDevOps</span>
          <span class="logo-subtext">AI Agent</span>
        </div>
      </div>

      <el-menu
        :default-active="activeMenuPath"
        class="sidebar-nav el-menu-vertical"
        :collapse="appStore.sidebarCollapsed"
        router
        :collapse-transition="false"
      >
        <template v-for="item in visibleMenuItems" :key="item.title">
          <el-sub-menu v-if="item.children?.length" :index="item.menuKey || item.title">
            <template #title>
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item
              v-for="child in item.children"
              :key="child.menuKey || child.path"
              :index="child.menuKey || child.path"
              :route="child.route || child.path"
            >
              <template #title>
                <el-icon v-if="child.icon"><component :is="child.icon" /></el-icon>
                <span>{{ child.title }}</span>
              </template>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item v-else :index="item.menuKey || item.path" :route="item.route || item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>
              <span>{{ item.title }}</span>
            </template>
          </el-menu-item>
        </template>
      </el-menu>
    </aside>

    <div class="main-area">
      <header class="header">
        <div class="header-left">
          <button class="collapse-btn" @click="appStore.toggleSidebar">
            <el-icon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></el-icon>
          </button>
          <span class="breadcrumb">{{ currentTitle }}</span>
        </div>
        <div class="header-right">
          <el-tooltip content="查看 AI Agent 产品介绍" placement="bottom">
            <button class="promo-trigger" type="button" @click="openAIAgentPromo">
              <el-icon :size="17"><Promotion /></el-icon>
              <span>产品介绍</span>
            </button>
          </el-tooltip>

          <el-tooltip v-if="canOpenAIOpsAssistant" content="打开智能助手" placement="bottom">
            <button class="assistant-trigger" type="button" @click="openAIOpsAssistant">
              <el-icon :size="18"><Service /></el-icon>
            </button>
          </el-tooltip>

          <el-popover placement="bottom-end" :width="360" trigger="click" popper-class="header-notice-popover">
            <template #reference>
              <button class="notice-trigger" type="button" @click="handleNoticeOpen">
                <el-badge :value="notificationCount" :max="99" :hidden="!notificationCount">
                  <el-icon :size="18"><Bell /></el-icon>
                </el-badge>
              </button>
            </template>

            <div class="notice-panel">
              <div class="notice-panel__header">
                <div>
                  <div class="notice-panel__title">平台提醒</div>
                  <div class="notice-panel__subtitle">
                    {{ notificationCount ? `当前有 ${notificationCount} 条待关注动态` : '当前暂无待关注动态' }}
                  </div>
                </div>
                <el-button link type="primary" :loading="notificationsLoading" @click="loadNotifications">刷新</el-button>
              </div>

              <div v-if="notificationSections.length" class="notice-groups">
                <section
                  v-for="section in notificationSections"
                  :key="section.key"
                  class="notice-group"
                >
                  <div class="notice-group__header">
                    <div class="notice-group__meta">
                      <span class="notice-group__title">{{ section.title }}</span>
                      <span class="notice-group__count">{{ section.items.length }}</span>
                    </div>
                    <el-button
                      v-if="section.route"
                      link
                      type="primary"
                      class="notice-group__more"
                      @click="goSection(section)"
                    >
                      查看更多
                    </el-button>
                  </div>
                  <div class="notice-list">
                    <button
                      v-for="item in section.items"
                      :key="item.key"
                      type="button"
                      class="notice-item"
                      @click="goNotification(item)"
                    >
                      <div class="notice-item__dot" :class="`is-${item.dotTone}`"></div>
                      <div class="notice-item__body">
                        <div class="notice-item__top">
                          <div class="notice-item__title-wrap">
                            <span class="notice-item__title">{{ item.title }}</span>
                            <el-tag size="small" effect="light" :type="item.tagType">{{ item.tag }}</el-tag>
                          </div>
                          <span class="notice-item__time">{{ formatDateTime(item.time) }}</span>
                        </div>
                        <div class="notice-item__desc">{{ item.description }}</div>
                      </div>
                    </button>
                  </div>
                </section>
              </div>
              <div v-else class="notice-empty">
                <el-icon><Bell /></el-icon>
                <span>告警、事件与高风险动态会在这里实时汇总</span>
              </div>
            </div>
          </el-popover>

          <el-dropdown @command="handleUserCommand">
            <div class="user-trigger">
              <el-avatar :size="36" class="user-avatar">
                <span>{{ userInitials }}</span>
              </el-avatar>
              <div class="user-meta">
                <span class="user-name">{{ authStore.displayName || '未登录' }}</span>
                <span class="user-role">{{ primaryRoleLabel }}</span>
              </div>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="refresh">刷新权限</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
      <AIOpsChatWidget v-if="!isAIOpsChatRoute" />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import AIOpsChatWidget from '@/components/aiops/AIOpsChatWidget.vue'
import { getDashboardStats, getDeployments, getTransactionTickets } from '@/api/modules/ops'
import { getEventWallAnalysis } from '@/api/modules/eventwall'
import { getResourceRequests } from '@/api/modules/cmdb'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const notificationsLoading = ref(false)
const notificationItems = ref([])
const notificationCount = ref(0)
let notificationTimer = null

const menuItems = [
  { path: '/dashboard', title: '仪表盘', icon: 'Odometer', permission: 'ops.dashboard.view' },
  {
    title: 'CMDB',
    icon: 'Files',
    children: [
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=items',
        route: { path: '/cmdb', query: { tab: 'items' } },
        title: '配置项管理',
        icon: 'Grid',
        permission: 'cmdb.ci.view',
      },
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=topology',
        route: { path: '/cmdb', query: { tab: 'topology' } },
        title: '资源地图',
        icon: 'Share',
        permission: 'cmdb.topology.view',
      },
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=cost',
        route: { path: '/cmdb', query: { tab: 'cost' } },
        title: '成本分析',
        icon: 'TrendCharts',
        permission: 'cmdb.cost.view',
      },
      {
        path: '/cmdb',
        menuKey: '/cmdb?tab=optimize',
        route: { path: '/cmdb', query: { tab: 'optimize' } },
        title: '资源优化',
        icon: 'Lightning',
        permission: 'cmdb.cost.view',
      },
    ],
  },
  {
    title: '主机中心',
    icon: 'Monitor',
    children: [
      {
        path: '/hosts/assets',
        title: '主机资产',
        icon: 'Monitor',
        anyPermissions: ['ops.host.view', 'ops.host.manage', 'ops.host.terminal'],
      },
      {
        path: '/hosts/tasks',
        title: '任务中心',
        icon: 'Operation',
        permission: 'ops.host.execute',
      },
      {
        path: '/hosts/schedules',
        title: '定时任务',
        icon: 'Timer',
        anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'],
      },
      {
        path: '/hosts/requests',
        title: '主机申请',
        icon: 'Ticket',
        anyPermissions: ['cmdb.request.submit', 'cmdb.request.approve'],
      },
    ],
  },
  {
    title: '多云管理',
    icon: 'MostlyCloudy',
    children: [
      { path: '/multicloud', title: '多云环境', icon: 'MostlyCloudy', permission: 'ops.multicloud.view' },
      { path: '/terraform', title: 'IaC 编排', icon: 'SetUp', permission: 'ops.iac.view' },
    ],
  },
  {
    title: '工单系统',
    icon: 'Tickets',
    children: [
      {
        path: '/workorders/releases',
        title: '应用发布',
        icon: 'Promotion',
        anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
      },
      {
        path: '/workorders/sql',
        title: 'SQL 审计',
        icon: 'DataAnalysis',
        anyPermissions: [
          'sqlaudit.datasource.view',
          'sqlaudit.order.view',
          'sqlaudit.order.submit',
          'sqlaudit.order.review',
          'sqlaudit.order.execute',
          'sqlaudit.query.view',
          'sqlaudit.query.execute',
        ],
      },
      {
        path: '/workorders/transactions',
        title: '事务工单',
        icon: 'Tickets',
        anyPermissions: ['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'],
      },
      {
        path: '/workorders/approval-flows',
        title: '审批流',
        icon: 'Checked',
        anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
      },
    ],
  },
  {
    title: '容器管理',
    icon: 'Box',
    children: [
      { path: '/containers/k8s', title: 'K8s 集群', icon: 'Connection', permission: 'ops.k8s.view' },
      { path: '/containers/docker', title: 'Docker 环境', icon: 'Platform', permission: 'ops.docker.view' },
    ],
  },
  {
    title: '中间件',
    icon: 'DataBoard',
    children: [
      { path: '/middleware/nginx', title: 'Nginx 管理', icon: 'Location', permission: 'ops.nginx.view' },
      { path: '/middleware/redis', title: 'Redis 管理', icon: 'Coin', permission: 'ops.middleware.view' },
      { path: '/middleware/rocketmq', title: 'RocketMQ 管理', icon: 'Promotion', permission: 'ops.middleware.view' },
      { path: '/middleware/elasticsearch', title: 'ES 管理', icon: 'Search', permission: 'ops.middleware.view' },
    ],
  },
  {
    title: '可观测性',
    icon: 'DataLine',
    children: [
      {
        path: '/observability/overview',
        title: '平台总览',
        icon: 'DataLine',
        anyPermissions: ['ops.observability.system_posture.view', 'ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.alert.config.view', 'ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view', 'ops.grafana.view'],
      },
      { path: '/observability/grafana', title: '监控看板', icon: 'Histogram', permission: 'ops.grafana.view' },
      { path: '/logs', title: '日志中心', icon: 'Search', anyPermissions: ['ops.log.query', 'ops.log.datasource.view'] },
      { path: '/observability/tracing', title: '链路追踪', icon: 'Connection', anyPermissions: ['ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view'] },
      { path: '/alerts', title: '告警中心', icon: 'Bell', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
    ],
  },
  {
    title: '事件中心',
    icon: 'Tickets',
    children: [
      { path: '/events/wall', title: '事件中心', icon: 'Aim', permission: 'eventwall.view' },
      { path: '/events/sources', title: '事件源', icon: 'Share', permission: 'eventwall.source.view' },
    ],
  },
  {
    path: '/marketplace',
    title: '工具市场',
    icon: 'Shop',
    anyPermissions: ['marketplace.template.view', 'marketplace.deployment.view', 'marketplace.deployment.manage'],
  },
  {
    title: 'AIOps',
    icon: 'ChatDotSquare',
    children: [
      { path: '/aiops/chat', title: '智能助手', icon: 'Service', permission: 'aiops.chat.view' },
      { path: '/aiops/knowledge', title: '知识图谱', icon: 'Share', permission: 'aiops.knowledge.view' },
      { path: '/aiops/config', title: '智能体配置', icon: 'Tools', permission: 'aiops.config.view' },
    ],
  },
  {
    title: '用户管理',
    icon: 'User',
    children: [
      {
        path: '/users',
        title: '用户管理',
        icon: 'User',
        anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view'],
      },
      { path: '/users/audit', title: '操作审计', icon: 'DocumentChecked', permission: 'rbac.audit.view' },
    ],
  },
]

function canAccess(item) {
  if (item.permission) return authStore.hasPermission(item.permission)
  if (item.anyPermissions) return authStore.hasAnyPermission(item.anyPermissions)
  return true
}

const visibleMenuItems = computed(() => {
  const mapped = menuItems
    .map((item) => {
      if (!item.children) return item
      const children = item.children.filter(canAccess)
      return { ...item, children }
    })
    .filter((item) => item.children ? item.children.length > 0 : canAccess(item))

  const marketplaceIndex = mapped.findIndex((item) => item.path === '/marketplace')
  const containerIndex = mapped.findIndex((item) => Array.isArray(item.children) && item.children.some((child) => child.path === '/containers/k8s'))

  if (marketplaceIndex === -1 || containerIndex === -1) return mapped

  const marketplaceItem = mapped[marketplaceIndex]
  const nextItems = mapped.filter((_, index) => index !== marketplaceIndex)
  const target = nextItems[containerIndex > marketplaceIndex ? containerIndex - 1 : containerIndex]
  if (!target?.children?.some((child) => child.path === '/marketplace')) {
    target.children = [...target.children, marketplaceItem]
  }
  return nextItems
})

const normalizedMenuPath = computed(() => {
  if (route.path.startsWith('/sql')) {
    return '/sql'
  }
  if (route.path.startsWith('/events/')) {
    return route.path
  }
  if (route.path.startsWith('/logs/')) {
    return '/logs'
  }
  if (route.path === '/cmdb') {
    const currentTab = typeof route.query.tab === 'string' ? route.query.tab : 'items'
    return `/cmdb?tab=${currentTab}`
  }
  return route.path
})

const activeMenuPath = computed(() => {
  return normalizedMenuPath.value
})

const currentTitle = computed(() => {
  const currentPath = normalizedMenuPath.value
  for (const item of visibleMenuItems.value) {
    if ((item.menuKey || item.path) === currentPath) return item.title
    if (item.children) {
      const child = item.children.find((entry) => (entry.menuKey || entry.path) === currentPath)
      if (child) return `${item.title} / ${child.title}`
    }
  }
  return route.meta.title || ''
})

const currentRoleLabel = computed(() => {
  const roles = authStore.currentUser?.roles || []
  if (!roles.length) return '无角色'
  return roles.map(role => role.name).join(' / ')
})

const primaryRoleLabel = computed(() => {
  const roles = authStore.currentUser?.roles || []
  if (!roles.length) return '访客'
  if (roles.length === 1) return roles[0].name
  return `${roles[0].name} +${roles.length - 1}`
})

const userInitials = computed(() => {
  const source = authStore.displayName || authStore.currentUser?.username || 'S'
  return source.slice(0, 1).toUpperCase()
})

const isAIOpsChatRoute = computed(() => route.name === 'AIOpsChat' || route.path === '/aiops/chat')
const canOpenAIOpsAssistant = computed(() => authStore.hasPermission('aiops.chat.view') && !isAIOpsChatRoute.value)

const notificationSections = computed(() => {
  const sectionOrder = ['approval', 'alert', 'event']
  const sectionTitleMap = {
    approval: '待审批清单',
    alert: '告警提醒',
    event: '关键事件',
  }
  const sectionRouteMap = {
    approval: '/workorders/releases',
    alert: '/alerts',
    event: '/events/wall',
  }
  return sectionOrder
    .map((key) => ({
      key,
      title: sectionTitleMap[key],
      route: sectionRouteMap[key],
      items: notificationItems.value.filter(item => item.section === key),
    }))
    .filter(section => section.items.length)
})

function formatDateTime(value) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function buildAlertNotificationItem(item) {
  const levelMap = {
    critical: { tag: '严重告警', tagType: 'danger' },
    warning: { tag: '告警提醒', tagType: 'warning' },
    info: { tag: '信息提醒', tagType: 'info' },
  }
  const meta = levelMap[item.level] || { tag: '平台提醒', tagType: 'info' }
  return {
    key: `alert-${item.id}`,
    section: 'alert',
    title: item.title || '告警中心通知',
    description: item.message || item.source || '请进入告警中心查看详情',
    time: item.created_at,
    route: '/alerts',
    tag: meta.tag,
    tagType: meta.tagType,
    dotTone: item.level === 'critical' ? 'danger' : item.level === 'warning' ? 'warning' : 'info',
    priority: item.level === 'critical' ? 3 : item.level === 'warning' ? 2 : 1,
  }
}

function buildDeploymentApprovalItem(item) {
  const nodeName = item.current_approval_step?.node_name || '默认审批'
  const scopeText = formatScopeText(item)
  return {
    key: `deploy-approval-${item.id}`,
    section: 'approval',
    title: `${item.app_name} / ${item.version}`,
    description: `${scopeText} · 发布审批待处理 · ${nodeName}`,
    time: item.deployed_at,
    route: '/workorders/releases',
    tag: '发布审批',
    tagType: 'warning',
    dotTone: 'warning',
    priority: 4,
  }
}

function buildTransactionApprovalItem(item) {
  const scopeText = formatScopeText(item)
  return {
    key: `transaction-approval-${item.id}`,
    section: 'approval',
    title: item.title || '事务工单待审批',
    description: `${scopeText} · 事务工单待处理 · ${item.type_display || '运维事务'}`,
    time: item.updated_at || item.created_at,
    route: '/workorders/transactions',
    tag: '事务审批',
    tagType: 'warning',
    dotTone: 'warning',
    priority: 4,
  }
}

function buildResourceRequestApprovalItem(item) {
  const scopeText = formatScopeText(item)
  const quantityText = item.quantity ? ` × ${item.quantity}` : ''
  return {
    key: `resource-approval-${item.id}`,
    section: 'approval',
    title: item.title || '主机申请待审批',
    description: `${scopeText} · ${(item.resource_type || '资源')}申请待处理${quantityText}`,
    time: item.created_at,
    route: '/hosts/requests',
    tag: '资源审批',
    tagType: 'info',
    dotTone: 'info',
    priority: 4,
  }
}

function buildEventNotificationItem(item) {
  const resultToneMap = {
    failed: { tag: '高风险事件', tagType: 'danger', priority: 3 },
    partial: { tag: '待关注事件', tagType: 'warning', priority: 2 },
    pending: { tag: '待处理事件', tagType: 'warning', priority: 2 },
  }
  const meta = resultToneMap[item.result] || { tag: '平台动态', tagType: 'info', priority: 1 }
  return {
    key: `event-${item.id}`,
    section: 'event',
    title: item.title || '事件中心动态',
    description: item.summary || item.detail || item.resource_name || '请进入事件中心查看详情',
    time: item.occurred_at,
    route: '/events/wall',
    tag: meta.tag,
    tagType: meta.tagType,
    dotTone: item.result === 'failed' ? 'danger' : item.result === 'partial' || item.result === 'pending' ? 'warning' : 'info',
    priority: meta.priority,
  }
}

function formatScopeText(item) {
  const parts = []
  if (item?.system_name || item?.business_line) parts.push(item.system_name || item.business_line)
  if (item?.environment_display) {
    parts.push(item.environment_display)
  } else if (item?.environment) {
    parts.push(item.environment)
  }
  return parts.join(' / ') || '未指定业务线 / 环境'
}

async function loadNotifications() {
  notificationsLoading.value = true
  try {
    const tasks = []
    if (authStore.hasPermission('ops.deployment.approve')) {
      tasks.push(getDeployments({ approval_status: 'pending' }))
    } else {
      tasks.push(Promise.resolve(null))
    }

    if (authStore.hasPermission('cmdb.request.approve')) {
      tasks.push(getResourceRequests({ status: 'pending' }))
    } else {
      tasks.push(Promise.resolve(null))
    }

    if (authStore.hasPermission('ops.ticket.approve')) {
      tasks.push(getTransactionTickets({ status: 'pending' }))
    } else {
      tasks.push(Promise.resolve(null))
    }

    if (authStore.hasPermission('ops.dashboard.view')) {
      tasks.push(getDashboardStats())
    } else {
      tasks.push(Promise.resolve(null))
    }

    if (authStore.hasPermission('eventwall.view')) {
      tasks.push(getEventWallAnalysis({ limit: 80 }))
    } else {
      tasks.push(Promise.resolve(null))
    }

    const [deploymentsResult, resourceRequestsResult, transactionTicketsResult, dashboardStatsResult, eventOverviewResult] = await Promise.allSettled(tasks)
    const deploymentsResponse = deploymentsResult.status === 'fulfilled' ? deploymentsResult.value : null
    const resourceRequestsResponse = resourceRequestsResult.status === 'fulfilled' ? resourceRequestsResult.value : null
    const transactionTicketsResponse = transactionTicketsResult.status === 'fulfilled' ? transactionTicketsResult.value : null
    const dashboardStats = dashboardStatsResult.status === 'fulfilled' ? dashboardStatsResult.value : null
    const eventOverview = eventOverviewResult.status === 'fulfilled' ? eventOverviewResult.value : null

    const items = []
    let total = 0

    if (deploymentsResponse) {
      const deploymentItems = Array.isArray(deploymentsResponse.results) ? deploymentsResponse.results : (deploymentsResponse || [])
      const pendingDeploymentApprovals = deploymentItems.filter(canHandleDeploymentApproval)
      items.push(...pendingDeploymentApprovals.slice(0, 3).map(buildDeploymentApprovalItem))
      total += pendingDeploymentApprovals.length
    }

    if (resourceRequestsResponse) {
      const requestItems = Array.isArray(resourceRequestsResponse.results) ? resourceRequestsResponse.results : (resourceRequestsResponse || [])
      items.push(...requestItems.slice(0, 3).map(buildResourceRequestApprovalItem))
      total += requestItems.length
    }

    if (transactionTicketsResponse) {
      const ticketItems = Array.isArray(transactionTicketsResponse.results) ? transactionTicketsResponse.results : (transactionTicketsResponse || [])
      items.push(...ticketItems.slice(0, 3).map(buildTransactionApprovalItem))
      total += ticketItems.length
    }

    if (dashboardStats) {
      const recentAlerts = Array.isArray(dashboardStats.recent_alerts) ? dashboardStats.recent_alerts : []
      items.push(...recentAlerts.slice(0, 4).map(buildAlertNotificationItem))
      total += Number(dashboardStats.alerts?.unacknowledged || 0)
    }

    if (eventOverview) {
      const priorityEvents = Array.isArray(eventOverview.suspects) ? eventOverview.suspects : []
      items.push(...priorityEvents.slice(0, 4).map(buildEventNotificationItem))
      total += priorityEvents.length
    }

    notificationItems.value = items
      .sort((left, right) => {
        if (right.priority !== left.priority) return right.priority - left.priority
        return new Date(right.time || 0).getTime() - new Date(left.time || 0).getTime()
      })
      .slice(0, 6)
    notificationCount.value = total
  } catch {
    notificationItems.value = []
    notificationCount.value = 0
  } finally {
    notificationsLoading.value = false
  }
}

function handleNoticeOpen() {
  if (!notificationItems.value.length && !notificationsLoading.value) {
    void loadNotifications()
  }
}

function openAIOpsAssistant() {
  window.dispatchEvent(new Event('sxdevops-aiops-open'))
}

function openAIAgentPromo() {
  router.push('/ai-agent-promo')
}

function canHandleDeploymentApproval(item) {
  const step = item?.current_approval_step
  if (!step?.approver_type || !step?.approver_value) return authStore.hasPermission('ops.deployment.approve')
  if (step.approver_type === 'user') return authStore.currentUser?.username === step.approver_value
  if (step.approver_type === 'role') {
    return (authStore.currentUser?.roles || []).some(role => role.code === step.approver_value)
  }
  if (step.approver_type === 'group') {
    return (authStore.currentUser?.user_groups || []).some(group => group.code === step.approver_value)
  }
  return false
}

function goNotification(item) {
  if (!item?.route) return
  router.push(item.route)
}

function goSection(section) {
  if (!section?.route) return
  router.push(section.route)
}

async function handleUserCommand(command) {
  if (command === 'refresh') {
    await authStore.reloadProfile()
    ElMessage.success('权限已刷新')
    return
  }
  if (command === 'logout') {
    await authStore.logout()
    router.replace('/login')
  }
}

onMounted(() => {
  void loadNotifications()
  notificationTimer = window.setInterval(() => {
    void loadNotifications()
  }, 60000)
})

onBeforeUnmount(() => {
  if (notificationTimer) {
    window.clearInterval(notificationTimer)
    notificationTimer = null
  }
})
</script>

<style scoped>
.brand-mark {
  width: 24px;
  height: 24px;
  display: block;
}

.assistant-trigger,
.promo-trigger,
.notice-trigger {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.promo-trigger {
  width: auto;
  min-width: 102px;
  padding: 0 12px;
  gap: 6px;
  color: #5b7fc7;
  border-color: rgba(96, 165, 250, 0.22);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.92) 0%, rgba(236, 253, 245, 0.74) 100%);
  box-shadow: 0 8px 18px rgba(59, 130, 246, 0.08);
  font-size: 13px;
  font-weight: 700;
}

.promo-trigger:hover {
  color: #3f6fbd;
  border-color: rgba(96, 165, 250, 0.36);
  background: linear-gradient(135deg, rgba(219, 234, 254, 0.98) 0%, rgba(209, 250, 229, 0.84) 100%);
  transform: translateY(-1px);
  box-shadow: 0 12px 24px rgba(59, 130, 246, 0.12);
}

.assistant-trigger {
  position: relative;
  overflow: hidden;
  color: #3b82f6;
  border-color: rgba(96, 165, 250, 0.22);
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.92) 0%, rgba(255, 247, 237, 0.72) 100%);
  box-shadow: 0 8px 18px rgba(59, 130, 246, 0.08);
}

.assistant-trigger::after {
  content: '';
  position: absolute;
  inset: 6px;
  border-radius: 9px;
  border: 1px solid rgba(59, 130, 246, 0.12);
  pointer-events: none;
}

.assistant-trigger:hover {
  color: #2563eb;
  border-color: rgba(96, 165, 250, 0.34);
  background: linear-gradient(135deg, rgba(219, 234, 254, 0.96) 0%, rgba(255, 237, 213, 0.82) 100%);
  transform: translateY(-1px);
  box-shadow: 0 12px 24px rgba(59, 130, 246, 0.12);
}

.notice-trigger:hover {
  color: #356fc8;
  border-color: rgba(96, 165, 250, 0.26);
  background: rgba(239, 246, 255, 0.86);
}

.notice-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.notice-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.notice-panel__title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.notice-panel__subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.notice-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-height: 420px;
  overflow-y: auto;
  padding-right: 4px;
}

.notice-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notice-group__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.notice-group__meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notice-group__title {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
}

.notice-group__count {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.72);
  color: #64748b;
  font-size: 11px;
  line-height: 20px;
  text-align: center;
}

.notice-group__more {
  padding: 0;
  font-size: 12px;
}

.notice-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.notice-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 10px 10px 8px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.92);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.notice-item:hover {
  border-color: rgba(148, 163, 184, 0.26);
  background: rgba(248, 250, 252, 0.96);
}

.notice-item__dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  flex-shrink: 0;
  border-radius: 999px;
  background: #94a3b8;
}

.notice-item__dot.is-danger {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.08);
}

.notice-item__dot.is-warning {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.08);
}

.notice-item__dot.is-info {
  background: #60a5fa;
  box-shadow: 0 0 0 4px rgba(96, 165, 250, 0.08);
}

.notice-item__body {
  min-width: 0;
  flex: 1;
}

.notice-item__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.notice-item__title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.notice-item__title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.notice-item__time {
  flex-shrink: 0;
  font-size: 11px;
  color: #94a3b8;
}

.notice-item__desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.55;
  color: #64748b;
}

.notice-empty {
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #94a3b8;
  font-size: 12px;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 2px 4px 2px 2px;
  border-radius: 14px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.user-trigger:hover {
  background: rgba(255, 255, 255, 0.56);
}

.user-avatar {
  background: linear-gradient(135deg, #72c1b5 0%, #5f90c1 58%, #506ba5 100%);
  color: #ffffff;
  box-shadow: 0 8px 18px rgba(80, 107, 165, 0.18);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.user-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.user-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.user-role {
  font-size: 11px;
  color: var(--text-secondary);
}
</style>


