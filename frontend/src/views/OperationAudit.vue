<template>
  <div class="fade-in operation-audit-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><DocumentChecked /></el-icon></span>
          <h2>操作审计</h2>
          <p class="page-inline-desc">查看平台关键写操作、执行动作、审批与配置变更记录。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button :loading="loading" @click="fetchAudits">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
        <el-button v-if="canManageAudit" type="danger" plain @click="cleanupVisible = true">
          <el-icon><Delete /></el-icon>
          批量删除
        </el-button>
      </div>
    </section>

    <div class="table-card">
      <div class="filter-bar">
        <el-input v-model="filters.search" placeholder="搜索标题 / 资源 / 操作人" clearable style="width: 280px" @keyup.enter="handleSearch" />
        <el-select v-model="filters.result" placeholder="结果" clearable style="width: 140px" @change="handleSearch">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
          <el-option label="部分成功" value="partial" />
          <el-option label="待处理" value="pending" />
        </el-select>
        <el-input v-model="filters.actor" placeholder="操作人" clearable style="width: 160px" @keyup.enter="handleSearch" />
        <el-date-picker
          v-model="timeRange"
          type="datetimerange"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          range-separator="至"
          style="width: 360px"
          @change="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>

      <el-table :data="audits" stripe v-loading="loading">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.occurred_at) }}</template>
        </el-table-column>
        <el-table-column prop="title" label="操作" min-width="220" show-overflow-tooltip />
        <el-table-column label="模块" width="120">
          <template #default="{ row }">{{ moduleLabel(row.module) }}</template>
        </el-table-column>
        <el-table-column label="动作" width="130">
          <template #default="{ row }">{{ row.action || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作人" width="140">
          <template #default="{ row }">{{ row.actor_display || row.actor_username || 'system' }}</template>
        </el-table-column>
        <el-table-column label="资源" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ resourceLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="resultTone(row.result)">{{ resultLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">{{ row.source_type_display || row.source_type || '-' }}</template>
        </el-table-column>
        <el-table-column label="请求" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ requestLabel(row) }}</template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          :page-size="20"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchAudits"
        />
      </div>
    </div>

    <el-dialog v-model="cleanupVisible" title="批量删除操作审计" width="460px" destroy-on-close>
      <div class="cleanup-body">
        <p>将删除指定时间之前的操作审计记录，外部事件源接入数据不会被清理。</p>
        <el-date-picker
          v-model="cleanupBeforeAt"
          type="datetime"
          placeholder="选择截止时间"
          style="width: 100%"
        />
      </div>
      <template #footer>
        <el-button @click="cleanupVisible = false">取消</el-button>
        <el-button type="danger" :loading="cleanupLoading" @click="handleCleanup">确认删除</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentChecked, RefreshRight } from '@element-plus/icons-vue'
import { getOperationAuditEvents, pruneOperationAuditEvents } from '@/api/modules/eventwall'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const cleanupLoading = ref(false)
const cleanupVisible = ref(false)
const cleanupBeforeAt = ref(null)
const audits = ref([])
const total = ref(0)
const page = ref(1)
const timeRange = ref([])
const filters = reactive({
  search: '',
  result: '',
  actor: '',
})
const canManageAudit = computed(() => authStore.hasPermission('rbac.audit.manage'))

function buildParams() {
  const params = { page: page.value }
  if (filters.search.trim()) params.search = filters.search.trim()
  if (filters.result) params.result = filters.result
  if (filters.actor.trim()) params.actor = filters.actor.trim()
  if (Array.isArray(timeRange.value) && timeRange.value.length === 2) {
    params.start_at = new Date(timeRange.value[0]).toISOString()
    params.end_at = new Date(timeRange.value[1]).toISOString()
  }
  return params
}

async function fetchAudits() {
  loading.value = true
  try {
    const response = await getOperationAuditEvents(buildParams())
    audits.value = response.results || response || []
    total.value = response.count || audits.value.length
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  fetchAudits()
}

function resetFilters() {
  filters.search = ''
  filters.result = ''
  filters.actor = ''
  timeRange.value = []
  handleSearch()
}

async function handleCleanup() {
  if (!cleanupBeforeAt.value) {
    ElMessage.warning('请选择截止时间')
    return
  }
  const cutoff = new Date(cleanupBeforeAt.value)
  if (Number.isNaN(cutoff.getTime())) {
    ElMessage.warning('截止时间无效')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定删除 ${formatTime(cutoff)} 之前的操作审计记录吗？该操作不可恢复。`,
      '确认批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  cleanupLoading.value = true
  try {
    const response = await pruneOperationAuditEvents({ before_at: cutoff.toISOString() })
    ElMessage.success(`已删除 ${response.deleted || 0} 条操作审计记录`)
    cleanupVisible.value = false
    cleanupBeforeAt.value = null
    page.value = 1
    await fetchAudits()
  } finally {
    cleanupLoading.value = false
  }
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function moduleLabel(module) {
  return {
    ops: '运维',
    cmdb: 'CMDB',
    sqlaudit: 'SQL 审计',
    marketplace: '工具市场',
    rbac: '用户权限',
    aiops: 'AIOps',
    eventwall: '事件墙',
  }[module] || module || '-'
}

function resultLabel(row) {
  return row.result_display || {
    success: '成功',
    failed: '失败',
    partial: '部分成功',
    pending: '待处理',
    rejected: '已拒绝',
  }[row.result] || row.result || '-'
}

function resultTone(result) {
  return {
    success: 'success',
    failed: 'danger',
    partial: 'warning',
    pending: 'warning',
    rejected: 'info',
  }[result] || 'info'
}

function resourceLabel(row) {
  return [row.resource_type, row.resource_name || row.resource_id].filter(Boolean).join(' / ') || '-'
}

function requestLabel(row) {
  return [row.request_method, row.source_path].filter(Boolean).join(' ') || row.ip_address || '-'
}

onMounted(fetchAudits)
</script>

<style scoped>
.panel {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
  padding: 12px 14px;
}

.hero,
.hero-copy,
.hero-title-row,
.hero-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero-copy {
  gap: 4px;
}

.hero {
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.hero-title-row {
  align-items: center;
  gap: 12px;
}

.hero-title-row h2 {
  font-size: 23px;
  line-height: 1.1;
  margin: 0;
  color: #0f172a;
}

.hero-icon {
  width: 42px;
  height: 42px;
  border-radius: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #fff;
  background: linear-gradient(135deg, #0f766e, #0ea5e9);
}

.page-inline-desc {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.hero-actions {
  align-items: center;
  justify-content: flex-end;
}

.hero-actions :deep(.el-button) {
  min-height: 32px;
  padding: 0 14px;
  border-radius: 10px;
  font-weight: 500;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.table-card {
  padding: 14px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.92));
  box-shadow: 0 18px 36px rgba(15,23,42,.06);
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.cleanup-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cleanup-body p {
  margin: 0;
  color: #475569;
  line-height: 1.6;
}

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
    align-items: stretch;
  }
}

.hero.panel { border-radius: 20px; }
</style>
