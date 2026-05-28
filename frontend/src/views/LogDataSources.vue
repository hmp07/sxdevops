<template>
  <div class="fade-in log-datasource-page">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="log-header-icon"><el-icon><DataBoard /></el-icon></span>
          <h2>日志中心</h2>
          <p class="page-desc inline-subtitle">{{ activeLogTab.description }}</p>
        </div>
      </div>
    </section>

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

    <div class="table-card">
      <div class="table-head">
        <div class="filter-bar">
          <el-input v-model="keyword" placeholder="搜索名称或描述" clearable style="width: 260px">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="providerFilter" clearable placeholder="全部类型" style="width: 180px">
            <el-option v-for="provider in providers" :key="provider.id" :label="providerLabel(provider.id)" :value="provider.id" />
          </el-select>
          <el-switch v-model="enabledOnly" active-text="仅看启用" inactive-text="全部状态" />
        </div>
        <el-button v-if="canManageLogDataSources" type="primary" @click="openDialog()">
          <el-icon><Plus /></el-icon>
          新增数据源
        </el-button>
      </div>

      <el-table :data="filteredItems" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="名称" min-width="220">
          <template #default="{ row }">
            <div class="name-cell">
              <span class="name-text">{{ row.name }}</span>
              <el-tag v-if="row.is_default" size="small" type="warning">默认</el-tag>
            </div>
            <div class="sub-text">{{ row.description || '未填写描述' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="180">
          <template #default="{ row }">
            <el-tag :type="providerTagType(row.provider)">{{ providerLabel(row.provider) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连接摘要" min-width="280">
          <template #default="{ row }">
            <div class="summary-text">{{ formatSummary(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column v-if="canManageLogDataSources" label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="success" size="small" @click="handleTest(row)" :loading="testingId === row.id">测试连接</el-button>
            <el-button link type="primary" size="small" @click="openDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该日志数据源吗？" @confirm="handleDelete(row.id)">
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
      :title="editingId ? '编辑日志数据源' : '新增日志数据源'"
      width="720px"
      top="6vh"
      append-to-body
      destroy-on-close
    >
      <el-form :model="form" label-width="110px">
        <el-form-item label="数据源名称">
          <el-input v-model="form.name" placeholder="例如：生产 ELK" />
        </el-form-item>
        <el-form-item label="日志类型">
          <el-select v-model="form.provider" style="width: 100%" @change="onProviderChange">
            <el-option v-for="provider in providers" :key="provider.id" :label="providerLabel(provider.id)" :value="provider.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="说明该数据源的用途，例如生产业务日志" />
        </el-form-item>
        <div class="switch-row">
          <el-switch v-model="form.is_enabled" active-text="启用" inactive-text="停用" />
          <el-switch v-model="form.is_default" active-text="设为默认" inactive-text="普通数据源" />
        </div>

        <template v-if="form.provider === 'loki'">
          <el-form-item label="Loki 地址">
            <el-input v-model="form.config.endpoint" placeholder="http://localhost:3100" />
          </el-form-item>
        </template>

        <template v-else-if="form.provider === 'elk'">
          <el-form-item label="ES 地址">
            <el-input v-model="form.config.endpoint" placeholder="https://es.example.com:9200" />
          </el-form-item>
          <el-form-item label="认证方式">
            <el-select v-model="form.config.auth_type" style="width: 100%">
              <el-option label="无认证" value="none" />
              <el-option label="Basic Auth" value="basic" />
              <el-option label="API Key" value="api_key" />
              <el-option label="Bearer Token" value="bearer" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="form.config.auth_type === 'basic'" label="用户名">
            <el-input v-model="form.config.username" placeholder="elastic" />
          </el-form-item>
          <el-form-item v-if="form.config.auth_type === 'basic'" label="密码">
            <el-input v-model="form.config.password" show-password :placeholder="secretPlaceholder('password')" />
          </el-form-item>
          <el-form-item v-if="form.config.auth_type === 'api_key'" label="API Key">
            <el-input v-model="form.config.api_key" show-password :placeholder="secretPlaceholder('api_key')" />
          </el-form-item>
          <el-form-item v-if="form.config.auth_type === 'bearer'" label="Bearer Token">
            <el-input v-model="form.config.bearer_token" show-password :placeholder="secretPlaceholder('bearer_token')" />
          </el-form-item>
          <el-form-item label="索引模式">
            <el-input v-model="form.config.index_pattern" placeholder="logs-*" />
          </el-form-item>
          <el-form-item label="时间字段">
            <el-input v-model="form.config.time_field" placeholder="@timestamp" />
          </el-form-item>
          <el-form-item label="消息字段">
            <el-input v-model="form.config.message_fields" placeholder="message,log,msg" />
          </el-form-item>
        </template>

        <template v-else-if="form.provider === 'sls'">
          <el-form-item label="SLS Endpoint">
            <el-input v-model="form.config.endpoint" placeholder="cn-hangzhou.log.aliyuncs.com" />
          </el-form-item>
          <el-form-item label="Project">
            <el-input v-model="form.config.project" placeholder="project-name" />
          </el-form-item>
          <el-form-item label="Logstore">
            <el-input v-model="form.config.logstore" placeholder="app-logstore" />
          </el-form-item>
          <el-form-item label="Topic">
            <el-input v-model="form.config.topic" placeholder="可选" />
          </el-form-item>
          <el-form-item label="AccessKey ID">
            <el-input v-model="form.config.access_key_id" :placeholder="secretPlaceholder('access_key_id')" />
          </el-form-item>
          <el-form-item label="AccessKey Secret">
            <el-input v-model="form.config.access_key_secret" show-password :placeholder="secretPlaceholder('access_key_secret')" />
          </el-form-item>
        </template>
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
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createLogDataSource,
  deleteLogDataSource,
  getLogDataSources,
  getLogProviders,
  testLogDataSource,
  updateLogDataSource,
} from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
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
const loading = ref(false)
const saving = ref(false)
const testingId = ref(null)
const dialogVisible = ref(false)
const editingId = ref(null)
const keyword = ref('')
const providerFilter = ref('')
const enabledOnly = ref(true)
const items = ref([])
const providers = ref([])
const providerDefaults = ref({})
const secretFlags = ref({})
const form = ref(createEmptyForm())

function createEmptyForm(provider = 'loki') {
  return {
    name: '',
    provider,
    description: '',
    is_enabled: true,
    is_default: false,
    config: getProviderDefaults(provider),
  }
}

function getProviderDefaults(provider) {
  const defaults = providerDefaults.value[provider] || {}
  const config = {}
  Object.entries(defaults).forEach(([key, value]) => {
    if (value !== 'configured') config[key] = value
  })
  if (provider === 'elk') {
    config.auth_type = config.auth_type || 'none'
    config.index_pattern = config.index_pattern || 'logs-*'
    config.time_field = config.time_field || '@timestamp'
    config.message_fields = config.message_fields || 'message,log,msg'
  }
  return config
}

const filteredItems = computed(() => {
  return items.value.filter((item) => {
    if (providerFilter.value && item.provider !== providerFilter.value) return false
    if (enabledOnly.value && !item.is_enabled) return false
    if (!keyword.value) return true
    const text = `${item.name} ${item.description || ''}`.toLowerCase()
    return text.includes(keyword.value.toLowerCase())
  })
})
const canManageLogDataSources = computed(() => authStore.hasPermission('ops.log.datasource.manage'))

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

function formatSummary(row) {
  const config = row.config || {}
  if (row.provider === 'loki') return config.endpoint || '未配置 Loki 地址'
  if (row.provider === 'elk') {
    return [config.endpoint, config.index_pattern && `索引 ${config.index_pattern}`].filter(Boolean).join(' / ') || '未配置 ELK 连接'
  }
  return [config.project && `项目 ${config.project}`, config.logstore && `日志库 ${config.logstore}`, config.endpoint].filter(Boolean).join(' / ') || '未配置 SLS 连接'
}

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function secretPlaceholder(key) {
  return secretFlags.value[key] ? '已配置，留空则保持不变' : '请输入敏感信息'
}

async function fetchProviders() {
  const response = await getLogProviders()
  providers.value = response.providers || []
  const defaults = {}
  providers.value.forEach((provider) => {
    defaults[provider.id] = provider.defaults || {}
  })
  providerDefaults.value = defaults
}

async function fetchDataSources() {
  loading.value = true
  try {
    const response = await getLogDataSources()
    items.value = Array.isArray(response) ? response : response.results || []
  } finally {
    loading.value = false
  }
}

function onProviderChange(provider) {
  form.value.config = {
    ...getProviderDefaults(provider),
    ...form.value.config,
  }
  if (provider !== 'elk') {
    delete form.value.config.username
    delete form.value.config.password
    delete form.value.config.api_key
    delete form.value.config.bearer_token
  }
}

function openDialog(row) {
  if (row) {
    editingId.value = row.id
    const config = { ...(row.config || {}) }
    secretFlags.value = {
      password: config.password === 'configured',
      api_key: config.api_key === 'configured',
      bearer_token: config.bearer_token === 'configured',
      access_key_id: config.access_key_id === 'configured',
      access_key_secret: config.access_key_secret === 'configured',
    }
    Object.keys(secretFlags.value).forEach((key) => {
      if (secretFlags.value[key]) config[key] = ''
    })
    form.value = {
      id: row.id,
      name: row.name,
      provider: row.provider,
      description: row.description,
      is_enabled: row.is_enabled,
      is_default: row.is_default,
      config,
    }
  } else {
    editingId.value = null
    secretFlags.value = {}
    form.value = createEmptyForm(providers.value[0]?.id || 'loki')
  }
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.value.name) return ElMessage.warning('请填写数据源名称')
  saving.value = true
  try {
    const payload = {
      name: form.value.name,
      provider: form.value.provider,
      description: form.value.description,
      is_enabled: form.value.is_enabled,
      is_default: form.value.is_default,
      config: form.value.config,
    }
    if (editingId.value) {
      await updateLogDataSource(editingId.value, payload)
      ElMessage.success('日志数据源已更新')
    } else {
      await createLogDataSource(payload)
      ElMessage.success('日志数据源已创建')
    }
    dialogVisible.value = false
    await fetchDataSources()
  } finally {
    saving.value = false
  }
}

async function handleDelete(id) {
  await deleteLogDataSource(id)
  ElMessage.success('日志数据源已删除')
  await fetchDataSources()
}

async function handleTest(row) {
  testingId.value = row.id
  try {
    const response = await testLogDataSource(row.id)
    if (response.success) ElMessage.success(`${response.message}，发现 ${response.preview_count || 0} 条目录项`)
    else ElMessage.error(response.message || '连接测试失败')
  } finally {
    testingId.value = null
  }
}

function switchLogTab(path) {
  if (route.path !== path) router.push(path)
}

onMounted(async () => {
  await fetchProviders()
  await fetchDataSources()
})
</script>

<style scoped>
.log-datasource-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.panel {
  background: linear-gradient(135deg, rgba(239,246,255,.96) 0%, rgba(236,254,255,.94) 52%, rgba(248,250,252,.98) 100%);
  border: 1px solid rgba(96,165,250,.18);
  border-radius: 24px;
  box-shadow: 0 16px 36px rgba(14,165,233,.08);
  padding: 12px 14px;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.log-center-tabs {
  margin-bottom: 0;
  padding: 6px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.9));
  border: 1px solid rgba(148,163,184,.16);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.release-hero-title-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.release-hero-title-inline {
  flex-wrap: wrap;
}

.hero h2 {
  margin: 0;
  color: #0f172a;
  font-size: 23px;
  line-height: 1.1;
}


.log-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #fff;
  background: linear-gradient(135deg, #0ea5e9, #2563eb);
  box-shadow: 0 10px 20px rgba(37,99,235,.2);
}

.page-desc {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}

.inline-subtitle {
  max-width: none;
}

.log-center-tabs .neo-tab-btn {
  padding: 10px 24px;
  border-radius: 8px;
}

.log-center-tabs.theme-blue .neo-tab-btn.active {
  color: #245bdb !important;
  background: rgba(51, 112, 255, 0.1) !important;
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.08) !important;
}

.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.filter-bar {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 0;
}

.table-card {
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.92));
  box-shadow: 0 18px 36px rgba(15,23,42,.06);
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.name-text {
  font-weight: 700;
}

.disabled {
  opacity: 0.55;
  pointer-events: none;
}

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
    align-items: stretch;
  }
}

.sub-text,
.summary-text {
  color: var(--text-secondary);
  font-size: 12px;
  margin-top: 6px;
  word-break: break-word;
}

.switch-row {
  display: flex;
  gap: 24px;
  margin-bottom: 18px;
  padding-left: 110px;
}

@media (max-width: 960px) {
  .page-title-row { align-items: flex-start; }
  .switch-row { flex-direction: column; gap: 12px; padding-left: 0; }
}

.hero.panel { border-radius: 20px; }
</style>

