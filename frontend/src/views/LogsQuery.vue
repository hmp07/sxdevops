<template>
  <div class="logs-query-page">
    <div class="page-header compact-header">
      <div class="page-title-row">
        <h2>日志中心</h2>
        <p class="page-desc">{{ activeLogTab.description }}</p>
      </div>
    </div>

    <div class="neo-tabs theme-blue log-center-tabs">
      <button
        v-for="tab in logTabs"
        :key="tab.path"
        class="neo-tab-btn"
        :class="{ active: route.path === tab.path }"
        @click="switchLogTab(tab.path)"
      >
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <el-empty v-if="!dataSources.length && !loadingSources" description="还没有日志数据源，请先新增后再查询。">
      <el-button type="primary" @click="goToDatasources">去新增数据源</el-button>
    </el-empty>

    <template v-else>
      <section class="panel tabs-panel">
        <el-tabs v-model="activeTabName" type="card" editable @edit="handleTabsEdit">
          <el-tab-pane v-for="tab in queryTabs" :key="tab.id" :name="tab.id" :label="tab.title" />
        </el-tabs>
      </section>

      <div v-if="currentTab" class="query-layout">
        <section class="panel query-panel">
          <div class="panel-head slim-head">
            <h3>查询条件</h3>
            <div class="toolbar-actions">
              <el-button @click="saveFavorite(currentTab)" :disabled="!currentTab.datasourceId">收藏此查询</el-button>
              <el-button @click="savedDialogVisible = true">查询历史/收藏</el-button>
              <el-button @click="loadCatalog(currentTab)" :loading="currentTab.catalogLoading">刷新数据源</el-button>
              <el-button type="primary" @click="runQuery(currentTab)" :loading="currentTab.queryLoading">查询日志</el-button>
            </div>
          </div>

          <el-form label-position="top">
            <el-form-item label="日志数据源">
              <el-select v-model="currentTab.datasourceId" filterable placeholder="请选择日志数据源" style="width: 100%" @change="handleDatasourceChange">
                <el-option
                  v-for="item in dataSources"
                  :key="item.id"
                  :label="`${item.name}（${providerLabel(item.provider)}）`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="时间范围">
              <el-date-picker
                v-model="currentTab.timeRange"
                type="datetimerange"
                format="YYYY-MM-DD HH:mm:ss"
                range-separator="至"
                start-placeholder="开始时间"
                end-placeholder="结束时间"
                @change="handleTimeRangeChange(currentTab)"
              />
              <div class="quick-ranges">
                <button
                  v-for="item in quickRanges"
                  :key="item.key"
                  type="button"
                  class="quick-range-btn"
                  :class="{ active: currentTab.quickRange === item.key }"
                  @click="applyQuickRange(currentTab, item)"
                >
                  {{ item.label }}
                </button>
              </div>
            </el-form-item>

            <el-form-item label="返回条数">
              <el-input-number v-model="currentTab.limit" :min="20" :max="2000" :step="20" />
              <span class="inline-tip">演示数据源已扩充更多日志，返回条数会尽量按上限展示。</span>
            </el-form-item>

            <template v-if="isLoki">
              <el-form-item label="标签过滤">
                <div class="stack">
                  <div v-for="(filter, index) in currentTab.labelFilters" :key="index" class="filter-row">
                    <el-select v-model="filter.key" placeholder="标签" filterable @change="onLokiLabelKeyChange(currentTab, index)">
                      <el-option v-for="item in currentTab.lokiLabels" :key="item" :label="item" :value="item" />
                    </el-select>
                    <el-select v-model="filter.operator" class="operator-select">
                      <el-option label="=" value="=" />
                      <el-option label="!=" value="!=" />
                      <el-option label="=~" value="=~" />
                      <el-option label="!~" value="!~" />
                    </el-select>
                    <el-select v-model="filter.value" placeholder="值" filterable allow-create @focus="loadLokiLabelValues(currentTab, index)">
                      <el-option v-for="item in filter.options" :key="item" :label="item" :value="item" />
                    </el-select>
                    <el-button text type="danger" @click="removeLabelFilter(currentTab, index)">移除</el-button>
                  </div>
                  <el-button text type="primary" @click="addLabelFilter(currentTab)">新增标签</el-button>
                </div>
              </el-form-item>
              <el-form-item label="内容检索">
                <el-input v-model="currentTab.lokiContentQuery" placeholder="例如：error OR timeout" />
              </el-form-item>
              <el-form-item>
                <template #label>
                  <span class="field-label-with-help">
                    <span>LogQL</span>
                    <el-button link type="primary" @click="openSyntaxHelp('loki')">查询语法帮助</el-button>
                  </span>
                </template>
                <el-input v-model="currentTab.lokiManualQuery" type="textarea" :rows="3" placeholder='{job="nginx"} |= "error"' />
                <div class="helper">留空时自动生成：{{ generatedLokiQuery }}</div>
              </el-form-item>
            </template>

            <template v-else-if="isElk">
              <el-form-item label="索引">
                <el-select v-model="currentTab.sourceName" placeholder="选择索引或直接输入索引模式" filterable allow-create clearable>
                  <el-option v-for="item in currentTab.catalogItems" :key="item.name" :label="item.name" :value="item.name" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <template #label>
                  <span class="field-label-with-help">
                    <span>Lucene 查询</span>
                    <el-button link type="primary" @click="openSyntaxHelp('elk')">查询语法帮助</el-button>
                  </span>
                </template>
                <el-input v-model="currentTab.queryText" type="textarea" :rows="3" placeholder='service.name:"payment" AND level:error' />
              </el-form-item>
            </template>

            <template v-else-if="isSls">
              <el-form-item label="Logstore">
                <el-select v-model="currentTab.sourceName" placeholder="选择 Logstore" filterable allow-create clearable>
                  <el-option v-for="item in currentTab.catalogItems" :key="item.name" :label="item.name" :value="item.name" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <template #label>
                  <span class="field-label-with-help">
                    <span>SLS 查询语句</span>
                    <el-button link type="primary" @click="openSyntaxHelp('sls')">查询语法帮助</el-button>
                  </span>
                </template>
                <el-input v-model="currentTab.queryText" type="textarea" :rows="3" placeholder='timeout OR auth error OR cache' />
              </el-form-item>
            </template>
          </el-form>
        </section>

        <section class="panel info-panel">
          <div class="panel-head slim-head">
            <h3>当前数据源</h3>
            <el-tag v-if="currentDataSource" :type="providerTagType(activeProvider)">{{ providerLabel(activeProvider) }}</el-tag>
          </div>

          <div v-if="currentDataSource" class="source-card compact-card">
            <div class="source-title-row">
              <strong class="source-title">{{ currentDataSource.name }}</strong>
              <el-tag v-if="currentDataSource.is_default" size="small" type="warning">默认</el-tag>
            </div>
            <p class="source-desc">{{ currentDataSource.description || '未填写描述' }}</p>
            <div class="source-meta">
              <span>状态：{{ currentDataSource.is_enabled ? '启用' : '停用' }}</span>
              <span>更新时间：{{ formatTime(currentDataSource.updated_at) }}</span>
            </div>
            <div class="summary-list">
              <div class="summary-item" v-for="item in currentSummary" :key="item.label">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
          </div>

          <div class="tips-box compact-card">
            <strong>查询提示</strong>
            <p v-if="isLoki">Loki 当前可暂时忽略，后续恢复连通后可再演示。</p>
            <p v-else-if="isElk">可直接演示 `payment error`、`gateway warning`、`checkout error`。</p>
            <p v-else-if="isSls">可直接演示 `timeout`、`auth error`、`cache`，并切换不同 Logstore。</p>
            <p v-else>请选择一个日志数据源开始查询。</p>
          </div>
        </section>
      </div>

      <div v-if="currentTab" class="stats-grid compact-stats">
        <div class="stat-card warm">
          <span>日志总数</span>
          <strong>{{ currentResults.total || 0 }}</strong>
        </div>
        <div class="stat-card cool">
          <span>当前来源</span>
          <strong>{{ currentResults.source || '--' }}</strong>
        </div>
        <div class="stat-card accent">
          <span>查询耗时</span>
          <strong>{{ currentResults.took_ms != null ? `${currentResults.took_ms} ms` : '--' }}</strong>
        </div>
        <div class="stat-card neutral">
          <span>错误日志</span>
          <strong>{{ errorCount }}</strong>
        </div>
      </div>

      <section v-if="currentTab" class="panel chart-panel compact-panel">
        <div class="panel-head slim-head">
          <h3>趋势图</h3>
          <span>{{ currentResults.logs.length ? '按时间聚合展示' : '暂无图表数据' }}</span>
        </div>
        <div ref="chartRef" class="chart"></div>
      </section>

      <section v-if="currentTab" class="panel compact-panel">
        <div class="panel-head slim-head">
          <h3>查询结果</h3>
          <div class="result-tags">
            <el-tag type="warning">总匹配 {{ currentResults.total || 0 }} 条</el-tag>
            <el-tag type="success">已返回 {{ currentResults.logs.length }} 条</el-tag>
            <el-tag v-if="currentResults.progress" type="info">{{ currentResults.progress }}</el-tag>
          </div>
        </div>
        <el-alert v-if="currentTab.errorMessage" :title="currentTab.errorMessage" type="error" show-icon :closable="false" />
        <div v-else-if="currentTab.queryLoading" class="empty-state compact-empty">正在查询日志...</div>
        <div v-else-if="!currentResults.logs.length" class="empty-state compact-empty">暂无日志结果，请调整条件后重试。</div>
        <div v-else class="log-list compact-list">
          <article v-for="(item, index) in currentResults.logs" :key="`${item.timestamp}-${index}`" class="log-card compact-log-card">
            <button class="log-main compact-log-main expandable" @click="toggleRow(currentTab, index)">
              <div class="log-head-row">
                <div class="log-meta-inline">
                  <span class="time-text">{{ formatTimestamp(item.timestamp) }}</span>
                  <el-tag size="small" :type="levelTagType(item.level)">{{ levelLabel(item.level) }}</el-tag>
                  <span class="source-text">{{ item.source }}</span>
                </div>
                <span class="expand-text">{{ isExpanded(currentTab, index) ? '收起' : '展开' }}</span>
              </div>
              <div class="log-message inline-message" v-html="formatMessage(item.message)"></div>
            </button>
            <div v-if="isExpanded(currentTab, index)" class="log-detail compact-detail">
              <div class="attribute-grid compact-grid">
                <div v-for="attr in displayAttributes(item.attributes)" :key="attr.key" class="attribute-card compact-attr">
                  <strong>{{ attr.key }}</strong>
                  <span>{{ attr.value }}</span>
                </div>
              </div>
              <pre>{{ item.message }}</pre>
            </div>
          </article>
        </div>
      </section>
    </template>

    <el-dialog v-model="savedDialogVisible" title="查询历史与收藏" width="720px" class="saved-dialog">
      <div class="saved-dialog-head">
        <el-tabs v-model="savedTab" stretch class="saved-tabs">
          <el-tab-pane :label="`收藏条件（${favoriteItems.length}）`" name="favorites" />
          <el-tab-pane :label="`查询历史（${historyItems.length}）`" name="history" />
        </el-tabs>
        <el-button v-if="savedTab === 'history' && historyItems.length" text type="danger" @click="clearHistory">清空历史</el-button>
      </div>

      <div v-if="savedTab === 'favorites'">
        <div v-if="!favoriteItems.length" class="saved-empty">还没有收藏条件，可先配置一次再收藏。</div>
        <div v-else class="saved-list dialog-list">
          <article v-for="item in favoriteItems" :key="item.id" class="saved-item">
            <button class="saved-main" @click="applySavedQuery(item)">
              <strong>{{ item.title }}</strong>
              <span>{{ item.datasourceName || providerLabel(item.provider) }}</span>
              <p>{{ formatSavedSummary(item) }}</p>
            </button>
            <div class="saved-actions">
              <el-button text type="primary" @click.stop="applySavedQuery(item)">套用</el-button>
              <el-button text type="danger" @click.stop="removeFavorite(item.id)">删除</el-button>
            </div>
          </article>
        </div>
      </div>

      <div v-else>
        <div v-if="!historyItems.length" class="saved-empty">暂无查询历史，执行一次查询后会自动记录。</div>
        <div v-else class="saved-list dialog-list">
          <article v-for="item in historyItems" :key="item.id" class="saved-item">
            <button class="saved-main" @click="applySavedQuery(item)">
              <strong>{{ item.title }}</strong>
              <span>{{ item.datasourceName || providerLabel(item.provider) }} · {{ formatSavedTime(item.savedAt) }}</span>
              <p>{{ formatSavedSummary(item) }}</p>
            </button>
            <div class="saved-actions">
              <el-button text type="primary" @click.stop="applySavedQuery(item)">套用</el-button>
              <el-button text @click.stop="saveFavoriteFromItem(item)">收藏</el-button>
            </div>
          </article>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="helpDialogVisible" :title="currentHelpDoc.title" width="680px" class="syntax-help-dialog">
      <div class="syntax-help">
        <p class="syntax-desc">{{ currentHelpDoc.description }}</p>
        <div class="syntax-block">
          <strong>常用写法</strong>
          <ul>
            <li v-for="item in currentHelpDoc.examples" :key="item">
              <code>{{ item }}</code>
            </li>
          </ul>
        </div>
        <div class="syntax-block">
          <strong>使用提示</strong>
          <ul>
            <li v-for="item in currentHelpDoc.tips" :key="item">{{ item }}</li>
          </ul>
        </div>
        <el-link :href="currentHelpDoc.link" target="_blank" type="primary">查看官方查询语法文档</el-link>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { getLogDataSources, getLogProviderCatalog, queryLogs } from '@/api/modules/ops'

