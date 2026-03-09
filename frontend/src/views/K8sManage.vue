<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>☸️ K8s 集群管理</h2>
      <div class="k8s-toolbar" v-if="activeTab !== 'clusters'">
        <el-select v-model="selectedClusterId" placeholder="选择集群" style="width:220px" @change="onClusterChange">
          <el-option v-for="c in clusters" :key="c.id" :label="c.name" :value="c.id">
            <div style="display:flex;align-items:center;gap:6px;">
              <span class="state-pulse" :class="c.status==='connected'?'running':'exited'"></span> {{ c.name }}
            </div>
          </el-option>
        </el-select>
        <el-select v-if="needsNamespace" v-model="selectedNamespace" placeholder="命名空间" style="width:160px" @change="fetchCurrentTab">
          <el-option label="全部命名空间" value="_all" />
          <el-option v-for="ns in namespaces" :key="ns.name" :label="ns.name" :value="ns.name" />
        </el-select>
      </div>
    </div>

    <!-- 主 Tab 栏 -->
    <div class="k8s-main-tabs">
      <button v-for="tab in mainTabs" :key="tab.key" class="k8s-tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <!-- ============ 集群管理 ============ -->
    <div v-if="activeTab === 'clusters'" class="tab-content">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <el-button type="primary" size="small" @click="openClusterDialog()"><el-icon><Plus /></el-icon> 添加集群</el-button>
      </div>
      <el-table :data="clusters" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="集群名称" min-width="160">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='connected'?'running':'exited'"></span>
              <span style="font-weight:600">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="api_server" label="API Server" min-width="220" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status==='connected'?'success':'danger'" size="small">{{ row.status==='connected'?'运行中':'未连接' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="testCluster(row)">测试连接</el-button>
            <el-button link type="info" size="small" @click="openClusterDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该集群？" @confirm="delCluster(row)">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 节点管理 ============ -->
    <div v-if="activeTab === 'nodes'" class="tab-content">
      <el-table :data="nodes" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="节点名称" min-width="180">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='Ready'?'running':'exited'"></span>
              <span style="font-weight:600">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }"><el-tag :type="row.status==='Ready'?'success':'danger'" size="small">{{ row.status==='Ready'?'就绪':'未就绪' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="roles" label="角色" width="120">
          <template #default="{ row }"><el-tag size="small" type="info">{{ row.roles }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="version" label="Kubelet版本" width="120" />
        <el-table-column prop="internal_ip" label="内部IP" width="140" />
        <el-table-column label="CPU/内存" width="150">
          <template #default="{ row }">
            <div style="font-size:12px">CPU: <b>{{ row.cpu }}</b></div>
            <div style="font-size:12px">Memory: <b>{{ row.memory }}</b></div>
          </template>
        </el-table-column>
        <el-table-column prop="os_image" label="系统" min-width="180" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- ============ 命名空间 ============ -->
    <div v-if="activeTab === 'namespaces'" class="tab-content">
      <el-table :data="nsData" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="命名空间名称" min-width="200">
          <template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.status==='Active'?'success':'danger'" size="small">{{ row.status==='Active'?'活跃':'终止' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="created" label="创建时间" min-width="200" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- ============ 工作负载 ============ -->
    <div v-if="activeTab === 'workloads'" class="tab-content">
      <div class="k8s-sub-tabs">
        <button v-for="st in workloadSubTabs" :key="st" class="k8s-sub-tab" :class="{ active: workloadSub === st }" @click="workloadSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <!-- Deployment -->
      <el-table v-if="workloadSub==='Deployment'" :data="deployments" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column label="副本" width="100"><template #default="{ row }"><span :style="{color:row.ready_replicas===row.replicas?'#10b981':'#f59e0b',fontWeight:600}">{{ row.ready_replicas }}/{{ row.replicas }}</span></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="280" show-overflow-tooltip />
      </el-table>
      <!-- StatefulSet -->
      <el-table v-if="workloadSub==='StatefulSet'" :data="statefulsets" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column label="副本" width="100"><template #default="{ row }"><span :style="{color:row.ready_replicas===row.replicas?'#10b981':'#f59e0b',fontWeight:600}">{{ row.ready_replicas }}/{{ row.replicas }}</span></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="280" show-overflow-tooltip />
      </el-table>
      <!-- DaemonSet -->
      <el-table v-if="workloadSub==='DaemonSet'" :data="daemonsets" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column label="就绪" width="100"><template #default="{ row }"><span :style="{color:row.ready===row.desired?'#10b981':'#f59e0b',fontWeight:600}">{{ row.ready }}/{{ row.desired }}</span></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="280" show-overflow-tooltip />
      </el-table>
      <!-- Job -->
      <el-table v-if="workloadSub==='Job'" :data="jobs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="completions" label="完成数" width="100" />
        <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status==='Complete'?'success':'warning'" size="small">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="200" show-overflow-tooltip />
      </el-table>
      <!-- CronJob -->
      <el-table v-if="workloadSub==='CronJob'" :data="cronjobs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="200"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="schedule" label="调度" width="140"><template #default="{ row }"><code style="font-size:12px;background:#f1f5f9;padding:2px 6px;border-radius:3px">{{ row.schedule }}</code></template></el-table-column>
        <el-table-column label="暂停" width="70"><template #default="{ row }"><el-tag :type="row.suspend?'danger':'success'" size="small">{{ row.suspend?'是':'否' }}</el-tag></template></el-table-column>
        <el-table-column prop="last_schedule" label="上次调度" min-width="180" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- ============ 网络管理 ============ -->
    <div v-if="activeTab === 'network'" class="tab-content">
      <div class="k8s-sub-tabs">
        <button v-for="st in ['Service','Ingress']" :key="st" class="k8s-sub-tab" :class="{ active: networkSub === st }" @click="networkSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <el-table v-if="networkSub==='Service'" :data="services" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="200"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="type" label="类型" width="110"><template #default="{ row }"><el-tag size="small" :type="row.type==='LoadBalancer'?'warning':row.type==='NodePort'?'success':'info'">{{ row.type }}</el-tag></template></el-table-column>
        <el-table-column prop="cluster_ip" label="Cluster IP" width="140" />
        <el-table-column prop="ports" label="端口" min-width="200" show-overflow-tooltip />
      </el-table>
      <el-table v-if="networkSub==='Ingress'" :data="ingresses" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="180"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="class" label="Ingress Class" width="120" />
        <el-table-column prop="hosts" label="域名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="address" label="地址" width="140" />
        <el-table-column prop="ports" label="端口" width="100" />
      </el-table>
    </div>

    <!-- ============ 存储管理 ============ -->
    <div v-if="activeTab === 'storage'" class="tab-content">
      <div class="k8s-sub-tabs">
        <button v-for="st in ['PV','PVC','StorageClass']" :key="st" class="k8s-sub-tab" :class="{ active: storageSub === st }" @click="storageSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <el-table v-if="storageSub==='PV'" :data="pvs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="200"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="capacity" label="容量" width="90" />
        <el-table-column prop="access_modes" label="访问模式" width="100" />
        <el-table-column prop="reclaim_policy" label="回收策略" width="100" />
        <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status==='Bound'?'success':row.status==='Available'?'info':'warning'" size="small">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="claim" label="绑定声明" min-width="250" show-overflow-tooltip />
        <el-table-column prop="storage_class" label="存储类" width="120" />
      </el-table>
      <el-table v-if="storageSub==='PVC'" :data="pvcs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="240"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status==='Bound'?'success':'warning'" size="small">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="capacity" label="容量" width="90" />
        <el-table-column prop="access_modes" label="访问模式" width="100" />
        <el-table-column prop="storage_class" label="存储类" width="120" />
        <el-table-column prop="volume" label="PV" min-width="180" show-overflow-tooltip />
      </el-table>
      <el-table v-if="storageSub==='StorageClass'" :data="storageclasses" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="160">
          <template #default="{ row }">
            <span style="font-weight:600;font-family:monospace">{{ row.name }}</span>
            <el-tag v-if="row.is_default" type="primary" size="small" style="margin-left:6px">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="provisioner" label="Provisioner" min-width="220" show-overflow-tooltip />
        <el-table-column prop="reclaim_policy" label="回收策略" width="100" />
        <el-table-column prop="binding_mode" label="绑定模式" width="180" />
        <el-table-column label="允许扩展" width="90"><template #default="{ row }"><el-tag :type="row.allow_expansion?'success':'info'" size="small">{{ row.allow_expansion?'是':'否' }}</el-tag></template></el-table-column>
      </el-table>
    </div>

    <!-- ============ 配置管理 ============ -->
    <div v-if="activeTab === 'config'" class="tab-content">
      <div class="k8s-sub-tabs">
        <button v-for="st in ['ConfigMap','Secret']" :key="st" class="k8s-sub-tab" :class="{ active: configSub === st }" @click="configSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <el-table v-if="configSub==='ConfigMap'" :data="configmaps" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="250"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="data_count" label="数据条目" width="100" />
        <el-table-column prop="created" label="创建时间" min-width="200" show-overflow-tooltip />
      </el-table>
      <el-table v-if="configSub==='Secret'" :data="secrets" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="250"><template #default="{ row }"><span style="font-weight:600;font-family:monospace">{{ row.name }}</span></template></el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="type" label="类型" min-width="240"><template #default="{ row }"><code style="font-size:11px;background:#f1f5f9;padding:2px 6px;border-radius:3px">{{ row.type }}</code></template></el-table-column>
        <el-table-column prop="data_count" label="数据条目" width="100" />
        <el-table-column prop="created" label="创建时间" min-width="200" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- ============ 集群弹窗 ============ -->
    <el-dialog v-model="clusterDialogVisible" :title="editingClusterId ? '编辑集群' : '添加 K8s 集群'" width="90%" style="max-width:600px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="clusterForm" label-width="110px">
        <el-form-item label="集群名称"><el-input v-model="clusterForm.name" placeholder="例如 prod-cluster" /></el-form-item>
        <el-form-item label="API Server"><el-input v-model="clusterForm.api_server" placeholder="例如 https://10.0.0.1:6443 (可选)" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="clusterForm.description" placeholder="集群用途描述" /></el-form-item>
        <el-form-item label="KubeConfig"><el-input v-model="clusterForm.kubeconfig" type="textarea" :rows="12" placeholder="粘贴 kubeconfig YAML 内容" style="font-family:monospace;font-size:12px;" /></el-form-item>
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
import { ElMessage } from 'element-plus'
import {
  getK8sClusters, createK8sCluster, updateK8sCluster, deleteK8sCluster,
  testK8sConnection, getK8sNamespaces,
  getK8sPods, getK8sServices, getK8sDeployments, restartK8sPod,
  getK8sNodes, getK8sStatefulSets, getK8sDaemonSets, getK8sJobs, getK8sCronJobs,
  getK8sIngresses, getK8sPVs, getK8sPVCs, getK8sStorageClasses,
  getK8sConfigMaps, getK8sSecrets,
} from '@/api/modules/container'

