<template>
  <div class="app-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <el-icon><Cpu /></el-icon>
        </div>
        <span class="logo-text">AgDevOps</span>
      </div>
      <el-menu
        :default-active="route.path"
        class="sidebar-nav el-menu-vertical"
        :collapse="appStore.sidebarCollapsed"
        router
        :collapse-transition="false"
      >
        <template v-for="item in menuItems" :key="item.title">
          <!-- 有子菜单 -->
          <el-sub-menu v-if="item.children" :index="item.title">
            <template #title>
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item 
              v-for="child in item.children" 
              :key="child.path" 
              :index="child.path"
            >
              <template #title>
                <el-icon v-if="child.icon"><component :is="child.icon" /></el-icon>
                <span>{{ child.title }}</span>
              </template>
            </el-menu-item>
          </el-sub-menu>

          <!-- 无子菜单 -->
          <el-menu-item v-else :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>
              <span>{{ item.title }}</span>
            </template>
          </el-menu-item>
        </template>
      </el-menu>
    </aside>

    <!-- 主内容区 -->
    <div class="main-area">
      <!-- 顶栏 -->
      <header class="header">
        <div class="header-left">
          <button class="collapse-btn" @click="appStore.toggleSidebar">
            <el-icon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></el-icon>
          </button>
          <span class="breadcrumb">{{ currentTitle }}</span>
        </div>
        <div class="header-right">
          <el-badge :value="3" :max="99">
            <el-icon :size="20" style="cursor:pointer; color: var(--text-secondary)"><Bell /></el-icon>
          </el-badge>
          <el-dropdown>
            <div style="display:flex; align-items:center; gap:8px; cursor:pointer;">
              <el-avatar :size="32" style="background: var(--primary);">
                <el-icon><User /></el-icon>
              </el-avatar>
              <span style="font-size:14px; font-weight:500; color: var(--text-primary);">管理员</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item>个人设置</el-dropdown-item>
                <el-dropdown-item divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 页面内容 -->
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
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const appStore = useAppStore()

const menuItems = [
  { path: '/dashboard',   title: '仪表盘',   icon: 'Odometer' },
  { path: '/hosts',       title: '主机管理', icon: 'Monitor' },
  { path: '/deployments', title: '部署管理', icon: 'Promotion' },
  { path: '/marketplace', title: '工具市场', icon: 'Shop' },
  {
    path: '/containers',
    title: '容器管理',
    icon: 'Box',
    children: [
      { path: '/containers/k8s',    title: 'K8s 集群', icon: 'Connection' },
      { path: '/containers/docker', title: 'Docker 环境', icon: 'Platform' },
    ]
  },
  { path: '/logs',        title: '日志中心', icon: 'Document' },
  { path: '/alerts',      title: '告警中心', icon: 'Bell' },
  { path: '/users',       title: '用户管理', icon: 'User' },
  {
    title: 'SQL 审计',
    icon: 'DataAnalysis',
    children: [
      { path: '/sql/datasources', title: '数据源',   icon: 'Coin' },
      { path: '/sql/orders',      title: 'SQL 工单', icon: 'Tickets' },
      { path: '/sql/query',       title: 'SQL 查询', icon: 'Search' },
    ]
  }
]

// 递归查找当前激活菜单的 title
const currentTitle = computed(() => {
  const currentPath = route.path
  
  for (const item of menuItems) {
    if (item.path === currentPath) return item.title
    if (item.children) {
      const child = item.children.find(c => c.path === currentPath)
      if (child) return `${item.title} / ${child.title}`
    }
  }
  return ''
})
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
</style>
