<template>
  <div class="event-wall-page fade-in">
    <section class="hero panel">
      <div class="hero__title">
        <el-icon><Aim /></el-icon>
        <h2>事件墙</h2>
      </div>
      <div class="hero__actions">
        <el-button size="small" :loading="loading" @click="loadWall">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
        <el-button size="small" type="primary" @click="resetWindow">
          <el-icon><Clock /></el-icon>
          回到故障窗口
        </el-button>
      </div>
    </section>

    <EventWallTabs />

    <section class="metric-grid">
      <div v-for="item in statCards" :key="item.label" class="metric-cell">
        <span>{{ item.kicker }}</span>
        <strong>{{ item.value }}</strong>
        <em>{{ item.label }}</em>
      </div>
    </section>

    <section class="hint-strip">
      <el-icon><InfoFilled /></el-icon>
      <span>{{ wall.tips?.[0] || '先确定故障时刻，再按业务线、环境、应用和事件源收敛发布、配置、任务、K8s 与外部流水线事件。' }}</span>
    </section>

    <section class="query-panel panel">
      <div class="query-row">
        <el-date-picker
          v-model="faultAt"
          size="small"
          type="datetime"
          placeholder="故障发生时刻"
          class="query-time"
        />
        <el-select v-model="lookbackMinutes" size="small" class="query-select" placeholder="向前窗口">
          <el-option label="前 1 小时" :value="60" />
          <el-option label="前 2 小时" :value="120" />
          <el-option label="前 4 小时" :value="240" />
          <el-option label="前 12 小时" :value="720" />
          <el-option label="前 24 小时" :value="1440" />
        </el-select>
        <el-select v-model="afterMinutes" size="small" class="query-select" placeholder="向后窗口">
          <el-option label="不看故障后" :value="0" />
          <el-option label="后 30 分钟" :value="30" />
          <el-option label="后 1 小时" :value="60" />
          <el-option label="后 4 小时" :value="240" />
        </el-select>
        <el-button size="small" type="primary" :loading="loading" @click="applyQuery">分析</el-button>
      </div>

      <div class="preset-row">
        <span>快速窗口</span>
        <button type="button" @click="quickWindow(60, 30)">故障前 1 小时</button>
        <button type="button" @click="quickWindow(240, 60)">变更排查</button>
        <button type="button" @click="quickWindow(720, 120)">夜间巡检</button>
        <el-checkbox v-model="onlyRisk" size="small">仅看高风险</el-checkbox>
      </div>

      <div class="query-row">
        <el-select v-model="scope.business_line" size="small" placeholder="业务线" clearable filterable>
          <el-option v-for="item in filterOptions.business_lines || []" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="scope.environment" size="small" placeholder="环境" clearable filterable>
          <el-option v-for="item in filterOptions.environments || []" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="scope.application" size="small" placeholder="应用" clearable filterable>
          <el-option v-for="item in filterOptions.applications || []" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="eventSourceCode" size="small" placeholder="事件源" clearable filterable>
          <el-option v-for="item in sourceOptions" :key="item.code" :label="item.name" :value="item.code" />
        </el-select>
        <el-select v-model="resultFilter" size="small" placeholder="结果" clearable>
          <el-option label="失败" value="failed" />
          <el-option label="部分成功" value="partial" />
          <el-option label="待处理" value="pending" />
          <el-option label="成功" value="success" />
        </el-select>
        <el-input v-model="keyword" size="small" placeholder="标题 / 资源 / 操作人" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
    </section>

    <section v-if="activeFilterChips.length" class="active-filter-strip">
      <span>当前条件</span>
      <button v-for="item in activeFilterChips" :key="item.key" type="button" @click="clearFilter(item.key)">
        {{ item.label }}
        <i>×</i>
      </button>
      <button type="button" class="clear-all" @click="clearAllFilters">清空</button>
    </section>

    <section class="analysis-grid">
      <div class="panel analysis-panel">
        <div class="section-head">
          <h3>影响范围</h3>
          <span>{{ topScopes.length }} 个范围</span>
        </div>
        <button v-for="item in topScopes" :key="`${item.business_line}-${item.environment}-${item.application}`" type="button" class="scope-row" @click="focusScope(item)">
          <span>
            <strong>{{ item.application }}</strong>
            <em>{{ item.business_line }} / {{ item.environment }}</em>
          </span>
          <b>{{ item.risk_score }}</b>
          <small>{{ item.count }} 条 · 失败 {{ item.failed }} · 疑似 {{ item.suspects }} · 来源 {{ item.source_count }}</small>
        </button>
        <el-empty v-if="!loading && !topScopes.length" description="暂无聚合影响范围" />
      </div>

      <div class="panel analysis-panel">
        <div class="section-head">
          <h3>关联链路</h3>
          <span>{{ correlationChains.length }} 条链路</span>
        </div>
        <button v-for="item in correlationChains" :key="item.correlation_id" type="button" class="chain-row" @click="keyword = item.correlation_id">
          <strong>{{ item.correlation_id }}</strong>
          <span>{{ item.count }} 个事件 · 失败 {{ item.failed }} · {{ (item.source_names || []).join(' / ') }}</span>
        </button>
        <el-empty v-if="!loading && !correlationChains.length" description="暂无明显关联链路" />
      </div>

      <div class="panel analysis-panel">
        <div class="section-head">
          <h3>排查建议</h3>
          <span>{{ recommendations.length }} 条</span>
        </div>
        <ol class="recommend-list">
          <li v-for="item in recommendations" :key="item">{{ item }}</li>
        </ol>
      </div>
    </section>

    <section class="focus-grid">
      <div class="panel focus-panel">
        <div class="section-head">
          <h3>优先排查</h3>
          <span>{{ filteredSuspects.length }} 条</span>
        </div>
        <div class="suspect-list" v-loading="loading">
          <button v-for="item in filteredSuspects" :key="item.id" type="button" class="suspect-row" @click="openDetail(item)">
            <strong class="score">{{ item.suspicion_score }}</strong>
            <span class="suspect-main">
              <b>{{ item.title }}</b>
              <em>{{ item.summary || item.detail || item.resource_name || '-' }}</em>
              <small>
                {{ item.event_source?.name || moduleLabel(item.module) }} ·
                {{ relativeFaultTime(item.minutes_from_fault) }} ·
                {{ item.application || item.resource_name || '-' }}
              </small>
            </span>
            <span class="reason-stack">
              <i v-for="reason in item.suspicion_reasons || []" :key="reason">{{ reason }}</i>
            </span>
          </button>
          <el-empty v-if="!loading && !filteredSuspects.length" description="当前窗口没有高优先级疑似事件" />
        </div>
      </div>

      <div class="panel source-panel">
        <div class="section-head">
          <h3>事件源分布</h3>
          <span>{{ wall.source_breakdown?.length || 0 }} 个来源</span>
        </div>
        <button v-for="item in wall.source_breakdown || []" :key="item.code" type="button" class="source-row" @click="selectSource(item.code)">
          <span>
            <strong>{{ item.name }}</strong>
            <em>{{ item.source_kind === 'external' ? '外部接入' : '平台内置' }}</em>
          </span>
          <b>{{ item.count }}</b>
          <div class="source-track"><i :style="{ width: sourcePercent(item.count) }"></i></div>
          <small>失败 {{ item.failed }} · 关注 {{ item.warning }}</small>
        </button>
        <el-empty v-if="!loading && !(wall.source_breakdown || []).length" description="暂无事件源分布" />
      </div>
    </section>

    <section class="panel timeline-panel" v-loading="loading">
      <div class="section-head">
        <h3>故障时间线</h3>
        <span>{{ formatWindow(wall.window) }}</span>
      </div>
      <div class="axis-row">
        <span>窗口开始</span>
        <strong>故障时刻 {{ formatShortTime(wall.window?.fault_at) }}</strong>
        <span>窗口结束</span>
      </div>
      <div class="lane-stack">
        <article v-for="lane in filteredLanes" :key="lane.source.code" class="lane-row">
          <div class="lane-label">
            <strong>{{ lane.source.name }}</strong>
            <span>{{ lane.count }} 条 · 失败 {{ lane.failed }}</span>
          </div>
          <div class="lane-track">
            <i v-if="wall.window?.fault_at" class="fault-marker" :style="{ left: faultMarkerPosition }"></i>
            <button
              v-for="event in lane.events"
              :key="event.id"
              type="button"
              class="event-dot"
              :class="[`is-${event.result}`, { 'is-suspect': event.suspicion_score >= 35 }]"
              :style="{ left: eventPosition(event) }"
              :title="event.title"
              @click="openDetail(event)"
            >
              <span>{{ formatDotTime(event.occurred_at) }}</span>
              <strong>{{ event.title }}</strong>
            </button>
          </div>
        </article>
      </div>
      <el-empty v-if="!loading && !filteredLanes.length" description="当前条件下没有事件" />
    </section>

    <section class="panel table-panel">
      <div class="section-head">
        <h3>全部事件</h3>
        <span>{{ filteredEvents.length }} 条</span>
      </div>
      <el-table :data="filteredEvents" size="small" row-key="id" class="event-table" @row-click="openDetail">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ formatTime(row.occurred_at) }}</template>
        </el-table-column>
        <el-table-column prop="title" label="事件" min-width="240" show-overflow-tooltip />
        <el-table-column label="来源" width="150">
          <template #default="{ row }">{{ row.event_source?.name || moduleLabel(row.module) }}</template>
        </el-table-column>
        <el-table-column label="结果" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="tagType(row.result)">{{ resultLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="范围" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ scopeLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="距故障" width="120">
          <template #default="{ row }">{{ relativeFaultTime(row.minutes_from_fault) }}</template>
        </el-table-column>
      </el-table>
    </section>

    <el-drawer v-model="drawerVisible" title="事件详情" size="720px" append-to-body destroy-on-close>
      <div v-if="activeEvent" class="detail-stack">
        <section class="detail-section detail-section--main">
          <strong>{{ activeEvent.title }}</strong>
          <p>{{ activeEvent.summary || activeEvent.detail || '-' }}</p>
          <div class="reason-tags">
            <span v-for="reason in activeEvent.suspicion_reasons || []" :key="reason">{{ reason }}</span>
          </div>
        </section>
        <section class="detail-section">
          <div class="detail-row"><span>时间</span><b>{{ formatTime(activeEvent.occurred_at) }} · {{ relativeFaultTime(activeEvent.minutes_from_fault) }}</b></div>
          <div class="detail-row"><span>事件源</span><b>{{ activeEvent.event_source?.name || moduleLabel(activeEvent.module) }}</b></div>
          <div class="detail-row"><span>结果</span><b>{{ resultLabel(activeEvent) }}</b></div>
          <div class="detail-row"><span>业务范围</span><b>{{ scopeLabel(activeEvent) }}</b></div>
          <div class="detail-row"><span>资源</span><b>{{ activeEvent.resource_type || '-' }} / {{ activeEvent.resource_name || activeEvent.resource_id || '-' }}</b></div>
          <div class="detail-row"><span>操作人</span><b>{{ activeEvent.actor_username || activeEvent.actor_display || 'system' }}</b></div>
          <div class="detail-row"><span>关联 ID</span><b>{{ activeEvent.correlation_id || '-' }}</b></div>
        </section>
        <section v-if="relatedChainEvents.length" class="detail-section">
          <h4>同关联链路</h4>
          <button
            v-for="item in relatedChainEvents"
            :key="item.id"
            type="button"
            class="chain-event-row"
            :class="{ active: item.id === activeEvent.id }"
            @click="openDetail(item)"
          >
            <time>{{ formatTime(item.occurred_at) }}</time>
            <strong>{{ item.title }}</strong>
            <span>{{ item.event_source?.name || moduleLabel(item.module) }} · {{ resultLabel(item) }}</span>
          </button>
        </section>
        <section class="detail-section">
          <h4>关联资源</h4>
          <div class="chip-wrap">
            <span v-for="item in activeEvent.related_resources || []" :key="`${item.type}-${item.id}-${item.name}`">{{ item.name || item.id || item.type }}</span>
            <em v-if="!(activeEvent.related_resources || []).length">暂无关联资源</em>
          </div>
        </section>
        <section class="detail-section">
          <h4>变更内容</h4>
          <pre>{{ prettyJson(activeEvent.changes || {}) }}</pre>
        </section>
        <section class="detail-section">
          <h4>元数据</h4>
          <pre>{{ prettyJson(activeEvent.metadata || {}) }}</pre>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, Clock, InfoFilled, RefreshRight, Search } from '@element-plus/icons-vue'
import { getEventSources, getEventWallAnalysis, getEventWallFilterOptions } from '@/api/modules/eventwall'
import EventWallTabs from '@/components/eventwall/EventWallTabs.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const drawerVisible = ref(false)
const activeEvent = ref(null)
const wall = ref({ summary: {}, window: {}, lanes: [], suspects: [], events: [], source_breakdown: [], tips: [] })
const filterOptions = ref({ business_lines: [], environments: [], applications: [] })
const sourceOptions = ref([])
const faultAt = ref(new Date())
const lookbackMinutes = ref(240)
const afterMinutes = ref(60)
const eventSourceCode = ref('')
const resultFilter = ref('')
const keyword = ref('')
const onlyRisk = ref(false)
const scope = reactive({ business_line: '', environment: '', application: '' })

const statCards = computed(() => [
  { kicker: 'Events', value: wall.value.summary?.total || 0, label: '窗口事件' },
  { kicker: 'Failed', value: wall.value.summary?.failed || 0, label: '失败事件' },
  { kicker: 'Suspects', value: wall.value.summary?.suspects || 0, label: '优先排查' },
  { kicker: 'Sources', value: wall.value.summary?.source_count || 0, label: '事件源' },
])

const filteredEvents = computed(() => filterEvents(wall.value.events || []))
const filteredSuspects = computed(() => filterEvents(wall.value.suspects || []))
const topScopes = computed(() => wall.value.affected_scopes || [])
const correlationChains = computed(() => wall.value.correlation_chains || [])
const recommendations = computed(() => wall.value.recommendations || [])
const activeFilterChips = computed(() => {
  const chips = []
  if (scope.business_line) chips.push({ key: 'business_line', label: `业务线 ${scope.business_line}` })
  if (scope.environment) chips.push({ key: 'environment', label: `环境 ${scope.environment}` })
  if (scope.application) chips.push({ key: 'application', label: `应用 ${scope.application}` })
  if (eventSourceCode.value) {
    const source = sourceOptions.value.find(item => item.code === eventSourceCode.value)
    chips.push({ key: 'event_source_code', label: `事件源 ${source?.name || eventSourceCode.value}` })
  }
  if (resultFilter.value) chips.push({ key: 'result', label: `结果 ${resultLabel({ result: resultFilter.value })}` })
  if (keyword.value.trim()) chips.push({ key: 'search', label: `搜索 ${keyword.value.trim()}` })
  if (onlyRisk.value) chips.push({ key: 'risk', label: '仅看高风险' })
  return chips
})
const relatedChainEvents = computed(() => {
  const correlationId = activeEvent.value?.correlation_id
  if (!correlationId) return []
  return (wall.value.events || [])
    .filter(item => item.correlation_id === correlationId)
    .sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at))
})
const filteredLanes = computed(() => {
  return (wall.value.lanes || [])
    .map((lane) => {
      const events = filterEvents(lane.events || [])
      return { ...lane, events, count: events.length }
    })
    .filter((lane) => lane.events.length)
})
const maxSourceCount = computed(() => Math.max(...(wall.value.source_breakdown || []).map(item => item.count || 0), 1))
const faultMarkerPosition = computed(() => datePosition(wall.value.window?.fault_at))

