<template>
  <div class="zabbix-monitor">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Monitor /></el-icon></span>
          <h2>Zabbix 监控</h2>
          <p class="page-inline-desc">实时查看 Zabbix 服务器的主机状态、监控项、触发器与当前问题</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-select v-model="activeDsId" size="small" placeholder="选择数据源" style="width: 220px" @change="refreshAll">
          <el-option v-for="ds in dataSources" :key="ds.id" :label="ds.name" :value="ds.id" />
        </el-select>
        <el-button size="small" :icon="Refresh" :loading="loading" @click="refreshAll" style="margin-left: 8px">刷新</el-button>
      </div>
    </section>

    <div v-if="!activeDsId" class="panel" style="text-align: center; padding: 60px 0; color: #94a3b8;">
      <el-icon :size="40"><Monitor /></el-icon>
      <p style="margin-top: 12px;">请先选择一个 Zabbix 数据源</p>
    </div>

    <template v-else>
      <div class="audit-grid zabbix-top-stats">
        <div class="audit-card audit-card--inline">
          <div class="stat-label">主机总数</div>
          <div class="stat-value">{{ hosts.length }}</div>
        </div>
        <div class="audit-card audit-card--inline">
          <div class="stat-label">可用主机</div>
          <div class="stat-value">{{ onlineCount }}</div>
        </div>
        <div class="audit-card audit-card--inline">
          <div class="stat-label">当前问题</div>
          <div class="stat-value" :style="{ color: problems.length > 0 ? '#ef4444' : '' }">{{ problems.length }}</div>
        </div>
      </div>

      <div class="neo-tabs theme-blue">
        <button class="neo-tab-btn" :class="{ active: activeTab === 'hosts' }" @click="activeTab = 'hosts'">
          <el-icon style="margin-right: 4px"><Monitor /></el-icon>主机列表
        </button>
        <button class="neo-tab-btn" :class="{ active: activeTab === 'triggers' }" @click="switchTab('triggers')">
          <el-icon style="margin-right: 4px"><Bell /></el-icon>触发器
        </button>
        <button class="neo-tab-btn" :class="{ active: activeTab === 'problems' }" @click="switchTab('problems')">
          <el-icon style="margin-right: 4px"><WarningFilled /></el-icon>当前问题
        </button>
      </div>

      <!-- 主机列表 -->
      <section class="panel" v-if="activeTab === 'hosts'">
        <div class="toolbar">
          <div class="toolbar-left">
            <el-input v-model="hostSearch" size="small" placeholder="搜索主机名" clearable style="width: 200px" @clear="hostPage = 1" @keyup.enter="hostPage = 1" />
          </div>
          <div class="toolbar-right">
            <span style="font-size: 12px; color: #94a3b8; margin-right: 8px">每页</span>
            <el-select v-model="hostPageSize" size="small" style="width: 80px" @change="hostPage = 1">
              <el-option v-for="n in pageSizeOptions" :key="n" :label="String(n)" :value="n" />
            </el-select>
            <span style="font-size: 12px; color: #94a3b8; margin-left: 4px">条</span>
          </div>
        </div>
        <el-table :data="pagedHosts" v-loading="loading" stripe @row-click="showHostItems">
          <el-table-column prop="host" label="主机名" min-width="140" />
          <el-table-column prop="name" label="可见名称" min-width="160" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="isHostOnline(row) ? 'success' : 'danger'" size="small">
                {{ isHostOnline(row) ? '可用' : '不可用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="IP" width="140">
            <template #default="{ row }">
              {{ (row.interfaces || [])[0]?.ip || '--' }}
            </template>
          </el-table-column>
          <el-table-column label="主机组" min-width="150">
            <template #default="{ row }">
              <el-tag v-for="g in (row.groups || []).slice(0, 3)" :key="g.groupid" size="small" style="margin: 1px">{{ g.name }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="hostPage" :page-size="hostPageSize"
            :total="filteredHosts.length" layout="total, prev, pager, next, sizes"
            :page-sizes="pageSizeOptions" @size-change="onHostSizeChange" @current-change="hostPage = $event"
          />
        </div>
      </section>

      <!-- 触发器 -->
      <section class="panel" v-if="activeTab === 'triggers'">
        <div class="toolbar">
          <div class="toolbar-right">
            <span style="font-size: 12px; color: #94a3b8; margin-right: 8px">每页</span>
            <el-select v-model="triggerPageSize" size="small" style="width: 80px" @change="triggerPage = 1">
              <el-option v-for="n in pageSizeOptions" :key="n" :label="String(n)" :value="n" />
            </el-select>
            <span style="font-size: 12px; color: #94a3b8; margin-left: 4px">条</span>
          </div>
        </div>
        <el-table :data="pagedTriggers" v-loading="loading" stripe>
          <el-table-column prop="description" label="触发器名称" min-width="220" />
          <el-table-column label="严重度" width="90">
            <template #default="{ row }">
              <el-tag :type="severityType(row.priority)" size="small">{{ severityLabel(row.priority) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.value === '1' ? 'danger' : 'success'" size="small">
                {{ row.value === '1' ? '触发' : '正常' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="关联主机" width="150">
            <template #default="{ row }">
              <span v-for="h in (row.hosts || []).slice(0, 2)" :key="h.hostid" style="display:block;font-size:12px">{{ h.host }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="triggerPage" :page-size="triggerPageSize"
            :total="triggers.length" layout="total, prev, pager, next, sizes"
            :page-sizes="pageSizeOptions" @size-change="onTriggerSizeChange" @current-change="triggerPage = $event"
          />
        </div>
      </section>

      <!-- 当前问题 -->
      <section class="panel" v-if="activeTab === 'problems'">
        <div class="toolbar">
          <div class="toolbar-right">
            <span style="font-size: 12px; color: #94a3b8; margin-right: 8px">每页</span>
            <el-select v-model="problemPageSize" size="small" style="width: 80px" @change="problemPage = 1">
              <el-option v-for="n in pageSizeOptions" :key="n" :label="String(n)" :value="n" />
            </el-select>
            <span style="font-size: 12px; color: #94a3b8; margin-left: 4px">条</span>
          </div>
        </div>
        <el-table :data="pagedProblems" v-loading="loading" stripe>
          <el-table-column prop="name" label="问题描述" min-width="250" />
          <el-table-column label="严重度" width="90">
            <template #default="{ row }">
              <el-tag :type="severityType(row.severity)" size="small">{{ severityLabel(row.severity) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="确认" width="80">
            <template #default="{ row }">
              <el-tag :type="row.acknowledged === '1' ? 'success' : 'info'" size="small">
                {{ row.acknowledged === '1' ? '已确认' : '未确认' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="180">
            <template #default="{ row }">
              {{ formatTime(row.clock) }}
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="problemPage" :page-size="problemPageSize"
            :total="problems.length" layout="total, prev, pager, next, sizes"
            :page-sizes="pageSizeOptions" @size-change="onProblemSizeChange" @current-change="problemPage = $event"
          />
        </div>
      </section>

      <el-dialog v-model="itemsVisible" title="主机监控项" width="800px">
        <el-input v-model="itemSearch" size="small" placeholder="搜索监控项" clearable style="width: 240px; margin-bottom: 12px" />
        <el-table :data="filteredItems" v-loading="itemsLoading" stripe max-height="460">
          <el-table-column prop="name" label="监控项名称" min-width="200" />
          <el-table-column prop="key_" label="键值" min-width="160" />
          <el-table-column prop="lastvalue" label="最新值" width="140" />
          <el-table-column prop="units" label="单位" width="80" />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === '0' ? 'success' : 'warning'" size="small">
                {{ row.status === '0' ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import {
  getZabbixDataSources, getZabbixHosts,
  getZabbixItems, getZabbixTriggers, getZabbixProblems,
} from '@/api/modules/ops'

const SEVERITY_MAP = { 0: '未分类', 1: '信息', 2: '警告', 3: '一般严重', 4: '严重', 5: '灾难' }
const SEVERITY_TYPE = { 0: 'info', 1: 'info', 2: 'warning', 3: '', 4: 'danger', 5: 'danger' }
const pageSizeOptions = [10, 20, 50, 100]

const loading = ref(false)
const activeDsId = ref('')
const dataSources = ref([])
const hosts = ref([])
const triggers = ref([])
const problems = ref([])
const items = ref([])
const activeTab = ref('hosts')
const hostSearch = ref('')
const itemSearch = ref('')
const itemsVisible = ref(false)
const itemsLoading = ref(false)

// Pagination state
const hostPage = ref(1)
const hostPageSize = ref(20)
const triggerPage = ref(1)
const triggerPageSize = ref(20)
const problemPage = ref(1)
const problemPageSize = ref(20)

// ---- Host status logic (from ZBXScreen data_aggregator.py _build_online_status) ----
// Use main interface's 'available' field: 0=unknown(assume online), 1=available(online), 2=unavailable(offline)
// Rule: available != 2 → online
function isHostOnline(host) {
  const ifaces = host.interfaces || []
  const main = ifaces.find(i => i.main === '1') || ifaces[0]
  if (!main) return true  // no interface → assume online
  const avail = parseInt(main.available)
  return avail !== 2  // 0=unknown(online), 1=available(online), 2=unavailable(offline)
}

const onlineCount = computed(() => hosts.value.filter(h => isHostOnline(h)).length)

const filteredHosts = computed(() => {
  const kw = hostSearch.value.trim().toLowerCase()
  if (!kw) return hosts.value
  return hosts.value.filter(h => (h.host || '').toLowerCase().includes(kw) || (h.name || '').toLowerCase().includes(kw))
})

// Paginated computed slices
const pagedHosts = computed(() => {
  const start = (hostPage.value - 1) * hostPageSize.value
  return filteredHosts.value.slice(start, start + hostPageSize.value)
})
const pagedTriggers = computed(() => {
  const start = (triggerPage.value - 1) * triggerPageSize.value
  return triggers.value.slice(start, start + triggerPageSize.value)
})
const pagedProblems = computed(() => {
  const start = (problemPage.value - 1) * problemPageSize.value
  return problems.value.slice(start, start + problemPageSize.value)
})

const filteredItems = computed(() => {
  const kw = itemSearch.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(i => (i.name || '').toLowerCase().includes(kw) || (i.key_ || '').toLowerCase().includes(kw))
})

function onHostSizeChange(n) { hostPageSize.value = n; hostPage.value = 1 }
function onTriggerSizeChange(n) { triggerPageSize.value = n; triggerPage.value = 1 }
function onProblemSizeChange(n) { problemPageSize.value = n; problemPage.value = 1 }

function severityLabel(p) { return SEVERITY_MAP[parseInt(p)] || '未知' }
function severityType(p) { return SEVERITY_TYPE[parseInt(p)] || 'info' }
function formatTime(t) { return t ? new Date(parseInt(t) * 1000).toLocaleString() : '--' }

async function loadDataSources() {
  try {
    const resp = await getZabbixDataSources()
    const list = resp?.results || resp?.data || resp || []
    dataSources.value = Array.isArray(list) ? list : (list.results || [])
    if (dataSources.value.length && !activeDsId.value) {
      const def = dataSources.value.find(d => d.is_default) || dataSources.value[0]
      activeDsId.value = def.id
      setTimeout(() => refreshAll(), 100)
    }
  } catch { /* ignore */ }
}

async function refreshAll() {
  if (!activeDsId.value) return
  loading.value = true
  try {
    const params = { datasource_id: activeDsId.value }
    const results = await Promise.allSettled([
      getZabbixHosts(params),
      getZabbixTriggers(params),
      getZabbixProblems(params),
    ])
    const hRes = results[0].status === 'fulfilled' ? results[0].value : null
    const tRes = results[1].status === 'fulfilled' ? results[1].value : null
    const pRes = results[2].status === 'fulfilled' ? results[2].value : null
    hosts.value = Array.isArray(hRes) ? hRes : (hRes?.result || [])
    triggers.value = Array.isArray(tRes) ? tRes : (tRes?.result || [])
    problems.value = Array.isArray(pRes) ? pRes : (pRes?.result || [])
    // Reset pagination
    hostPage.value = 1; triggerPage.value = 1; problemPage.value = 1
  } catch {
    hosts.value = []; triggers.value = []; problems.value = []
  } finally {
    loading.value = false
  }
}

async function showHostItems(row) {
  itemsVisible.value = true
  itemsLoading.value = true
  try {
    const resp = await getZabbixItems({ datasource_id: activeDsId.value, host_ids: [row.hostid] })
    items.value = Array.isArray(resp) ? resp : (resp?.result || resp?.data || [])
  } catch {
    items.value = []
  } finally {
    itemsLoading.value = false
  }
}

function switchTab(tab) {
  activeTab.value = tab
  if (!hosts.value.length && activeDsId.value) refreshAll()
}

onMounted(() => { loadDataSources() })
</script>

<style scoped>
.zabbix-top-stats { margin-bottom: 16px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.toolbar-left { display: flex; align-items: center; gap: 8px; }
.toolbar-right { display: flex; align-items: center; }
.pagination-wrap { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
