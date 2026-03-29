<template>
  <div class="multicloud-page fade-in">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="release-header-icon"><el-icon><Promotion /></el-icon></span>
          <h2>多云环境</h2>
          <p class="subtitle inline-subtitle">多云资源统一管理平台，覆盖资源拓扑、批量动作、成本趋势和真实 SDK 状态。</p>
        </div>
        <h2>多云环境</h2>
        <p class="page-subtitle">多云资源统一管理平台，覆盖资源拓扑、批量动作、成本趋势和真实 SDK 状态。</p>
      </div>
      <div class="hero-actions">
        <el-button @click="refreshAll"><el-icon><RefreshRight /></el-icon>刷新</el-button>
        <el-button v-if="canManage" type="primary" @click="openCredentialDialog()"><el-icon><Plus /></el-icon>新建云账号</el-button>
      </div>
    </section>

    <div class="stats-grid release-stats">
      <div class="stat-card release-stat-card">
        <div class="stat-value">{{ overview.stats?.credential_count || 0 }}</div>
        <div class="stat-label">云账号</div>
      </div>
      <div class="stat-card release-stat-card warning-card">
        <div class="stat-value">{{ overview.stats?.environment_count || 0 }}</div>
        <div class="stat-label">云环境</div>
      </div>
      <div class="stat-card release-stat-card success-card">
        <div class="stat-value">{{ overview.stats?.asset_count || 0 }}</div>
        <div class="stat-label">资源总数</div>
      </div>
      <div class="stat-card release-stat-card danger-card">
        <div class="stat-value">{{ money(overview.stats?.monthly_cost) }}</div>
        <div class="stat-label">月成本</div>
      </div>
    </div>

    <div class="metric-grid">
      <div class="metric-card"><span>云账号</span><strong>{{ overview.stats?.credential_count || 0 }}</strong></div>
      <div class="metric-card"><span>云环境</span><strong>{{ overview.stats?.environment_count || 0 }}</strong></div>
      <div class="metric-card"><span>资源总数</span><strong>{{ overview.stats?.asset_count || 0 }}</strong></div>
      <div class="metric-card metric-card--highlight"><span>月成本</span><strong>{{ money(overview.stats?.monthly_cost) }}</strong></div>
    </div>

    <el-tabs v-model="activeTab" class="module-tabs">
      <el-tab-pane label="总览" name="overview">
        <div class="grid-2">
          <div class="card-panel overview-card overview-card--table">
            <div class="section-head"><span>云厂商概览</span></div>
            <el-table :data="overview.provider_summary || []" stripe>
              <el-table-column prop="provider_label" label="云厂商" min-width="120" />
              <el-table-column prop="credentials" label="账号数" width="90" />
              <el-table-column prop="environments" label="环境数" width="90" />
              <el-table-column prop="assets" label="资源数" width="90" />
              <el-table-column prop="risk_count" label="风险项" width="90" />
              <el-table-column label="月成本" width="120"><template #default="{ row }">{{ money(row.monthly_cost) }}</template></el-table-column>
            </el-table>
          </div>
          <div class="card-panel overview-card overview-card--governance">
            <div class="section-head"><span>治理建议</span></div>
            <div v-if="overview.recommendations?.length" class="suggest-list">
              <div v-for="item in overview.recommendations" :key="item.title" class="suggest-item">
                <el-tag size="small" :type="severityTag(item.severity)">{{ severityText(item.severity) }}</el-tag>
                <strong>{{ item.title }}</strong>
                <div>{{ item.detail }}</div>
              </div>
            </div>
            <el-empty v-else description="暂无建议" />
          </div>
        </div>
        <div class="card-panel overview-trend-card">
          <div class="section-head">
            <span>成本趋势</span>
            <div class="filter-inline">
              <el-select v-model="costTrendFilter.group_by" style="width: 150px" @change="loadCostTrend">
                <el-option label="按云厂商" value="provider" />
                <el-option label="按环境" value="environment" />
                <el-option label="按资源类型" value="resource_type" />
              </el-select>
              <el-select v-model="costTrendFilter.provider" clearable placeholder="云厂商" style="width: 150px" @change="loadCostTrend">
                <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="costTrendFilter.environment" clearable placeholder="环境" style="width: 220px" @change="loadCostTrend">
                <el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
              <el-select v-model="costTrendFilter.resource_type" clearable placeholder="资源类型" style="width: 170px" @change="loadCostTrend">
                <el-option v-for="item in resourceTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </div>
          </div>
          <div ref="costTrendChartRef" class="chart-block" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="资源拓扑" name="topology">
        <div class="card-panel">
          <div class="section-head">
            <span>资源拓扑</span>
            <div class="filter-inline">
              <el-select v-model="topologyFilter.provider" clearable placeholder="云厂商" style="width: 150px" @change="loadTopology">
                <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="topologyFilter.environment" clearable placeholder="环境" style="width: 220px" @change="loadTopology">
                <el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
              <el-tag type="info">节点 {{ topology.stats?.node_count || 0 }}</el-tag>
              <el-tag type="warning">连线 {{ topology.stats?.edge_count || 0 }}</el-tag>
            </div>
          </div>
          <div v-if="topologyEnvironmentOptions.length" class="topology-lane-toolbar">
            <div class="topology-lane-actions">
              <el-button size="small" @click="expandAllTopologyLanes">全部展开</el-button>
              <el-button size="small" @click="collapseAllTopologyLanes">全部折叠</el-button>
            </div>
            <div class="topology-lane-tags">
              <button
                v-for="item in topologyEnvironmentOptions"
                :key="item.id"
                type="button"
                class="topology-lane-chip"
                :class="{ 'is-collapsed': isTopologyLaneCollapsed(item.id) }"
                @click="toggleTopologyLane(item.id)"
              >
                <span class="topology-lane-chip__meta">
                  <span class="topology-lane-chip__dot" :style="{ background: providerPalette(item.provider).accentFill }" />
                  <span>{{ item.name }}</span>
                </span>
                <span class="topology-lane-chip__state">{{ isTopologyLaneCollapsed(item.id) ? '已折叠' : '已展开' }}</span>
              </button>
            </div>
          </div>
          <div ref="topologyChartRef" class="chart-block chart-block--topology" />
        </div>
      </el-tab-pane>

      <el-tab-pane :label="`云账号 (${credentials.length})`" name="credentials">
        <div class="card-panel">
          <div class="section-head">
            <span>云账号</span>
            <div class="filter-inline">
              <el-select v-model="credentialFilter.provider" clearable placeholder="云厂商" style="width: 150px">
                <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-button @click="loadCredentials">查询</el-button>
              <el-button v-if="canManage" type="primary" @click="openCredentialDialog()">新建账号</el-button>
            </div>
          </div>
          <div v-if="canManage" class="batch-toolbar">
            <el-button :disabled="!selectedCredentialIds.length" @click="runBatchAction('credentials', 'test_connection')">批量连通性</el-button>
            <el-button :disabled="!selectedCredentialIds.length" @click="runBatchAction('credentials', 'enable')">批量启用</el-button>
            <el-button :disabled="!selectedCredentialIds.length" @click="runBatchAction('credentials', 'disable')">批量禁用</el-button>
            <el-button :disabled="!selectedCredentialIds.length" @click="runBatchAction('credentials', 'demo_on')">批量开启 Demo</el-button>
            <el-button :disabled="!selectedCredentialIds.length" @click="runBatchAction('credentials', 'demo_off')">批量关闭 Demo</el-button>
          </div>
          <el-table :data="credentials" stripe v-loading="loading.credentials" @selection-change="rows => selectedCredentialIds = rows.map(item => item.id)">
            <el-table-column v-if="canManage" type="selection" width="50" />
            <el-table-column prop="name" label="名称" min-width="180" />
            <el-table-column prop="provider_label" label="云厂商" width="110" />
            <el-table-column prop="owner" label="负责人" width="110" />
            <el-table-column label="SDK 状态" min-width="180">
              <template #default="{ row }">
                <el-space wrap>
                  <el-tag size="small" :type="row.demo_mode ? 'warning' : sdkInstalled(row.provider) ? 'success' : 'info'">{{ row.demo_mode ? 'Demo' : sdkInstalled(row.provider) ? 'SDK 已就绪' : 'SDK 未安装' }}</el-tag>
                  <span class="muted-text">{{ sdkSummary(row.provider) }}</span>
                </el-space>
              </template>
            </el-table-column>
            <el-table-column label="连通性" width="100"><template #default="{ row }"><el-tag size="small" :type="statusTag(row.last_test_status)">{{ statusText(row.last_test_status) }}</el-tag></template></el-table-column>
            <el-table-column label="操作" fixed="right" width="320">
              <template #default="{ row }">
                <el-button link type="primary" @click="openCredentialDialog(row)">编辑</el-button>
                <el-button link type="success" @click="handleTestCredential(row)">连通性</el-button>
                <el-tooltip
                  v-if="canSync"
                  content="同步该云账号下绑定的全部环境资源清单，不会直接写入 CMDB。"
                  placement="top"
                >
                  <el-button link type="warning" @click="handleSyncCredential(row)">同步</el-button>
                </el-tooltip>
                <el-button link type="info" @click="focusCredential(row)">定位拓扑</el-button>
                <el-popconfirm v-if="canManage" title="确认删除该云账号吗" @confirm="handleDeleteCredential(row)">
                  <template #reference><el-button link type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="`云环境 (${environments.length})`" name="envs">
        <div class="card-panel">
          <div class="section-head">
            <span>云环境</span>
            <div class="filter-inline">
              <el-select v-model="envFilter.provider" clearable placeholder="云厂商" style="width: 150px">
                <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="envFilter.environment_type" clearable placeholder="环境类型" style="width: 150px">
                <el-option label="生产" value="prod" />
                <el-option label="测试" value="test" />
                <el-option label="开发" value="dev" />
                <el-option label="共享" value="shared" />
              </el-select>
              <el-button @click="loadEnvironments">查询</el-button>
              <el-button v-if="canManage" type="primary" @click="openEnvironmentDialog()">新建环境</el-button>
            </div>
          </div>
          <div v-if="canManage || canSync" class="batch-toolbar">
            <el-button v-if="canSync" :disabled="!selectedEnvironmentIds.length" @click="runBatchAction('environments', 'sync_inventory')">批量同步资源</el-button>
            <el-button v-if="canSync && canCmdbManage" :disabled="!selectedEnvironmentIds.length" @click="runBatchAction('environments', 'sync_cmdb')">批量同步 CMDB</el-button>
            <el-button v-if="canManage" :disabled="!selectedEnvironmentIds.length" @click="runBatchAction('environments', 'mark_active')">批量标记活跃</el-button>
            <el-button v-if="canManage" :disabled="!selectedEnvironmentIds.length" @click="runBatchAction('environments', 'mark_offline')">批量标记离线</el-button>
          </div>
          <el-table :data="environments" stripe v-loading="loading.environments" @selection-change="rows => selectedEnvironmentIds = rows.map(item => item.id)">
            <el-table-column v-if="canManage || canSync" type="selection" width="50" />
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column prop="provider_label" label="云厂商" width="110" />
            <el-table-column prop="credential_name" label="云账号" min-width="160" />
            <el-table-column prop="environment_type_label" label="类型" width="90" />
            <el-table-column prop="asset_count" label="资源数" width="90" />
            <el-table-column label="月成本" width="120"><template #default="{ row }">{{ money(row.monthly_cost) }}</template></el-table-column>
            <el-table-column label="同步状态" width="120"><template #default="{ row }"><el-tag size="small" :type="statusTag(row.sync_status)">{{ row.sync_status_label }}</el-tag></template></el-table-column>
            <el-table-column label="操作" fixed="right" width="340">
              <template #default="{ row }">
                <el-button link type="info" @click="openDrawer(row)">详情</el-button>
                <el-button v-if="canManage" link type="primary" @click="openEnvironmentDialog(row)">编辑</el-button>
                <el-tooltip
                  v-if="canSync"
                  content="从云厂商拉取该环境的最新资源，更新到多云资源表。"
                  placement="top"
                >
                  <el-button link type="success" @click="handleSyncEnvironment(row)">同步资源</el-button>
                </el-tooltip>
                <el-tooltip
                  v-if="canSync && canCmdbManage"
                  content="将当前环境已同步到多云模块的资源写入 CMDB；若本地无资源，会先补做一次资源同步。"
                  placement="top"
                >
                  <el-button link type="warning" @click="handleSyncEnvironmentCmdb(row)">同步 CMDB</el-button>
                </el-tooltip>
                <el-popconfirm v-if="canManage" title="确认删除该云环境吗" @confirm="handleDeleteEnvironment(row)">
                  <template #reference><el-button link type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="`云资源 (${assets.length})`" name="assets">
        <div class="card-panel">
          <div class="section-head">
            <span>云资源</span>
            <div class="filter-inline">
              <el-select v-model="assetFilter.environment" clearable placeholder="环境" style="width: 220px">
                <el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
              <el-select v-model="assetFilter.provider" clearable placeholder="云厂商" style="width: 150px">
                <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="assetFilter.resource_type" clearable placeholder="资源类型" style="width: 170px">
                <el-option v-for="item in resourceTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-input v-model="assetFilter.search" placeholder="搜索名称 / ID / IP" style="width: 220px" @keyup.enter="loadAssets()" />
              <el-button @click="loadAssets()">查询</el-button>
            </div>
          </div>
          <div v-if="canManage" class="batch-toolbar">
            <el-button :disabled="!selectedAssetIds.length" @click="runBatchAction('assets', 'set_warning')">批量设风险</el-button>
            <el-button :disabled="!selectedAssetIds.length" @click="runBatchAction('assets', 'set_normal')">批量清风险</el-button>
            <el-button :disabled="!selectedAssetIds.length" @click="runBatchAction('assets', 'mark_drift')">批量标漂移</el-button>
            <el-button :disabled="!selectedAssetIds.length" @click="runBatchAction('assets', 'mark_synced')">批量标同步</el-button>
          </div>
          <el-table :data="assets" stripe v-loading="loading.assets" @selection-change="rows => selectedAssetIds = rows.map(item => item.id)">
            <el-table-column v-if="canManage" type="selection" width="50" />
            <el-table-column prop="name" label="名称" min-width="180" />
            <el-table-column prop="resource_type_label" label="类型" width="110" />
            <el-table-column prop="environment_name" label="环境" min-width="150" />
            <el-table-column label="IP" min-width="180"><template #default="{ row }">{{ row.private_ip || '-' }} / {{ row.public_ip || '-' }}</template></el-table-column>
            <el-table-column prop="spec" label="规格" min-width="140" />
            <el-table-column label="风险" width="100"><template #default="{ row }"><el-tag size="small" :type="riskTag(row.risk_level)">{{ row.risk_level_label }}</el-tag></template></el-table-column>
            <el-table-column label="同步状态" width="110"><template #default="{ row }"><el-tag size="small" :type="syncTag(row.sync_state)">{{ row.sync_state_label }}</el-tag></template></el-table-column>
            <el-table-column label="月成本" width="120"><template #default="{ row }">{{ money(row.monthly_cost) }}</template></el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane :label="`同步任务 (${tasks.length})`" name="tasks">
        <div class="card-panel">
          <div class="section-head">
            <span>同步任务</span>
            <div class="filter-inline">
              <el-select v-model="taskFilter.status" clearable placeholder="状态" style="width: 140px">
                <el-option label="待执行" value="pending" />
                <el-option label="执行中" value="running" />
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
              </el-select>
              <el-select v-model="taskFilter.task_type" clearable placeholder="任务类型" style="width: 160px">
                <el-option label="全量同步" value="full" />
                <el-option label="资源同步" value="inventory" />
                <el-option label="同步 CMDB" value="cmdb" />
              </el-select>
              <el-button @click="loadTasks">查询</el-button>
            </div>
          </div>
          <el-table :data="tasks" stripe v-loading="loading.tasks">
            <el-table-column prop="task_type_label" label="类型" width="120" />
            <el-table-column prop="target_display" label="目标" min-width="160" />
            <el-table-column prop="operator" label="操作人" width="100" />
            <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag size="small" :type="statusTag(row.status)">{{ row.status_label }}</el-tag></template></el-table-column>
            <el-table-column prop="summary" label="摘要" min-width="260" />
            <el-table-column label="完成时间" min-width="170"><template #default="{ row }">{{ formatTime(row.finished_at || row.created_at) }}</template></el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="credentialDialog.visible" :title="credentialDialog.editing ? '编辑云账号' : '新建云账号'" width="700px">
      <el-form :model="credentialForm" label-width="100px">
        <el-form-item label="云厂商"><el-select v-model="credentialForm.provider" style="width: 100%"><el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="名称"><el-input v-model="credentialForm.name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="负责人"><el-input v-model="credentialForm.owner" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="账号 ID"><el-input v-model="credentialForm.account_id" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="默认 Region"><el-input v-model="credentialForm.default_region" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="认证方式"><el-select v-model="credentialForm.auth_mode" style="width: 100%"><el-option label="AK/SK" value="aksk" /><el-option label="STS" value="sts" /><el-option label="Demo" value="demo" /></el-select></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="Role ARN"><el-input v-model="credentialForm.role_arn" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="Project ID"><el-input v-model="credentialForm.project_id" placeholder="Huawei Cloud 场景下填写项目 ID" /></el-form-item>
        <el-form-item label="Access Key"><el-input v-model="credentialForm.access_key_id" /></el-form-item>
        <el-form-item label="Secret"><el-input v-model="credentialForm.access_key_secret" type="password" show-password :placeholder="credentialDialog.editing ? '编辑时留空则不修改' : ''" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="credentialForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="状态"><el-space><el-switch v-model="credentialForm.is_enabled" active-text="启用" /><el-switch v-model="credentialForm.demo_mode" active-text="Demo 模式" /></el-space></el-form-item>
      </el-form>
      <template #footer><el-button @click="credentialDialog.visible = false">取消</el-button><el-button type="primary" :loading="loading.credentialSubmit" @click="submitCredential">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="envDialog.visible" :title="envDialog.editing ? '编辑云环境' : '新建云环境'" width="760px">
      <el-form :model="envForm" label-width="100px">
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="云账号"><el-select v-model="envForm.credential" style="width: 100%"><el-option v-for="item in credentials" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="环境名称"><el-input v-model="envForm.name" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="环境编码"><el-input v-model="envForm.code" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="业务线"><el-input v-model="envForm.business_line" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8"><el-form-item label="环境类型"><el-select v-model="envForm.environment_type" style="width: 100%"><el-option label="生产" value="prod" /><el-option label="测试" value="test" /><el-option label="开发" value="dev" /><el-option label="共享" value="shared" /></el-select></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="Region"><el-input v-model="envForm.region" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="Zone"><el-input v-model="envForm.zone" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="VPC"><el-input v-model="envForm.vpc_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="网络 CIDR"><el-input v-model="envForm.network_cidr" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="负责人"><el-input v-model="envForm.owner" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="Tags JSON"><el-input v-model="envForm.tagsText" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="描述"><el-input v-model="envForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="envDialog.visible = false">取消</el-button><el-button type="primary" :loading="loading.envSubmit" @click="submitEnvironment">保存</el-button></template>
    </el-dialog>

    <el-drawer v-model="drawer.visible" title="环境详情" size="760px">
      <div v-if="drawer.record" class="card-panel card-panel--drawer">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="环境">{{ drawer.record.name }}</el-descriptions-item>
          <el-descriptions-item label="云账号">{{ drawer.record.credential_name }}</el-descriptions-item>
          <el-descriptions-item label="云厂商">{{ drawer.record.provider_label }}</el-descriptions-item>
          <el-descriptions-item label="月成本">{{ money(drawer.record.monthly_cost) }}</el-descriptions-item>
        </el-descriptions>
        <div class="section-head section-head--drawer"><span>环境资源</span></div>
        <el-table :data="drawerAssets" stripe v-loading="loading.drawerAssets">
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column prop="resource_type_label" label="类型" width="110" />
          <el-table-column prop="spec" label="规格" min-width="140" />
          <el-table-column label="风险" width="90"><template #default="{ row }"><el-tag size="small" :type="riskTag(row.risk_level)">{{ row.risk_level_label }}</el-tag></template></el-table-column>
          <el-table-column label="月成本" width="110"><template #default="{ row }">{{ money(row.monthly_cost) }}</template></el-table-column>
        </el-table>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Promotion, RefreshRight } from '@element-plus/icons-vue'
