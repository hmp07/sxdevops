<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>🐳 Docker 环境</h2>
      <div class="docker-toolbar" v-if="activeTab !== 'hosts'">
        <div class="toolbar-filter-bar">
          <div class="toolbar-filter-pill toolbar-filter-pill--env">
            <span class="toolbar-filter-label">环境</span>
            <el-select v-model="selectedHostId" placeholder="选择环境" @change="onHostChange" class="industrial-select toolbar-filter-select" popper-class="industrial-popper">
            <el-option v-for="h in dockerHosts" :key="h.id" :label="h.name" :value="h.id">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                  <span class="state-pulse" :class="h.status==='connected'?'running':'exited'"></span>
                  <span>{{ h.name }}</span>
                </div>
                <el-tag size="small" :type="h.status === 'connected' ? 'success' : 'info'">
                  {{ h.status === 'connected' ? '在线' : '离线' }}
                </el-tag>
              </div>
            </el-option>
            </el-select>
          </div>
        </div>
      </div>
    </div>

    <!-- 主 Tab 栏 (Pill Tab Theme: Blue) -->
    <section class="hero panel docker-hero">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="release-header-icon docker-header-icon"><el-icon><Platform /></el-icon></span>
          <h2>Docker 环境</h2>
          <p class="subtitle inline-subtitle">统一管理 Docker 主机、容器与镜像资源，支持连接测试、日志查看和批量镜像治理。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button @click="refreshView"><el-icon><RefreshRight /></el-icon>刷新</el-button>
        <el-button v-if="canManageDocker && activeTab === 'hosts'" type="primary" @click="openHostDialog()"><el-icon><Plus /></el-icon>新增环境</el-button>
      </div>
    </section>

    <div class="stats-grid release-stats docker-top-stats">
      <div v-for="card in summaryCards" :key="card.label" class="stat-card release-stat-card" :class="card.tone">
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
        <div class="docker-stat-meta">{{ card.meta }}</div>
      </div>
    </div>

    <div v-if="activeTips.length" class="docker-alert-strip">
      <span class="docker-alert-strip__label">运行提示</span>
      <el-tooltip
        v-for="(tip, index) in activeTips.slice(0, 2)"
        :key="index"
        :content="tip"
        placement="top"
        effect="light"
        :show-after="120"
      >
        <el-tag size="small" effect="light" type="info" class="docker-alert-strip__tag">
          {{ tip }}
        </el-tag>
      </el-tooltip>
      <el-popover v-if="activeTips.length > 2" placement="bottom-end" :width="320" trigger="hover">
        <template #reference>
          <el-button link type="primary">+{{ activeTips.length - 2 }} 更多</el-button>
        </template>
        <div class="alert-popover">
          <div v-for="(tip, index) in activeTips" :key="`docker-tip-${index}`" class="alert-popover__item">
            <el-tag size="small" type="info">提示</el-tag>
            <span>{{ tip }}</span>
          </div>
        </div>
      </el-popover>
    </div>

    <div class="neo-tabs theme-blue">
      <button v-for="tab in mainTabs" :key="tab.key" class="neo-tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <div v-if="false && activeTab !== 'hosts'" class="docker-toolbar toolbar-shell">
      <div class="toolbar-filter-bar">
        <div class="toolbar-filter-pill toolbar-filter-pill--env">
          <span class="toolbar-filter-label">环境</span>
          <el-select v-model="selectedHostId" placeholder="选择环境" @change="onHostChange" class="industrial-select toolbar-filter-select" popper-class="industrial-popper">
            <el-option v-for="h in dockerHosts" :key="h.id" :label="h.name" :value="h.id">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                  <span class="state-pulse" :class="h.status==='connected'?'running':'exited'"></span>
                  <span>{{ h.name }}</span>
                </div>
                <el-tag size="small" :type="h.status === 'connected' ? 'success' : 'info'">
                  {{ h.status === 'connected' ? '在线' : '离线' }}
                </el-tag>
              </div>
            </el-option>
          </el-select>
        </div>
      </div>
    </div>

    <!-- ============ 环境管理 ============ -->
    <div v-if="activeTab === 'hosts'" class="tab-content">
      <div class="stats-grid docker-summary-grid" style="margin-bottom:16px;">
        <div class="stat-card docker-summary-card">
          <div class="stat-icon primary"><el-icon><Platform /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ dockerHostStats.total }}</div>
            <div class="stat-label">环境总数</div>
          </div>
        </div>
        <div class="stat-card docker-summary-card">
          <div class="stat-icon success"><el-icon><CircleCheck /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ dockerHostStats.connected }}</div>
            <div class="stat-label">已连接环境</div>
          </div>
        </div>
        <div class="stat-card docker-summary-card">
          <div class="stat-icon warning"><el-icon><WarningFilled /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value">{{ dockerHostStats.attention }}</div>
            <div class="stat-label">待处理环境</div>
          </div>
        </div>
        <div class="stat-card docker-summary-card">
          <div class="stat-icon info"><el-icon><Monitor /></el-icon></div>
          <div class="stat-info">
            <div class="stat-value docker-summary-value-sm">{{ dockerHostStats.selected }}</div>
            <div class="stat-label">当前环境</div>
          </div>
        </div>
      </div>
      <div class="filter-bar" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <el-input v-model="hostSearchKeyword" clearable placeholder="搜索环境名称、IP、描述" style="max-width:320px" />
        <div style="display:flex;gap:8px;">
          <el-button size="small" @click="refreshView"><el-icon><RefreshRight /></el-icon> 刷新</el-button>
          <el-button v-if="canManageDocker" type="primary" size="small" @click="openHostDialog()"><el-icon><Plus /></el-icon> 添加环境</el-button>
        </div>
      </div>
      <el-table :data="filteredHosts" stripe v-loading="loading" style="width:100%">
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
      <template v-else>
        <div class="stats-grid docker-summary-grid" style="margin-bottom:16px;">
          <div class="stat-card docker-summary-card">
            <div class="stat-icon primary"><el-icon><Box /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ containerStats.total }}</div>
              <div class="stat-label">容器总数</div>
            </div>
          </div>
          <div class="stat-card docker-summary-card">
            <div class="stat-icon success"><el-icon><VideoPlay /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ containerStats.running }}</div>
              <div class="stat-label">运行中</div>
            </div>
          </div>
          <div class="stat-card docker-summary-card">
            <div class="stat-icon warning"><el-icon><WarningFilled /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ containerStats.attention }}</div>
              <div class="stat-label">需要关注</div>
            </div>
          </div>
          <div class="stat-card docker-summary-card">
            <div class="stat-icon info"><el-icon><Files /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ containerStats.uniqueImages }}</div>
              <div class="stat-label">镜像种类</div>
            </div>
          </div>
        </div>
        <div class="filter-bar filter-bar--context" style="margin-bottom:12px;">
          <el-input v-model="containerKeyword" clearable placeholder="搜索容器名称、镜像、端口" style="max-width:320px" />
          <el-select v-model="containerStateFilter" style="width:140px">
            <el-option label="全部状态" value="all" />
            <el-option label="运行中" value="running" />
            <el-option label="已停止" value="stopped" />
            <el-option label="需关注" value="attention" />
          </el-select>
          <div class="filter-inline-context filter-inline-context--push">
            <span class="filter-inline-label">当前环境</span>
            <el-select v-model="selectedHostId" placeholder="选择环境" @change="onHostChange" class="industrial-select toolbar-filter-select filter-inline-select" popper-class="industrial-popper">
              <el-option v-for="h in dockerHosts" :key="h.id" :label="h.name" :value="h.id">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                  <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                    <span class="state-pulse" :class="h.status==='connected'?'running':'exited'"></span>
                    <span>{{ h.name }}</span>
                  </div>
                  <el-tag size="small" :type="h.status === 'connected' ? 'success' : 'info'">
                    {{ h.status === 'connected' ? '在线' : '离线' }}
                  </el-tag>
                </div>
              </el-option>
            </el-select>
          </div>
          <el-button size="small" @click="refreshView"><el-icon><RefreshRight /></el-icon> 刷新</el-button>
        </div>
        <el-table :data="filteredContainers" stripe v-loading="loading" style="width:100%">
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
      </template>
    </div>

    <!-- ============ 镜像管理 ============ -->
    <div v-if="activeTab === 'images'" class="tab-content">
      <div v-if="!selectedHostId" class="empty-state">
        <div class="empty-icon">📦</div>
        <div class="empty-text">请在右上角选择一个 Docker 环境</div>
      </div>
      <template v-else>
        <div class="stats-grid docker-summary-grid" style="margin-bottom:16px;">
          <div class="stat-card docker-summary-card">
            <div class="stat-icon primary"><el-icon><Files /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ imageStats.total }}</div>
              <div class="stat-label">镜像总数</div>
            </div>
          </div>
          <div class="stat-card docker-summary-card">
            <div class="stat-icon success"><el-icon><CollectionTag /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ imageStats.repositories }}</div>
              <div class="stat-label">仓库数</div>
            </div>
          </div>
          <div class="stat-card docker-summary-card">
            <div class="stat-icon warning"><el-icon><WarningFilled /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ imageStats.dangling }}</div>
              <div class="stat-label">悬空镜像</div>
            </div>
          </div>
          <div class="stat-card docker-summary-card">
            <div class="stat-icon info"><el-icon><Monitor /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value docker-summary-value-sm">{{ imageStats.version }}</div>
              <div class="stat-label">Docker 版本</div>
            </div>
          </div>
        </div>
        <div class="filter-bar filter-bar--context" style="margin-bottom:12px;">
          <el-input v-model="imageKeyword" clearable placeholder="搜索仓库、标签、镜像 ID" style="max-width:320px" />
          <div class="filter-inline-context filter-inline-context--push">
            <span class="filter-inline-label">当前环境</span>
            <el-select v-model="selectedHostId" placeholder="选择环境" @change="onHostChange" class="industrial-select toolbar-filter-select filter-inline-select" popper-class="industrial-popper">
              <el-option v-for="h in dockerHosts" :key="h.id" :label="h.name" :value="h.id">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                  <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                    <span class="state-pulse" :class="h.status==='connected'?'running':'exited'"></span>
                    <span>{{ h.name }}</span>
                  </div>
                  <el-tag size="small" :type="h.status === 'connected' ? 'success' : 'info'">
                    {{ h.status === 'connected' ? '在线' : '离线' }}
                  </el-tag>
                </div>
              </el-option>
            </el-select>
          </div>
          <el-tag v-if="imageSelection.length" type="info" size="large">已选 {{ imageSelection.length }} 个镜像</el-tag>
          <el-button v-if="canManageDocker" size="small" type="warning" plain @click="pruneDanglingImages">清理悬空镜像</el-button>
          <el-button v-if="canManageDocker" size="small" type="danger" plain :disabled="!imageSelection.length" @click="removeSelectedImages">批量删除</el-button>
          <el-button size="small" @click="refreshView"><el-icon><RefreshRight /></el-icon> 刷新</el-button>
        </div>
        <el-table :data="filteredImages" stripe v-loading="loading" style="width:100%" @selection-change="handleImageSelectionChange">
        <el-table-column v-if="canManageDocker" type="selection" width="48" />
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
      </template>
    </div>

    <!-- ============ 容器日志弹窗 ============ -->
    <el-dialog v-model="logVisible" :title="'容器日志 — ' + logContainerName" width="90%" style="max-width:900px;" top="3vh" append-to-body destroy-on-close>
      <div class="filter-bar" style="margin-bottom:12px;">
        <el-select v-model="logTailLines" style="width:120px" @change="reloadContainerLogs">
          <el-option :value="100" label="最近 100 行" />
          <el-option :value="200" label="最近 200 行" />
          <el-option :value="500" label="最近 500 行" />
          <el-option :value="1000" label="最近 1000 行" />
        </el-select>
        <el-button size="small" @click="reloadContainerLogs" :disabled="!logContainerId"><el-icon><RefreshRight /></el-icon> 刷新日志</el-button>
      </div>
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
  dockerRemoveImages, dockerPruneDanglingImages,
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
const hostSearchKeyword = ref('')

