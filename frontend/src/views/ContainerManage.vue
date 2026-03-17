<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>🐳 Docker 环境</h2>
      <div class="docker-toolbar" v-if="activeTab !== 'hosts'">
        <div class="cluster-selector-group">
          <span class="toolbar-label"><el-icon><Monitor /></el-icon> 当前环境</span>
          <el-select v-model="selectedHostId" placeholder="选择环境" @change="onHostChange" style="width: 150px" class="industrial-select" popper-class="industrial-popper">
            <el-option v-for="h in dockerHosts" :key="h.id" :label="h.name" :value="h.id">
              <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                <span class="state-pulse" :class="h.status==='connected'?'running':'exited'"></span> {{ h.name }}
              </div>
            </el-option>
          </el-select>
        </div>
      </div>
    </div>

    <!-- 主 Tab 栏 (Pill Tab Theme: Blue) -->
    <div class="neo-tabs theme-blue">
      <button v-for="tab in mainTabs" :key="tab.key" class="neo-tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <!-- ============ 环境管理 ============ -->
    <div v-if="activeTab === 'hosts'" class="tab-content">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <el-button v-if="canManageDocker" type="primary" size="small" @click="openHostDialog()"><el-icon><Plus /></el-icon> 添加环境</el-button>
      </div>
      <el-table :data="dockerHosts" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="环境名称" min-width="160">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='connected'?'running':'exited'"></span>
              <span style="font-weight:600">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="ip_address" label="IP 地址" width="150" />
        <el-table-column prop="ssh_port" label="SSH 端口" width="90" />
        <el-table-column prop="ssh_user" label="用户" width="90" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status==='connected'?'success':'danger'" size="small">{{ row.status==='connected'?'已连接':'未连接' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="docker_api_version" label="Docker 版本" width="120" />
        <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
        <el-table-column v-if="canManageDocker" label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="testHost(row)">测试连接</el-button>
            <el-button link type="info" size="small" @click="openHostDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该环境？" @confirm="delHost(row)">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 容器管理 ============ -->
    <div v-if="activeTab === 'containers'" class="tab-content">
      <div v-if="!selectedHostId" class="empty-state">
        <div class="empty-icon">🐳</div>
        <div class="empty-text">请在右上角选择一个 Docker 环境</div>
      </div>
      <el-table v-else :data="containers" stripe v-loading="loading" style="width:100%">
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
            <el-button v-if="canManageDocker && row.state !== 'running'" link type="success" size="small" @click="doAction(row, 'start')">启动</el-button>
            <el-button v-if="canManageDocker && row.state === 'running'" link type="warning" size="small" @click="doAction(row, 'stop')">停止</el-button>
            <el-button v-if="canManageDocker && row.state === 'running'" link type="primary" size="small" @click="doAction(row, 'restart')">重启</el-button>
            <el-button link type="info" size="small" @click="viewContainerLogs(row)">日志</el-button>
            <el-button link type="info" size="small" @click="inspectContainer(row)">详情</el-button>
            <el-popconfirm v-if="canManageDocker" title="确定删除该容器？" @confirm="removeContainer(row)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 镜像管理 ============ -->
    <div v-if="activeTab === 'images'" class="tab-content">
      <div v-if="!selectedHostId" class="empty-state">
        <div class="empty-icon">📦</div>
        <div class="empty-text">请在右上角选择一个 Docker 环境</div>
      </div>
      <el-table v-else :data="images" stripe v-loading="loading" style="width:100%">
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

    <!-- ============ 容器日志弹窗 ============ -->
    <el-dialog v-model="logVisible" :title="'容器日志 — ' + logContainerName" width="90%" style="max-width:900px;" top="3vh" append-to-body destroy-on-close>
      <pre class="log-output terminal-log">{{ logContent || '加载中...' }}</pre>
    </el-dialog>

    <!-- ============ 容器详情弹窗 ============ -->
    <el-dialog v-model="inspectVisible" :title="'容器详情 — ' + inspectContainerName" width="90%" style="max-width:900px;" top="3vh" append-to-body destroy-on-close>
      <pre class="log-output terminal-log">{{ inspectContent || '加载中...' }}</pre>
    </el-dialog>

    <!-- ============ 新增/编辑 Docker 环境弹窗 ============ -->
    <el-dialog v-model="hostDialogVisible" :title="editingHostId ? '编辑 Docker 环境' : '添加 Docker 环境'" width="90%" style="max-width:560px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="hostForm" label-width="100px">
        <el-form-item label="环境名称"><el-input v-model="hostForm.name" placeholder="例如 prod-docker-01" /></el-form-item>
        <el-form-item label="IP 地址"><el-input v-model="hostForm.ip_address" placeholder="例如 192.168.1.100" /></el-form-item>
        <el-form-item label="SSH 端口"><el-input-number v-model="hostForm.ssh_port" :min="1" :max="65535" controls-position="right" style="width:150px" /></el-form-item>
        <el-form-item label="SSH 用户"><el-input v-model="hostForm.ssh_user" placeholder="root" /></el-form-item>
        <el-form-item label="SSH 密码"><el-input v-model="hostForm.ssh_password" type="password" show-password :placeholder="editingHostId ? '留空则不更新' : '请输入 SSH 密码'" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="hostForm.description" placeholder="环境用途简述" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="hostDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveHost" :loading="savingHost">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useRouteTabState } from '@/composables/useRouteTabState'
