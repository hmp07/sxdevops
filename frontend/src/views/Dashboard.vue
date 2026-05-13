<template>
  <div v-loading="loading" class="dashboard-page">
    <div class="stats-grid dashboard-stats">
      <article v-for="card in summaryCards" :key="card.label" class="summary-card" :class="card.tone">
        <div class="summary-card__head">
          <span class="summary-card__label">{{ card.label }}</span>
          <span class="summary-card__icon">
            <el-icon><component :is="card.icon" /></el-icon>
          </span>
        </div>
        <div class="summary-card__value-row">
          <div class="summary-card__value">{{ card.value }}</div>
          <span v-if="card.unit" class="summary-card__unit">{{ card.unit }}</span>
        </div>
        <div v-if="card.meta" class="summary-card__meta">{{ card.meta }}</div>
      </article>
    </div>

    <section class="focus-strip" :class="`is-${overallStatus}`">
      <div class="focus-strip__signal">
        <span class="focus-strip__icon" :class="`is-${overallStatus}`">
          <el-icon><component :is="focusIcon" /></el-icon>
        </span>
        <span class="focus-strip__label">{{ focusBadge }}</span>
      </div>
      <div class="focus-strip__body">
        <strong>{{ focusTitle }}</strong>
        <el-tooltip
          v-if="focusTooltip"
          effect="light"
          placement="top"
          popper-class="dashboard-focus-popper"
        >
          <template #content>
            <div class="dashboard-focus-tip">{{ focusTooltip }}</div>
          </template>
          <span class="focus-strip__text">{{ focusText }}</span>
        </el-tooltip>
        <span v-else class="focus-strip__text">{{ focusText }}</span>
      </div>
      <div class="focus-strip__actions">
        <el-button size="small" type="primary" @click="refreshDashboard">
          <el-icon><RefreshRight /></el-icon>
          刷新首页
        </el-button>
        <el-button size="small" @click="openOverview('system-posture')">查看系统态势</el-button>
        <el-button size="small" text @click="openOverview('posture-history')">查看完整历史</el-button>
      </div>
    </section>

    <section class="panel dashboard-history-shell">
      <div class="dashboard-history-shell__head">
        <div class="dashboard-history-shell__title">
          <div class="dashboard-history-shell__headline">
            <h3>系统SLA统计</h3>
            <span class="dashboard-history-shell__tag">{{ latestDay ? `统计至 ${latestDay}` : '近 30 天' }}</span>
          </div>
        </div>
        <div class="dashboard-history-shell__meta">
          <span class="history-meta-pill">{{ latestSystems.length }} 个系统</span>
          <div class="history-meta-legend">
            <span><i class="is-healthy"></i>健康 {{ statusCounts.healthy }}</span>
            <span><i class="is-critical"></i>故障 {{ statusCounts.critical }}</span>
            <span><i class="is-unknown"></i>未知 {{ statusCounts.unknown }}</span>
          </div>
        </div>
      </div>
      <ObservabilityPostureHistory :key="historyPanelKey" embedded />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, CircleCheck, QuestionFilled, RefreshRight, WarningFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { getObservabilitySystemPostureHistory } from '@/api/modules/ops'
import ObservabilityPostureHistory from '@/views/ObservabilityPostureHistory.vue'

const router = useRouter()
const loading = ref(false)
const historyPanelKey = ref(0)
const dashboardHistory = ref({ days: [], systems: [], summary: {}, context: {} })

const historyUnknownBefore = '2026-04-07'

const latestDay = computed(() => dashboardHistory.value.summary?.latest_day || dashboardHistory.value.context?.end_day || '')

const latestSystems = computed(() => (dashboardHistory.value.systems || []).map((system) => {
  const record = latestSystemRecord(system, latestDay.value)
  const status = resolveDashboardStatus(record, system.target, latestDay.value)
  return {
    id: system.id,
    name: system.name,
    environment: system.environment_name || system.environment || '默认环境',
    status,
  }
}))