const route = useRoute()
const router = useRouter()
const LAST_DATASOURCE_KEY = 'logs:last-datasource-id'
const QUERY_HISTORY_KEY = 'logs:query-history'
const QUERY_FAVORITES_KEY = 'logs:query-favorites'
const DEFAULT_DATASOURCE_NAME = 'SLS 演示（上海）'
const MAX_HISTORY_ITEMS = 12
const logTabs = [
  {
    path: '/logs/query',
    label: '日志查询',
    icon: 'Search',
    description: '支持 ELK、Loki、阿里云 SLS 日志查询，可在页面内新增多个查询标签页并快速切换条件。',
  },
  {
    path: '/logs/datasources',
    label: '日志数据源',
    icon: 'DataBoard',
    description: '统一管理 Loki、ELK 和阿里云 SLS 的连接配置，查询页可以直接复用已保存的数据源。',
  },
]
const activeLogTab = computed(() => logTabs.find((item) => item.path === route.path) || logTabs[0])
const MAX_FAVORITE_ITEMS = 8
const SYNTAX_HELP_DOCS = {
  loki: {
    title: 'Loki / LogQL 帮助',
    description: '适合基于标签筛选日志，再叠加关键字或正则过滤内容。',
    examples: [
      '{job="gateway"}',
      '{job="gateway", namespace="prod"} |= "timeout"',
      '{app=~"payment|checkout"} |~ "error|exception"',
    ],
    tips: [
      '花括号里写标签过滤，适合先缩小日志范围。',
      '|= 表示包含关键字，|~ 表示正则匹配。',
      '内容为空时，页面会根据上面的标签过滤自动生成基础 LogQL。',
    ],
    link: 'https://grafana.com/docs/loki/latest/query/',
  },
  elk: {
    title: 'ELK / Lucene 查询帮助',
    description: '适合按字段精确过滤、布尔组合和通配匹配 Elasticsearch 日志。',
    examples: [
      'service.name:"payment" AND level:error',
      'host.name:app-02 OR host.name:app-03',
      'message:timeout AND NOT env:staging',
    ],
    tips: [
      '字段查询推荐使用 field:value 或 field:"phrase"。',
      '支持 AND、OR、NOT 组合条件。',
      '可结合索引模式一起缩小查询范围。',
    ],
    link: 'https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-query-string-query',
  },
  sls: {
    title: '阿里云 SLS 查询帮助',
    description: '适合关键字检索、字段过滤和布尔查询，演示场景可直接搜 timeout、auth、cache。',
    examples: [
      'timeout',
      'level:ERROR AND service:auth-service',
      'host:sls-app-04 OR message:cache',
    ],
    tips: [
      '可直接搜关键字，也可写 field:value 形式。',
      '支持 AND、OR、NOT 组合条件。',
      '先选定 Logstore，再输入条件更接近真实 SLS 使用方式。',
    ],
    link: 'https://www.alibabacloud.com/help/en/sls/query-syntax/',
  },
}
const quickRanges = [
  { key: '10m', label: '最近10分钟', minutes: 10 },
  { key: '30m', label: '最近30分钟', minutes: 30 },
  { key: '1h', label: '最近1小时', minutes: 60 },
  { key: '6h', label: '最近6小时', minutes: 360 },
]

