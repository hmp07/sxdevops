import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppLayout from '@/layout/AppLayout.vue'
import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/Forbidden.vue'),
    meta: { public: true, title: '无权访问' },
  },
  {
    path: '/',
    component: AppLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '仪表盘', icon: 'Odometer', permission: 'ops.dashboard.view' },
      },
      {
        path: 'hosts',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasAnyPermission(['ops.host.view', 'ops.host.manage', 'ops.host.terminal'])) {
            return '/hosts/assets'
          }
          if (authStore.hasAnyPermission(['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'])) {
            return '/hosts/schedules'
          }
          if (authStore.hasPermission('ops.host.execute')) {
            return '/hosts/tasks'
          }
          if (authStore.hasAnyPermission(['cmdb.request.submit', 'cmdb.request.approve'])) {
            return '/hosts/requests'
          }
          return '/403'
        },
        meta: { hidden: true },
      },
      {
        path: 'hosts/assets',
        name: 'HostsAssets',
        component: () => import('@/views/Hosts.vue'),
        meta: {
          title: '主机资产',
          icon: 'Monitor',
          anyPermissions: ['ops.host.view', 'ops.host.manage', 'ops.host.terminal'],
        },
      },
      {
        path: 'hosts/schedules',
        name: 'HostSchedules',
        component: () => import('@/views/Hosts.vue'),
        meta: {
          title: '定时任务',
          icon: 'Timer',
          anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'],
        },
      },
      {
        path: 'hosts/tasks',
        name: 'HostTasks',
        component: () => import('@/views/Hosts.vue'),
        meta: { title: '任务中心', icon: 'Operation', permission: 'ops.host.execute' },
      },
      {
        path: 'hosts/requests',
        name: 'HostRequests',
        component: () => import('@/views/Hosts.vue'),
        meta: {
          title: '主机申请',
          icon: 'Ticket',
          anyPermissions: ['cmdb.request.submit', 'cmdb.request.approve'],
        },
      },
      {
        path: 'cmdb',
        name: 'CmdbManage',
        component: () => import('@/views/CmdbManage.vue'),
        meta: {
          title: 'CMDB',
          icon: 'Files',
          anyPermissions: ['cmdb.ci.view', 'cmdb.topology.view', 'cmdb.cost.view'],
        },
      },
      {
        path: 'deployments',
        redirect: '/workorders/releases',
        meta: { hidden: true, anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'] },
      },
      {
        path: 'workorders',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasAnyPermission(['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'])) {
            return '/workorders/releases'
          }
          if (authStore.hasAnyPermission([
            'sqlaudit.order.view',
            'sqlaudit.order.submit',
            'sqlaudit.order.review',
            'sqlaudit.order.execute',
            'sqlaudit.datasource.view',
            'sqlaudit.query.view',
            'sqlaudit.query.execute',
          ])) {
            return '/workorders/sql'
          }
          if (authStore.hasAnyPermission(['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'])) {
            return '/workorders/transactions'
          }
          return '/403'
        },
        meta: { hidden: true },
      },
      {
        path: 'workorders/releases',
        name: 'WorkOrderReleases',
        component: () => import('@/views/Deployments.vue'),
        meta: {
          title: '应用发布',
          icon: 'Promotion',
          anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
        },
      },
      {
        path: 'workorders/approval-flows',
        name: 'WorkOrderApprovalFlows',
        component: () => import('@/views/Deployments.vue'),
        meta: {
          title: '审批流',
          icon: 'Checked',
          anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
        },
      },
      {
        path: 'workorders/sql',
        name: 'WorkOrderSqlAudit',
        component: () => import('@/views/SqlAudit.vue'),
        meta: {
          title: 'SQL 审计',
          icon: 'DataAnalysis',
          defaultTab: 'orders',
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
      },
      {
        path: 'workorders/transactions',
        name: 'TransactionTickets',
        component: () => import('@/views/TransactionTickets.vue'),
        meta: {
          title: '事务工单',
          icon: 'Tickets',
          anyPermissions: ['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'],
        },
      },
      {
        path: 'marketplace',
        name: 'ServiceMarket',
        component: () => import('@/views/ServiceMarket.vue'),
        meta: {
          title: '工具市场',
          icon: 'Shop',
          anyPermissions: ['marketplace.template.view', 'marketplace.deployment.view', 'marketplace.deployment.manage'],
        },
      },
      {
        path: 'containers/k8s',
        name: 'ContainerManageK8s',
        component: () => import('@/views/K8sManage.vue'),
        meta: { title: 'K8s 集群', icon: 'Connection', permission: 'ops.k8s.view' },
      },
      {
        path: 'containers/docker',
        name: 'ContainerManageDocker',
        component: () => import('@/views/ContainerManage.vue'),
        meta: { title: 'Docker 环境', icon: 'Platform', permission: 'ops.docker.view' },
      },
      {
        path: 'middleware/redis',
        name: 'RedisManage',
        component: () => import('@/views/MiddlewareManage.vue'),
        meta: { title: 'Redis 管理', icon: 'Coin', permission: 'ops.middleware.view', moduleKey: 'redis' },
      },
      {
        path: 'middleware/rocketmq',
        name: 'RocketMqManage',
        component: () => import('@/views/MiddlewareManage.vue'),
        meta: { title: 'RocketMQ 管理', icon: 'Promotion', permission: 'ops.middleware.view', moduleKey: 'rocketmq' },
      },
      {
        path: 'middleware/elasticsearch',
        name: 'ElasticsearchManage',
        component: () => import('@/views/MiddlewareManage.vue'),
        meta: { title: 'Elasticsearch 管理', icon: 'Search', permission: 'ops.middleware.view', moduleKey: 'elasticsearch' },
      },
      {
        path: 'middleware/nginx',
        name: 'NginxManage',
        component: () => import('@/views/NginxManage.vue'),
        meta: { title: 'Nginx 管理', icon: 'Location', permission: 'ops.nginx.view' },
      },
      {
        path: 'middleware/common',
        redirect: '/middleware/redis',
        meta: { hidden: true, permission: 'ops.middleware.view' },
      },
      {
        path: 'nginx',
        redirect: '/middleware/nginx',
        meta: { hidden: true, permission: 'ops.nginx.view' },
      },
      {
        path: 'terraform',
        name: 'TerraformIac',
        component: () => import('@/views/TerraformIac.vue'),
        meta: { title: 'IaC 编排', icon: 'SetUp', permission: 'ops.iac.view' },
      },
      {
        path: 'multicloud',
        name: 'MultiCloudManage',
        component: () => import('@/views/MultiCloudManage.vue'),
        meta: { title: '多云环境', icon: 'MostlyCloudy', permission: 'ops.multicloud.view' },
      },
      {
        path: 'logs',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          return authStore.hasPermission('ops.log.query') ? '/logs/query' : '/logs/datasources'
        },
        meta: { hidden: true },
      },
      {
        path: 'logs/query',
        name: 'LogsQuery',
        component: () => import('@/views/LogsQuery.vue'),
        meta: { title: '日志查询', icon: 'Search', permission: 'ops.log.query' },
      },
      {
        path: 'logs/datasources',
        name: 'LogDataSources',
        component: () => import('@/views/LogDataSources.vue'),
        meta: { title: '日志数据源', icon: 'DataBoard', permission: 'ops.log.datasource.view' },
      },
      {
        path: 'alerts',
        name: 'Alerts',
        component: () => import('@/views/Alerts.vue'),
        meta: { title: '告警中心', icon: 'Bell', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
      },
      {
        path: 'observability',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasAnyPermission(['ops.observability.system_posture.view', 'ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.alert.config.view', 'ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view', 'ops.grafana.view'])) {
            return '/observability/overview'
          }
          return '/403'
        },
        meta: { hidden: true },
      },
      {
        path: 'observability/system-posture',
        name: 'ObservabilitySystemPosture',
        component: () => import('@/views/ObservabilitySystemPosture.vue'),
        meta: { title: '系统态势', icon: 'Aim', permission: 'ops.observability.system_posture.view' },
      },
      {
        path: 'observability/overview',
        name: 'ObservabilityOverview',
        component: () => import('@/views/ObservabilityOverview.vue'),
        meta: {
          title: '平台总览',
          icon: 'DataLine',
          anyPermissions: ['ops.observability.system_posture.view', 'ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.alert.config.view', 'ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view', 'ops.grafana.view'],
        },
      },
      {
        path: 'observability/grafana',
        name: 'GrafanaDashboard',
        component: () => import('@/views/GrafanaDashboard.vue'),
        meta: { title: '监控看板', icon: 'Histogram', permission: 'ops.grafana.view' },
      },
      {
        path: 'observability/tracing',
        name: 'TraceObservability',
        component: () => import('@/views/TraceObservability.vue'),
        meta: { title: '链路追踪', icon: 'Connection', anyPermissions: ['ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view'] },
      },
      {
        path: 'observability/tracing/datasources',
        redirect: { path: '/observability/tracing', query: { tab: 'datasources' } },
        meta: { hidden: true, permission: 'ops.trace.datasource.view' },
      },
      {
        path: 'observability/datasource-links',
        redirect: { path: '/observability/overview' },
        meta: { hidden: true, permission: 'ops.observability.link.view' },
      },
      {
        path: 'events',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/wall',
        name: 'EventWall',
        component: () => import('@/views/EventWall.vue'),
        meta: { title: '事件墙', icon: 'Aim', permission: 'eventwall.view' },
      },
      {
        path: 'events/overview',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/wall-v2',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/sources',
        name: 'EventSources',
        component: () => import('@/views/EventSources.vue'),
        meta: { title: '事件源', icon: 'Share', permission: 'eventwall.source.view' },
      },
      {
        path: 'events/audit',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/analysis',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/Users.vue'),
        meta: {
          title: '用户管理',
          icon: 'User',
          anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view', 'rbac.audit.view'],
        },
      },
      {
        path: 'users/audit',
        name: 'OperationAudit',
        component: () => import('@/views/OperationAudit.vue'),
        meta: { title: '操作审计', icon: 'DocumentChecked', permission: 'rbac.audit.view' },
      },
      {
        path: 'aiops/chat',
        name: 'AIOpsChat',
        component: () => import('@/views/AIOpsChatEntry.vue'),
        meta: {
          title: '智能助手',
          icon: 'Service',
          permission: 'aiops.chat.view',
        },
      },
      {
        path: 'aiops/knowledge',
        name: 'AIOpsKnowledgeGraph',
        component: () => import('@/views/AIOpsKnowledgeGraph.vue'),
        meta: {
          title: '知识图谱',
          icon: 'Share',
          permission: 'aiops.knowledge.view',
        },
      },
      {
        path: 'aiops/config',
        name: 'AIOpsConfig',
        component: () => import('@/views/AIOpsConfig.vue'),
        meta: {
          title: '智能体配置',
          icon: 'ChatDotSquare',
          permission: 'aiops.config.view',
        },
      },
      {
        path: 'sql',
        redirect: (to) => ({ path: '/workorders/sql', query: to.query }),
        meta: { hidden: true },
      },
      {
        path: 'sql/datasources',
        redirect: { path: '/workorders/sql', query: { tab: 'datasources' } },
        meta: { hidden: true },
      },
      {
        path: 'sql/orders',
        redirect: { path: '/workorders/sql', query: { tab: 'orders' } },
        meta: { hidden: true },
      },
      {
        path: 'sql/query',
        redirect: { path: '/workorders/sql', query: { tab: 'query' } },
        meta: { hidden: true },
      },
    ],
  },
  {
    path: '/webshell/:hostId',
    name: 'WebShell',
    component: () => import('@/views/WebShell.vue'),
    meta: { title: 'WebShell', permission: 'ops.host.terminal' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore(pinia)
  if (!authStore.initialized) {
    await authStore.bootstrap()
  }

  if (to.meta.public) {
    if (to.name === 'Login' && authStore.isAuthenticated) {
      return to.query.redirect || '/dashboard'
    }
    return true
  }

  if (!authStore.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  const allowed = to.meta.permission
    ? authStore.hasPermission(to.meta.permission)
    : authStore.hasAnyPermission(to.meta.anyPermissions || [])

  if (!allowed) {
    ElMessage.warning('你没有访问该页面的权限')
    return { name: 'Forbidden' }
  }

  return true
})

export default router