import echarts from '@/lib/echarts'
import { useAuthStore } from '@/stores/auth'
import { createCloudCredential, createCloudEnvironment, deleteCloudCredential, deleteCloudEnvironment, getCloudAssets, getCloudCredentials, getCloudEnvironments, getCloudSyncTasks, getMultiCloudCatalog, getMultiCloudCostTrend, getMultiCloudOverview, getMultiCloudTopology, runMultiCloudBatchAction, syncCloudCredential, syncCloudEnvironment, syncCloudEnvironmentCmdb, testCloudCredential, updateCloudCredential, updateCloudEnvironment } from '@/api/modules/multicloud'

const auth = useAuthStore()
const activeTab = ref('overview')
const loading = reactive({ credentials: false, environments: false, assets: false, tasks: false, drawerAssets: false, credentialSubmit: false, envSubmit: false })
const catalog = ref({ providers: {} })
const overview = ref({ stats: {}, provider_summary: [], recommendations: [] })
const topology = ref({ categories: [], nodes: [], edges: [], stats: {} })
const costTrend = ref({ labels: [], series: [] })
const credentials = ref([])
const environments = ref([])
const assets = ref([])
const tasks = ref([])
const drawerAssets = ref([])
const selectedCredentialIds = ref([])
const selectedEnvironmentIds = ref([])
const selectedAssetIds = ref([])
const collapsedEnvironmentIds = ref([])
const credentialFilter = reactive({ provider: '' })
const envFilter = reactive({ provider: '', environment_type: '' })
const assetFilter = reactive({ environment: '', provider: '', resource_type: '', search: '' })
const taskFilter = reactive({ status: '', task_type: '' })
const topologyFilter = reactive({ provider: '', environment: '' })
const costTrendFilter = reactive({ group_by: 'provider', provider: '', environment: '', resource_type: '' })
const credentialDialog = reactive({ visible: false, editing: false, id: null })
const envDialog = reactive({ visible: false, editing: false, id: null })
const drawer = reactive({ visible: false, record: null })
const credentialForm = reactive({ provider: 'aliyun', name: '', account_id: '', owner: '', default_region: '', auth_mode: 'demo', access_key_id: '', access_key_secret: '', role_arn: '', project_id: '', description: '', is_enabled: true, demo_mode: true })
const envForm = reactive({ credential: '', name: '', code: '', business_line: '', environment_type: 'prod', region: '', zone: '', vpc_name: '', network_cidr: '', owner: '', description: '', tagsText: '{}' })
const costTrendChartRef = ref(null)
const topologyChartRef = ref(null)
let costTrendChart = null
let topologyChart = null

