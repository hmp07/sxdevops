<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>🧰 工具市场 <span class="page-header-subtitle">支持 Docker Compose 单机 / Kubernetes 集群 两种部署模式</span></h2>
      <div class="market-tabs">
        <button class="tab-btn" :class="{ active: activeTab === 'market' }" @click="activeTab = 'market'">
          <el-icon><Shop /></el-icon> 工具市场
        </button>
        <button
          v-if="canViewMarketplaceDeployments"
          class="tab-btn"
          :class="{ active: activeTab === 'deploy' }"
          @click="activeTab = 'deploy'; fetchDeployments()"
        >
          <el-icon><Setting /></el-icon> 部署管理
          <span v-if="deployments.length" class="tab-badge">{{ deployments.length }}</span>
        </button>
      </div>
    </div>

    <div v-show="activeTab === 'market'" class="market-content">
      <div class="category-bar">
        <button
          v-for="cat in categories"
          :key="cat.value"
          class="cat-btn"
          :class="{ active: activeCategory === cat.value }"
          @click="activeCategory = cat.value"
        >{{ cat.label }}</button>
      </div>

      <div class="service-grid">
        <div
          v-for="tpl in filteredTemplates"
          :key="tpl.id"
          class="service-card"
          :class="{ disabled: !canManageMarketplaceDeployments }"
          @click="openDeployDialog(tpl)"
        >
          <div class="card-icon" :class="'icon-' + tpl.icon">
            <span class="icon-text">{{ getIconEmoji(tpl.icon) }}</span>
          </div>
          <div class="card-name">{{ tpl.name }}</div>
          <div class="card-desc">{{ tpl.description }}</div>
          <div class="card-versions">
            <el-tag
              v-for="ver in tpl.versions"
              :key="ver"
              type="primary"
              size="small"
              effect="plain"
              round
            >{{ ver }}</el-tag>
          </div>
          <div class="card-modes">
            <el-tag
              v-for="mode in tpl.available_deploy_modes || []"
              :key="mode"
              :type="mode === 'k8s' ? 'success' : 'info'"
              size="small"
              effect="light"
            >{{ deployModeLabel(mode) }}</el-tag>
          </div>
        </div>
      </div>
    </div>

    <div v-show="activeTab === 'deploy'" class="deploy-content">
      <div class="table-card">
        <el-table :data="deployments" stripe v-loading="depLoading" style="width:100%">
          <el-table-column label="服务" min-width="160">
            <template #default="{ row }">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="mini-icon" :class="'icon-' + row.template_icon">{{ getIconEmoji(row.template_icon) }}</span>
                <span style="font-weight:600;">{{ row.template_name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="100" />
          <el-table-column prop="deploy_mode_display" label="模式" width="170" />
          <el-table-column prop="target_display" label="部署目标" min-width="220" />
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="depStatusType(row.status)" size="small">{{ row.status_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="deployer" label="部署人" width="110" />
          <el-table-column prop="created_at" label="部署时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="viewLogs(row)">日志</el-button>
              <el-button
                v-if="canManageMarketplaceDeployments && row.status === 'running'"
                link
                type="warning"
                size="small"
                @click="handleStop(row)"
              >停止</el-button>
              <el-button
                v-if="canManageMarketplaceDeployments && row.status === 'stopped'"
                link
                type="success"
                size="small"
                @click="handleStart(row)"
              >启动</el-button>
              <el-popconfirm
                v-if="canManageMarketplaceDeployments"
                title="确定卸载该服务？关联资源会被清理。"
                @confirm="handleRemove(row)"
              >
                <template #reference>
                  <el-button link type="danger" size="small">卸载</el-button>
                </template>
              </el-popconfirm>
              <el-button link type="info" size="small" @click="viewDeployLog(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog
      v-model="deployVisible"
      :title="'部署 ' + (deployTemplate?.name || '')"
      width="90%"
      style="max-width:620px;"
      top="5vh"
      append-to-body
      destroy-on-close
    >
      <el-form :model="deployForm" label-width="100px">
        <el-form-item label="部署模式">
          <el-radio-group v-model="deployForm.deploy_mode">
            <el-radio-button
              v-for="mode in deployModeOptions"
              :key="mode"
              :label="mode"
            >{{ deployModeLabel(mode) }}</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="deployForm.deploy_mode === 'docker_compose'" label="目标主机">
          <el-select v-model="deployForm.host_id" placeholder="选择主机" style="width:100%">
            <el-option
              v-for="host in hosts"
              :key="host.id"
              :label="`${host.hostname} (${host.ip_address})`"
              :value="host.id"
            />
          </el-select>
        </el-form-item>

        <template v-else>
          <el-form-item label="目标集群">
            <el-select v-model="deployForm.cluster_id" placeholder="选择 K8s 集群" style="width:100%">
              <el-option
                v-for="cluster in clusters"
                :key="cluster.id"
                :label="cluster.name"
                :value="cluster.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="命名空间">
            <el-input v-model="deployForm.namespace" placeholder="default" />
          </el-form-item>
          <el-form-item label="发布名称">
            <el-input v-model="deployForm.release_name" placeholder="默认自动生成" />
          </el-form-item>
          <el-form-item label="副本数">
            <el-input-number v-model="deployForm.replicas" :min="1" :max="99" style="width:180px" />
          </el-form-item>
        </template>

        <el-form-item label="版本">
          <el-select v-model="deployForm.version" placeholder="选择版本" style="width:100%">
            <el-option v-for="version in (deployTemplate?.versions || [])" :key="version" :label="version" :value="version" />
          </el-select>
        </el-form-item>

        <template v-if="deployTemplate?.env_schema?.length">
          <el-divider content-position="left">配置参数</el-divider>
          <el-form-item v-for="field in deployTemplate.env_schema" :key="field.key" :label="field.label">
            <el-input v-model="deployForm.env_config[field.key]" :placeholder="field.default" />
          </el-form-item>
        </template>

        <el-form-item label="部署人">
          <el-input v-model="deployForm.deployer" style="width:220px" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deployVisible = false">取消</el-button>
        <el-button type="primary" :loading="deploying" @click="handleDeploy">
          <el-icon><Promotion /></el-icon> 开始部署
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="logVisible"
      title="服务日志"
      width="90%"
      style="max-width:800px;"
      top="5vh"
      append-to-body
      destroy-on-close
    >
      <pre class="log-output">{{ logContent || '加载中...' }}</pre>
    </el-dialog>

    <el-dialog
      v-model="detailVisible"
      title="部署详情"
      width="90%"
      style="max-width:760px;"
      top="5vh"
      append-to-body
      destroy-on-close
    >
      <template v-if="detailDep">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="服务">{{ detailDep.template_name }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ detailDep.version }}</el-descriptions-item>
          <el-descriptions-item label="部署模式">{{ detailDep.deploy_mode_display }}</el-descriptions-item>
          <el-descriptions-item label="部署目标">{{ detailDep.target_display }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="depStatusType(detailDep.status)" size="small">{{ detailDep.status_display }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="部署人">{{ detailDep.deployer }}</el-descriptions-item>
          <el-descriptions-item v-if="detailDep.namespace" label="命名空间">{{ detailDep.namespace }}</el-descriptions-item>
          <el-descriptions-item v-if="detailDep.release_name" label="发布名称">{{ detailDep.release_name }}</el-descriptions-item>
          <el-descriptions-item v-if="detailDep.deploy_mode === 'k8s'" label="副本数">{{ detailDep.replicas }}</el-descriptions-item>
          <el-descriptions-item label="部署目录" :span="detailDep.deploy_mode === 'k8s' ? 1 : 2">
            {{ detailDep.deploy_dir || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间" :span="2">{{ formatTime(detailDep.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-divider content-position="left">部署日志</el-divider>
        <pre class="log-output">{{ detailDep.deploy_log || '暂无日志' }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Promotion, Setting, Shop } from '@element-plus/icons-vue'
import { useRouteTabState } from '@/composables/useRouteTabState'
import {
  getTemplates, getDeployments, deployService,
  stopService, startService, removeService, getServiceLogs,
} from '@/api/modules/marketplace'
import { getHosts } from '@/api/modules/ops'
import { getK8sClusters } from '@/api/modules/container'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const templates = ref([])
const deployments = ref([])
const hosts = ref([])
const clusters = ref([])
const activeCategory = ref('all')
const depLoading = ref(false)

const categories = [
  { label: '全部', value: 'all' },
  { label: '数据库', value: 'database' },
  { label: '缓存', value: 'cache' },
  { label: 'CI/CD', value: 'cicd' },
  { label: '监控与日志', value: 'monitoring' },
  { label: '安全运维', value: 'security' },
  { label: '中间件', value: 'middleware' },
  { label: '开发环境', value: 'devenv' },
]

const ICON_MAP = {
  mysql: '🛢️',
  mongodb: '🍃',
  redis: '🟥',
  postgresql: '🐘',
  nginx: '🌐',
  jenkins: '🧰',
  gitlab: '🦊',
  grafana: '📊',
  elasticsearch: '🔎',
  loki: '🪵',
  jumpserver: '🛡️',
  nacos: '🧭',
  xxljob: '⏰',
  java: '☕',
  python: '🐍',
  go: '🐹',
  nodejs: '🟢',
}

const filteredTemplates = computed(() => {
  if (activeCategory.value === 'all') return templates.value
  return templates.value.filter(item => item.category === activeCategory.value)
})
const canViewMarketplaceDeployments = computed(() => authStore.hasPermission('marketplace.deployment.view'))
const canManageMarketplaceDeployments = computed(() => authStore.hasPermission('marketplace.deployment.manage'))
const availableTabs = computed(() => [
  'market',
  canViewMarketplaceDeployments.value && 'deploy',
].filter(Boolean))
const activeTab = useRouteTabState({
  tabs: () => availableTabs.value,
  defaultTab: 'market',
}).activeTab

function getIconEmoji(icon) {
  return ICON_MAP[icon] || '📦'
}

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function depStatusType(status) {
  const mapping = {
    running: 'success',
    stopped: 'info',
    deploying: 'warning',
    pending: '',
    failed: 'danger',
    removing: 'warning',
  }
  return mapping[status] || ''
}

function deployModeLabel(mode) {
  return mode === 'k8s' ? 'Kubernetes 集群' : 'Docker Compose 单机'
}

async function fetchTemplates() {
  try {
    templates.value = await getTemplates()
  } catch (error) {
    templates.value = []
  }
}

async function fetchDeployments() {
  depLoading.value = true
  try {
    const response = await getDeployments()
    deployments.value = response.results || response
  } catch (error) {
    deployments.value = []
  }
  depLoading.value = false
}

async function fetchHosts() {
  try {
    const response = await getHosts()
    hosts.value = response.results || response
  } catch (error) {
    hosts.value = []
  }
}

async function fetchClusters() {
  try {
    const response = await getK8sClusters()
    clusters.value = response.results || response
  } catch (error) {
    clusters.value = []
  }
}

let pollTimer = null

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await fetchDeployments()
    const hasActive = deployments.value.some(item => ['deploying', 'pending'].includes(item.status))
    if (!hasActive) stopPolling()
  }, 3000)
}

function stopPolling() {
  if (!pollTimer) return
  clearInterval(pollTimer)
  pollTimer = null
}

watch(activeTab, (value) => {
  if (value === 'deploy') {
    fetchDeployments().then(() => {
      const hasActive = deployments.value.some(item => ['deploying', 'pending'].includes(item.status))
      if (hasActive) startPolling()
    })
  } else {
    stopPolling()
  }
})

onMounted(() => {
  fetchTemplates()
  fetchDeployments().then(() => {
    const hasActive = deployments.value.some(item => ['deploying', 'pending'].includes(item.status))
    if (hasActive) startPolling()
  })
  fetchHosts()
  fetchClusters()
})

onBeforeUnmount(() => {
  stopPolling()
})

const deployVisible = ref(false)
const deployTemplate = ref(null)
const deployForm = ref({
  deploy_mode: 'docker_compose',
  host_id: null,
  cluster_id: null,
  namespace: 'default',
  release_name: '',
  replicas: 1,
  version: '',
  env_config: {},
  deployer: authStore.currentUser?.username || 'admin',
})
const deploying = ref(false)

const deployModeOptions = computed(() => deployTemplate.value?.available_deploy_modes || ['docker_compose'])

function buildDefaultForm(template) {
  const envConfig = {}
  ;(template?.env_schema || []).forEach(field => {
    envConfig[field.key] = field.default || ''
  })
  return {
    deploy_mode: (template?.available_deploy_modes || [])[0] || 'docker_compose',
    host_id: null,
    cluster_id: null,
    namespace: 'default',
    release_name: '',
    replicas: 1,
    version: template?.versions?.[0] || '',
    env_config: envConfig,
    deployer: authStore.currentUser?.username || 'admin',
  }
}

function openDeployDialog(template) {
  if (!canManageMarketplaceDeployments.value) {
    ElMessage.warning('当前账号没有部署权限')
    return
  }
  deployTemplate.value = template
  deployForm.value = buildDefaultForm(template)
  deployVisible.value = true
}

async function handleDeploy() {
  if (deployForm.value.deploy_mode === 'docker_compose' && !deployForm.value.host_id) {
    return ElMessage.warning('请选择目标主机')
  }
  if (deployForm.value.deploy_mode === 'k8s' && !deployForm.value.cluster_id) {
    return ElMessage.warning('请选择目标集群')
  }
  if (!deployForm.value.version) {
    return ElMessage.warning('请选择部署版本')
  }

  deploying.value = true
  try {
    await deployService({
      template_id: deployTemplate.value.id,
      deploy_mode: deployForm.value.deploy_mode,
      host_id: deployForm.value.host_id,
      cluster_id: deployForm.value.cluster_id,
      namespace: deployForm.value.namespace,
      release_name: deployForm.value.release_name,
      replicas: deployForm.value.replicas,
      version: deployForm.value.version,
      env_config: deployForm.value.env_config,
    })
    ElMessage.success('部署任务已发起，正在自动跟踪状态...')
    deployVisible.value = false
    activeTab.value = 'deploy'
    await fetchDeployments()
    startPolling()
  } catch (error) {
    /* handled by interceptor */
  }
  deploying.value = false
}

async function handleStop(deployment) {
  try {
    await stopService(deployment.id)
    ElMessage.success('服务已停止')
    fetchDeployments()
  } catch (error) {
    /* handled by interceptor */
  }
}

async function handleStart(deployment) {
  try {
    await startService(deployment.id)
    ElMessage.success('服务已启动')
    fetchDeployments()
  } catch (error) {
    /* handled by interceptor */
  }
}

async function handleRemove(deployment) {
  try {
    await removeService(deployment.id)
    ElMessage.success('服务已卸载')
    fetchDeployments()
  } catch (error) {
    /* handled by interceptor */
  }
}

const logVisible = ref(false)
const logContent = ref('')

async function viewLogs(deployment) {
  logContent.value = ''
  logVisible.value = true
  try {
    const response = await getServiceLogs(deployment.id)
    logContent.value = response.logs
  } catch (error) {
    logContent.value = '获取日志失败'
  }
}

const detailVisible = ref(false)
const detailDep = ref(null)

function viewDeployLog(deployment) {
  detailDep.value = deployment
  detailVisible.value = true
}
</script>

<style scoped>
.service-card.disabled {
  opacity: 0.58;
}

.card-modes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.page-header-subtitle {
  font-size: 13px;
  font-weight: 400;
  color: #64748b;
  margin-left: 8px;
}
</style>
