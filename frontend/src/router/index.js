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
        name: 'Hosts',
        component: () => import('@/views/Hosts.vue'),
        meta: { title: '主机管理', icon: 'Monitor', permission: 'ops.host.view' },
      },
      {
        path: 'cmdb',
        name: 'CmdbManage',
        component: () => import('@/views/CmdbManage.vue'),
        meta: {
          title: 'CMDB',
          icon: 'Files',
          anyPermissions: ['cmdb.dashboard.view', 'cmdb.ci.view', 'cmdb.topology.view', 'cmdb.cost.view', 'cmdb.request.submit'],
        },
      },
      {
        path: 'deployments',
        name: 'Deployments',
        component: () => import('@/views/Deployments.vue'),
        meta: { title: '部署管理', icon: 'Promotion', permission: 'ops.deployment.view' },
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
        path: 'nginx',
        name: 'NginxManage',
        component: () => import('@/views/NginxManage.vue'),
        meta: { title: 'Nginx 管理', icon: 'Location', permission: 'ops.nginx.view' },
      },
      {
        path: 'logs',
        redirect: '/logs/query',
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
        meta: { title: '告警中心', icon: 'Bell', permission: 'ops.alert.view' },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/Users.vue'),
        meta: {
          title: '用户管理',
          icon: 'User',
          anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view'],
        },
      },
      {
        path: 'sql/datasources',
        name: 'SqlDatasources',
        component: () => import('@/views/SqlDatasources.vue'),
        meta: { title: '数据源', icon: 'Coin', permission: 'sqlaudit.datasource.view' },
      },
      {
        path: 'sql/orders',
        name: 'SqlOrders',
        component: () => import('@/views/SqlOrders.vue'),
        meta: {
          title: 'SQL 工单',
          icon: 'Tickets',
          anyPermissions: ['sqlaudit.order.view', 'sqlaudit.order.submit', 'sqlaudit.order.review', 'sqlaudit.order.execute'],
        },
      },
      {
        path: 'sql/query',
        name: 'SqlQuery',
        component: () => import('@/views/SqlQuery.vue'),
        meta: { title: 'SQL 查询', icon: 'Search', anyPermissions: ['sqlaudit.query.view', 'sqlaudit.query.execute'] },
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