const canManage = computed(() => auth.hasPermission('ops.multicloud.manage'))
const canSync = computed(() => auth.hasPermission('ops.multicloud.sync'))
const canCmdbManage = computed(() => auth.hasPermission('cmdb.ci.manage'))
const providerOptions = computed(() => Object.entries(catalog.value.providers || {}).map(([value, meta]) => ({ value, label: meta.label })))
const resourceTypeOptions = computed(() => {
  const rows = new Map()
  Object.values(catalog.value.providers || {}).forEach(meta => (meta.resource_types || []).forEach(type => rows.set(type, typeText(type))))
  return Array.from(rows.entries()).map(([value, label]) => ({ value, label }))
})
const topologyEnvironmentOptions = computed(() => (topology.value.nodes || [])
  .filter(node => String(node.id || '').startsWith('environment-'))
  .sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
  .map(node => ({ id: node.id, name: node.name, provider: node.provider, provider_label: node.provider_label })))

const money = value => `¥ ${Number(value || 0).toFixed(2)}`
const formatTime = value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'
const severityText = value => ({ danger: '高优先级', warning: '中优先级', info: '治理项' }[value] || value)
const severityTag = value => ({ danger: 'danger', warning: 'warning', info: 'info' }[value] || 'info')
const statusText = value => ({ unknown: '未检测', healthy: '健康', warning: '告警', error: '异常', pending: '待执行', running: '执行中', success: '成功', failed: '失败' }[value] || value)
const statusTag = value => (['healthy', 'success'].includes(value) ? 'success' : ['warning', 'running'].includes(value) ? 'warning' : ['error', 'failed'].includes(value) ? 'danger' : 'info')
const riskTag = value => (value === 'critical' ? 'danger' : value === 'warning' ? 'warning' : 'success')
const syncTag = value => ({ synced: 'success', drift: 'warning', idle: 'info' }[value] || 'info')
const typeText = value => ({ ecs: '云主机', rds: '数据库', slb: '负载均衡', k8s: 'Kubernetes', redis: 'Redis', oss: '对象存储', nat: 'NAT 网关', eip: '弹性 IP', security_group: '安全组' }[value] || value)
const sdkInstalled = provider => !!catalog.value.providers?.[provider]?.sdk?.installed
const sdkSummary = provider => { const sdk = catalog.value.providers?.[provider]?.sdk; return !sdk ? '' : sdk.installed ? '可走真实 SDK 调用' : `依赖: ${(sdk.required_modules || []).join(', ')}` }