function filterEvents(events) {
  const key = keyword.value.trim().toLowerCase()
  return events.filter((item) => {
    if (resultFilter.value && item.result !== resultFilter.value) return false
    if (eventSourceCode.value && item.event_source?.code !== eventSourceCode.value) return false
    if (onlyRisk.value && item.result !== 'failed' && !['warning', 'danger'].includes(item.severity) && (item.suspicion_score || 0) < 35) return false
    if (!key) return true
    return [item.title, item.summary, item.detail, item.resource_name, item.resource_id, item.actor_username, item.application, item.correlation_id]
      .some(value => String(value || '').toLowerCase().includes(key))
  })
}

function restoreFromRoute() {
  const query = route.query
  const queryFaultAt = query.fault_at ? new Date(String(query.fault_at)) : new Date()
  faultAt.value = Number.isNaN(queryFaultAt.getTime()) ? new Date() : queryFaultAt
  lookbackMinutes.value = Number(query.lookback_minutes || 240)
  afterMinutes.value = Number(query.after_minutes || 60)
  eventSourceCode.value = String(query.event_source_code || '')
  resultFilter.value = String(query.result || '')
  keyword.value = String(query.search || '')
  onlyRisk.value = ['1', 'true'].includes(String(query.risk || '').toLowerCase())
  scope.business_line = String(query.business_line || '')
  scope.environment = String(query.environment || '')
  scope.application = String(query.application || '')
}