const loadingSources = ref(false)
const dataSources = ref([])
const queryTabs = ref([])
const activeTabName = ref('')
const historyItems = ref([])
const favoriteItems = ref([])
const savedTab = ref('favorites')
const savedDialogVisible = ref(false)
const helpDialogVisible = ref(false)
const helpProvider = ref('loki')
const chartRef = ref(null)
let chart = null
let tabSeed = 1

const currentTab = computed(() => queryTabs.value.find((item) => item.id === activeTabName.value) || null)
const currentDataSource = computed(() => dataSources.value.find((item) => item.id === currentTab.value?.datasourceId) || null)
const activeProvider = computed(() => currentDataSource.value?.provider || '')
const isLoki = computed(() => activeProvider.value === 'loki')
const isElk = computed(() => activeProvider.value === 'elk')
const isSls = computed(() => activeProvider.value === 'sls')
const currentResults = computed(() => currentTab.value?.results || { total: 0, source: '', took_ms: null, progress: '', logs: [] })
const errorCount = computed(() => currentResults.value.logs.filter((item) => item.level === 'error').length)
const currentHelpDoc = computed(() => SYNTAX_HELP_DOCS[helpProvider.value] || SYNTAX_HELP_DOCS.loki)
const currentSummary = computed(() => {
  const config = currentDataSource.value?.config || {}
  if (activeProvider.value === 'loki') return [{ label: '接入地址', value: config.endpoint || '--' }]
  if (activeProvider.value === 'elk') {
    return [
      { label: '接入地址', value: config.endpoint || '--' },
      { label: '索引模式', value: config.index_pattern || '--' },
      { label: '时间字段', value: config.time_field || '@timestamp' },
    ]
  }
  if (activeProvider.value === 'sls') {
    return [
      { label: 'Project', value: config.project || '--' },
      { label: 'Logstore', value: config.logstore || '--' },
      { label: 'Endpoint', value: config.endpoint || '--' },
    ]
  }
  return []
})
const generatedLokiQuery = computed(() => {
  if (!currentTab.value) return ''
  const selector = currentTab.value.labelFilters
    .filter((item) => item.key && item.value)
    .map((item) => `${item.key}${item.operator}"${escapeLogValue(item.value)}"`)
  const base = selector.length ? `{${selector.join(',')}}` : '{job!=""}'
  return currentTab.value.lokiContentQuery.trim()
    ? `${base} |= "${escapeLogValue(currentTab.value.lokiContentQuery.trim())}"`
    : base
})