function parseJson(value) { try { return value ? JSON.parse(value) : {} } catch { ElMessage.error('Tags JSON 格式不正确'); throw new Error('invalid-json') } }
function ensureChart(chart, el) { return el ? chart || echarts.init(el) : null }
function resizeCharts() { costTrendChart?.resize(); topologyChart?.resize() }
async function loadCatalog() { catalog.value = await getMultiCloudCatalog() }
async function loadOverview() { overview.value = await getMultiCloudOverview() }
async function loadTopology() { topology.value = await getMultiCloudTopology({ provider: topologyFilter.provider || undefined, environment: topologyFilter.environment || undefined }); normalizeCollapsedTopology(); await nextTick(); renderTopology() }
async function loadCostTrend() { costTrend.value = await getMultiCloudCostTrend({ group_by: costTrendFilter.group_by, provider: costTrendFilter.provider || undefined, environment: costTrendFilter.environment || undefined, resource_type: costTrendFilter.resource_type || undefined }); await nextTick(); renderCostTrend() }
async function loadCredentials() { loading.credentials = true; try { credentials.value = await getCloudCredentials({ provider: credentialFilter.provider || undefined }) } finally { loading.credentials = false } }
async function loadEnvironments() { loading.environments = true; try { environments.value = await getCloudEnvironments({ provider: envFilter.provider || undefined, environment_type: envFilter.environment_type || undefined }) } finally { loading.environments = false } }
async function loadAssets(environmentId) { environmentId ? loading.drawerAssets = true : loading.assets = true; try { const data = await getCloudAssets({ environment: environmentId || assetFilter.environment || undefined, provider: environmentId ? undefined : assetFilter.provider || undefined, resource_type: environmentId ? undefined : assetFilter.resource_type || undefined, search: environmentId ? undefined : assetFilter.search || undefined }); environmentId ? drawerAssets.value = data : assets.value = data } finally { loading.drawerAssets = false; loading.assets = false } }
async function loadTasks() { loading.tasks = true; try { tasks.value = await getCloudSyncTasks({ status: taskFilter.status || undefined, task_type: taskFilter.task_type || undefined }) } finally { loading.tasks = false } }
async function refreshAll() { await Promise.all([loadOverview(), loadCredentials(), loadEnvironments(), loadAssets(), loadTasks(), loadTopology(), loadCostTrend()]) }
function normalizeCollapsedTopology() {
  const validIds = new Set(topologyEnvironmentOptions.value.map(item => item.id))
  collapsedEnvironmentIds.value = collapsedEnvironmentIds.value.filter(id => validIds.has(id))
}

function isTopologyLaneCollapsed(id) {
  return collapsedEnvironmentIds.value.includes(id)
}

function toggleTopologyLane(id) {
  collapsedEnvironmentIds.value = isTopologyLaneCollapsed(id)
    ? collapsedEnvironmentIds.value.filter(item => item !== id)
    : [...collapsedEnvironmentIds.value, id]
  renderTopology()
}

function collapseAllTopologyLanes() {
  collapsedEnvironmentIds.value = topologyEnvironmentOptions.value.map(item => item.id)
  renderTopology()
}

function expandAllTopologyLanes() {
  collapsedEnvironmentIds.value = []
  renderTopology()
}

function renderCostTrend() {
  costTrendChart = ensureChart(costTrendChart, costTrendChartRef.value)
  if (!costTrendChart) return
  costTrendChart.setOption({ tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 20, right: 20, bottom: 20, top: 50, containLabel: true }, xAxis: { type: 'category', data: costTrend.value.labels || [] }, yAxis: { type: 'value', axisLabel: { formatter: value => `楼${value}` } }, series: (costTrend.value.series || []).map(item => ({ name: item.label, type: 'line', smooth: true, data: item.values })) })
}

function providerPalette(provider) {
  const palettes = {
    aliyun: { laneFill: 'rgba(249,115,22,0.10)', laneStroke: 'rgba(249,115,22,0.28)', accentFill: 'rgba(249,115,22,0.88)', cardFill: 'rgba(255,247,237,0.96)', cardStroke: 'rgba(251,146,60,0.38)', text: '#9a3412', badgeFill: 'rgba(249,115,22,0.14)' },
    huawei: { laneFill: 'rgba(220,38,38,0.10)', laneStroke: 'rgba(220,38,38,0.22)', accentFill: 'rgba(220,38,38,0.88)', cardFill: 'rgba(254,242,242,0.96)', cardStroke: 'rgba(248,113,113,0.34)', text: '#b91c1c', badgeFill: 'rgba(220,38,38,0.14)' },
    aws: { laneFill: 'rgba(37,99,235,0.10)', laneStroke: 'rgba(37,99,235,0.22)', accentFill: 'rgba(37,99,235,0.84)', cardFill: 'rgba(239,246,255,0.96)', cardStroke: 'rgba(96,165,250,0.34)', text: '#1d4ed8', badgeFill: 'rgba(37,99,235,0.12)' },
    tencent: { laneFill: 'rgba(8,145,178,0.10)', laneStroke: 'rgba(8,145,178,0.24)', accentFill: 'rgba(8,145,178,0.84)', cardFill: 'rgba(236,254,255,0.96)', cardStroke: 'rgba(34,211,238,0.30)', text: '#0f766e', badgeFill: 'rgba(8,145,178,0.12)' },
    baidu: { laneFill: 'rgba(13,148,136,0.10)', laneStroke: 'rgba(13,148,136,0.22)', accentFill: 'rgba(13,148,136,0.82)', cardFill: 'rgba(240,253,250,0.96)', cardStroke: 'rgba(45,212,191,0.32)', text: '#0f766e', badgeFill: 'rgba(13,148,136,0.12)' },
    default: { laneFill: 'rgba(226,232,240,0.40)', laneStroke: 'rgba(148,163,184,0.22)', accentFill: 'rgba(100,116,139,0.84)', cardFill: 'rgba(255,255,255,0.96)', cardStroke: 'rgba(148,163,184,0.22)', text: '#334155', badgeFill: 'rgba(148,163,184,0.12)' },
  }
  return palettes[provider] || palettes.default
}

function categoryPalette(category) {
  const palettes = [
    { fill: 'rgba(241,245,249,0.98)', stroke: 'rgba(148,163,184,0.28)', text: '#334155' },
    { fill: 'rgba(239,246,255,0.98)', stroke: 'rgba(96,165,250,0.30)', text: '#1d4ed8' },
    { fill: 'rgba(240,253,244,0.98)', stroke: 'rgba(74,222,128,0.30)', text: '#15803d' },
    { fill: 'rgba(255,247,237,0.98)', stroke: 'rgba(251,146,60,0.30)', text: '#c2410c' },
    { fill: 'rgba(250,245,255,0.98)', stroke: 'rgba(192,132,252,0.30)', text: '#7e22ce' },
  ]
  return palettes[Number(category || 0)] || palettes[0]
}

