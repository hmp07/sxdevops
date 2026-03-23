<template>
  <div class="fade-in sql-audit-page">
    <div class="page-header compact-header">
      <div class="page-title-row">
        <h2>📄SQL审计</h2>
        <p class="page-desc">{{ SQL_AUDIT_SUPPORT_TEXT }}</p>
      </div>
    </div>

    <div class="neo-tabs theme-blue log-center-tabs">
      <button
        v-for="tab in availableTabs"
        :key="tab.name"
        class="neo-tab-btn"
        :class="{ active: activeTab === tab.name }"
        @click="handleTabChange(tab.name)"
      >
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <SqlDatasources v-if="activeTab === 'datasources'" embedded />
    <SqlOrders v-else-if="activeTab === 'orders'" embedded />
    <SqlQuery v-else-if="activeTab === 'query'" embedded />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Coin, Search, Tickets } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import SqlDatasources from '@/views/SqlDatasources.vue'
import SqlOrders from '@/views/SqlOrders.vue'
import SqlQuery from '@/views/SqlQuery.vue'
import { SQL_AUDIT_SUPPORT_TEXT } from '@/utils/sqlaudit'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const activeTab = ref('datasources')

const availableTabs = computed(() => {
  const tabs = []
  if (authStore.hasPermission('sqlaudit.datasource.view')) {
    tabs.push({ name: 'datasources', label: '数据源', icon: Coin })
  }
  if (authStore.hasAnyPermission(['sqlaudit.order.view', 'sqlaudit.order.submit', 'sqlaudit.order.review', 'sqlaudit.order.execute'])) {
    tabs.push({ name: 'orders', label: '工单', icon: Tickets })
  }
  if (authStore.hasAnyPermission(['sqlaudit.query.view', 'sqlaudit.query.execute'])) {
    tabs.push({ name: 'query', label: '查询', icon: Search })
  }
  return tabs
})

const normalizeTab = (tab) => {
  if (availableTabs.value.some(item => item.name === tab)) {
    return tab
  }
  return availableTabs.value[0]?.name || 'datasources'
}

watch(
  [() => route.query.tab, availableTabs],
  ([tab]) => {
    const nextTab = normalizeTab(tab)
    if (activeTab.value !== nextTab) {
      activeTab.value = nextTab
    }
    if (route.query.tab !== nextTab) {
      router.replace({ path: '/sql', query: { ...route.query, tab: nextTab } })
    }
  },
  { immediate: true },
)

const handleTabChange = (tab) => {
  const nextTab = normalizeTab(tab)
  if (activeTab.value !== nextTab) {
    activeTab.value = nextTab
  }
  if (route.query.tab !== nextTab) {
    router.replace({ path: '/sql', query: { ...route.query, tab: nextTab } })
  }
}
</script>

<style scoped>
.compact-header {
  margin-bottom: 14px;
}

.page-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.log-center-tabs {
  margin-bottom: 20px;
}

.page-desc {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}
</style>