const statusCounts = computed(() => latestSystems.value.reduce((acc, system) => {
  acc[system.status] += 1
  return acc
}, { healthy: 0, critical: 0, unknown: 0 }))

const failureSystems = computed(() => latestSystems.value.filter(system => system.status === 'critical'))
const unknownSystems = computed(() => latestSystems.value.filter(system => system.status === 'unknown'))

const overallStatus = computed(() => {
  if (failureSystems.value.length) return 'critical'
  if (unknownSystems.value.length) return 'unknown'
  return 'healthy'
})

const focusIcon = computed(() => {
  if (overallStatus.value === 'critical') return WarningFilled
  if (overallStatus.value === 'unknown') return QuestionFilled
  return CircleCheck
})

const focusEnvironment = computed(() => {
  const source = failureSystems.value.length ? failureSystems.value : unknownSystems.value
  if (!source.length) return '全部环境'
  const counts = new Map()
  source.forEach((system) => {
    counts.set(system.environment, (counts.get(system.environment) || 0) + 1)
  })
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] || '全部环境'
})

const summaryCards = computed(() => [
  {
    label: '健康系统',
    value: `${statusCounts.value.healthy}`,
    unit: '个',
    meta: `当前纳管 ${latestSystems.value.length} 个系统`,
    tone: 'success',
    icon: CircleCheck,
  },
  {
    label: '故障系统',
    value: `${statusCounts.value.critical}`,
    unit: '个',
    meta: statusCounts.value.critical ? '建议优先进入系统态势排查' : '当前没有故障系统',
    tone: 'danger',
    icon: WarningFilled,
  },
  {
    label: '未知系统',
    value: `${statusCounts.value.unknown}`,
    unit: '个',
    meta: statusCounts.value.unknown ? '存在采集缺口或历史不足' : '当前没有未知系统',
    tone: 'neutral',
    icon: QuestionFilled,
  },
  {
    label: '重点环境',
    value: focusEnvironment.value,
    unit: '',
    meta: '',
    tone: 'context',
    icon: Calendar,
  },
])

const failureInline = computed(() => failureSystems.value
  .map(system => `${system.environment} / ${system.name}`)
  .join('、'))

const unknownInline = computed(() => unknownSystems.value
  .map(system => `${system.environment} / ${system.name}`)
  .join('、'))

const focusTitle = computed(() => {
  if (failureSystems.value.length) return '优先处理故障系统'
  if (unknownSystems.value.length) return '补齐未知系统数据'
  return '当前系统运行稳定'
})

const focusBadge = computed(() => {
  if (failureSystems.value.length) return '故障优先'
  if (unknownSystems.value.length) return '数据待补'
  return '整体稳定'
})

const focusText = computed(() => {
  if (failureSystems.value.length) return truncateText(failureInline.value, 92)
  if (unknownSystems.value.length) return truncateText(`当前暂无可用数据：${unknownInline.value}`, 92)
  return '首页趋势区保留完整历史条视图，可继续查看近阶段状态波动。'
})

const focusTooltip = computed(() => {
  if (failureSystems.value.length) return failureInline.value
  if (unknownSystems.value.length) return `当前暂无可用数据：${unknownInline.value}`
  return ''
})

function latestSystemRecord(system, dayKey = '') {
  const records = Array.isArray(system?.records) ? system.records : []
  if (!records.length) return null
  if (dayKey) {
    const matched = records.find(item => item.day === dayKey)
    if (matched) return matched
  }
  return records[records.length - 1]
}

function resolveDashboardStatus(record, target, dayKey = '') {
  if (!record || !dayKey || dayKey < historyUnknownBefore) return 'unknown'
  if (record.status === 'unknown' || record.sla == null) return 'unknown'
  const sla = Number(record.sla)
  const slo = Number(record.target ?? target)
  if (!Number.isFinite(sla)) return 'unknown'
  if (Number.isFinite(slo)) return sla >= slo ? 'healthy' : 'critical'
  return record.status === 'healthy' ? 'healthy' : record.status === 'critical' ? 'critical' : 'unknown'
}