function topologyNodeStyle(node, envNode) {
  const palette = providerPalette(envNode?.provider || node.provider)
  const categoryStyle = categoryPalette(node.category)
  const nodeId = String(node.id || '')
  const isCredential = nodeId.startsWith('credential-')
  const isEnvironment = nodeId.startsWith('environment-')
  const isBucket = nodeId.startsWith('compute-') || nodeId.startsWith('data-') || nodeId.startsWith('network-')
  const isAsset = nodeId.startsWith('asset-')

  if (isCredential) {
    return {
      symbol: 'roundRect',
      symbolSize: [164, 42],
      itemStyle: { color: palette.cardFill, borderColor: palette.accentFill, borderWidth: 1.5, shadowBlur: 14, shadowColor: 'rgba(15,23,42,0.08)', shadowOffsetY: 6 },
      label: { show: true, position: 'inside', color: palette.text, fontSize: 12, fontWeight: 700, formatter: ({ data }) => data?.name || '' },
    }
  }

  if (isEnvironment) {
    return {
      symbol: 'roundRect',
      symbolSize: [170, 48],
      cursor: 'pointer',
      itemStyle: { color: '#ffffff', borderColor: palette.laneStroke, borderWidth: 1.6, shadowBlur: 16, shadowColor: 'rgba(15,23,42,0.08)', shadowOffsetY: 8 },
      label: { show: true, position: 'inside', color: '#334155', fontSize: 12, fontWeight: 700, formatter: ({ data }) => data?.name || '' },
    }
  }

  if (isBucket) {
    return {
      symbol: 'roundRect',
      symbolSize: [128, 34],
      itemStyle: { color: categoryStyle.fill, borderColor: categoryStyle.stroke, borderWidth: 1.2, shadowBlur: 10, shadowColor: 'rgba(15,23,42,0.05)', shadowOffsetY: 4 },
      label: { show: true, position: 'inside', color: categoryStyle.text, fontSize: 11, fontWeight: 700, formatter: ({ data }) => data?.name || '' },
    }
  }

  if (isAsset) {
    return {
      symbol: 'roundRect',
      symbolSize: [142, 38],
      itemStyle: { color: '#ffffff', borderColor: categoryStyle.stroke, borderWidth: 1.1, shadowBlur: 10, shadowColor: 'rgba(15,23,42,0.04)', shadowOffsetY: 4 },
      label: { show: true, position: 'inside', color: '#475569', fontSize: 11, overflow: 'truncate', width: 112, formatter: ({ data }) => data?.name || '' },
    }
  }

  return {
    symbol: 'roundRect',
    symbolSize: [126, 34],
    itemStyle: { color: '#ffffff', borderColor: palette.cardStroke, borderWidth: 1.1 },
    label: { show: true, position: 'inside', color: '#475569', fontSize: 11, formatter: ({ data }) => data?.name || '' },
  }
}