watch(activeTabName, async () => {
  await nextTick()
  renderChart()
})

function defaultTimeRange(minutes = 60) {
  const end = new Date()
  return [new Date(end.getTime() - minutes * 60 * 1000), end]
}

function toTimestampMs(value) {
  if (value instanceof Date) return value.getTime()
  if (typeof value === 'number') return value
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value)
    if (!Number.isNaN(numeric)) return numeric
    const parsed = new Date(value).getTime()
    if (!Number.isNaN(parsed)) return parsed
  }
  return Date.now()
}

function normalizeTimeRange(range) {
  if (!Array.isArray(range) || range.length !== 2) return defaultTimeRange()
  return range.map((item) => {
    if (item instanceof Date) return item
    return new Date(toTimestampMs(item))
  })
}

function makeLabelFilter() {
  return { key: '', operator: '=', value: '', options: [] }
}

function emptyResults() {
  return { provider: '', source: '', total: 0, took_ms: null, progress: '', logs: [] }
}

function createQueryTab(seed = {}) {
  const serial = tabSeed++
  return reactive({
    id: `query-tab-${Date.now()}-${serial}`,
    title: seed.title || `查询 ${serial}`,
    datasourceId: seed.datasourceId || '',
    timeRange: normalizeTimeRange(seed.timeRange || defaultTimeRange()),
    quickRange: seed.quickRange || '1h',
    limit: seed.limit || 200,
    sourceName: seed.sourceName || '',
    queryText: seed.queryText || '',
    lokiLabels: [],
    labelFilters: [makeLabelFilter()],
    lokiContentQuery: '',
    lokiManualQuery: '',
    catalogItems: [],
    catalogLoading: false,
    queryLoading: false,
    errorMessage: '',
    results: emptyResults(),
    expandedRows: [],
  })
}

function providerLabel(provider) {
  return {
    loki: 'Loki',
    elk: 'ELK / Elasticsearch',
    sls: '阿里云 SLS',
  }[provider] || provider
}

function providerTagType(provider) {
  return {
    loki: 'success',
    elk: 'warning',
    sls: 'info',
  }[provider] || 'info'
}

function goToDatasources() {
  router.push('/logs/datasources')
}

function switchLogTab(path) {
  if (route.path !== path) router.push(path)
}

function openSyntaxHelp(provider) {
  helpProvider.value = provider || activeProvider.value || 'loki'
  helpDialogVisible.value = true
}

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function getPreferredDatasourceId() {
  const saved = Number(localStorage.getItem(LAST_DATASOURCE_KEY))
  if (saved && dataSources.value.some((item) => item.id === saved)) return saved
  const shanghai = dataSources.value.find((item) => item.name === DEFAULT_DATASOURCE_NAME)
  if (shanghai) return shanghai.id
  return dataSources.value[0]?.id || null
}