const mainTabs = [
  { key: 'clusters',   label: '集群管理', icon: 'OfficeBuilding' },
  { key: 'nodes',      label: '节点管理', icon: 'Monitor' },
  { key: 'namespaces', label: '命名空间', icon: 'FolderOpened' },
  { key: 'workloads',  label: '工作负载', icon: 'Cpu' },
  { key: 'network',    label: '网络管理', icon: 'Connection' },
  { key: 'storage',    label: '存储管理', icon: 'Coin' },
  { key: 'config',     label: '配置管理', icon: 'Setting' },
]

const activeTab = ref('clusters')
const loading = ref(false)

// ====== 集群 ======
const clusters = ref([])
const selectedClusterId = ref(null)
const selectedNamespace = ref('_all')
const namespaces = ref([])

const needsNamespace = computed(() => ['namespaces', 'workloads', 'network', 'config'].includes(activeTab.value) || (activeTab.value === 'storage' && storageSub.value === 'PVC'))

// ====== 各 Tab 数据 ======
const nodes = ref([])
const nsData = ref([])
const deployments = ref([])
const statefulsets = ref([])
const daemonsets = ref([])
const jobs = ref([])
const cronjobs = ref([])
const services = ref([])
const ingresses = ref([])
const pvs = ref([])
const pvcs = ref([])
const storageclasses = ref([])
const configmaps = ref([])
const secrets = ref([])

