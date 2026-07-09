<template>
  <div class="fade-in zabbix-datasource-page workbench-page-shell">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="log-header-icon"><el-icon><Monitor /></el-icon></span>
          <h2>Zabbix 数据源</h2>
          <p class="page-inline-desc inline-subtitle">管理 Zabbix 服务器的连接配置，支持 API Token 和用户名/密码两种认证方式。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="fetchItems" :loading="loading">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <ObservabilityRouteTabs group="datasources" />

    <div class="workbench-card log-datasource-card">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <span class="toolbar-title">数据源列表</span>
          <span class="toolbar-desc">配置后可被监控查看、告警接入和 AIOps 智能体工具调用使用。</span>
        </div>
        <div class="workbench-card-actions">
          <el-button v-if="canManage" type="primary" @click="openDialog()">
            <el-icon><Plus /></el-icon>
            新增数据源
          </el-button>
        </div>
      </div>

      <div class="workbench-toolbar workbench-toolbar--history datasource-filter-bar">
        <div class="workbench-toolbar-left">
          <el-input v-model="keyword" size="small" placeholder="搜索名称或 API 地址" clearable style="width: 260px">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>
        <div class="workbench-toolbar-right">
          <span class="toolbar-count">共 {{ filteredItems.length }} 个数据源</span>
        </div>
      </div>

      <el-table :data="filteredItems" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="名称" min-width="200">
          <template #default="{ row }">
            <div class="name-cell">
              <span class="name-text">{{ row.name }}</span>
              <el-tag v-if="row.is_default" size="small" type="warning">默认</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="API 地址" min-width="260">
          <template #default="{ row }">
            <span class="summary-text">{{ row.api_url }}</span>
          </template>
        </el-table-column>
        <el-table-column label="认证方式" width="130">
          <template #default="{ row }">
            <el-tag :type="row.auth_type === 'token' ? 'success' : 'info'" size="small">
              {{ row.auth_type === 'token' ? 'API Token' : '用户名/密码' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="TLS 验证" width="100">
          <template #default="{ row }">
            <el-tag :type="row.tls_verify ? 'success' : 'warning'" size="small">
              {{ row.tls_verify ? '开启' : '关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="超时" width="80">
          <template #default="{ row }">
            <span>{{ row.timeout || 15 }}s</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近同步" width="180">
          <template #default="{ row }">{{ formatTime(row.last_sync_at) }}</template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="success" size="small" @click="handleTest(row)" :loading="testingId === row.id">
              测试连接
            </el-button>
            <el-button link type="primary" size="small" @click="openDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该 Zabbix 数据源吗？关联的设备映射也将失效。" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑 Zabbix 数据源' : '新增 Zabbix 数据源'"
      width="620px"
      top="6vh"
      append-to-body
      destroy-on-close
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="数据源名称">
          <el-input v-model="form.name" placeholder="例如：生产 Zabbix" />
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input v-model="form.api_url" placeholder="https://zabbix.example.com/api_jsonrpc.php" />
        </el-form-item>
        <el-form-item label="认证方式">
          <el-select v-model="form.auth_type" style="width: 100%" @change="onAuthTypeChange">
            <el-option label="API Token (推荐)" value="token" />
            <el-option label="用户名 / 密码" value="userpass" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.auth_type === 'token'" label="API Token">
          <el-input v-model="form.auth_token" show-password :placeholder="editingId ? '已配置，留空则保持不变' : '请输入 Zabbix API Token'" />
        </el-form-item>
        <template v-if="form.auth_type === 'userpass'">
          <el-form-item label="用户名">
            <el-input v-model="form.username" placeholder="Admin" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" show-password :placeholder="editingId ? '已配置，留空则保持不变' : '请输入密码'" />
          </el-form-item>
        </template>
        <div class="switch-row">
          <el-switch v-model="form.is_enabled" active-text="启用" inactive-text="停用" />
          <el-switch v-model="form.is_default" active-text="设为默认" inactive-text="普通数据源" />
          <el-switch v-model="form.tls_verify" active-text="TLS 验证" inactive-text="跳过 TLS" />
        </div>
        <el-form-item label="超时 (秒)">
          <el-input-number v-model="form.timeout" :min="5" :max="60" style="width: 180px" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Monitor, Plus, RefreshRight, Search } from '@element-plus/icons-vue'
import {
  createZabbixDataSource,
  deleteZabbixDataSource,
  getZabbixDataSources,
  testZabbixConnection,
  updateZabbixDataSource,
} from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const testingId = ref(null)
const dialogVisible = ref(false)
const editingId = ref(null)
const keyword = ref('')
const items = ref([])
const form = ref(createEmptyForm())

function createEmptyForm() {
  return {
    name: '',
    api_url: '',
    auth_type: 'token',
    auth_token: '',
    username: '',
    password: '',
    tls_verify: true,
    timeout: 15,
    is_enabled: true,
    is_default: false,
  }
}

const filteredItems = computed(() => {
  if (!keyword.value) return items.value
  const kw = keyword.value.toLowerCase()
  return items.value.filter((item) => {
    return (item.name || '').toLowerCase().includes(kw)
      || (item.api_url || '').toLowerCase().includes(kw)
  })
})

const canManage = computed(() => authStore.hasPermission('ops.zabbix.datasource.manage'))

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function onAuthTypeChange() {
  if (form.value.auth_type === 'token') {
    form.value.username = ''
    form.value.password = ''
  } else {
    form.value.auth_token = ''
  }
}

async function fetchItems() {
  loading.value = true
  try {
    const resp = await getZabbixDataSources()
    items.value = Array.isArray(resp) ? resp : (resp?.results || resp?.data || [])
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  if (row) {
    editingId.value = row.id
    form.value = {
      name: row.name,
      api_url: row.api_url,
      auth_type: row.auth_type,
      auth_token: '',
      username: '',
      password: '',
      tls_verify: row.tls_verify,
      timeout: row.timeout || 15,
      is_enabled: row.is_enabled,
      is_default: row.is_default,
    }
  } else {
    editingId.value = null
    form.value = createEmptyForm()
  }
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.value.name) return ElMessage.warning('请填写数据源名称')
  if (!form.value.api_url) return ElMessage.warning('请填写 API 地址')
  if (form.value.auth_type === 'userpass' && !editingId.value) {
    if (!form.value.username) return ElMessage.warning('请填写用户名')
    if (!form.value.password) return ElMessage.warning('请填写密码')
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name,
      api_url: form.value.api_url,
      auth_type: form.value.auth_type,
      tls_verify: form.value.tls_verify,
      timeout: form.value.timeout,
      is_enabled: form.value.is_enabled,
      is_default: form.value.is_default,
    }
    if (form.value.auth_token) payload.auth_token = form.value.auth_token
    if (form.value.username) payload.username = form.value.username
    if (form.value.password) payload.password = form.value.password

    if (editingId.value) {
      // Only send credential fields if the user entered new values
      const updatePayload = { ...payload }
      if (!form.value.auth_token && !form.value.username && !form.value.password) {
        delete updatePayload.auth_token
        delete updatePayload.username
        delete updatePayload.password
      }
      await updateZabbixDataSource(editingId.value, updatePayload)
      ElMessage.success('Zabbix 数据源已更新')
    } else {
      await createZabbixDataSource(payload)
      ElMessage.success('Zabbix 数据源已创建')
    }
    dialogVisible.value = false
    await fetchItems()
  } finally {
    saving.value = false
  }
}

async function handleDelete(id) {
  await deleteZabbixDataSource(id)
  ElMessage.success('Zabbix 数据源已删除')
  await fetchItems()
}

async function handleTest(row) {
  testingId.value = row.id
  try {
    const resp = await testZabbixConnection(row.id)
    if (resp.status === 'success') {
      ElMessage.success(`Zabbix API 连接正常，版本：${resp.version || '--'}`)
    } else {
      ElMessage.error(resp.message || '连接测试失败')
    }
  } catch {
    ElMessage.error('连接测试请求失败')
  } finally {
    testingId.value = null
  }
}

onMounted(() => { fetchItems() })
</script>

<style scoped>
.zabbix-datasource-page {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hero.panel {
  align-items: center;
  background: linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%);
  border: 1px solid rgba(36, 91, 219, 0.09);
  border-radius: 20px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding: 14px 16px;
}

.release-hero-title-row {
  align-items: center;
  display: flex;
  gap: 12px;
  min-width: 0;
}

.hero h2 {
  color: #0f172a;
  font-size: 23px;
  line-height: 1.1;
  margin: 0;
}

.log-header-icon {
  align-items: center;
  background: linear-gradient(180deg, #f3f7ff 0%, #ebf2ff 100%);
  border: 1px solid rgba(36, 91, 219, 0.12);
  border-radius: 14px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
  color: #245bdb;
  display: inline-flex;
  flex: 0 0 42px;
  font-size: 20px;
  height: 42px;
  justify-content: center;
  width: 42px;
}

.page-inline-desc {
  color: #475569;
  flex: 0 1 auto;
  font-size: 13px;
  line-height: 1.45;
  margin: 0;
  transform: translateY(1px);
}

.inline-subtitle { max-width: none; }

.hero-actions {
  align-items: center;
  display: flex;
  gap: 8px;
}

.hero-actions :deep(.el-button) {
  border-radius: 10px;
  font-weight: 500;
  min-height: 32px;
  padding: 0 14px;
}

.log-datasource-card { padding: 14px; }

.datasource-filter-bar { margin-bottom: 8px; }

.toolbar-count {
  color: #64748b;
  font-size: 12px;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.name-text { font-weight: 700; }

.summary-text {
  color: var(--text-secondary);
  font-size: 13px;
  word-break: break-word;
}

.switch-row {
  display: flex;
  gap: 24px;
  margin-bottom: 18px;
  padding-left: 100px;
}

@media (max-width: 960px) {
  .switch-row { flex-direction: column; gap: 12px; padding-left: 0; }
}
</style>
