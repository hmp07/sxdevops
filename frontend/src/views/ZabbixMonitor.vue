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
          <div class="stat-value">{{ hosts.filter(h => h.available === '1').length }}</div>
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

      <section class="panel" v-if="activeTab === 'hosts'">
        <div class="toolbar">
          <el-input v-model="hostSearch" size="small" placeholder="搜索主机名" clearable style="width: 200px" />
        </div>
        <el-table :data="filteredHosts" v-loading="loading" stripe @row-click="showHostItems">
          <el-table-column prop="host" label="主机名" min-width="140" />
          <el-table-column prop="name" label="可见名称" min-width="160" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.available === '1' ? 'success' : 'danger'" size="small">
                {{ row.available === '1' ? '可用' : '不可用' }}
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
      </section>

      <section class="panel" v-if="activeTab === 'triggers'">
        <el-table :data="triggers" v-loading="loading" stripe>
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
              <span v-for="h in (row.hosts || []).slice(0, 2)" :key="h.hostid">{{ h.host }}</span>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel" v-if="activeTab === 'problems'">
        <el-table :data="problems" v-loading="loading" stripe>
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

const filteredHosts = computed(() => {
  const kw = hostSearch.value.trim().toLowerCase()
  if (!kw) return hosts.value
  return hosts.value.filter(h => (h.host || '').toLowerCase().includes(kw) || (h.name || '').toLowerCase().includes(kw))
})

const filteredItems = computed(() => {
  const kw = itemSearch.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(i => (i.name || '').toLowerCase().includes(kw) || (i.key_ || '').toLowerCase().includes(kw))
})

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
      // Auto-load data after short delay for Vue to render
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
    const { data } = await getZabbixItems({ datasource_id: activeDsId.value, host_ids: [row.hostid] })
    items.value = Array.isArray(data) ? data : (data?.result || [])
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
</style>