function buildLayeredTopologyLayout() {
  const nodes = [...(topology.value.nodes || [])]
  const links = [...(topology.value.edges || [])]
  if (!nodes.length) return { nodes, graphics: [], visibleNodeIds: new Set() }

  const width = topologyChartRef.value?.clientWidth || 1200
  const height = topologyChartRef.value?.clientHeight || 560
  const leftPadding = 92
  const rightPadding = 76
  const topPadding = 56
  const bottomPadding = 28
  const categoryCount = Math.max(1, (topology.value.categories || []).length)
  const usableWidth = Math.max(360, width - leftPadding - rightPadding)
  const usableHeight = Math.max(280, height - topPadding - bottomPadding)
  const xStep = categoryCount === 1 ? 0 : usableWidth / (categoryCount - 1)
  const nodeMap = new Map(nodes.map(node => [node.id, node]))
  const outgoing = new Map()
  const incoming = new Map()

  links.forEach((link) => {
    if (!outgoing.has(link.source)) outgoing.set(link.source, [])
    if (!incoming.has(link.target)) incoming.set(link.target, [])
    outgoing.get(link.source).push(link.target)
    incoming.get(link.target).push(link.source)
  })

  const environmentNodes = nodes.filter(node => String(node.id || '').startsWith('environment-'))
  const credentialNodes = nodes.filter(node => String(node.id || '').startsWith('credential-'))
  const environmentByNode = new Map()
  const collapsedSet = new Set(collapsedEnvironmentIds.value)
  const credentialEnvironmentIds = new Map()
  const credentialIdByEnvironment = new Map()
  const credentialNameByEnvironment = new Map()
  const collapsedWeight = 0.46
  const expandedWeight = 1

  environmentNodes.forEach(node => environmentByNode.set(node.id, node.id))

  environmentNodes.forEach((envNode) => {
    for (const childId of outgoing.get(envNode.id) || []) {
      environmentByNode.set(childId, envNode.id)
      for (const grandChildId of outgoing.get(childId) || []) {
        environmentByNode.set(grandChildId, envNode.id)
      }
    }
  })

  credentialNodes.forEach((credentialNode) => {
    const relatedEnvs = (outgoing.get(credentialNode.id) || []).filter(id => String(id || '').startsWith('environment-'))
    credentialEnvironmentIds.set(credentialNode.id, relatedEnvs)
    relatedEnvs.forEach(envId => environmentByNode.set(credentialNode.id, envId))
  })

  environmentNodes.forEach((envNode) => {
    const credentialId = (incoming.get(envNode.id) || []).find(id => String(id || '').startsWith('credential-'))
    credentialIdByEnvironment.set(envNode.id, credentialId || '')
    credentialNameByEnvironment.set(envNode.id, credentialId ? (nodeMap.get(credentialId)?.name || '') : '')
  })

  environmentNodes.sort((a, b) => (
    String(a.provider || '').localeCompare(String(b.provider || ''))
    || String(credentialNameByEnvironment.get(a.id) || '').localeCompare(String(credentialNameByEnvironment.get(b.id) || ''))
    || String(a.business_line || '').localeCompare(String(b.business_line || ''))
    || String(a.name || '').localeCompare(String(b.name || ''))
  ))

  const laneCount = Math.max(1, environmentNodes.length)
  const laneHeight = usableHeight / laneCount
  const environmentIndex = new Map(environmentNodes.map((node, index) => [node.id, index]))
  const laneGap = laneCount > 1 ? 10 : 0

  const laneBudget = Math.max(240, usableHeight - laneGap * (laneCount - 1))
  const laneWeights = environmentNodes.map(node => (collapsedSet.has(node.id) ? collapsedWeight : expandedWeight))
  const totalLaneWeight = laneWeights.reduce((sum, item) => sum + item, 0) || 1
  const laneMetrics = new Map()
  let laneCursor = topPadding

  environmentNodes.forEach((envNode, index) => {
    const isLastLane = index === environmentNodes.length - 1
    const rawHeight = laneBudget * (laneWeights[index] / totalLaneWeight)
    const remainingHeight = topPadding + usableHeight - laneCursor
    const laneSize = isLastLane ? Math.max(collapsedSet.has(envNode.id) ? 92 : 140, remainingHeight) : Math.max(collapsedSet.has(envNode.id) ? 92 : 140, Math.round(rawHeight))
    laneMetrics.set(envNode.id, {
      top: laneCursor,
      height: laneSize,
      collapsed: collapsedSet.has(envNode.id),
    })
    laneCursor += laneSize + laneGap
  })

  const laneWidth = usableWidth + 96
  const providerGroups = []
  const accountGroups = []

  environmentNodes.forEach((envNode, index) => {
    const laneMeta = laneMetrics.get(envNode.id) || { top: topPadding + index * laneHeight, height: laneHeight }
    const provider = envNode.provider || 'default'
    const providerLabel = envNode.provider_label || provider
    const credentialId = credentialIdByEnvironment.get(envNode.id) || ''
    const credentialName = credentialNameByEnvironment.get(envNode.id) || '未绑定账号'
    const laneBottom = laneMeta.top + Math.max(laneMeta.collapsed ? 84 : 120, laneMeta.height - 8)

    const providerGroup = providerGroups[providerGroups.length - 1]
    if (!providerGroup || providerGroup.provider !== provider) {
      providerGroups.push({ provider, providerLabel, start: laneMeta.top, end: laneBottom })
    } else {
      providerGroup.end = laneBottom
    }

    const accountGroup = accountGroups[accountGroups.length - 1]
    if (!accountGroup || accountGroup.provider !== provider || accountGroup.credentialId !== credentialId) {
      accountGroups.push({ provider, credentialId, credentialName, start: laneMeta.top, end: laneBottom })
    } else {
      accountGroup.end = laneBottom
    }
  })

  const visibleNodes = nodes.filter((node) => {
    const nodeId = String(node.id || '')
    const envId = environmentByNode.get(node.id) || environmentNodes[0]?.id || null
    const isCredential = nodeId.startsWith('credential-')
    const isEnvironment = nodeId.startsWith('environment-')
    if (!envId) return true
    if (!collapsedSet.has(envId)) return true
    return isCredential || isEnvironment
  })
  const visibleNodeIds = new Set(visibleNodes.map(node => node.id))

  const groupedByLaneAndCategory = new Map()
  const pushGroup = (laneKey, category, node) => {
    const key = `${laneKey}:${category}`
    if (!groupedByLaneAndCategory.has(key)) groupedByLaneAndCategory.set(key, [])
    groupedByLaneAndCategory.get(key).push(node)
  }

  visibleNodes.forEach((node) => {
    const envId = environmentByNode.get(node.id) || environmentNodes[0]?.id || null
    const laneKey = envId || 'ungrouped'
    pushGroup(laneKey, Number(node.category || 0), node)
  })

  groupedByLaneAndCategory.forEach((items) => {
    items.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
  })

  const columnColors = ['rgba(14,116,144,0.06)', 'rgba(59,130,246,0.07)', 'rgba(22,163,74,0.07)', 'rgba(234,88,12,0.07)', 'rgba(147,51,234,0.07)']
  const graphics = []

  for (let category = 0; category < categoryCount; category += 1) {
    const x = leftPadding + category * xStep - 52
    graphics.push({
      type: 'rect',
      shape: { x, y: topPadding - 16, width: Math.max(90, xStep * 0.86), height: usableHeight + 32 },
      style: { fill: columnColors[category % columnColors.length], stroke: 'rgba(148,163,184,0.08)', lineWidth: 1, radius: 18 },
      silent: true,
      z: -20,
    })
    graphics.push({
      type: 'text',
      style: { x: x + 14, y: topPadding - 42, text: topology.value.categories?.[category]?.name || '', fill: '#334155', font: '600 13px sans-serif' },
      silent: true,
      z: -10,
    })
  }

  providerGroups.forEach((group) => {
    const palette = providerPalette(group.provider)
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding - 84, y: group.start - 10, width: laneWidth + 124, height: Math.max(54, group.end - group.start + 20), r: 28 },
      style: { fill: 'rgba(255,255,255,0.30)', stroke: palette.laneStroke, lineWidth: 1.2, lineDash: [8, 6] },
      silent: true,
      z: -42,
    })
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding - 84, y: group.start - 24, width: 144, height: 26, r: 12 },
      style: { fill: palette.accentFill, shadowBlur: 10, shadowColor: 'rgba(15,23,42,0.08)' },
      silent: true,
      z: -18,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding - 66, y: group.start - 6, text: group.providerLabel, fill: '#ffffff', font: '700 11px sans-serif' },
      silent: true,
      z: -17,
    })
  })

  accountGroups.forEach((group) => {
    const palette = providerPalette(group.provider)
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding - 62, y: group.start + 6, width: laneWidth + 64, height: Math.max(68, group.end - group.start - 12), r: 20 },
      style: { fill: 'rgba(255,255,255,0.22)', stroke: palette.cardStroke, lineWidth: 1, lineDash: [5, 5] },
      silent: true,
      z: -35,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding - 40, y: group.start + 24, text: group.credentialName, fill: palette.text, font: '600 11px sans-serif' },
      silent: true,
      z: -16,
    })
  })

  environmentNodes.forEach((envNode, index) => {
    const laneMeta = laneMetrics.get(envNode.id) || { top: topPadding + index * laneHeight, height: laneHeight, collapsed: false }
    const y = laneMeta.top
    const laneHeightBox = Math.max(laneMeta.collapsed ? 84 : 120, laneMeta.height - 8)
    const palette = providerPalette(envNode.provider)
    graphics.push({
      type: 'rect',
      shape: { x: leftPadding - 70, y, width: laneWidth, height: laneHeightBox },
      style: { fill: palette.laneFill, radius: 22, stroke: palette.laneStroke, lineWidth: 1.2 },
      silent: true,
      z: -30,
    })
    graphics.push({
      type: 'rect',
      shape: { x: leftPadding - 70, y, width: 8, height: laneHeightBox },
      style: { fill: palette.accentFill, radius: [22, 0, 0, 22] },
      silent: true,
      z: -26,
    })
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding - 52, y: y + 12, width: 210, height: 34, r: 12 },
      style: { fill: 'rgba(255,255,255,0.94)', stroke: palette.cardStroke, lineWidth: 1.2, shadowBlur: 8, shadowColor: 'rgba(15,23,42,0.06)' },
      silent: false,
      cursor: 'pointer',
      onclick: () => toggleTopologyLane(envNode.id),
      z: -5,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding - 36, y: y + 34, text: envNode.name || '', fill: '#334155', font: '600 13px sans-serif' },
      silent: false,
      cursor: 'pointer',
      onclick: () => toggleTopologyLane(envNode.id),
      z: -4,
    })
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding + 164, y: y + 16, width: 78, height: 24, r: 10 },
      style: { fill: palette.badgeFill },
      silent: true,
      z: -4,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding + 178, y: y + 32, text: envNode.provider_label || envNode.provider || '', fill: palette.text, font: '600 11px sans-serif' },
      silent: true,
      z: -3,
    })
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding + 248, y: y + 16, width: 66, height: 24, r: 10 },
      style: { fill: (envNode.risk_count || 0) > 0 ? 'rgba(245,158,11,0.14)' : 'rgba(22,163,74,0.14)' },
      silent: true,
      z: -4,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding + 261, y: y + 32, text: (envNode.risk_count || 0) > 0 ? `风险 ${envNode.risk_count || 0}` : '健康', fill: (envNode.risk_count || 0) > 0 ? '#b45309' : '#15803d', font: '600 11px sans-serif' },
      silent: true,
      z: -3,
    })
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding + laneWidth - 252, y: y + 16, width: 74, height: 24, r: 10 },
      style: { fill: laneMeta.collapsed ? 'rgba(148,163,184,0.14)' : 'rgba(37,99,235,0.12)' },
      silent: true,
      z: -4,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding + laneWidth - 234, y: y + 32, text: laneMeta.collapsed ? '已折叠' : '已展开', fill: laneMeta.collapsed ? '#475569' : '#1d4ed8', font: '600 11px sans-serif' },
      silent: true,
      z: -3,
    })
    graphics.push({
      type: 'roundRect',
      shape: { x: leftPadding + laneWidth - 164, y: y + 16, width: 136, height: 24, r: 10 },
      style: { fill: palette.badgeFill },
      silent: true,
      z: -4,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding + laneWidth - 150, y: y + 32, text: `资源 ${envNode.value || 0} · ${envNode.business_line || '未设置业务线'}`, fill: palette.text, font: '600 11px sans-serif' },
      silent: true,
      z: -3,
    })
    graphics.push({
      type: 'text',
      style: { x: leftPadding - 34, y: y + laneHeightBox - 12, text: `ENV-${String(index + 1).padStart(2, '0')}`, fill: 'rgba(100,116,139,0.55)', font: '600 10px sans-serif' },
      silent: true,
      z: -3,
    })
  })

  const laidOutNodes = nodes.map((node) => {
    const category = Number(node.category || 0)
    const envId = environmentByNode.get(node.id) || environmentNodes[0]?.id || null
    const envNode = envId ? nodeMap.get(envId) : null
    const laneIndex = environmentIndex.has(envId) ? environmentIndex.get(envId) : 0
    const laneMeta = laneMetrics.get(envId) || { top: topPadding + laneIndex * laneHeight, height: laneHeight }
    const laneTop = laneMeta.top
    const credentialLaneCenters = String(node.id || '').startsWith('credential-')
      ? (credentialEnvironmentIds.get(node.id) || [])
        .map(id => laneMetrics.get(id))
        .filter(Boolean)
        .map(item => item.top + item.height / 2)
      : []
    const laneCenter = credentialLaneCenters.length
      ? credentialLaneCenters.reduce((sum, item) => sum + item, 0) / credentialLaneCenters.length
      : laneTop + laneMeta.height / 2
    const items = groupedByLaneAndCategory.get(`${envId || 'ungrouped'}:${category}`) || [node]
    const rowIndex = Math.max(0, items.findIndex(item => item.id === node.id))
    const isCredential = String(node.id || '').startsWith('credential-')
    const isEnvironment = String(node.id || '').startsWith('environment-')
    const laneSpacing = laneMeta.height / (items.length + 1)
    const xBase = leftPadding + category * xStep
    const yBase = isCredential || isEnvironment
      ? laneCenter
      : laneTop + (rowIndex + 1) * laneSpacing
    const offset = isCredential || isEnvironment ? 0 : ((rowIndex % 2 === 0 ? -1 : 1) * Math.min(16, Math.floor(rowIndex / 2) * 6))
    const visual = topologyNodeStyle(node, envNode)
    return {
      ...node,
      x: Math.round(xBase),
      y: Math.round(yBase + offset),
      ignore: !visibleNodeIds.has(node.id),
      ...visual,
    }
  })

  return { nodes: laidOutNodes.filter(node => !node.ignore), graphics, visibleNodeIds }
}

