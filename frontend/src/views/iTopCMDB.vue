<template>
  <div class="itop-cmdb">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Connection /></el-icon></span>
          <h2>CMDB 数据源</h2>
          <p class="page-inline-desc">管理 CMDB 外部数据源，同步配置项、关联关系与工单数据</p>
        </div>
      </div>
    </section>

    <div class="info-banner">
      <el-icon :size="18"><InfoFilled /></el-icon>
      <span>iTop 集成采用双通道架构：<strong>同步引擎</strong>将 CMDB/工单批量导入本地，供拓扑和事件墙使用；<strong>MCP Server</strong>（在 AIOps 配置 → MCP 中管理）为 Agent 提供实时查询能力。</span>
    </div>

    <ObservabilityRouteTabs group="cmdb" />

    <!-- 数据源配置 -->
    <section class="panel">
      <div style="margin-bottom: 12px; display: flex; justify-content: flex-end">
        <el-button size="small" type="primary" @click="openDsDialog()">新增数据源</el-button>
      </div>
      <el-table :data="dataSources" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="api_url" label="API 地址" min-width="220" />
        <el-table-column prop="api_version" label="版本" width="70" />
        <el-table-column prop="organization" label="组织" width="120" />
        <el-table-column prop="sync_mode" label="同步模式" width="90" />
        <el-table-column prop="sync_status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.sync_status === 'ok' ? 'success' : row.sync_status === 'running' ? 'warning' : 'info'" size="small">
              {{ row.sync_status === 'ok' ? '正常' : row.sync_status === 'running' ? '同步中' : row.sync_status || '空闲' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上次同步" width="170">
          <template #default="{ row }">{{ row.last_sync_at || '--' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="testConnection(row)">测试</el-button>
            <el-button link type="primary" size="small" @click="triggerSync(row)">同步</el-button>
            <el-button link type="primary" size="small" @click="openDsDialog(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="deleteDs(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 数据源对话框 -->
    <el-dialog v-model="dsVisible" :title="editingDs ? '编辑数据源' : '新增数据源'" width="560px">
      <el-form :model="dsForm" label-width="100px">
        <el-form-item label="名称"><el-input v-model="dsForm.name" /></el-form-item>
        <el-form-item label="API 地址"><el-input v-model="dsForm.api_url" placeholder="http://itop.example.com/webservices/rest.php" /></el-form-item>
        <el-form-item label="API 版本"><el-input v-model="dsForm.api_version" placeholder="1.4" /></el-form-item>
        <el-form-item label="用户名"><el-input v-model="dsForm.auth_user" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="dsForm.auth_password" type="password" /></el-form-item>
        <el-form-item label="组织"><el-input v-model="dsForm.organization" /></el-form-item>
        <el-form-item label="同步模式">
          <el-select v-model="dsForm.sync_mode"><el-option label="全量" value="full" /><el-option label="增量" value="incremental" /></el-select>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="dsForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dsVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDs" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import {
  getITopDataSources, createITopDataSource, updateITopDataSource,
  deleteITopDataSource, testITopConnection, triggerITopSync,
} from '@/api/modules/cmdb'

const loading = ref(false)
const saving = ref(false)
const dataSources = ref([])
const dsVisible = ref(false)
const editingDs = ref(null)
const dsForm = reactive({ name: '', api_url: '', api_version: '1.4', auth_user: '', auth_password: '',
  organization: '', sync_mode: 'full', is_enabled: true })

async function loadDataSources() {
  loading.value = true
  try {
    const resp = await getITopDataSources()
    const list = resp?.results || resp?.data || resp || []
    dataSources.value = Array.isArray(list) ? list : (list.results || [])
  } catch { /* ignore */ } finally { loading.value = false }
}

function openDsDialog(row) {
  editingDs.value = row || null
  if (row) {
    Object.assign(dsForm, { name: row.name, api_url: row.api_url, api_version: row.api_version || '1.4',
      auth_user: row.auth_user, auth_password: '', organization: row.organization || '',
      sync_mode: row.sync_mode || 'full', is_enabled: row.is_enabled !== false })
  } else {
    Object.assign(dsForm, { name: '', api_url: '', api_version: '1.4', auth_user: '', auth_password: '',
      organization: '', sync_mode: 'full', is_enabled: true })
  }
  dsVisible.value = true
}

async function saveDs() {
  saving.value = true
  try {
    const payload = { ...dsForm }
    if (!payload.auth_password) delete payload.auth_password
    if (editingDs.value) {
      await updateITopDataSource(editingDs.value.id, payload)
      ElMessage.success('数据源已更新')
    } else {
      await createITopDataSource(payload)
      ElMessage.success('数据源已创建')
    }
    dsVisible.value = false
    await loadDataSources()
  } catch { /* error handled by interceptor */ } finally { saving.value = false }
}

async function testConnection(row) {
  try {
    await testITopConnection(row.id)
    ElMessage.success('连接测试成功')
  } catch { /* */ }
}

async function triggerSync(row) {
  try {
    await triggerITopSync(row.id)
    ElMessage.success('同步已触发')
    await loadDataSources()
  } catch { /* */ }
}

async function deleteDs(row) {
  try {
    await ElMessageBox.confirm(`确定删除数据源 "${row.name}"？`, '确认删除', { type: 'warning' })
    await deleteITopDataSource(row.id)
    ElMessage.success('已删除')
    await loadDataSources()
  } catch { /* cancelled */ }
}

onMounted(() => { loadDataSources() })
</script>