function buildParams() {
  const currentFaultAt = faultAt.value instanceof Date ? faultAt.value : new Date(faultAt.value)
  const safeFaultAt = Number.isNaN(currentFaultAt.getTime()) ? new Date() : currentFaultAt
  const params = {
    fault_at: safeFaultAt.toISOString(),
    lookback_minutes: lookbackMinutes.value,
    after_minutes: afterMinutes.value,
    limit: 240,
  }
  if (scope.business_line) params.business_line = scope.business_line
  if (scope.environment) params.environment = scope.environment
  if (scope.application) params.application = scope.application
  if (eventSourceCode.value) params.event_source_code = eventSourceCode.value
  return params
}

async function loadFilterOptions() {
  const [options, sources] = await Promise.all([
    getEventWallFilterOptions(),
    getEventSources({ page_size: 100 }),
  ])
  filterOptions.value = options || {}
  sourceOptions.value = sources.results || sources || []
}

async function loadWall() {
  loading.value = true
  try {
    wall.value = await getEventWallAnalysis(buildParams())
  } finally {
    loading.value = false
  }
}

async function applyQuery() {
  const query = {
    ...buildParams(),
    result: resultFilter.value || undefined,
    search: keyword.value || undefined,
    risk: onlyRisk.value ? '1' : undefined,
  }
  await router.replace({ path: '/events/wall', query })
  await loadWall()
}