function buildStyledTopologyLinks(visibleNodeIds) {
  return [...(topology.value.edges || [])]
    .filter(link => !visibleNodeIds || (visibleNodeIds.has(link.source) && visibleNodeIds.has(link.target)))
    .map((link) => {
    const source = String(link.source || '')
    const target = String(link.target || '')
    const sourceIsCredential = source.startsWith('credential-')
    const sourceIsEnvironment = source.startsWith('environment-')
    const targetIsEnvironment = target.startsWith('environment-')
    const targetIsBucket = target.startsWith('compute-') || target.startsWith('data-') || target.startsWith('network-')
    const targetIsAsset = target.startsWith('asset-')

    if (sourceIsCredential && targetIsEnvironment) {
      return {
        ...link,
        lineStyle: { color: '#0f766e', width: 2.6, opacity: 0.72, curveness: 0.02 },
        label: { show: false },
      }
    }

    if (sourceIsEnvironment && targetIsBucket) {
      return {
        ...link,
        lineStyle: { color: '#2563eb', width: 1.9, opacity: 0.6, curveness: 0.04, type: 'solid' },
        label: { show: false },
      }
    }

    if (targetIsAsset) {
      return {
        ...link,
        lineStyle: { color: '#94a3b8', width: 1.1, opacity: 0.42, curveness: 0.03, type: 'dashed' },
        label: { show: false },
      }
    }

    return {
      ...link,
      lineStyle: { color: '#64748b', width: 1.2, opacity: 0.38, curveness: 0.03 },
      label: { show: false },
    }
  })
}

function renderTopology() {
  topologyChart = ensureChart(topologyChart, topologyChartRef.value)
  if (!topologyChart) return
  topologyChart.off('click')
  topologyChart.resize()
  const { nodes: graphNodes, graphics, visibleNodeIds } = buildLayeredTopologyLayout()
  const graphLinks = buildStyledTopologyLinks(visibleNodeIds)
  topologyChart.setOption({
    animationDurationUpdate: 600,
    graphic: graphics,
    tooltip: {
      formatter: params => params.dataType === 'node'
        ? [params.data?.name, params.data?.provider_label, params.data?.resource_type_label, params.data?.risk_level].filter(Boolean).join('<br/>')
        : params.data?.value || '',
    },
    legend: [{ top: 8, left: 'center', data: (topology.value.categories || []).map(item => item.name) }],
    series: [{
      type: 'graph',
      layout: 'none',
      left: '1%',
      right: '1%',
      top: 52,
      bottom: 8,
      center: ['50%', '54%'],
      roam: true,
      draggable: true,
      categories: topology.value.categories || [],
      data: graphNodes,
      links: graphLinks,
      label: { show: true, position: 'inside', distance: 0 },
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [0, 6],
      lineStyle: { color: '#94a3b8', opacity: 0.46, curveness: 0.04, width: 1.1 },
      emphasis: { focus: 'adjacency', scale: 1.08 },
    }],
  }, true)
  topologyChart.on('click', (params) => {
    if (params.dataType !== 'node') return
    const id = String(params.data?.id || '')
    if (!id.startsWith('environment-')) return
    toggleTopologyLane(id)
  })
}

function openCredentialDialog(row = null) { Object.assign(credentialForm, row ? { provider: row.provider, name: row.name, account_id: row.account_id, owner: row.owner, default_region: row.default_region, auth_mode: row.auth_mode, access_key_id: row.access_key_id, access_key_secret: '', role_arn: row.role_arn || '', project_id: row.project_id || '', description: row.description, is_enabled: row.is_enabled, demo_mode: row.demo_mode } : { provider: 'aliyun', name: '', account_id: '', owner: '', default_region: catalog.value.providers?.aliyun?.default_region || '', auth_mode: 'demo', access_key_id: '', access_key_secret: '', role_arn: '', project_id: '', description: '', is_enabled: true, demo_mode: true }); credentialDialog.visible = true; credentialDialog.editing = !!row; credentialDialog.id = row?.id || null }
async function submitCredential() { if (!credentialForm.name) return ElMessage.warning('请填写账号名称'); loading.credentialSubmit = true; try { const payload = { provider: credentialForm.provider, name: credentialForm.name, account_id: credentialForm.account_id, owner: credentialForm.owner, default_region: credentialForm.default_region, auth_mode: credentialForm.auth_mode, access_key_id: credentialForm.access_key_id, access_key_secret: credentialForm.access_key_secret, role_arn: credentialForm.role_arn, project_id: credentialForm.project_id, description: credentialForm.description, is_enabled: credentialForm.is_enabled, demo_mode: credentialForm.demo_mode }; credentialDialog.editing ? await updateCloudCredential(credentialDialog.id, payload) : await createCloudCredential(payload); credentialDialog.visible = false; ElMessage.success('云账号已保存'); await refreshAll() } finally { loading.credentialSubmit = false } }
async function handleDeleteCredential(row) { await deleteCloudCredential(row.id); ElMessage.success('云账号已删除'); await refreshAll() }
async function handleTestCredential(row) { const result = await testCloudCredential(row.id); ElMessage.success(result.message); await Promise.all([loadCredentials(), loadOverview()]) }
async function handleSyncCredential(row) { const result = await syncCloudCredential(row.id); ElMessage.success(result.message); await refreshAll() }
function focusCredential(row) { activeTab.value = 'envs'; envFilter.provider = row.provider; void loadEnvironments() }

