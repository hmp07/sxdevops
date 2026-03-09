<template>
  <div class="fade-in">
    <!-- 页头 -->
    <div class="page-header">
      <h2 v-if="activeTab === 'docker'"> Docker 环境</h2>
      <h2 v-if="activeTab === 'k8s'"> K8s 集群</h2>
    </div>

    <!-- ============ Docker Tab ============ -->
    <div v-show="activeTab === 'docker'">
      <!-- 工具栏 -->
      <div class="container-toolbar">
        <div class="toolbar-left">
          <el-select v-model="selectedHostId" placeholder="选择主机" style="width:280px" @change="fetchContainers">
            <el-option v-for="h in hosts" :key="h.id" :label="`${h.hostname} (${h.ip_address})`" :value="h.id" />
          </el-select>
          <el-button :icon="Refresh" @click="fetchContainers" :loading="dockerLoading" circle />
        </div>
        <div class="toolbar-right">
          <el-radio-group v-model="dockerView" size="small">
            <el-radio-button value="containers">容器</el-radio-button>
            <el-radio-button value="images">镜像</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <!-- 未选择主机提示 -->
      <div v-if="!selectedHostId" class="empty-state">
        <div class="empty-icon">🐳</div>
        <div class="empty-text">请选择一台主机查看 Docker 容器</div>
      </div>

      <!-- 容器列表 -->
      <div v-else-if="dockerView === 'containers'" class="table-card">
        <el-table :data="containers" stripe v-loading="dockerLoading" style="width:100%">
          <el-table-column prop="name" label="容器名称" min-width="180">
            <template #default="{ row }">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="state-pulse" :class="row.state"></span>
                <span style="font-weight:600">{{ row.name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="image" label="镜像" min-width="200" show-overflow-tooltip />
          <el-table-column label="状态" width="180">
            <template #default="{ row }">
              <el-tag :type="containerStateType(row.state)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="ports" label="端口映射" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.state !== 'running'" link type="success" size="small" @click="doAction(row, 'start')">启动</el-button>
              <el-button v-if="row.state === 'running'" link type="warning" size="small" @click="doAction(row, 'stop')">停止</el-button>
              <el-button v-if="row.state === 'running'" link type="primary" size="small" @click="doAction(row, 'restart')">重启</el-button>
              <el-button link type="info" size="small" @click="viewContainerLogs(row)">日志</el-button>
              <el-button link type="info" size="small" @click="inspectContainer(row)">详情</el-button>
              <el-popconfirm title="确定删除该容器？" @confirm="removeContainer(row)">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 镜像列表 -->
      <div v-else class="table-card">
        <el-table :data="images" stripe v-loading="dockerLoading" style="width:100%">
          <el-table-column prop="repository" label="仓库" min-width="250" show-overflow-tooltip />
          <el-table-column prop="tag" label="标签" width="120" />
          <el-table-column prop="id" label="镜像 ID" width="160">
            <template #default="{ row }">
              <span style="font-family:monospace; font-size:12px; color:var(--text-secondary)">{{ row.id?.slice(0, 12) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="size" label="大小" width="110" />
          <el-table-column prop="created" label="创建时间" min-width="180" show-overflow-tooltip />
        </el-table>
      </div>
    </div>

    <!-- ============ K8s Tab ============ -->
    <div v-show="activeTab === 'k8s'">
      <div class="container-toolbar">
        <div class="toolbar-left">
          <el-select v-model="selectedClusterId" placeholder="选择集群" style="width:280px" @change="onClusterChange">
            <el-option v-for="c in clusters" :key="c.id" :label="c.name" :value="c.id">
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="state-pulse" :class="c.status === 'connected' ? 'running' : 'exited'"></span>
                {{ c.name }}
              </div>
            </el-option>
          </el-select>
          <el-button type="primary" size="small" @click="openClusterDialog()">
            <el-icon><Plus /></el-icon> 添加集群
          </el-button>
          <el-button v-if="selectedClusterId" size="small" @click="testCluster" :loading="testingCluster">
            测试连接
          </el-button>
        </div>
        <div v-if="selectedClusterId" class="toolbar-right">
          <el-select v-model="selectedNamespace" placeholder="命名空间" style="width:180px" @change="fetchK8sResources">
            <el-option label="全部命名空间" value="_all" />
            <el-option v-for="ns in namespaces" :key="ns.name" :label="ns.name" :value="ns.name" />
          </el-select>
        </div>
      </div>

      <!-- 未选择集群提示 -->
      <div v-if="!selectedClusterId" class="empty-state">
        <div class="empty-icon">☸️</div>
        <div class="empty-text">请选择或添加一个 K8s 集群</div>
      </div>

      <!-- K8s 资源管理 -->
      <div v-else>
        <!-- 资源子 Tab -->
        <div class="k8s-resource-tabs">
          <button v-for="rt in resourceTabs" :key="rt.key" class="resource-tab" :class="{ active: k8sResourceTab === rt.key }" @click="k8sResourceTab = rt.key; fetchK8sResources()">
            {{ rt.label }}
            <span v-if="rt.count > 0" class="resource-count">{{ rt.count }}</span>
          </button>
        </div>

        <div class="table-card">
          <!-- Pods -->
          <el-table v-if="k8sResourceTab === 'pods'" :data="k8sPods" stripe v-loading="k8sLoading" style="width:100%">
            <el-table-column prop="name" label="Pod 名称" min-width="250" show-overflow-tooltip>
              <template #default="{ row }">
                <div style="display:flex; align-items:center; gap:8px;">
                  <span class="state-pulse" :class="row.status === 'Running' ? 'running' : 'exited'"></span>
                  <span style="font-weight:600; font-family:monospace; font-size:13px;">{{ row.name }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="namespace" label="命名空间" width="130" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="podStatusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="ip" label="Pod IP" width="130" />
            <el-table-column prop="node" label="节点" width="140" show-overflow-tooltip />
            <el-table-column prop="restarts" label="重启" width="70" />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-popconfirm title="删除 Pod 触发重启？" @confirm="handleRestartPod(row)">
                  <template #reference>
                    <el-button link type="warning" size="small">重启</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>

          <!-- Services -->
          <el-table v-if="k8sResourceTab === 'services'" :data="k8sServices" stripe v-loading="k8sLoading" style="width:100%">
            <el-table-column prop="name" label="Service 名称" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-weight:600; font-family:monospace; font-size:13px;">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="namespace" label="命名空间" width="130" />
            <el-table-column prop="type" label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="row.type === 'LoadBalancer' ? 'warning' : row.type === 'NodePort' ? 'success' : 'info'">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="cluster_ip" label="Cluster IP" width="140" />
            <el-table-column prop="ports" label="端口" min-width="200" show-overflow-tooltip />
          </el-table>

          <!-- Deployments -->
          <el-table v-if="k8sResourceTab === 'deployments'" :data="k8sDeployments" stripe v-loading="k8sLoading" style="width:100%">
            <el-table-column prop="name" label="Deployment 名称" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-weight:600; font-family:monospace; font-size:13px;">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="namespace" label="命名空间" width="130" />
            <el-table-column label="副本" width="110">
              <template #default="{ row }">
                <span :style="{ color: row.ready_replicas === row.replicas ? '#10b981' : '#f59e0b', fontWeight: 600 }">
                  {{ row.ready_replicas }}/{{ row.replicas }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="images" label="镜像" min-width="280" show-overflow-tooltip />
          </el-table>
        </div>
      </div>
    </div>

    <!-- ============ 容器日志弹窗 ============ -->
    <el-dialog v-model="logVisible" :title="'容器日志 — ' + logContainerName" width="90%" style="max-width:900px;" top="3vh" append-to-body destroy-on-close>
      <pre class="log-output terminal-log">{{ logContent || '加载中...' }}</pre>
    </el-dialog>

    <!-- ============ 容器详情弹窗 ============ -->
    <el-dialog v-model="inspectVisible" :title="'容器详情 — ' + inspectContainerName" width="90%" style="max-width:900px;" top="3vh" append-to-body destroy-on-close>
      <pre class="log-output terminal-log">{{ inspectContent || '加载中...' }}</pre>
    </el-dialog>

    <!-- ============ 新增 K8s 集群弹窗 ============ -->
    <el-dialog v-model="clusterDialogVisible" :title="editingClusterId ? '编辑集群' : '添加 K8s 集群'" width="90%" style="max-width:600px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="clusterForm" label-width="110px">
        <el-form-item label="集群名称">
          <el-input v-model="clusterForm.name" placeholder="例如 prod-cluster" />
        </el-form-item>
        <el-form-item label="API Server">
          <el-input v-model="clusterForm.api_server" placeholder="例如 https://10.0.0.1:6443 (可选)" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="clusterForm.description" placeholder="集群用途描述" />
        </el-form-item>
        <el-form-item label="KubeConfig">
          <el-input v-model="clusterForm.kubeconfig" type="textarea" :rows="12" placeholder="粘贴 kubeconfig YAML 内容" style="font-family:monospace; font-size:12px;" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="clusterDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCluster" :loading="savingCluster">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { getHosts } from '@/api/modules/ops'
import {
  getDockerContainers, getDockerImages,
  dockerContainerAction, dockerContainerRemove,
  getDockerContainerLogs, getDockerContainerInspect,
  getK8sClusters, createK8sCluster, updateK8sCluster, deleteK8sCluster,
  testK8sConnection, getK8sNamespaces,
  getK8sPods, getK8sServices, getK8sDeployments, restartK8sPod,
} from '@/api/modules/container'

const route = useRoute()

// ====== 通用 ======
const activeTab = ref('docker')
const hosts = ref([])

// ====== Docker ======
const selectedHostId = ref(null)
const dockerView = ref('containers')
const dockerLoading = ref(false)
const containers = ref([])
const images = ref([])

function containerStateType(state) {
  const m = { running: 'success', exited: 'danger', paused: 'warning', created: 'info', restarting: 'warning', dead: 'danger' }
  return m[state] || 'info'
}

async function fetchContainers() {
  if (!selectedHostId.value) return
  dockerLoading.value = true
  try {
    if (dockerView.value === 'containers') {
      containers.value = await getDockerContainers(selectedHostId.value)
    } else {
      images.value = await getDockerImages(selectedHostId.value)
    }
  } catch (e) {
    console.error(e)
  }
  dockerLoading.value = false
}

async function doAction(row, action) {
  try {
    const res = await dockerContainerAction(row.id, selectedHostId.value, action)
    ElMessage.success(res.message || `${action} 成功`)
    fetchContainers()
  } catch (e) {
    ElMessage.error(`操作失败`)
  }
}

async function removeContainer(row) {
  try {
    await dockerContainerRemove(row.id, selectedHostId.value)
    ElMessage.success('容器已删除')
    fetchContainers()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

// 日志
const logVisible = ref(false)
const logContainerName = ref('')
const logContent = ref('')
async function viewContainerLogs(row) {
  logContainerName.value = row.name
  logContent.value = ''
  logVisible.value = true
  try {
    const res = await getDockerContainerLogs(row.id, selectedHostId.value)
    logContent.value = res.logs
  } catch (e) {
    logContent.value = '获取日志失败'
  }
}

// 详情
const inspectVisible = ref(false)
const inspectContainerName = ref('')
const inspectContent = ref('')
async function inspectContainer(row) {
  inspectContainerName.value = row.name
  inspectContent.value = ''
  inspectVisible.value = true
  try {
    const res = await getDockerContainerInspect(row.id, selectedHostId.value)
    inspectContent.value = JSON.stringify(res, null, 2)
  } catch (e) {
    inspectContent.value = '获取详情失败'
  }
}

// ====== K8s ======
const clusters = ref([])
const selectedClusterId = ref(null)
const selectedNamespace = ref('_all')
const namespaces = ref([])
const k8sResourceTab = ref('pods')
const k8sLoading = ref(false)
const k8sPods = ref([])
const k8sServices = ref([])
const k8sDeployments = ref([])
const testingCluster = ref(false)

const resourceTabs = computed(() => [
  { key: 'pods', label: 'Pods', count: k8sPods.value.length },
  { key: 'services', label: 'Services', count: k8sServices.value.length },
  { key: 'deployments', label: 'Deployments', count: k8sDeployments.value.length },
])

function podStatusType(s) {
  const m = { Running: 'success', Succeeded: 'success', Pending: 'warning', Failed: 'danger', Unknown: 'info' }
  return m[s] || 'info'
}

function switchToK8s() {
  activeTab.value = 'k8s'
  if (!clusters.value.length) fetchClusters()
}

async function fetchClusters() {
  try {
    const res = await getK8sClusters()
    clusters.value = res.results || res
  } catch (e) { /* */ }
}

async function onClusterChange() {
  namespaces.value = []
  k8sPods.value = []
  k8sServices.value = []
  k8sDeployments.value = []
  if (!selectedClusterId.value) return
  try {
    namespaces.value = await getK8sNamespaces(selectedClusterId.value)
  } catch (e) { /* */ }
  fetchK8sResources()
}

async function fetchK8sResources() {
  if (!selectedClusterId.value) return
  k8sLoading.value = true
  const ns = selectedNamespace.value
  try {
    if (k8sResourceTab.value === 'pods') {
      k8sPods.value = await getK8sPods(selectedClusterId.value, ns)
    } else if (k8sResourceTab.value === 'services') {
      k8sServices.value = await getK8sServices(selectedClusterId.value, ns)
    } else if (k8sResourceTab.value === 'deployments') {
      k8sDeployments.value = await getK8sDeployments(selectedClusterId.value, ns)
    }
  } catch (e) {
    ElMessage.error('获取资源列表失败')
  }
  k8sLoading.value = false
}

async function testCluster() {
  testingCluster.value = true
  try {
    const res = await testK8sConnection(selectedClusterId.value)
    if (res.success) ElMessage.success(res.message)
    else ElMessage.error(res.message)
    fetchClusters()
  } catch (e) {
    ElMessage.error('连接测试失败')
  }
  testingCluster.value = false
}

async function handleRestartPod(pod) {
  try {
    const res = await restartK8sPod(selectedClusterId.value, pod.name, pod.namespace)
    ElMessage.success(res.message || 'Pod 正在重启')
    setTimeout(fetchK8sResources, 2000)
  } catch (e) {
    ElMessage.error('重启失败')
  }
}

// 集群增删
const clusterDialogVisible = ref(false)
const editingClusterId = ref(null)
const savingCluster = ref(false)
const clusterForm = ref({ name: '', api_server: '', description: '', kubeconfig: '' })

function openClusterDialog(cluster) {
  if (cluster) {
    editingClusterId.value = cluster.id
    clusterForm.value = { name: cluster.name, api_server: cluster.api_server, description: cluster.description, kubeconfig: '' }
  } else {
    editingClusterId.value = null
    clusterForm.value = { name: '', api_server: '', description: '', kubeconfig: '' }
  }
  clusterDialogVisible.value = true
}

async function saveCluster() {
  if (!clusterForm.value.name) return ElMessage.warning('请填写集群名称')
  if (!clusterForm.value.kubeconfig && !editingClusterId.value) return ElMessage.warning('请粘贴 KubeConfig')
  savingCluster.value = true
  try {
    const data = { ...clusterForm.value }
    if (!data.kubeconfig) delete data.kubeconfig  // 编辑时如果没填就不更新
    if (editingClusterId.value) {
      await updateK8sCluster(editingClusterId.value, data)
      ElMessage.success('集群已更新')
    } else {
      await createK8sCluster(data)
      ElMessage.success('集群已添加')
    }
    clusterDialogVisible.value = false
    fetchClusters()
  } catch (e) { /* */ }
  savingCluster.value = false
}

// ====== 初始化 ======
watch(() => route.path, (newPath) => {
  if (newPath.includes('k8s')) {
    activeTab.value = 'k8s'
    if (!clusters.value.length) fetchClusters()
  } else {
    activeTab.value = 'docker'
  }
}, { immediate: true })

onMounted(async () => {
  try {
    const res = await getHosts()
    hosts.value = res.results || res
  } catch (e) { /* */ }
  fetchClusters()
})
</script>
