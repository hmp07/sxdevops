<template>
  <div class="app-layout">
    <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <el-icon><Cpu /></el-icon>
        </div>
        <span class="logo-text">AgDevOps</span>
      </div>

      <el-menu
        :default-active="activeMenuPath"
        class="sidebar-nav el-menu-vertical"
        :collapse="appStore.sidebarCollapsed"
        router
        :collapse-transition="false"
      >
        <template v-for="item in visibleMenuItems" :key="item.title">
          <el-sub-menu v-if="item.children?.length" :index="item.title">
            <template #title>
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">
              <template #title>
                <el-icon v-if="child.icon"><component :is="child.icon" /></el-icon>
                <span>{{ child.title }}</span>
              </template>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item v-else :index="item.path">
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
          <el-badge :value="3" :max="99">
            <el-icon :size="20" style="cursor: pointer; color: var(--text-secondary)"><Bell /></el-icon>
          </el-badge>
          <el-dropdown @command="handleUserCommand">
            <div style="display: flex; align-items: center; gap: 8px; cursor: pointer">
              <el-avatar :size="32" style="background: var(--primary)">
                <el-icon><User /></el-icon>
              </el-avatar>
              <div class="user-meta">
                <span class="user-name">{{ authStore.displayName || '未登录' }}</span>
                <span class="user-role">{{ currentRoleLabel }}</span>
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
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()

const menuItems = [
  { path: '/dashboard', title: '仪表盘', icon: 'Odometer', permission: 'ops.dashboard.view' },
  {
    path: '/cmdb',
    title: 'CMDB',
    icon: 'Files',
    anyPermissions: ['cmdb.dashboard.view', 'cmdb.ci.view', 'cmdb.topology.view', 'cmdb.cost.view', 'cmdb.request.submit'],
  },
  { path: '/hosts', title: '主机管理', icon: 'Monitor', permission: 'ops.host.view' },
  { path: '/deployments', title: '部署管理', icon: 'Promotion', permission: 'ops.deployment.view' },
  {
    path: '/marketplace',
    title: '工具市场',
    icon: 'Shop',
    anyPermissions: ['marketplace.template.view', 'marketplace.deployment.view', 'marketplace.deployment.manage'],
  },
  {
    title: '容器管理',
    icon: 'Box',
    children: [
      { path: '/containers/k8s', title: 'K8s 集群', icon: 'Connection', permission: 'ops.k8s.view' },
      { path: '/containers/docker', title: 'Docker 环境', icon: 'Platform', permission: 'ops.docker.view' },
    ],
  },
  { path: '/nginx', title: 'Nginx 管理', icon: 'Location', permission: 'ops.nginx.view' },
  { path: '/terraform', title: 'IaC 资源编排', icon: 'SetUp', permission: 'ops.iac.view' },
  {
    key: 'log-center',
    title: '日志中心',
    icon: 'Document',
    anyPermissions: ['ops.log.query', 'ops.log.datasource.view'],
  },
  { path: '/alerts', title: '告警中心', icon: 'Bell', permission: 'ops.alert.view' },
  {
    path: '/users',
    title: '用户管理',
    icon: 'User',
    anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view'],
  },
  {
    path: '/sql',
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
]

function canAccess(item) {
  if (item.permission) return authStore.hasPermission(item.permission)
  if (item.anyPermissions) return authStore.hasAnyPermission(item.anyPermissions)
  return true
}

const visibleMenuItems = computed(() => menuItems
  .map((item) => {
    if (item.key === 'log-center') {
      return {
        ...item,
        path: authStore.hasPermission('ops.log.query') ? '/logs/query' : '/logs/datasources',
      }
    }
    if (!item.children) return item
    const children = item.children.filter(canAccess)
    return { ...item, children }
  })
  .filter((item) => item.children ? item.children.length > 0 : canAccess(item)))

const activeMenuPath = computed(() => {
  if (route.path.startsWith('/logs')) {
    return authStore.hasPermission('ops.log.query') ? '/logs/query' : '/logs/datasources'
  }
  if (route.path.startsWith('/sql')) {
    return '/sql'
  }
  return route.path
})

const currentTitle = computed(() => {
  const currentPath = route.path
  for (const item of visibleMenuItems.value) {
    if (item.path === currentPath) return item.title
    if (item.children) {
      const child = item.children.find((entry) => entry.path === currentPath)
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
</script>

<style scoped>
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
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.user-role {
  font-size: 11px;
  color: var(--text-secondary);
}
</style>