// ====== 数据 ======
const containers = ref([])
const images = ref([])
const containerKeyword = ref('')
const containerStateFilter = ref('all')
const imageKeyword = ref('')
const imageSelection = ref([])

const selectedHost = computed(() => dockerHosts.value.find(item => item.id === selectedHostId.value) || null)
const dockerHostStats = computed(() => ({
  total: dockerHosts.value.length,
  connected: dockerHosts.value.filter(item => item.status === 'connected').length,
  attention: dockerHosts.value.filter(item => item.status !== 'connected').length,
  selected: selectedHost.value?.name || '未选择',
}))
const filteredHosts = computed(() => {
  const keyword = hostSearchKeyword.value.trim().toLowerCase()
  if (!keyword) return dockerHosts.value
  return dockerHosts.value.filter(item =>
    [item.name, item.ip_address, item.description, item.docker_api_version].some(field => String(field || '').toLowerCase().includes(keyword))
  )
})
const containerStats = computed(() => {
  const total = containers.value.length
  const running = containers.value.filter(item => item.state === 'running').length
  const attention = containers.value.filter(item =>
    ['restarting', 'dead'].includes(item.state) || String(item.status || '').toLowerCase().includes('unhealthy')
  ).length
  const uniqueImages = new Set(containers.value.map(item => item.image).filter(Boolean)).size
  return { total, running, attention, uniqueImages }
})
const filteredContainers = computed(() => {
  const keyword = containerKeyword.value.trim().toLowerCase()
  return containers.value.filter(item => {
    const matchesKeyword = !keyword || [item.name, item.image, item.ports, item.status].some(field =>
      String(field || '').toLowerCase().includes(keyword)
    )
    if (!matchesKeyword) return false
    if (containerStateFilter.value === 'all') return true
    if (containerStateFilter.value === 'running') return item.state === 'running'
    if (containerStateFilter.value === 'stopped') return ['exited', 'dead'].includes(item.state)
    return ['restarting', 'dead'].includes(item.state) || String(item.status || '').toLowerCase().includes('unhealthy')
  })
})
const imageStats = computed(() => ({
  total: images.value.length,
  repositories: new Set(images.value.map(item => item.repository).filter(item => item && item !== '<none>')).size,
  dangling: images.value.filter(item => item.repository === '<none>' || item.tag === '<none>').length,
  version: selectedHost.value?.docker_api_version || '未知',
}))
const summaryCards = computed(() => {
  if (activeTab.value === 'hosts') {
    return [
      { label: '环境总数', value: dockerHostStats.value.total, meta: 'Docker 主机', tone: '' },
      { label: '已连接', value: dockerHostStats.value.connected, meta: '可运维环境', tone: 'success-card' },
      { label: '待处理', value: dockerHostStats.value.attention, meta: '需排查环境', tone: 'warning-card' },
      { label: '当前环境', value: dockerHostStats.value.selected, meta: '当前上下文', tone: 'context-card' },
    ]
  }
  if (activeTab.value === 'containers') {
    return [
      { label: '容器总数', value: containerStats.value.total, meta: '当前环境容器', tone: '' },
      { label: '运行中', value: containerStats.value.running, meta: '在线实例', tone: 'success-card' },
      { label: '需关注', value: containerStats.value.attention, meta: '重启 / 不健康', tone: 'warning-card' },
      { label: '镜像种类', value: containerStats.value.uniqueImages, meta: '镜像覆盖', tone: 'danger-card' },
    ]
  }
  return [
    { label: '镜像总数', value: imageStats.value.total, meta: '当前环境镜像', tone: '' },
    { label: '仓库数', value: imageStats.value.repositories, meta: '镜像仓库', tone: 'success-card' },
    { label: '悬空镜像', value: imageStats.value.dangling, meta: '建议清理', tone: 'warning-card' },
    { label: 'Docker 版本', value: imageStats.value.version, meta: '目标主机版本', tone: 'danger-card' },
  ]
})
const activeTips = computed(() => {
  if (activeTab.value !== 'hosts' && !selectedHostId.value) return ['请选择一个 Docker 环境后再查看容器或镜像数据。']
  return {
    hosts: ['新增环境后建议先执行连接测试，再进入容器或镜像管理。'],
    containers: ['容器操作会作用到当前选中的 Docker 环境。', '查看日志和详情前建议先确认容器状态是否正常。'],
    images: ['批量删除镜像前请先确认当前环境选择无误。', '悬空镜像清理适合在发布完成后执行。'],
  }[activeTab.value] || []
})
const filteredImages = computed(() => {
  const keyword = imageKeyword.value.trim().toLowerCase()
  if (!keyword) return images.value
  return images.value.filter(item =>
    [item.repository, item.tag, item.id, item.size].some(field => String(field || '').toLowerCase().includes(keyword))
  )
})

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
    const hasSelection = dockerHosts.value.some(item => item.id === selectedHostId.value)
    selectedHostId.value = hasSelection ? selectedHostId.value : (dockerHosts.value[0]?.id || null)
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
      imageSelection.value = []
    }
  } catch (e) {
    ElMessage.error('获取数据失败')
  }
  loading.value = false
}