function persistDatasource(id) {
  if (id) localStorage.setItem(LAST_DATASOURCE_KEY, String(id))
}

function loadSavedQueries() {
  try {
    historyItems.value = JSON.parse(localStorage.getItem(QUERY_HISTORY_KEY) || '[]')
  } catch {
    historyItems.value = []
  }

  try {
    favoriteItems.value = JSON.parse(localStorage.getItem(QUERY_FAVORITES_KEY) || '[]')
  } catch {
    favoriteItems.value = []
  }
}

function persistSavedQueries() {
  localStorage.setItem(QUERY_HISTORY_KEY, JSON.stringify(historyItems.value))
  localStorage.setItem(QUERY_FAVORITES_KEY, JSON.stringify(favoriteItems.value))
}

function datasourceNameById(id) {
  return dataSources.value.find((item) => item.id === id)?.name || ''
}

function buildSavedTitle(snapshot) {
  const text = (
    snapshot.provider === 'loki'
      ? snapshot.lokiManualQuery || snapshot.lokiContentQuery
      : snapshot.queryText || snapshot.sourceName
  )?.trim()
  return text ? text.slice(0, 30) : `${providerLabel(snapshot.provider)} 查询`
}

function createSnapshot(tab) {
  const datasource = dataSources.value.find((item) => item.id === tab.datasourceId)
  return {
    provider: datasource?.provider || '',
    datasourceId: tab.datasourceId,
    datasourceName: datasource?.name || '',
    sourceName: tab.sourceName || '',
    queryText: tab.queryText || '',
    quickRange: tab.quickRange || '',
    timeRange: normalizeTimeRange(tab.timeRange).map((item) => item.getTime()),
    limit: tab.limit,
    lokiContentQuery: tab.lokiContentQuery || '',
    lokiManualQuery: tab.lokiManualQuery || '',
    labelFilters: (tab.labelFilters || []).map((item) => ({
      key: item.key || '',
      operator: item.operator || '=',
      value: item.value || '',
    })),
  }
}

function snapshotFingerprint(snapshot) {
  return JSON.stringify({
    provider: snapshot.provider,
    datasourceId: snapshot.datasourceId,
    sourceName: snapshot.sourceName,
    queryText: snapshot.queryText,
    quickRange: snapshot.quickRange,
    timeRange: snapshot.timeRange,
    limit: snapshot.limit,
    lokiContentQuery: snapshot.lokiContentQuery,
    lokiManualQuery: snapshot.lokiManualQuery,
    labelFilters: snapshot.labelFilters,
  })
}

function formatSavedSummary(item) {
  const source = item.sourceName ? `来源：${item.sourceName}` : '来源：默认'
  const query = item.provider === 'loki'
    ? item.lokiManualQuery || item.lokiContentQuery || '未填写关键字'
    : item.queryText || '未填写关键字'
  return `${source} · 条数：${item.limit} · 条件：${query}`
}

function formatSavedTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function updateHistory(snapshot) {
  const fingerprint = snapshotFingerprint(snapshot)
  historyItems.value = [
    { ...snapshot, id: `history-${Date.now()}`, title: buildSavedTitle(snapshot), savedAt: new Date().toISOString(), fingerprint },
    ...historyItems.value.filter((item) => item.fingerprint !== fingerprint),
  ].slice(0, MAX_HISTORY_ITEMS)
  persistSavedQueries()
}

function updateFavorites(snapshot, silent = false) {
  const fingerprint = snapshotFingerprint(snapshot)
  const exists = favoriteItems.value.some((item) => item.fingerprint === fingerprint)
  favoriteItems.value = [
    { ...snapshot, id: exists ? favoriteItems.value.find((item) => item.fingerprint === fingerprint)?.id : `favorite-${Date.now()}`, title: buildSavedTitle(snapshot), savedAt: new Date().toISOString(), fingerprint },
    ...favoriteItems.value.filter((item) => item.fingerprint !== fingerprint),
  ].slice(0, MAX_FAVORITE_ITEMS)
  persistSavedQueries()
  if (!silent) ElMessage.success(exists ? '已更新收藏条件' : '已收藏当前查询条件')
}

async function fetchDataSources() {
  loadingSources.value = true
  try {
    const response = await getLogDataSources({ is_enabled: true })
    dataSources.value = Array.isArray(response) ? response : response.results || []
  } finally {
    loadingSources.value = false
  }
}

function resetTabState(tab) {
  tab.sourceName = ''
  tab.queryText = ''
  tab.lokiLabels = []
  tab.catalogItems = []
  tab.labelFilters = [makeLabelFilter()]
  tab.lokiContentQuery = ''
  tab.lokiManualQuery = ''
  tab.errorMessage = ''
  tab.results = emptyResults()
  tab.expandedRows = []
}

async function initializeTabs() {
  if (!dataSources.value.length) return
  if (!queryTabs.value.length) {
    const tab = createQueryTab({ datasourceId: getPreferredDatasourceId() })
    queryTabs.value = [tab]
    activeTabName.value = tab.id
    persistDatasource(tab.datasourceId)
    await prepareTab(tab)
    return
  }
  queryTabs.value.forEach((tab) => {
    if (!dataSources.value.some((item) => item.id === tab.datasourceId)) {
      tab.datasourceId = getPreferredDatasourceId()
    }
  })
}

async function prepareTab(tab) {
  resetTabState(tab)
  if (!tab.datasourceId) return
  persistDatasource(tab.datasourceId)
  await loadCatalog(tab)
}