// ====== Sub-tabs ======
const workloadSubTabs = ['Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob']
const workloadSub = ref('Deployment')
const networkSub = ref('Service')
const storageSub = ref('PV')
const configSub = ref('ConfigMap')

// ====== 切换 Tab ======
function switchTab(tab) {
  activeTab.value = tab
  if (tab === 'clusters') {
    fetchClusters()
  } else if (selectedClusterId.value) {
    fetchCurrentTab()
  }
}

async function fetchClusters() {
  loading.value = true
  try {
    const res = await getK8sClusters()
    clusters.value = res.results || res
  } catch (e) { /* */ }
  loading.value = false
}

async function onClusterChange() {
  namespaces.value = []
  if (!selectedClusterId.value) return
  try { namespaces.value = await getK8sNamespaces(selectedClusterId.value) } catch (e) { /* */ }
  fetchCurrentTab()
}

async function fetchCurrentTab() {
  if (!selectedClusterId.value && activeTab.value !== 'clusters') return
  loading.value = true
  const id = selectedClusterId.value
  const ns = selectedNamespace.value
  try {
    switch (activeTab.value) {
      case 'nodes': nodes.value = await getK8sNodes(id); break
      case 'namespaces': nsData.value = await getK8sNamespaces(id); break
      case 'workloads':
        if (workloadSub.value === 'Deployment') deployments.value = await getK8sDeployments(id, ns)
        else if (workloadSub.value === 'StatefulSet') statefulsets.value = await getK8sStatefulSets(id, ns)
        else if (workloadSub.value === 'DaemonSet') daemonsets.value = await getK8sDaemonSets(id, ns)
        else if (workloadSub.value === 'Job') jobs.value = await getK8sJobs(id, ns)
        else if (workloadSub.value === 'CronJob') cronjobs.value = await getK8sCronJobs(id, ns)
        break
      case 'network':
        if (networkSub.value === 'Service') services.value = await getK8sServices(id, ns)
        else ingresses.value = await getK8sIngresses(id, ns)
        break
      case 'storage':
        if (storageSub.value === 'PV') pvs.value = await getK8sPVs(id)
        else if (storageSub.value === 'PVC') pvcs.value = await getK8sPVCs(id, ns)
        else storageclasses.value = await getK8sStorageClasses(id)
        break
      case 'config':
        if (configSub.value === 'ConfigMap') configmaps.value = await getK8sConfigMaps(id, ns)
        else secrets.value = await getK8sSecrets(id, ns)
        break
    }
  } catch (e) {
    ElMessage.error('获取数据失败')
  }
  loading.value = false
}

// ====== 集群 CRUD ======
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
    if (!data.kubeconfig) delete data.kubeconfig
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

async function testCluster(row) {
  try {
    const res = await testK8sConnection(row.id)
    if (res.success) ElMessage.success(res.message)
    else ElMessage.error(res.message)
    fetchClusters()
  } catch (e) { ElMessage.error('连接测试失败') }
}

async function delCluster(row) {
  try {
    await deleteK8sCluster(row.id)
    ElMessage.success('集群已删除')
    fetchClusters()
  } catch (e) { ElMessage.error('删除失败') }
}

// ====== 初始化 ======
onMounted(() => { fetchClusters() })
</script>