async function resetWindow() {
  faultAt.value = new Date()
  lookbackMinutes.value = 240
  afterMinutes.value = 60
  resultFilter.value = ''
  keyword.value = ''
  await applyQuery()
}

async function quickWindow(lookback, after) {
  lookbackMinutes.value = lookback
  afterMinutes.value = after
  await applyQuery()
}

async function focusScope(item) {
  scope.business_line = item.business_line === '未标注业务线' ? '' : item.business_line
  scope.environment = item.environment === '未标注环境' ? '' : item.environment
  scope.application = item.application === '未标注应用' ? '' : item.application
  await applyQuery()
}

async function selectSource(code) {
  eventSourceCode.value = eventSourceCode.value === code ? '' : code
  await applyQuery()
}

async function clearFilter(key) {
  if (key === 'business_line') scope.business_line = ''
  else if (key === 'environment') scope.environment = ''
  else if (key === 'application') scope.application = ''
  else if (key === 'event_source_code') eventSourceCode.value = ''
  else if (key === 'result') resultFilter.value = ''
  else if (key === 'search') keyword.value = ''
  else if (key === 'risk') onlyRisk.value = false
  await applyQuery()
}

async function clearAllFilters() {
  scope.business_line = ''
  scope.environment = ''
  scope.application = ''
  eventSourceCode.value = ''
  resultFilter.value = ''
  keyword.value = ''
  onlyRisk.value = false
  await applyQuery()
}

