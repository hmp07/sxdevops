<template>
  <div class="fade-in">
    <!-- Header -->
    <div class="page-header">
      <h2><el-icon style="vertical-align: middle; margin-right: 8px;"><Location /></el-icon>Nginx 管理</h2>
      <div class="k8s-toolbar" v-if="activeTab === 'domains'">
        <div class="cluster-selector-group">
          <span class="toolbar-label"><el-icon><Monitor /></el-icon> 当前环境</span>
          <el-select v-model="filterEnvId" placeholder="选择环境" @change="onEnvChange" style="width: 160px" class="industrial-select" popper-class="industrial-popper">
            <el-option v-for="e in envs" :key="e.id" :label="e.name" :value="e.id">
              <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                <span class="state-pulse" :class="e.status==='connected'?'running':'exited'"></span> {{ e.name }}
              </div>
            </el-option>
          </el-select>
        </div>
      </div>
      <div class="k8s-toolbar" v-if="activeTab === 'routes'">
        <div class="cluster-selector-group">
          <span class="toolbar-label"><el-icon><Monitor /></el-icon> 环境</span>
          <el-select v-model="filterEnvId" placeholder="选择环境" @change="onEnvChange" style="width: 140px" class="industrial-select" popper-class="industrial-popper">
            <el-option v-for="e in envs" :key="e.id" :label="e.name" :value="e.id">
              <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                <span class="state-pulse" :class="e.status==='connected'?'running':'exited'"></span> {{ e.name }}
              </div>
            </el-option>
          </el-select>
        </div>
        <div class="cluster-selector-group" v-if="filterEnvId">
          <span class="toolbar-label"><el-icon><Connection /></el-icon> 域名</span>
          <el-select v-model="filterDomainId" placeholder="选择域名" @change="onDomainChange" style="width: 180px" class="industrial-select" popper-class="industrial-popper">
            <el-option v-for="d in filteredDomains" :key="d.id" :label="`${d.domain}:${d.listen_port}`" :value="d.id" />
          </el-select>
        </div>
      </div>
    </div>

    <!-- 主 Tab 栏 -->
    <div class="k8s-main-tabs">
      <button v-for="tab in mainTabs" :key="tab.key" class="k8s-tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <!-- ============ 环境管理 ============ -->
    <div v-if="activeTab === 'envs'" class="tab-content">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <el-button type="primary" size="small" @click="openEnvDialog()"><el-icon><Plus /></el-icon> 添加环境</el-button>
      </div>
      <el-table :data="envs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="环境名称" min-width="140">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='connected'?'running':row.status==='error'?'danger':'exited'"></span>
              <span style="font-weight:600;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="ip_address" label="IP 地址" min-width="140">
          <template #default="{ row }">{{ row.ip_address }}:{{ row.ssh_port }}</template>
        </el-table-column>
        <el-table-column prop="nginx_path" label="Nginx 路径" min-width="160" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status==='connected'?'success':row.status==='error'?'danger':'info'" size="small">
              {{ row.status==='connected'?'已连接':row.status==='error'?'异常':'未连接' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="testEnv(row.id)">测试连接</el-button>
            <el-button link type="info" size="small" @click="openEnvDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该环境？" @confirm="delEnv(row.id)">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 域名管理 ============ -->
    <div v-if="activeTab === 'domains'" class="tab-content">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <el-button type="primary" size="small" @click="openDomainDialog()" :disabled="!filterEnvId"><el-icon><Plus /></el-icon> 添加域名</el-button>
      </div>
      <el-table :data="filteredDomains" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="domain" label="域名/IP" min-width="180">
          <template #default="{ row }">
            <div style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.domain }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="listen_port" label="端口" width="80">
          <template #default="{ row }">
            <span style="color:#0ea5e9; font-weight:600">{{ row.listen_port }}</span>
          </template>
        </el-table-column>
        <el-table-column label="SSL" width="90">
          <template #default="{ row }">
            <el-tag :type="row.ssl_enabled?'success':'info'" size="small">{{ row.ssl_enabled ? `✓ :${row.ssl_port}` : '关闭' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled?'success':'info'" size="small">{{ row.enabled?'启用':'禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="cert_path" label="证书路径" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <code v-if="row.cert_path" style="font-size:12px;color:#64748b;">{{ row.cert_path }}</code>
            <span v-else style="color:#cbd5e1;font-size:12px;">未部署</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button link type="info" size="small" @click="openDomainDialog(row)">编辑</el-button>
            <el-button link type="primary" size="small" @click="handleToggleSSL(row)">{{ row.ssl_enabled ? '关闭SSL' : '开启SSL' }}</el-button>
            <el-button link type="warning" size="small" @click="handlePreviewConf(row)">预览</el-button>
            <el-button link type="success" size="small" @click="handleDeployConf(row)">发布配置</el-button>
            <el-popconfirm title="确定删除该域名？" @confirm="delDomain(row.id)">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 路由配置 ============ -->
    <div v-if="activeTab === 'routes'" class="tab-content">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <el-alert title="提示：配置完路由后，请到【域名管理】选择对应域名【预览】并确认，无误后点击【发布配置】生效" type="info" :closable="false" show-icon style="padding:4px 12px; width:auto; background:var(--bg-main);" />
        <el-button type="primary" size="small" @click="openRouteDialog()" :disabled="!filterDomainId"><el-icon><Plus /></el-icon> 添加路由</el-button>
      </div>
      <div v-if="!filterEnvId || !filterDomainId" style="text-align:center;padding:40px;color:#94a3b8;">
        请先在右上角选择<strong>环境</strong>和<strong>域名</strong>
      </div>
      <el-table v-else :data="routes" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="location" label="Location" min-width="120">
          <template #default="{ row }">
            <code style="font-weight:600;font-size:13px;">{{ row.location }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="upstream_servers" label="后端地址" min-width="220">
          <template #default="{ row }">
            <div v-for="(s, i) in (row.upstream_servers||'').split('\n').filter(Boolean)" :key="i">
              <code style="font-size:12px;background:#f1f5f9;padding:1px 6px;border-radius:3px;">{{ s }}</code>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="重定向" min-width="150">
          <template #default="{ row }">
            <span v-if="row.redirect_url" style="font-size:12px;color:#f59e0b;">{{ row.redirect_code }} → {{ row.redirect_url }}</span>
            <span v-else style="color:#cbd5e1;font-size:12px;">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="启用" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled?'success':'info'" size="small">{{ row.enabled?'是':'否' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="info" size="small" @click="openRouteDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该路由？" @confirm="delRoute(row.id)">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ========== MODALS ========== -->

    <!-- 环境弹窗 -->
    <el-dialog v-model="envDialog" :title="envForm.id ? '编辑 Nginx 环境' : '添加 Nginx 环境'" width="90%" style="max-width:600px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="envForm" label-width="110px">
        <el-form-item label="环境名称" required><el-input v-model="envForm.name" placeholder="例如 web-prod-01" /></el-form-item>
        <el-form-item label="IP 地址" required><el-input v-model="envForm.ip_address" placeholder="192.168.1.100" /></el-form-item>
        <div style="display:flex; gap:10px;">
          <el-form-item label="SSH 端口" style="flex:1"><el-input v-model="envForm.ssh_port" type="number" /></el-form-item>
          <el-form-item label="SSH 用户" style="flex:1" label-width="80px"><el-input v-model="envForm.ssh_user" /></el-form-item>
        </div>
        <el-form-item label="SSH 密码"><el-input v-model="envForm.ssh_password" type="password" placeholder="留空则不修改" show-password /></el-form-item>
        <el-form-item label="Nginx 路径"><el-input v-model="envForm.nginx_path" placeholder="/etc/nginx" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="envForm.description" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="envDialog = false">取消</el-button>
        <el-button type="primary" @click="saveEnv" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 域名弹窗 -->
    <el-dialog v-model="domainDialog" :title="domainForm.id ? '编辑域名' : '添加域名'" width="90%" style="max-width:650px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="domainForm" label-width="110px">
        <el-alert title="没有域名也可以直接填写 IP 地址" type="info" :closable="false" style="margin-bottom:16px;" />
        <el-form-item label="域名/IP" required><el-input v-model="domainForm.domain" placeholder="example.com 或 192.168.1.100" /></el-form-item>
        <div style="display:flex; gap:10px;">
          <el-form-item label="HTTP 端口" style="flex:1"><el-input v-model.number="domainForm.listen_port" type="number" /></el-form-item>
          <el-form-item label="SSL 端口" style="flex:1" label-width="80px"><el-input v-model.number="domainForm.ssl_port" type="number" /></el-form-item>
        </div>
        <el-form-item label="是否启用此域名">
          <el-switch v-model="domainForm.enabled" />
        </el-form-item>
        <el-divider content-position="left">SSL 证书（可选）</el-divider>
        <el-form-item label="证书 (PEM)">
          <el-input v-model="domainForm.cert_content" type="textarea" :rows="4" placeholder="粘贴 PEM 证书内容（-----BEGIN CERTIFICATE-----）" />
        </el-form-item>
        <el-form-item label="私钥 (KEY)">
          <el-input v-model="domainForm.key_content" type="textarea" :rows="4" placeholder="粘贴私钥内容（-----BEGIN PRIVATE KEY-----）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="domainDialog = false">取消</el-button>
        <el-button type="primary" @click="saveDomain" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 路由弹窗 -->
    <el-dialog v-model="routeDialog" :title="routeForm.id ? '编辑路由' : '添加路由'" width="90%" style="max-width:700px;" top="3vh" append-to-body destroy-on-close>
      <el-form :model="routeForm" label-width="130px">
        <el-divider content-position="left">基础信息（必填）</el-divider>
        <el-form-item label="Location 路径" required><el-input v-model="routeForm.location" placeholder="/" /></el-form-item>
        <el-form-item label="后端地址" required>
          <el-input v-model="routeForm.upstream_servers" type="textarea" :rows="3" placeholder="每行一个后端地址，如：&#10;http://127.0.0.1:8080&#10;http://127.0.0.1:8081" />
          <div style="font-size:12px;color:#94a3b8;margin-top:4px;">多个地址会自动生成 upstream 负载均衡配置</div>
        </el-form-item>
        <el-form-item label="是否启用此路由">
          <el-switch v-model="routeForm.enabled" />
        </el-form-item>

        <el-divider content-position="left">高级配置（可选）</el-divider>
        <el-form-item label="重定向地址">
          <el-input v-model="routeForm.redirect_url" placeholder="https://example.com（留空则不重定向）" />
        </el-form-item>
        <el-form-item label="重定向状态码" v-if="routeForm.redirect_url">
          <el-radio-group v-model="routeForm.redirect_code">
            <el-radio :value="301">301 永久</el-radio>
            <el-radio :value="302">302 临时</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="自定义 Header">
          <el-input v-model="routeForm.custom_headers" type="textarea" :rows="2" placeholder='[{"name":"X-Custom","value":"val"}]' />
          <div style="font-size:12px;color:#94a3b8;margin-top:4px;">JSON 数组格式，用于 add_header 指令</div>
        </el-form-item>
        <el-form-item label="proxy_set_header">
          <el-input v-model="routeForm.proxy_set_headers" type="textarea" :rows="2" placeholder='[{"name":"Host","value":"$host"}]' />
          <div style="font-size:12px;color:#94a3b8;margin-top:4px;">JSON 数组格式，覆盖默认的 proxy_set_header</div>
        </el-form-item>
        <el-form-item label="上传大小限制">
          <el-input v-model="routeForm.client_max_body_size" placeholder="10m" style="width:120px" />
        </el-form-item>
        <el-form-item label="额外指令">
          <el-input v-model="routeForm.extra_directives" type="textarea" :rows="3" placeholder="原始 Nginx 指令，每行一条，如：&#10;proxy_connect_timeout 60s&#10;proxy_read_timeout 120s" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="routeDialog = false">取消</el-button>
        <el-button type="primary" @click="saveRoute" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 配置预览弹窗 -->
    <el-dialog v-model="previewDialog" title="Nginx 配置预览" width="90%" style="max-width:750px;" top="5vh" append-to-body>
      <div class="yaml-viewer-toolbar">
        <span class="yaml-viewer-badge">{{ previewFilename }}</span>
        <el-button size="small" @click="copyConf">复制</el-button>
      </div>
      <div class="yaml-viewer-container">
        <pre class="yaml-viewer-code"><code>{{ previewContent }}</code></pre>
      </div>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Location, Connection, Plus, Monitor, Lock, FolderOpened } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import {
  getNginxEnvironments, createNginxEnvironment, updateNginxEnvironment, deleteNginxEnvironment, testNginxConnection,
  getNginxDomains, createNginxDomain, updateNginxDomain, deleteNginxDomain, toggleDomainSSL, deployDomainConf, previewDomainConf,
  getNginxRoutes, createNginxRoute, updateNginxRoute, deleteNginxRoute
} from '@/api/modules/nginx'

const mainTabs = [
  { key: 'envs', label: '环境管理', icon: 'Monitor' },
  { key: 'domains', label: '域名管理', icon: 'Connection' },
  { key: 'routes', label: '路由配置', icon: 'FolderOpened' }
]

const activeTab = ref('envs')
const loading = ref(false)
const saving = ref(false)

const envs = ref([])
const domains = ref([])
const routes = ref([])
const filterEnvId = ref(localStorage.getItem('lastNginxEnvId') ? Number(localStorage.getItem('lastNginxEnvId')) : '')
const filterDomainId = ref(localStorage.getItem('lastNginxDomainId') ? Number(localStorage.getItem('lastNginxDomainId')) : '')

const filteredDomains = computed(() => {
  if (!filterEnvId.value) return []
  return domains.value.filter(d => d.environment === filterEnvId.value)
})

// DIALOGS
const envDialog = ref(false)
const domainDialog = ref(false)
const routeDialog = ref(false)
const previewDialog = ref(false)

const envForm = ref({})
const domainForm = ref({})
const routeForm = ref({})
const previewContent = ref('')
const previewFilename = ref('')

function formatDate(ds) {
  if (!ds) return '-'
  return dayjs(ds).format('YYYY-MM-DD HH:mm:ss')
}

// ====== DATA FETCH ======
async function fetchEnvs() {
  loading.value = true
  try {
    const res = await getNginxEnvironments()
    envs.value = res.results || res
    
    // 如果没有选中的环境，或者之前选中的环境不复存在，则默认选择第一个
    if (envs.value.length > 0 && !envs.value.some(e => e.id === filterEnvId.value)) {
      filterEnvId.value = envs.value[0].id
      localStorage.setItem('lastNginxEnvId', filterEnvId.value)
    }
  } catch (e) { ElMessage.error('获取环境失败') }
  loading.value = false
}

async function fetchDomains() {
  loading.value = true
  try {
    const params = filterEnvId.value ? { environment: filterEnvId.value } : {}
    const res = await getNginxDomains(params)
    domains.value = res.results || res
    
    // Default select first available domain
    const availableDomains = filteredDomains.value
    if (availableDomains.length > 0 && !availableDomains.some(d => d.id === filterDomainId.value)) {
      filterDomainId.value = availableDomains[0].id
      localStorage.setItem('lastNginxDomainId', filterDomainId.value)
    } else if (availableDomains.length === 0) {
      filterDomainId.value = ''
      localStorage.removeItem('lastNginxDomainId')
    }
  } catch (e) { ElMessage.error('获取域名失败') }
  loading.value = false
}

async function fetchRoutes() {
  if (!filterDomainId.value) { routes.value = []; return }
  loading.value = true
  try {
    const res = await getNginxRoutes({ nginx_domain: filterDomainId.value })
    routes.value = res.results || res
  } catch (e) { ElMessage.error('获取路由失败') }
  loading.value = false
}

function onEnvChange() {
  localStorage.setItem('lastNginxEnvId', filterEnvId.value)
  filterDomainId.value = ''
  localStorage.removeItem('lastNginxDomainId')
  routes.value = []
  fetchDomains()
}

function onDomainChange() {
  localStorage.setItem('lastNginxDomainId', filterDomainId.value)
  fetchRoutes()
}

function switchTab(t) {
  activeTab.value = t
  if (t === 'envs') fetchEnvs()
  if (t === 'domains') { if (filterEnvId.value) fetchDomains(); else if (envs.value.length) { filterEnvId.value = envs.value[0].id; fetchDomains() } }
  if (t === 'routes') { if (filterDomainId.value) fetchRoutes() }
}

onMounted(() => {
  fetchEnvs().then(() => {
    // 也预加载所有域名用于路由 tab
    getNginxDomains().then(res => { domains.value = res.results || res }).catch(() => {})
  })
})

// ====== ENV CRUD ======
function openEnvDialog(row) {
  if (row) {
    envForm.value = { ...row, ssh_password: '' }
  } else {
    envForm.value = { ssh_port: 22, ssh_user: 'root', nginx_path: '/etc/nginx', status: 'disconnected' }
  }
  envDialog.value = true
}
async function saveEnv() {
  saving.value = true
  try {
    if (envForm.value.id) {
      const payload = { ...envForm.value }
      if (!payload.ssh_password) delete payload.ssh_password
      await updateNginxEnvironment(payload.id, payload)
    } else {
      await createNginxEnvironment(envForm.value)
    }
    ElMessage.success('保存成功')
    envDialog.value = false
    fetchEnvs()
  } catch (e) { }
  saving.value = false
}
async function delEnv(id) {
  try { await deleteNginxEnvironment(id); ElMessage.success('删除成功'); fetchEnvs() } catch (e) { }
}
async function testEnv(id) {
  ElMessage.info('测试连接中...')
  try {
    const res = await testNginxConnection(id)
    if (res.success) ElMessage.success(res.message); else ElMessage.error(res.message)
    fetchEnvs()
  } catch (e) { ElMessage.error('连接失败') }
}

// ====== DOMAIN CRUD ======
function openDomainDialog(row) {
  if (row) {
    domainForm.value = { ...row, cert_content: '', key_content: '' }
  } else {
    domainForm.value = { environment: filterEnvId.value, listen_port: 80, ssl_port: 443, ssl_enabled: false, enabled: true, cert_content: '', key_content: '' }
  }
  domainDialog.value = true
}
async function saveDomain() {
  if (!domainForm.value.domain) return ElMessage.warning('请填写域名或 IP')
  saving.value = true
  try {
    const payload = { ...domainForm.value }
    if (!payload.cert_content) delete payload.cert_content
    if (!payload.key_content) delete payload.key_content
    if (payload.id) {
      await updateNginxDomain(payload.id, payload)
    } else {
      await createNginxDomain(payload)
    }
    ElMessage.success('保存成功')
    domainDialog.value = false
    fetchDomains()
  } catch (e) { }
  saving.value = false
}
async function delDomain(id) {
  try { await deleteNginxDomain(id); ElMessage.success('删除成功'); fetchDomains() } catch (e) { }
}
async function handleToggleSSL(row) {
  const enable = !row.ssl_enabled
  if (enable && !row.cert_path) {
    return ElMessage.warning('请先在编辑中上传证书内容，保存后再启用 SSL')
  }
  try {
    const res = await toggleDomainSSL(row.id, enable)
    if (res.success) ElMessage.success(res.message); else ElMessage.error(res.message)
    fetchDomains()
  } catch (e) { ElMessage.error('操作失败') }
}
async function handleDeployConf(row) {
  ElMessage.info('正在发布配置...')
  try {
    const res = await deployDomainConf(row.id)
    if (res.success) ElMessage.success(res.message); else ElMessage.error(res.message)
  } catch (e) { ElMessage.error('发布失败') }
}
async function handlePreviewConf(row) {
  try {
    const res = await previewDomainConf(row.id)
    previewContent.value = res.conf
    previewFilename.value = res.filename
    previewDialog.value = true
  } catch (e) { ElMessage.error('预览失败') }
}
function copyConf() {
  navigator.clipboard.writeText(previewContent.value).then(() => ElMessage.success('已复制')).catch(() => ElMessage.error('复制失败'))
}

// ====== ROUTE CRUD ======
function openRouteDialog(row) {
  if (row) {
    routeForm.value = { ...row }
  } else {
    routeForm.value = {
      nginx_domain: filterDomainId.value,
      location: '/',
      upstream_servers: '',
      enabled: true,
      redirect_url: '',
      redirect_code: 301,
      custom_headers: '',
      proxy_set_headers: '',
      client_max_body_size: '10m',
      extra_directives: ''
    }
  }
  routeDialog.value = true
}
async function saveRoute() {
  if (!routeForm.value.location) return ElMessage.warning('请填写 Location')
  if (!routeForm.value.upstream_servers && !routeForm.value.redirect_url) return ElMessage.warning('请填写后端地址或重定向地址')
  saving.value = true
  try {
    if (routeForm.value.id) {
      await updateNginxRoute(routeForm.value.id, routeForm.value)
    } else {
      await createNginxRoute(routeForm.value)
    }
    ElMessage.success('保存成功')
    routeDialog.value = false
    fetchRoutes()
  } catch (e) { }
  saving.value = false
}
async function delRoute(id) {
  try { await deleteNginxRoute(id); ElMessage.success('删除成功'); fetchRoutes() } catch (e) { }
}
</script>

<style scoped>
.w-full {
  width: 100%;
}
</style>
