<template>
  <div class="cmdb-config-items">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Monitor /></el-icon></span>
          <h2>配置项</h2>
          <p class="page-inline-desc">管理所有配置项（CI），支持按类型、环境、业务线筛选</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="Refresh" :loading="loading" @click="fetch">刷新</el-button>
      </div>
    </section>

    <div class="audit-grid cmdb-top-stats">
      <div class="audit-card audit-card--inline">
        <div class="stat-label">配置项总数</div>
        <div class="stat-value">{{ total }}</div>
      </div>
      <div class="audit-card audit-card--inline">
        <div class="stat-label">CI 类型</div>
        <div class="stat-value">{{ ciTypes.length }}</div>
      </div>
    </div>

    <section class="panel">
      <div class="toolbar">
        <el-select v-model="filters.ci_type" size="small" clearable placeholder="CI 类型" style="width: 160px" @change="onFilterChange">
          <el-option v-for="item in ciTypes" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-select v-model="filters.environment" size="small" clearable placeholder="环境" style="width: 120px; margin-left: 10px" @change="onFilterChange">
          <el-option label="生产" value="prod" />
          <el-option label="测试" value="test" />
          <el-option label="开发" value="dev" />
        </el-select>
        <el-select v-model="filters.business_line" size="small" clearable placeholder="业务线" style="width: 140px; margin-left: 10px" @change="onFilterChange">
          <el-option v-for="item in businessLines" :key="item" :label="item" :value="item" />
        </el-select>
        <el-input v-model="filters.search" size="small" placeholder="搜索名称/IP" clearable style="width: 200px; margin-left: 10px" @clear="onFilterChange" @keyup.enter="onFilterChange" />
      </div>

      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="ci_type_name" label="CI 类型" width="120" />
        <el-table-column label="IP 地址" width="150">
          <template #default="{ row }">
            {{ row.attributes?.ip_address || row.attributes?.managementip || '--' }}
          </template>
        </el-table-column>
        <el-table-column prop="business_line" label="业务线" width="120" />
        <el-table-column prop="environment" label="环境" width="80" />
        <el-table-column prop="admin_user" label="负责人" width="100" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : row.status === 'idle' ? 'warning' : 'info'" size="small">
              {{ row.status === 'active' ? '活跃' : row.status === 'idle' ? '空闲' : '离线' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap" v-if="total > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetch"
        />
      </div>
    </section>

    <el-dialog v-model="detailVisible" title="配置项详情" width="640px">
      <el-descriptions :column="2" border v-if="currentItem">
        <el-descriptions-item label="名称">{{ currentItem.name }}</el-descriptions-item>
        <el-descriptions-item label="CI 类型">{{ currentItem.ci_type_name }}</el-descriptions-item>
        <el-descriptions-item label="业务线">{{ currentItem.business_line || '--' }}</el-descriptions-item>
        <el-descriptions-item label="环境">{{ currentItem.environment || '--' }}</el-descriptions-item>
        <el-descriptions-item label="负责人">{{ currentItem.admin_user || '--' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ currentItem.status }}</el-descriptions-item>
        <el-descriptions-item label="创建时间" :span="2">{{ currentItem.created_at }}</el-descriptions-item>
        <el-descriptions-item label="属性" :span="2">
          <pre class="attr-json">{{ JSON.stringify(currentItem.attributes, null, 2) }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getConfigItems, getCITypes } from '@/api/modules/cmdb'

const loading = ref(false)
const items = ref([])
const ciTypes = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const businessLines = ref([])
const detailVisible = ref(false)
const currentItem = ref(null)
const filters = ref({ ci_type: '', environment: '', business_line: '', search: '' })

async function fetch() {
  loading.value = true
  try {
    const params = { page: currentPage.value }
    if (filters.value.ci_type) params.ci_type = filters.value.ci_type
    if (filters.value.environment) params.environment = filters.value.environment
    if (filters.value.business_line) params.business_line = filters.value.business_line
    if (filters.value.search) params.search = filters.value.search
    const { data } = await getConfigItems(params)
    items.value = data.results || []
    total.value = data.count || 0
    if (items.value.length) {
      const lines = new Set(items.value.map(i => i.business_line).filter(Boolean))
      businessLines.value = [...lines].sort()
    }
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  currentPage.value = 1
  fetch()
}

async function loadTypes() {
  try {
    const { data } = await getCITypes()
    ciTypes.value = data?.results || data || []
  } catch { /* ignore */ }
}

function showDetail(row) {
  currentItem.value = row
  detailVisible.value = true
}

onMounted(() => {
  loadTypes()
  fetch()
})
</script>

<style scoped>
.cmdb-top-stats {
  margin-bottom: 16px;
}
.attr-json {
  max-height: 200px;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