function openEnvironmentDialog(row = null) { Object.assign(envForm, row ? { credential: row.credential, name: row.name, code: row.code, business_line: row.business_line, environment_type: row.environment_type, region: row.region, zone: row.zone, vpc_name: row.vpc_name, network_cidr: row.network_cidr, owner: row.owner, description: row.description, tagsText: JSON.stringify(row.tags || {}) } : { credential: credentials.value[0]?.id || '', name: '', code: '', business_line: '', environment_type: 'prod', region: '', zone: '', vpc_name: '', network_cidr: '', owner: '', description: '', tagsText: '{}' }); envDialog.visible = true; envDialog.editing = !!row; envDialog.id = row?.id || null }
async function submitEnvironment() { if (!envForm.credential || !envForm.name || !envForm.code) return ElMessage.warning('请完善环境信息'); loading.envSubmit = true; try { const payload = { credential: envForm.credential, name: envForm.name, code: envForm.code, business_line: envForm.business_line, environment_type: envForm.environment_type, region: envForm.region, zone: envForm.zone, vpc_name: envForm.vpc_name, network_cidr: envForm.network_cidr, owner: envForm.owner, description: envForm.description, tags: parseJson(envForm.tagsText) }; envDialog.editing ? await updateCloudEnvironment(envDialog.id, payload) : await createCloudEnvironment(payload); envDialog.visible = false; ElMessage.success('云环境已保存'); await refreshAll() } finally { loading.envSubmit = false } }
async function handleDeleteEnvironment(row) { await deleteCloudEnvironment(row.id); ElMessage.success('云环境已删除'); await refreshAll() }
async function handleSyncEnvironment(row) { const result = await syncCloudEnvironment(row.id); ElMessage.success(result.message); await refreshAll() }
async function handleSyncEnvironmentCmdb(row) { const result = await syncCloudEnvironmentCmdb(row.id); ElMessage.success(result.message); await refreshAll() }
async function openDrawer(row) { drawer.record = row; drawer.visible = true; await loadAssets(row.id) }
async function runBatchAction(scope, action) { const ids = scope === 'credentials' ? selectedCredentialIds.value : scope === 'environments' ? selectedEnvironmentIds.value : selectedAssetIds.value; if (!ids.length) return; const result = await runMultiCloudBatchAction({ scope, action, ids }); ElMessage.success(result.message); await refreshAll() }

watch(activeTab, async value => {
  await nextTick()
  requestAnimationFrame(() => {
    if (value === 'overview') renderCostTrend()
    if (value === 'topology') renderTopology()
  })
})
onMounted(async () => { await loadCatalog(); await refreshAll(); window.addEventListener('resize', resizeCharts) })
onBeforeUnmount(() => { window.removeEventListener('resize', resizeCharts); costTrendChart?.dispose(); topologyChart?.dispose() })
</script>

<style scoped>
.multicloud-page { display: flex; flex-direction: column; gap: 10px; }
.filter-inline, .batch-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.panel { background: linear-gradient(180deg, #fff 0%, #f8fbff 100%); border: 1px solid #dbe4f0; border-radius: 24px; box-shadow: 0 14px 34px rgba(15,23,42,.06); padding: 14px 22px; }
.hero { background: linear-gradient(135deg, #fff7ed 0%, #f8fbff 100%); display: flex; gap: 12px; justify-content: space-between; }
.hero h2 { color: #0f172a; margin: 0; }
.subtitle { color: #475569; margin: 10px 0 0; max-width: 620px; }
.hero-actions { display: flex; gap: 12px; }
.release-hero-title-row { display: flex; align-items: center; gap: 12px; }
.release-hero-title-inline { flex-wrap: wrap; }
.inline-subtitle { margin: 0; max-width: none; font-size: 13px; line-height: 1.45; }
.release-header-icon { width: 42px; height: 42px; border-radius: 14px; display: inline-flex; align-items: center; justify-content: center; font-size: 20px; color: #fff; background: linear-gradient(135deg, #409eff, #36cfc9); box-shadow: 0 10px 20px rgba(64,158,255,.2); }
.page-badge, .page-subtitle, .release-hero-copy > h2, .release-hero-copy > .page-subtitle, .metric-grid { display: none; }
.muted-text { color: var(--text-secondary); }
.release-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.release-stat-card { position: relative; min-height: 76px; background: linear-gradient(145deg, #ffffff 0%, #f6faff 100%); border: 1px solid rgba(148,163,184,.18); box-shadow: 0 16px 34px rgba(15,23,42,.07); text-align: left; padding: 12px 16px; overflow: hidden; width: 100%; color: inherit; }
.release-stat-card::after { content: ''; position: absolute; inset: auto -24px -30px auto; width: 108px; height: 108px; border-radius: 50%; background: radial-gradient(circle, rgba(64,158,255,.16) 0%, rgba(64,158,255,0) 70%); }
.warning-card::after { background: radial-gradient(circle, rgba(245,158,11,.18) 0%, rgba(245,158,11,0) 70%); }
.success-card::after { background: radial-gradient(circle, rgba(16,185,129,.18) 0%, rgba(16,185,129,0) 70%); }
.danger-card::after { background: radial-gradient(circle, rgba(239,68,68,.18) 0%, rgba(239,68,68,0) 70%); }
.release-stat-card .stat-value { font-size: 26px; line-height: 1.05; }
.release-stat-card .stat-label { margin-top: 4px; color: #64748b; }
.card-panel { border-radius: 18px; background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.92)); box-shadow: 0 18px 36px rgba(15,23,42,.06); }
.module-tabs { margin-top: -8px; padding: 18px; border-radius: 20px; background: rgba(255,255,255,.86); box-shadow: 0 18px 36px rgba(15,23,42,.06); }
.grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; align-items: start; }
.card-panel { padding: 12px 16px; }
.card-panel--drawer { box-shadow: none; background: transparent; padding: 0; }
.section-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 10px; }
.section-head span { font-weight: 700; color: var(--text-primary); }
.section-head--drawer { margin-top: 16px; }
.suggest-list { display: flex; flex-direction: column; gap: 10px; min-height: 180px; }
.suggest-item { padding: 12px; border-radius: 14px; background: rgba(248,250,252,.9); border: 1px solid rgba(226,232,240,.9); }
.suggest-item strong { display: block; margin: 8px 0; }
.chart-block { width: 100%; height: 320px; }
.chart-block--topology { height: 560px; }
.overview-card--table :deep(.el-table th.el-table__cell),
.overview-card--table :deep(.el-table td.el-table__cell) { padding: 6px 0; }
.overview-card--table :deep(.el-table .cell) { font-size: 13px; }
.overview-card--governance .section-head { margin-bottom: 8px; }
.overview-card--governance .suggest-list { min-height: 152px; gap: 6px; }
.overview-card--governance .suggest-item { padding: 8px 10px; font-size: 12px; line-height: 1.4; }
.overview-card--governance .suggest-item strong { margin: 4px 0 2px; font-size: 12px; }
.overview-trend-card .section-head { margin-bottom: 10px; }
.overview-trend-card .chart-block { height: 280px; }
.batch-toolbar { margin-bottom: 12px; }
.topology-lane-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; padding: 12px 14px; border-radius: 16px; background: rgba(248,250,252,.8); border: 1px solid rgba(226,232,240,.9); }
.topology-lane-actions, .topology-lane-tags, .topology-lane-chip__meta { display: flex; align-items: center; gap: 10px; }
.topology-lane-tags { flex: 1; flex-wrap: wrap; justify-content: flex-end; }
.topology-lane-chip { display: inline-flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 168px; padding: 8px 12px; border: 1px solid rgba(203,213,225,.95); border-radius: 12px; background: rgba(255,255,255,.96); color: #334155; cursor: pointer; transition: all .18s ease; }
.topology-lane-chip:hover { border-color: rgba(59,130,246,.35); box-shadow: 0 10px 22px rgba(15,23,42,.06); transform: translateY(-1px); }
.topology-lane-chip.is-collapsed { background: rgba(241,245,249,.92); color: #64748b; border-color: rgba(148,163,184,.32); }
.topology-lane-chip__dot { width: 10px; height: 10px; border-radius: 999px; box-shadow: 0 0 0 3px rgba(255,255,255,.88); }
.topology-lane-chip__state { font-size: 12px; font-weight: 700; }
@media (max-width: 1200px) { .release-stats, .grid-2 { grid-template-columns: 1fr 1fr; } }
@media (max-width: 768px) { .hero { flex-direction: column; } .hero-actions { justify-content: flex-start; } .release-stats, .grid-2 { grid-template-columns: 1fr; } .chart-block--topology { height: 420px; } .topology-lane-toolbar, .topology-lane-tags { flex-direction: column; align-items: stretch; } .topology-lane-chip { width: 100%; } }
</style>