function openDetail(row) {
  activeEvent.value = row
  drawerVisible.value = true
}

function sourcePercent(count) {
  return `${Math.max(6, Math.round(((count || 0) / maxSourceCount.value) * 100))}%`
}

function datePosition(value) {
  const start = new Date(wall.value.window?.start_at).getTime()
  const end = new Date(wall.value.window?.end_at).getTime()
  const current = new Date(value).getTime()
  if (![start, end, current].every(Number.isFinite) || end <= start) return '50%'
  const percent = ((current - start) / (end - start)) * 100
  return `${Math.min(96, Math.max(2, percent))}%`
}

function eventPosition(event) {
  return datePosition(event.occurred_at)
}

function tagType(result) {
  return { success: 'success', failed: 'danger', partial: 'warning', pending: 'warning' }[result] || 'info'
}

function resultLabel(row) {
  return row.result_display || { success: '成功', failed: '失败', partial: '部分成功', pending: '待处理' }[row.result] || row.result || '-'
}

function moduleLabel(module) {
  return {
    ops: '运维平台',
    cmdb: 'CMDB',
    sqlaudit: 'SQL 审计',
    marketplace: '工具市场',
    eventwall: '事件墙',
  }[module] || module || '其他事件'
}

function scopeLabel(row) {
  return [row.business_line, row.environment, row.application].filter(Boolean).join(' / ') || row.resource_name || '-'
}