function refreshView() {
  if (activeTab.value === 'hosts') {
    fetchHosts()
    return
  }
  fetchCurrentTab()
}

function handleImageSelectionChange(rows) {
  imageSelection.value = rows || []
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
const logContainerId = ref('')
const logContainerName = ref('')
const logContent = ref('')
async function viewContainerLogs(row) {
  logContainerId.value = row.id
  logContainerName.value = row.name
  logContent.value = ''
  logVisible.value = true
  await reloadContainerLogs()
}

const logTailLines = ref(200)
async function reloadContainerLogs() {
  if (!logContainerId.value || !selectedHostId.value) return
  try {
    const res = await getDockerContainerLogs(logContainerId.value, selectedHostId.value, logTailLines.value)
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

async function removeSelectedImages() {
  if (!canManageDocker.value || !selectedHostId.value || !imageSelection.value.length) return
  try {
    const res = await dockerRemoveImages(selectedHostId.value, imageSelection.value.map(item => item.id))
    ElMessage.success(res.message || '镜像已删除')
    await fetchCurrentTab()
  } catch (e) {
    ElMessage.error('批量删除镜像失败')
  }
}

async function pruneDanglingImages() {
  if (!canManageDocker.value || !selectedHostId.value) return
  try {
    const res = await dockerPruneDanglingImages(selectedHostId.value)
    ElMessage.success(res.message || '悬空镜像已清理')
    await fetchCurrentTab()
  } catch (e) {
    ElMessage.error('清理悬空镜像失败')
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

<style scoped>
.page-header { display: none; }
.panel { background: linear-gradient(180deg, #fff 0%, #f8fbff 100%); border: 1px solid #dbe4f0; border-radius: 24px; box-shadow: 0 14px 34px rgba(15,23,42,.06); padding: 14px 22px; }
.hero { background: linear-gradient(135deg, #fff7ed 0%, #f8fbff 100%); display: flex; gap: 12px; justify-content: space-between; }
.hero h2 { color: #0f172a; margin: 0; }
.subtitle { color: #475569; margin: 10px 0 0; max-width: 620px; }
.hero-actions { display: flex; gap: 12px; }
.release-hero-title-row { display: flex; align-items: center; gap: 12px; }
.release-hero-title-inline { flex-wrap: wrap; }
.inline-subtitle { margin: 0; max-width: none; font-size: 13px; line-height: 1.45; }
.release-header-icon { width: 42px; height: 42px; border-radius: 14px; display: inline-flex; align-items: center; justify-content: center; font-size: 20px; color: #fff; background: linear-gradient(135deg, #409eff, #36cfc9); box-shadow: 0 10px 20px rgba(64,158,255,.2); }
.docker-header-icon { background: linear-gradient(135deg, #2563eb, #14b8a6); }
.docker-hero { margin-bottom: 16px; }
.release-stats { gap: 16px; }
.docker-top-stats { margin-bottom: 16px; }
.release-stat-card { position: relative; min-height: 76px; background: linear-gradient(145deg, #ffffff 0%, #f6faff 100%); border: 1px solid rgba(148,163,184,.18); box-shadow: 0 16px 34px rgba(15,23,42,.07); text-align: left; padding: 12px 16px; overflow: hidden; width: 100%; color: inherit; }
.release-stat-card::after { content: ''; position: absolute; inset: auto -24px -30px auto; width: 108px; height: 108px; border-radius: 50%; background: radial-gradient(circle, rgba(64,158,255,.16) 0%, rgba(64,158,255,0) 70%); }
.warning-card::after { background: radial-gradient(circle, rgba(245,158,11,.18) 0%, rgba(245,158,11,0) 70%); }
.success-card::after { background: radial-gradient(circle, rgba(16,185,129,.18) 0%, rgba(16,185,129,0) 70%); }
.danger-card::after { background: radial-gradient(circle, rgba(239,68,68,.18) 0%, rgba(239,68,68,0) 70%); }
.release-stat-card .stat-value { font-size: 26px; line-height: 1.05; color: #0f172a; }
.release-stat-card .stat-label { margin-top: 4px; color: #64748b; }
.release-stat-card.context-card { border-color: rgba(148, 163, 184, 0.18); background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%); }
.release-stat-card.context-card::after { background: radial-gradient(circle, rgba(148, 163, 184, 0.16) 0%, rgba(148, 163, 184, 0) 72%); }
.docker-stat-meta { margin-top: 6px; color: #94a3b8; font-size: 12px; }
.docker-alert-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; padding: 10px 12px; border-radius: 12px; background: rgba(248,250,252,.88); border: 1px solid rgba(148,163,184,.18); }
.docker-alert-strip__label { font-size: 12px; font-weight: 700; color: #475569; }
.docker-alert-strip__tag { max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
.alert-popover { display: flex; flex-direction: column; gap: 8px; }
.alert-popover__item { display: flex; gap: 8px; align-items: flex-start; color: #334155; line-height: 1.5; }
.toolbar-shell { margin-bottom: 16px; }
.docker-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  margin-top: 2px;
}

.toolbar-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 12px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
}

.toolbar-filter-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.toolbar-filter-label {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  padding: 5px 10px;
  border-radius: 999px;
  letter-spacing: 0.02em;
  line-height: 1;
  border: 1px solid rgba(203, 213, 225, 0.74);
  background: #f8fafc;
}

.toolbar-filter-pill--env .toolbar-filter-label {
  color: #1d4ed8;
  background: rgba(219, 234, 254, 0.9);
  border-color: rgba(96, 165, 250, 0.28);
}

.toolbar-filter-select {
  width: 180px;
}

:deep(.toolbar-filter-select .el-select__wrapper) {
  min-height: 34px;
  padding-top: 0;
  padding-bottom: 0;
  border-radius: 14px;
  background: #fff;
  box-shadow: none;
  border: 1px solid rgba(203, 213, 225, 0.74);
}

:deep(.toolbar-filter-select .el-select__selected-item) {
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}

:deep(.toolbar-filter-select.is-focus .el-select__wrapper) {
  border-color: rgba(59, 130, 246, 0.42);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.filter-bar--context {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-inline-context {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.filter-inline-context--push {
  margin-left: auto;
}

.filter-inline-label {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  line-height: 1;
}

.filter-inline-select {
  width: 220px;
}

.docker-summary-grid { display: none; }

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
  }

  .hero-actions {
    justify-content: flex-start;
  }

  .docker-toolbar {
    justify-content: flex-start;
  }

  .toolbar-filter-bar {
    width: 100%;
    border-radius: 16px;
  }

  .toolbar-filter-pill {
    width: 100%;
    justify-content: space-between;
  }

  .filter-inline-context {
    width: 100%;
    justify-content: space-between;
  }

  .filter-inline-context--push {
    margin-left: 0;
  }

  .filter-inline-select {
    flex: 1;
    width: auto;
    min-width: 0;
  }

  .toolbar-filter-select {
    flex: 1;
    min-width: 0;
  }
}
</style>