function saveFavorite(tab) {
  if (!tab?.datasourceId) return ElMessage.warning('请先选择日志数据源')
  updateFavorites(createSnapshot(tab))
}

function saveFavoriteFromItem(item) {
  updateFavorites({
    ...item,
    datasourceName: datasourceNameById(item.datasourceId) || item.datasourceName || '',
  })
}

function removeFavorite(id) {
  favoriteItems.value = favoriteItems.value.filter((item) => item.id !== id)
  persistSavedQueries()
}

function clearHistory() {
  historyItems.value = []
  persistSavedQueries()
}

async function applySavedQuery(item) {
  if (!currentTab.value) return
  const datasourceId = dataSources.value.some((source) => source.id === item.datasourceId)
    ? item.datasourceId
    : getPreferredDatasourceId()
  currentTab.value.datasourceId = datasourceId
  currentTab.value.timeRange = normalizeTimeRange(item.timeRange)
  currentTab.value.quickRange = item.quickRange || ''
  currentTab.value.limit = item.limit || 200
  await prepareTab(currentTab.value)
  currentTab.value.sourceName = item.sourceName || ''
  currentTab.value.queryText = item.queryText || ''
  currentTab.value.lokiContentQuery = item.lokiContentQuery || ''
  currentTab.value.lokiManualQuery = item.lokiManualQuery || ''
  currentTab.value.labelFilters = (item.labelFilters || []).length
    ? item.labelFilters.map((filter) => ({ ...makeLabelFilter(), ...filter }))
    : [makeLabelFilter()]
  savedDialogVisible.value = false
  ElMessage.success('已套用查询条件')
}

function handleTabsEdit(targetName, action) {
  if (action === 'add') {
    const base = currentTab.value
      ? {
          datasourceId: currentTab.value.datasourceId,
          timeRange: currentTab.value.timeRange,
          quickRange: currentTab.value.quickRange,
          limit: currentTab.value.limit,
        }
      : { datasourceId: getPreferredDatasourceId() }
    const tab = createQueryTab(base)
    queryTabs.value.push(tab)
    activeTabName.value = tab.id
    prepareTab(tab)
    return
  }

  if (queryTabs.value.length <= 1) return
  const index = queryTabs.value.findIndex((item) => item.id === targetName)
  if (index === -1) return
  queryTabs.value.splice(index, 1)
  if (activeTabName.value === targetName) {
    activeTabName.value = queryTabs.value[Math.max(index - 1, 0)]?.id || ''
  }
}

async function handleDatasourceChange() {
  if (!currentTab.value) return
  await prepareTab(currentTab.value)
  await nextTick()
  renderChart()
}

function applyQuickRange(tab, option) {
  tab.quickRange = option.key
  tab.timeRange = defaultTimeRange(option.minutes)
  if (tab.datasourceId) loadCatalog(tab)
}

function handleTimeRangeChange(tab) {
  tab.quickRange = ''
  if (tab.datasourceId && tab.datasourceId === currentTab.value?.datasourceId && isLoki.value) {
    loadCatalog(tab)
  }
}

async function loadCatalog(tab = currentTab.value) {
  if (!tab || !tab.datasourceId) return
  tab.catalogLoading = true
  try {
    const datasource = dataSources.value.find((item) => item.id === tab.datasourceId)
    if (!datasource) return

    if (datasource.provider === 'loki') {
      const response = await getLogProviderCatalog('loki', {
        datasource_id: tab.datasourceId,
        action: 'labels',
        start_ms: toTimestampMs(tab.timeRange[0]),
        end_ms: toTimestampMs(tab.timeRange[1]),
      })
      tab.lokiLabels = response.items || []
    } else if (datasource.provider === 'elk') {
      const response = await getLogProviderCatalog('elk', {
        datasource_id: tab.datasourceId,
        action: 'sources',
        index_pattern: datasource.config?.index_pattern,
      })
      tab.catalogItems = response.items || []
      if (!tab.sourceName) {
        tab.sourceName = datasource.config?.index_pattern || tab.catalogItems[0]?.name || ''
      }
    } else if (datasource.provider === 'sls') {
      const response = await getLogProviderCatalog('sls', {
        datasource_id: tab.datasourceId,
        action: 'sources',
      })
      tab.catalogItems = response.items || []
      if (!tab.sourceName) {
        tab.sourceName = datasource.config?.logstore || tab.catalogItems[0]?.name || ''
      }
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.error || '加载目录失败')
  } finally {
    tab.catalogLoading = false
  }
}

function addLabelFilter(tab) {
  tab.labelFilters.push(makeLabelFilter())
}

function removeLabelFilter(tab, index) {
  tab.labelFilters.splice(index, 1)
  if (!tab.labelFilters.length) addLabelFilter(tab)
}

async function onLokiLabelKeyChange(tab, index) {
  tab.labelFilters[index].value = ''
  tab.labelFilters[index].options = []
  await loadLokiLabelValues(tab, index)
}

async function loadLokiLabelValues(tab, index) {
  const filter = tab.labelFilters[index]
  if (!filter.key) return
  const response = await getLogProviderCatalog('loki', {
    datasource_id: tab.datasourceId,
    action: 'label_values',
    label: filter.key,
    start_ms: toTimestampMs(tab.timeRange[0]),
    end_ms: toTimestampMs(tab.timeRange[1]),
  })
  filter.options = response.items || []
}