function relativeFaultTime(minutes) {
  if (minutes === null || minutes === undefined || Number.isNaN(Number(minutes))) return '-'
  const value = Number(minutes)
  if (Math.abs(value) < 1) return '故障时刻'
  const abs = Math.abs(value)
  const text = abs >= 60 ? `${(abs / 60).toFixed(abs >= 120 ? 0 : 1)} 小时` : `${Math.round(abs)} 分钟`
  return value < 0 ? `故障前 ${text}` : `故障后 ${text}`
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function formatShortTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatDotTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatWindow(window) {
  if (!window?.start_at || !window?.end_at) return '最近事件窗口'
  return `${formatTime(window.start_at)} - ${formatTime(window.end_at)}`
}

function prettyJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

onMounted(async () => {
  restoreFromRoute()
  await loadFilterOptions()
  await loadWall()
})
</script>

<style scoped>
.event-wall-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  color: #1f2329;
}

.panel {
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
}

.hero {
  min-height: 64px;
  padding: 14px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero__title,
.hero__actions,
.query-row,
.section-head,
.axis-row {
  display: flex;
  align-items: center;
}

.hero__title {
  gap: 10px;
}

.hero__title h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}

.hero__title .el-icon {
  color: #3370ff;
  font-size: 22px;
}

.hero__actions {
  gap: 8px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-cell {
  min-height: 82px;
  padding: 13px 14px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.metric-cell span {
  font-size: 12px;
  color: #8f959e;
}

.metric-cell strong {
  font-size: 26px;
  line-height: 1;
  color: #1f2329;
}

.metric-cell em,
.source-row em,
.suspect-row em,
.suspect-row small,
.lane-label span,
.source-row small {
  font-style: normal;
  color: #646a73;
}

.hint-strip {
  min-height: 38px;
  padding: 9px 12px;
  border: 1px solid #bacefd;
  border-radius: 8px;
  background: #f3f7ff;
  color: #245bdb;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.query-panel {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.query-row {
  gap: 8px;
  flex-wrap: wrap;
}

.preset-row {
  min-height: 30px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #646a73;
}

.preset-row button {
  height: 26px;
  padding: 0 10px;
  border: 1px solid #dee0e3;
  border-radius: 6px;
  background: #fff;
  color: #1f2329;
  cursor: pointer;
}

.preset-row button:hover {
  border-color: #bacefd;
  color: #245bdb;
  background: #f7faff;
}

.query-row :deep(.el-select),
.query-row :deep(.el-input) {
  width: 180px;
}

.query-time {
  width: 210px;
}

.query-select {
  width: 130px !important;
}

.active-filter-strip {
  min-height: 34px;
  padding: 6px 8px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
}

.active-filter-strip > span {
  color: #8f959e;
}

.active-filter-strip button {
  height: 24px;
  padding: 0 8px;
  border: 1px solid #dee0e3;
  border-radius: 6px;
  background: #f7f8fa;
  color: #4e5969;
  cursor: pointer;
}

.active-filter-strip button:hover {
  border-color: #bacefd;
  color: #245bdb;
  background: #f7faff;
}

.active-filter-strip button i {
  margin-left: 5px;
  color: #8f959e;
  font-style: normal;
}

.active-filter-strip .clear-all {
  background: #fff;
  color: #245bdb;
}

.focus-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 12px;
}

.analysis-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.1fr) minmax(280px, .8fr);
  gap: 12px;
}

.focus-panel,
.source-panel,
.analysis-panel,
.timeline-panel,
.table-panel {
  padding: 14px;
}

.section-head {
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.section-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.section-head span {
  color: #8f959e;
  font-size: 12px;
}

.suspect-list,
.source-panel,
.analysis-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.suspect-row,
.scope-row,
.chain-row,
.source-row,
.event-dot {
  border: 0;
  background: transparent;
  font: inherit;
  cursor: pointer;
}

.suspect-row {
  width: 100%;
  padding: 10px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) 190px;
  gap: 10px;
  text-align: left;
}

.suspect-row:hover,
.scope-row:hover,
.chain-row:hover,
.source-row:hover {
  border-color: #bacefd;
  background: #f7faff;
}

.scope-row,
.chain-row {
  width: 100%;
  padding: 10px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  display: grid;
  gap: 5px 10px;
  text-align: left;
}

.scope-row {
  grid-template-columns: minmax(0, 1fr) auto;
}

.scope-row span,
.chain-row {
  min-width: 0;
}