import {
  getDockerHosts, createDockerHost, updateDockerHost, deleteDockerHost, testDockerConnection,
  getDockerContainers, getDockerImages,
  dockerContainerAction, dockerContainerRemove,
  getDockerContainerLogs, getDockerContainerInspect,
} from '@/api/modules/container'

const authStore = useAuthStore()
const canManageDocker = computed(() => authStore.hasPermission('ops.docker.manage'))

const mainTabs = [
  { key: 'hosts',      label: '环境管理', icon: 'OfficeBuilding' },
  { key: 'containers', label: '容器管理', icon: 'Box' },
  { key: 'images',     label: '镜像管理', icon: 'Files' },
]

const tabState = useRouteTabState({
  tabs: () => mainTabs.map(item => item.key),
  defaultTab: 'hosts',
})
const activeTab = tabState.activeTab
const loading = ref(false)

// ====== Docker 环境列表 ======
const dockerHosts = ref([])
const selectedHostId = ref(null)

// ====== 数据 ======
const containers = ref([])
const images = ref([])

// ====== Tab 切换逻辑 ======
function switchTab(tab) {
  tabState.switchTab(tab)
}

function onHostChange() {
  fetchCurrentTab()
}

async function fetchHosts() {
  loading.value = true
  try {
    const res = await getDockerHosts()
    dockerHosts.value = res.results || res
    // 默认选中第一个
    if (dockerHosts.value.length > 0 && !selectedHostId.value) {
      selectedHostId.value = dockerHosts.value[0].id
    }
  } catch (e) { /* */ }
  loading.value = false
}

async function fetchCurrentTab() {
  if (!selectedHostId.value && activeTab.value !== 'hosts') return
  loading.value = true
  const id = selectedHostId.value
  try {
    if (activeTab.value === 'containers') {
      containers.value = await getDockerContainers(id)
    } else if (activeTab.value === 'images') {
      images.value = await getDockerImages(id)
    }
  } catch (e) {
    ElMessage.error('获取数据失败')
  }
  loading.value = false
}

// ====== 容器状态映射 ======
function containerStateType(state) {
  const m = { running: 'success', exited: 'danger', paused: 'warning', created: 'info', restarting: 'warning', dead: 'danger' }
  return m[state] || 'info'
}

// ====== 容器操作 ======
async function doAction(row, action) {
  if (!canManageDocker.value) return
  try {
    const res = await dockerContainerAction(row.id, selectedHostId.value, action)
    ElMessage.success(res.message || `${action} 成功`)
    fetchCurrentTab()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

async function removeContainer(row) {
  if (!canManageDocker.value) return
  try {
    await dockerContainerRemove(row.id, selectedHostId.value)
    ElMessage.success('容器已删除')
    fetchCurrentTab()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

// ====== 日志 ======
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

// ====== 详情 ======
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

// ====== Docker 环境 CRUD ======
const hostDialogVisible = ref(false)
const editingHostId = ref(null)
const savingHost = ref(false)
const hostForm = ref({ name: '', ip_address: '', ssh_port: 22, ssh_user: 'root', ssh_password: '', description: '' })

function openHostDialog(host) {
  if (!canManageDocker.value) return
  if (host) {
    editingHostId.value = host.id
    hostForm.value = { name: host.name, ip_address: host.ip_address, ssh_port: host.ssh_port, ssh_user: host.ssh_user, ssh_password: '', description: host.description }
  } else {
    editingHostId.value = null
    hostForm.value = { name: '', ip_address: '', ssh_port: 22, ssh_user: 'root', ssh_password: '', description: '' }
  }
  hostDialogVisible.value = true
}

async function saveHost() {
  if (!canManageDocker.value) return
  if (!hostForm.value.name) return ElMessage.warning('请填写环境名称')
  if (!hostForm.value.ip_address) return ElMessage.warning('请填写 IP 地址')
  savingHost.value = true
  try {
    const data = { ...hostForm.value }
    if (!data.ssh_password) delete data.ssh_password
    if (editingHostId.value) {
      await updateDockerHost(editingHostId.value, data)
      ElMessage.success('环境已更新')
    } else {
      await createDockerHost(data)
      ElMessage.success('环境已添加')
    }
    hostDialogVisible.value = false
    fetchHosts()
  } catch (e) { /* */ }
  savingHost.value = false
}

async function testHost(row) {
  if (!canManageDocker.value) return
  try {
    const res = await testDockerConnection(row.id)
    if (res.success) ElMessage.success(res.message)
    else ElMessage.error(res.message)
    fetchHosts()
  } catch (e) { ElMessage.error('连接测试失败') }
}

async function delHost(row) {
  if (!canManageDocker.value) return
  try {
    await deleteDockerHost(row.id)
    ElMessage.success('环境已删除')
    if (selectedHostId.value === row.id) selectedHostId.value = null
    fetchHosts()
  } catch (e) { ElMessage.error('删除失败') }
}

// ====== 初始化 ======
watch(activeTab, (tab, prev) => {
  if (!tab || tab === prev) return
  if (tab === 'hosts') {
    fetchHosts()
  } else if (selectedHostId.value) {
    fetchCurrentTab()
  }
})

onMounted(() => {
  fetchHosts().then(() => {
    if (activeTab.value !== 'hosts') {
      fetchCurrentTab()
    }
  })
})
</script>