function escapeLogValue(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

function buildPayload(tab) {
  const datasource = dataSources.value.find((item) => item.id === tab.datasourceId)
  const payload = {
    datasource_id: tab.datasourceId,
    provider: datasource?.provider,
    start_ms: toTimestampMs(tab.timeRange[0]),
    end_ms: toTimestampMs(tab.timeRange[1]),
    limit: tab.limit,
  }

  if (datasource?.provider === 'loki') {
    const selector = tab.labelFilters
      .filter((item) => item.key && item.value)
      .map((item) => `${item.key}${item.operator}"${escapeLogValue(item.value)}"`)
    const base = selector.length ? `{${selector.join(',')}}` : '{job!=""}'
    payload.query = tab.lokiManualQuery.trim() || (tab.lokiContentQuery.trim() ? `${base} |= "${escapeLogValue(tab.lokiContentQuery.trim())}"` : base)
  } else if (datasource?.provider === 'elk') {
    payload.query = tab.queryText.trim()
    payload.source = tab.sourceName || datasource.config?.index_pattern
    payload.index_pattern = payload.source
    payload.time_field = datasource.config?.time_field || '@timestamp'
    payload.message_fields = datasource.config?.message_fields || 'message,log,msg'
  } else if (datasource?.provider === 'sls') {
    payload.query = tab.queryText.trim()
    payload.source = tab.sourceName || datasource.config?.logstore
    payload.logstore = payload.source
    payload.topic = datasource.config?.topic || ''
  }
  return payload
}

async function runQuery(tab) {
  if (!tab?.datasourceId) return ElMessage.warning('请先选择日志数据源')
  tab.queryLoading = true
  tab.errorMessage = ''
  tab.expandedRows = []
  try {
    const response = await queryLogs(buildPayload(tab))
    tab.results = {
      provider: response.provider,
      source: response.source,
      total: response.total || 0,
      took_ms: response.took_ms,
      progress: response.progress || '',
      logs: response.logs || [],
    }
    updateHistory(createSnapshot(tab))
    await nextTick()
    renderChart()
  } catch (error) {
    tab.results = emptyResults()
    tab.errorMessage = error.response?.data?.error || error.message || '日志查询失败'
  } finally {
    tab.queryLoading = false
  }
}

function bucketize(logs) {
  const points = logs
    .map((item) => new Date(item.timestamp).getTime())
    .filter((item) => !Number.isNaN(item))
    .sort((a, b) => a - b)
  if (!points.length) return []

  const min = points[0]
  const max = points[points.length - 1]
  const count = Math.min(20, Math.max(6, Math.ceil(points.length / 15)))
  const step = Math.max(60000, Math.ceil(Math.max(1, max - min) / count))
  const buckets = Array.from({ length: count }, (_, index) => ({ start: min + index * step, total: 0, error: 0 }))

  logs.forEach((item) => {
    const time = new Date(item.timestamp).getTime()
    if (Number.isNaN(time)) return
    const index = Math.min(count - 1, Math.floor((time - min) / step))
    buckets[index].total += 1
    if (item.level === 'error') buckets[index].error += 1
  })

  return buckets.map((item) => ({
    total: item.total,
    error: item.error,
    label: `${String(new Date(item.start).getHours()).padStart(2, '0')}:${String(new Date(item.start).getMinutes()).padStart(2, '0')}`,
  }))
}

function renderChart() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  const buckets = bucketize(currentResults.value.logs)
  chart.setOption(
    {
      grid: { left: 30, right: 12, top: 16, bottom: 20 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: buckets.map((item) => item.label),
        axisLabel: { color: '#6b7280', fontSize: 11 },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#6b7280', fontSize: 11 },
        splitLine: { lineStyle: { color: '#e5e7eb' } },
      },
      series: [
        {
          name: '日志量',
          type: 'bar',
          data: buckets.map((item) => item.total),
          itemStyle: { color: '#2563eb', borderRadius: [6, 6, 0, 0] },
          barMaxWidth: 22,
        },
        {
          name: '错误数',
          type: 'line',
          smooth: true,
          data: buckets.map((item) => item.error),
          itemStyle: { color: '#ea580c' },
          lineStyle: { color: '#ea580c', width: 2 },
          symbolSize: 6,
        },
      ],
    },
    true
  )
}

function toggleRow(tab, index) {
  if (tab.expandedRows.includes(index)) {
    tab.expandedRows = tab.expandedRows.filter((item) => item !== index)
  } else {
    tab.expandedRows = [...tab.expandedRows, index]
  }
}

function isExpanded(tab, index) {
  return tab.expandedRows.includes(index)
}

function displayAttributes(attributes) {
  return Object.entries(attributes || {})
    .filter(([key]) => !['message', 'log', 'msg'].includes(key))
    .slice(0, 8)
    .map(([key, value]) => ({ key, value: typeof value === 'object' ? JSON.stringify(value) : String(value) }))
}