function truncateText(text = '', maxLength = 0) {
  if (!text || !maxLength || text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}...`
}

function openOverview(tab) {
  router.push({
    name: 'ObservabilityOverview',
    query: { tab },
  })
}

async function loadDashboardSummary(showMessage = false) {
  loading.value = true
  try {
    dashboardHistory.value = await getObservabilitySystemPostureHistory({ days: 30 })
    if (showMessage) ElMessage.success('首页态势已刷新')
  } catch (error) {
    console.error('获取首页态势摘要失败', error)
    ElMessage.error('获取首页态势摘要失败')
  } finally {
    loading.value = false
  }
}

async function refreshDashboard() {
  await loadDashboardSummary(true)
  historyPanelKey.value += 1
}

onMounted(() => {
  loadDashboardSummary()
})
</script>

<style scoped>
.dashboard-page {
  min-height: 100%;
  padding: 0 0 24px;
}

.panel {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}

.focus-strip,
.focus-strip__signal,
.focus-strip__body,
.focus-strip__actions,
.summary-card__head {
  display: flex;
  gap: 10px;
}

.dashboard-stats {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 6px;
}

.summary-card {
  border: 1px solid #e8edf2;
  border-radius: 14px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.03);
  padding: 10px 12px;
  position: relative;
  overflow: hidden;
}

.summary-card::after {
  background: linear-gradient(90deg, rgba(255, 255, 255, 0), rgba(255, 255, 255, 0.6));
  content: '';
  inset: 0 auto 0 0;
  position: absolute;
  width: 100%;
  pointer-events: none;
}

.summary-card.context {
  background: linear-gradient(180deg, #ffffff 0%, #f7fbff 100%);
}

.summary-card.success {
  background: linear-gradient(180deg, #ffffff 0%, #f5fbf7 100%);
}

.summary-card.danger {
  background: linear-gradient(180deg, #ffffff 0%, #fff6f7 100%);
}

.summary-card.neutral {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.summary-card__head {
  align-items: center;
  justify-content: space-between;
}

.summary-card__label {
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}

.summary-card__icon {
  align-items: center;
  border-radius: 9px;
  color: #64748b;
  display: inline-flex;
  height: 24px;
  justify-content: center;
  width: 24px;
}

.summary-card.context .summary-card__icon {
  background: #eef4ff;
  color: #2563eb;
}

.summary-card.success .summary-card__icon {
  background: #ecfdf3;
  color: #18a957;
}

.summary-card.danger .summary-card__icon {
  background: #fff1f3;
  color: #e11d48;
}

.summary-card.neutral .summary-card__icon {
  background: #f1f5f9;
  color: #64748b;
}

.summary-card__value-row {
  align-items: baseline;
  display: flex;
  gap: 4px;
  margin-top: 10px;
}

.summary-card__value {
  color: #0f172a;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  min-width: 0;
}

.summary-card__unit {
  color: #8b95a1;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}

.summary-card__meta {
  color: #7b8794;
  font-size: 10px;
  line-height: 1.4;
  margin-top: 5px;
}

.focus-strip {
  align-items: center;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  margin-bottom: 8px;
  padding: 10px 12px;
  position: relative;
}

.focus-strip.is-critical {
  background: linear-gradient(180deg, #fff8f9 0%, #ffffff 100%);
  border-color: #f4cdd6;
}

.focus-strip.is-unknown {
  background: linear-gradient(180deg, #fafbfc 0%, #ffffff 100%);
  border-color: #e5e7eb;
}

.focus-strip.is-healthy {
  background: linear-gradient(180deg, #f8fcfa 0%, #ffffff 100%);
  border-color: #dcefe3;
}

.focus-strip::before {
  border-radius: 14px 0 0 14px;
  content: '';
  inset: 0 auto 0 0;
  position: absolute;
  width: 4px;
}

.focus-strip.is-critical::before {
  background: #f31260;
}

.focus-strip.is-unknown::before {
  background: #c9ced6;
}

.focus-strip.is-healthy::before {
  background: #18c964;
}

.focus-strip__signal {
  align-items: center;
  flex: 0 0 auto;
  padding-top: 1px;
}

.focus-strip__icon {
  align-items: center;
  border-radius: 999px;
  display: inline-flex;
  flex: 0 0 auto;
  height: 28px;
  justify-content: center;
  width: 28px;
}

.focus-strip__icon.is-critical {
  background: #fff1f3;
  color: #e11d48;
}

.focus-strip__icon.is-unknown {
  background: #f2f4f7;
  color: #98a2b3;
}

.focus-strip__icon.is-healthy {
  background: #ecfdf3;
  color: #16a34a;
}

.focus-strip__label {
  align-items: center;
  background: rgba(255, 255, 255, 0.78);
  border-radius: 999px;
  color: #475467;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  min-height: 24px;
  padding: 0 9px;
}

.focus-strip__body {
  align-items: baseline;
  flex: 1 1 auto;
  min-width: 0;
}

.focus-strip__body strong {
  color: #111827;
  flex: 0 0 auto;
  font-size: 13px;
  line-height: 1.3;
}

.focus-strip__text {
  color: #667085;
  font-size: 12px;
  line-height: 1.4;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.focus-strip__actions {
  align-items: center;
  flex: 0 0 auto;
  gap: 8px;
}

.focus-strip__actions :deep(.el-button) {
  border-color: #dfe6e2;
  border-radius: 9px;
  color: #475467;
  min-height: 28px;
  padding: 0 10px;
}

.focus-strip__actions :deep(.el-button--primary) {
  background: #edf8f1;
  border-color: #d4e8da;
  color: #166534;
}

.focus-strip__actions :deep(.el-button--default) {
  background: #ffffff;
}

.focus-strip__actions :deep(.el-button--text) {
  color: #667085;
}

.dashboard-history-shell {
  padding: 12px 15px 14px;
}

.dashboard-history-shell__head {
  align-items: flex-start;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  justify-content: space-between;
  margin-bottom: 6px;
}

.dashboard-history-shell__title {
  flex: 1 1 auto;
  min-width: 0;
}

.dashboard-history-shell__headline {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.dashboard-history-shell__head h3 {
  color: #111827;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.2;
  margin: 0;
}

.dashboard-history-shell__tag {
  align-items: center;
  background: linear-gradient(180deg, #f5faf7 0%, #eef5f0 100%);
  border: 1px solid #e3ebe6;
  border-radius: 999px;
  color: #55606f;
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  min-height: 22px;
  padding: 0 9px;
}

.dashboard-history-shell__meta,
.history-meta-legend,
.history-meta-pill,
.history-meta-legend span {
  align-items: center;
  display: flex;
}

.dashboard-history-shell__meta {
  gap: 6px;
  justify-content: flex-end;
}

.history-meta-pill {
  background: #fafcfb;
  border: 1px solid #e8eeea;
  border-radius: 999px;
  color: #667085;
  font-size: 11px;
  line-height: 1;
  min-height: 22px;
  padding: 0 9px;
  white-space: nowrap;
}

.history-meta-legend {
  background: #fafcfb;
  border: 1px solid #e8eeea;
  border-radius: 999px;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 22px;
  padding: 0 9px;
}

.history-meta-legend span {
  color: #667085;
  font-size: 10px;
  gap: 5px;
  line-height: 1;
}

.history-meta-legend i {
  border-radius: 999px;
  display: inline-block;
  height: 6px;
  width: 12px;
}

.history-meta-legend i.is-healthy {
  background: #18c964;
}

.history-meta-legend i.is-critical {
  background: #f31260;
}

.history-meta-legend i.is-unknown {
  background: #c9ced6;
}

.dashboard-history-shell :deep(.posture-history-page) {
  background: transparent;
  justify-content: stretch;
  min-height: auto;
  padding: 0;
}

.dashboard-history-shell :deep(.status-wrap) {
  background: transparent;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  max-width: none;
}

.dashboard-history-shell :deep(.status-topbar) {
  background: linear-gradient(180deg, #f5faf7 0%, #eef5f0 100%);
  border: 1px solid #e3ebe6;
  border-radius: 12px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
  margin-bottom: 8px;
  min-height: auto;
  padding: 7px 10px;
}

.dashboard-history-shell :deep(.brand) {
  display: none;
}

.dashboard-history-shell :deep(.topbar-actions) {
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
  margin-left: auto;
  width: 100%;
}

.dashboard-history-shell :deep(.history-date-picker) {
  width: 248px;
}

.dashboard-history-shell :deep(.history-date-picker .el-input__wrapper) {
  background: rgba(255, 255, 255, 0.94);
  border-radius: 8px;
  box-shadow: 0 0 0 1px rgba(221, 231, 225, 0.56) inset;
  min-height: 28px;
}

.dashboard-history-shell :deep(.topbar-actions button) {
  background: rgba(255, 255, 255, 0.92);
  border-color: #dde6e0;
  border-radius: 8px;
  color: #475467;
  font-size: 11px;
  font-weight: 600;
  min-height: 28px;
  padding: 0 9px;
}

.dashboard-history-shell :deep(.topbar-actions button:first-of-type) {
  background: #eff8f2;
  border-color: #d8e8dd;
  color: #166534;
}

.dashboard-history-shell :deep(.topbar-actions button:hover) {
  background: #ffffff;
  border-color: #d5e1da;
}

.dashboard-history-shell :deep(.topbar-actions button:last-child) {
  display: none;
}

.dashboard-history-shell :deep(.overall) {
  display: none;
}

.dashboard-history-shell :deep(.system-status) {
  background: transparent;
  border-bottom: 0;
  padding: 0;
}

.dashboard-history-shell :deep(.block-title) {
  display: none;
}

.dashboard-history-shell :deep(.environment-section) {
  margin-bottom: 7px;
  padding: 11px 12px 8px;
}

.dashboard-history-shell :deep(.environment-section:first-of-type) {
  margin-top: 0;
}

.dashboard-history-shell :deep(.environment-head) {
  margin-bottom: 0;
  padding-bottom: 7px;
}

.dashboard-history-shell :deep(.environment-head h3) {
  font-size: 15px;
}

.dashboard-history-shell :deep(.environment-section .status-row:first-of-type) {
  padding-top: 10px;
}

.dashboard-history-shell :deep(.status-row) {
  padding: 10px 0;
}

.dashboard-history-shell :deep(.row-head) {
  margin-bottom: 7px;
}

.dashboard-history-shell :deep(.row-bars) {
  padding: 7px;
}

:global(.dashboard-focus-popper) {
  border: 1px solid #dfe3ea !important;
  border-radius: 12px !important;
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.1) !important;
  max-width: 420px;
}

.dashboard-focus-tip {
  color: #475467;
  font-size: 12px;
  line-height: 1.7;
  padding: 2px 4px;
}

@media (max-width: 1180px) {
  .dashboard-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .dashboard-page {
    padding-bottom: 16px;
  }

  .focus-strip,
  .dashboard-history-shell {
    padding-left: 14px;
    padding-right: 14px;
  }

  .focus-strip {
    align-items: flex-start;
    flex-direction: column;
  }

  .focus-strip__actions {
    width: 100%;
  }

  .dashboard-stats {
    grid-template-columns: 1fr;
  }

  .focus-strip__body {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .focus-strip__text {
    white-space: normal;
  }

  .dashboard-history-shell__meta {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .dashboard-history-shell :deep(.status-topbar) {
    padding-bottom: 10px;
  }

  .dashboard-history-shell :deep(.topbar-actions) {
    justify-content: flex-start;
  }

  .dashboard-history-shell :deep(.history-date-picker) {
    width: 100%;
  }
}
</style>
