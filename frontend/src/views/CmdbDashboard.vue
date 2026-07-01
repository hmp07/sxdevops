<template>
  <div class="cmdb-dashboard">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Coin /></el-icon></span>
          <h2>CMDB 总览</h2>
          <p class="page-inline-desc">配置管理数据库概览，查看 CI 统计、成本趋势与资源分布</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </section>

    <div class="audit-grid cmdb-top-stats" v-loading="loading">
      <div class="audit-card audit-card--inline">
        <div class="stat-label">CI 总数</div>
        <div class="stat-value">{{ stats.total_ci || 0 }}</div>
      </div>
      <div class="audit-card audit-card--inline">
        <div class="stat-label">活跃 CI</div>
        <div class="stat-value">{{ stats.active_ci || 0 }}</div>
      </div>
      <div class="audit-card audit-card--inline">
        <div class="stat-label">关联关系</div>
        <div class="stat-value">{{ stats.relation_count || 0 }}</div>
      </div>
      <div class="audit-card audit-card--inline">
        <div class="stat-label">待审批</div>
        <div class="stat-value">{{ stats.pending_requests || 0 }}</div>
      </div>
    </div>

    <div class="cmdb-distribution">
      <section class="panel" v-if="(stats.by_type || []).length">
        <div class="panel-header">
          <h4>按 CI 类型分布</h4>
        </div>
        <div class="audit-grid">
          <div v-for="item in stats.by_type" :key="item.name" class="audit-card audit-card--inline">
            <div class="stat-label">{{ item.name }}</div>
            <div class="stat-value">{{ item.count }}</div>
          </div>
        </div>
      </section>

      <section class="panel" v-if="(stats.by_environment || []).length">
        <div class="panel-header">
          <h4>按环境分布</h4>
        </div>
        <div class="audit-grid">
          <div v-for="item in stats.by_environment" :key="item.environment" class="audit-card audit-card--inline">
            <div class="stat-label">{{ item.environment }}</div>
            <div class="stat-value">{{ item.count }}</div>
          </div>
        </div>
      </section>

      <section class="panel" v-if="(stats.by_business_line || []).length">
        <div class="panel-header">
          <h4>按业务线分布</h4>
        </div>
        <div class="audit-grid">
          <div v-for="item in stats.by_business_line" :key="item.business_line" class="audit-card audit-card--inline">
            <div class="stat-label">{{ item.business_line }}</div>
            <div class="stat-value">{{ item.count }}</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getCmdbDashboard } from '@/api/modules/cmdb'

const loading = ref(false)
const stats = ref({})

async function load() {
  loading.value = true
  try {
    const resp = await getCmdbDashboard()
    stats.value = resp || {}
  } catch {
    stats.value = {}
  } finally {
    loading.value = false
  }
}

onMounted(() => { load() })
</script>

<style scoped>
.cmdb-top-stats {
  margin-bottom: 16px;
}
.cmdb-distribution {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