.scope-row strong,
.scope-row em,
.scope-row small,
.chain-row strong,
.chain-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scope-row span {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.scope-row em,
.scope-row small,
.chain-row span {
  color: #646a73;
  font-size: 12px;
  font-style: normal;
}

.scope-row b {
  color: #245bdb;
}

.scope-row small {
  grid-column: 1 / -1;
}

.recommend-list {
  margin: 0;
  padding-left: 18px;
  color: #4e5969;
  line-height: 1.7;
  font-size: 13px;
}

.recommend-list li + li {
  margin-top: 6px;
}

.score {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: #e8f0ff;
  color: #245bdb;
  display: grid;
  place-items: center;
}

.suspect-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suspect-main b,
.suspect-main em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reason-stack {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
}

.reason-stack i,
.reason-tags span,
.chip-wrap span {
  padding: 2px 7px;
  border-radius: 6px;
  background: #f2f3f5;
  color: #4e5969;
  font-size: 12px;
  font-style: normal;
}

.source-row {
  position: relative;
  padding: 10px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  text-align: left;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px 10px;
}

.source-row span {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.source-track {
  grid-column: 1 / -1;
  height: 6px;
  border-radius: 999px;
  background: #eff0f1;
  overflow: hidden;
}

.source-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #3370ff;
}

.source-row small {
  grid-column: 1 / -1;
}

.axis-row {
  height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  background: #f7f8fa;
  justify-content: space-between;
  font-size: 12px;
  color: #646a73;
}

.axis-row strong {
  color: #245bdb;
}

.lane-stack {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.lane-row {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}

.lane-label {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.lane-label strong,
.lane-label span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lane-track {
  position: relative;
  min-height: 52px;
  border-radius: 8px;
  background: #f7f8fa;
  overflow: hidden;
}

.fault-marker {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #f54a45;
  z-index: 2;
}

.event-dot {
  position: absolute;
  top: 9px;
  width: 118px;
  transform: translateX(-12px);
  padding: 5px 8px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  overflow: hidden;
}

.event-dot span,
.event-dot strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-dot span {
  font-size: 11px;
  color: #8f959e;
}

.event-dot strong {
  font-size: 12px;
  font-weight: 600;
}

.event-dot.is-failed,
.event-dot.is-suspect {
  border-color: #f54a45;
}

.event-dot.is-partial,
.event-dot.is-pending {
  border-color: #ffb11a;
}

.event-table :deep(.el-table__row) {
  cursor: pointer;
}

.detail-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-section {
  padding: 12px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
}

.detail-section--main {
  background: #f7faff;
  border-color: #bacefd;
}

.detail-section strong {
  font-size: 16px;
}

.detail-section p {
  margin: 8px 0 0;
  color: #646a73;
  line-height: 1.6;
}

.detail-section h4 {
  margin: 0 0 10px;
  font-size: 14px;
}

.chain-event-row {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
  display: grid;
  grid-template-columns: 145px minmax(0, 1fr);
  gap: 4px 10px;
  text-align: left;
  cursor: pointer;
}

.chain-event-row + .chain-event-row {
  margin-top: 6px;
}

.chain-event-row:hover,
.chain-event-row.active {
  border-color: #bacefd;
  background: #f7faff;
}

.chain-event-row time {
  color: #8f959e;
  font-size: 12px;
}

.chain-event-row strong,
.chain-event-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chain-event-row span {
  grid-column: 2;
  color: #646a73;
  font-size: 12px;
}

.detail-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #eff0f1;
}

.detail-row:last-child {
  border-bottom: 0;
}

.detail-row span {
  color: #8f959e;
}

.detail-row b {
  min-width: 0;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.reason-tags,
.chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip-wrap em {
  color: #8f959e;
  font-style: normal;
}

pre {
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  background: #f7f8fa;
  color: #1f2329;
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 1100px) {
  .metric-grid,
  .focus-grid,
  .analysis-grid {
    grid-template-columns: 1fr 1fr;
  }

  .suspect-row {
    grid-template-columns: 44px minmax(0, 1fr);
  }

  .reason-stack {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .hero,
  .hero__actions {
    align-items: stretch;
    flex-direction: column;
  }

  .metric-grid,
  .focus-grid,
  .analysis-grid,
  .lane-row {
    grid-template-columns: 1fr;
  }

  .query-row :deep(.el-select),
  .query-row :deep(.el-input),
  .query-time,
  .query-select {
    width: 100% !important;
  }

  .chain-event-row {
    grid-template-columns: 1fr;
  }

  .chain-event-row span {
    grid-column: 1;
  }
}
</style>
