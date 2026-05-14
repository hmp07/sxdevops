<template>
  <div class="fade-in sql-audit-page">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row">
          <span class="sql-header-icon"><el-icon><Tickets /></el-icon></span>
          <h2>SQL 审计</h2>
          <p class="page-desc page-desc--secondary">{{ activeTabDescription }}</p>
        </div>
      </div>
    </section>

    <div v-if="sqlAuditPlatformTips.length" class="runtime-strip">
      <span class="runtime-strip__label">平台提醒</span>
      <el-tag
        v-for="item in sqlAuditPlatformTips"
        :key="item"
        size="small"
        effect="light"
        type="info"
      >
        {{ item }}
      </el-tag>
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

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const activeTab = ref('datasources')
const sqlAuditPlatformTips = computed(() => {
  const tipsMap = {
    datasources: [
      '新增或调整数据源后，建议先验证连接与权限范围',
      '生产数据源默认建议绑定审批工单再开放执行入口',
    ],
    orders: [
      '高风险变更建议先走工单审批，再安排低峰执行窗口',
      '执行结果会同步沉淀到事件中心，便于追溯复盘',
    ],
    query: [
      '查询优先使用只读账号，避免直接落到生产写权限',
      '慢 SQL 与大结果集建议先缩小时间范围再执行',
    ],
  }
  return tipsMap[activeTab.value] || tipsMap.datasources
})

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

const activeTabDescription = computed(() => {
  const descMap = {
    datasources: '维护 MySQL / PolarDB / MongoDB 数据源，支持测试连接与库列表发现。',
    orders: '覆盖提交、预检查、审核与执行链路，适合演示标准数据库变更流程。',
    query: '只读查询入口，支持 SQL / MongoDB 查询并自动沉淀到历史记录。',
  }
  return descMap[activeTab.value] || descMap.datasources
})

const normalizeTab = (tab) => {
  if (availableTabs.value.some(item => item.name === tab)) {
    return tab
  }
  const defaultTab = route.meta?.defaultTab
  if (availableTabs.value.some(item => item.name === defaultTab)) {
    return defaultTab
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
      router.replace({ path: route.path, query: { ...route.query, tab: nextTab } })
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
    router.replace({ path: route.path, query: { ...route.query, tab: nextTab } })
  }
}
</script>

<style scoped>
.panel {
  background: linear-gradient(135deg, rgba(239,246,255,.96) 0%, rgba(236,254,255,.94) 52%, rgba(248,250,252,.98) 100%);
  border: 1px solid rgba(96,165,250,.18);
  border-radius: 24px;
  box-shadow: 0 16px 36px rgba(14,165,233,.08);
  padding: 14px 22px;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}

.release-hero-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hero h2 {
  margin: 0;
  color: #0f172a;
}

.sql-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #fff;
  background: linear-gradient(135deg, #0ea5e9, #2563eb);
  box-shadow: 0 10px 20px rgba(37,99,235,.2);
}

.log-center-tabs {
  margin-bottom: 20px;
}

.runtime-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 8px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(248,250,252,.9);
  border: 1px solid rgba(148,163,184,.18);
}

.runtime-strip__label {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
}

.page-desc {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.45;
}

.page-desc--secondary {
  color: #64748b;
  flex: 0 1 auto;
}
.hero.panel { border-radius: 20px; }
</style>