function formatTimestamp(value) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function escapeHtml(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function formatMessage(message) {
  const safe = escapeHtml(message || '')
  const query = isLoki.value ? currentTab.value?.lokiContentQuery.trim() : currentTab.value?.queryText.trim()
  if (!query) return safe
  const words = query
    .split(/\s+/)
    .filter((item) => item && !['AND', 'OR', 'NOT'].includes(item.toUpperCase()))
    .slice(0, 4)
  return words.reduce(
    (content, word) => content.replace(new RegExp(`(${escapeRegex(escapeHtml(word))})`, 'gi'), '<mark>$1</mark>'),
    safe
  )
}

function levelTagType(level) {
  return { error: 'danger', warning: 'warning', info: 'success', debug: 'info' }[level] || ''
}

function levelLabel(level) {
  return { error: '错误', warning: '告警', info: '信息', debug: '调试', unknown: '未知' }[level] || '未知'
}

function handleResize() {
  chart?.resize()
}

onMounted(async () => {
  loadSavedQueries()
  await fetchDataSources()
  await initializeTabs()
  await nextTick()
  renderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
})
</script>

<style scoped>
.logs-query-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.compact-header {
  margin-bottom: 0;
}

.page-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.log-center-tabs {
  margin-bottom: 0;
}

.page-desc {
  margin-top: 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.panel {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
  padding: 16px 18px;
}

.tabs-panel {
  padding: 10px 14px 2px;
}

.query-layout {
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(0, 1.65fr) minmax(300px, 0.85fr);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-label-with-help {
  align-items: center;
  display: inline-flex;
  gap: 8px;
}

.slim-head {
  margin-bottom: 12px;
}

.toolbar-actions,
.source-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.filter-row {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1fr) 90px minmax(0, 1fr) auto;
}

.operator-select {
  width: 90px;
}

.quick-ranges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.quick-range-btn {
  background: #f8fafc;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: #64748b;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  padding: 8px 12px;
}

.quick-range-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.inline-tip,
.helper,
.source-desc,
.source-meta,
.tips-box p,
.empty-state,
.expand-text,
.time-text,
.source-text {
  color: var(--text-secondary);
}

.inline-tip {
  font-size: 12px;
  margin-left: 10px;
}

.source-card,
.tips-box {
  border-radius: 14px;
  padding: 14px;
}

.compact-card {
  background: linear-gradient(135deg, #eff6ff, #fff7ed);
  border: 1px solid #dbeafe;
}

.source-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.source-title {
  color: #0f172a;
  font-size: 16px;
}

.summary-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.summary-item {
  background: rgba(255, 255, 255, 0.72);
  border-radius: 10px;
  padding: 10px 12px;
}

.summary-item span {
  color: #64748b;
  display: block;
  font-size: 11px;
  margin-bottom: 4px;
}

.summary-item strong {
  color: #0f172a;
  font-size: 13px;
  word-break: break-word;
}

.compact-stats {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat-card {
  border-radius: 16px;
  color: #0f172a;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 88px;
  padding: 14px 16px;
}

.stat-card span {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.stat-card strong {
  font-size: 24px;
}

.stat-card.warm { background: linear-gradient(135deg, #fef3c7, #fdba74); }
.stat-card.cool { background: linear-gradient(135deg, #dbeafe, #93c5fd); }
.stat-card.accent { background: linear-gradient(135deg, #d1fae5, #6ee7b7); }
.stat-card.neutral { background: linear-gradient(135deg, #e2e8f0, #cbd5e1); }

.compact-panel {
  padding-top: 14px;
}

.chart {
  height: 140px;
}

.compact-empty {
  min-height: 120px;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.compact-log-card {
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  overflow: hidden;
}

.compact-log-main {
  background: #fff;
  border: 0;
  cursor: pointer;
  padding: 8px 12px;
  text-align: left;
  width: 100%;
}

.log-head-row {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: space-between;
  margin-bottom: 4px;
}

.log-meta-inline {
  align-items: center;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.inline-message {
  color: #0f172a;
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  white-space: pre-wrap;
  word-break: break-word;
}

.log-message :deep(mark) {
  background: rgba(250, 204, 21, 0.32);
  border-radius: 4px;
  padding: 0 2px;
}

.expand-text {
  flex-shrink: 0;
  font-size: 12px;
}

.result-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.saved-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

.saved-dialog-head {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  margin-bottom: 12px;
}

.saved-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dialog-list {
  max-height: 52vh;
  overflow: auto;
  padding-right: 4px;
}

.saved-item {
  align-items: center;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  display: flex;
  gap: 8px;
  justify-content: space-between;
  padding: 10px;
}

.saved-main {
  background: transparent;
  border: 0;
  cursor: pointer;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  padding: 0;
  text-align: left;
}

.saved-main strong {
  color: #0f172a;
  font-size: 13px;
}

.saved-main span,
.saved-main p,
.saved-empty {
  color: #64748b;
  font-size: 12px;
  margin: 0;
}

.saved-actions {
  display: flex;
  flex-shrink: 0;
  gap: 4px;
}

.syntax-help {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.syntax-desc {
  color: #475569;
  line-height: 1.7;
  margin: 0;
}

.syntax-block {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 14px;
}

.syntax-block strong {
  color: #0f172a;
}

.syntax-block ul {
  margin: 10px 0 0;
  padding-left: 18px;
}

.syntax-block li {
  color: #475569;
  line-height: 1.8;
}

.syntax-block code {
  background: rgba(37, 99, 235, 0.08);
  border-radius: 6px;
  color: #1d4ed8;
  padding: 2px 6px;
}

.compact-detail {
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  padding: 12px;
}

.compact-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 10px;
}

.compact-attr {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
}

.compact-attr span {
  color: #475569;
  word-break: break-word;
}

pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

:deep(.el-tabs__header) {
  margin-bottom: 0;
}

:deep(.el-tabs__item) {
  height: 34px;
  line-height: 34px;
}

@media (max-width: 1080px) {
  .query-layout,
  .compact-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .query-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .page-title-row {
    align-items: flex-start;
  }

  .compact-stats,
  .filter-row,
  .compact-grid {
    grid-template-columns: 1fr;
  }

  .log-head-row,
  .panel-head,
  .toolbar-actions,
  .saved-item,
  .saved-dialog-head {
    align-items: stretch;
    flex-direction: column;
  }

  .inline-tip {
    display: block;
    margin-left: 0;
    margin-top: 8px;
  }
}
</style>
