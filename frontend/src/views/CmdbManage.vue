<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>🗄️ CMDB 配置管理</h2>
    </div>

    <!-- 主 Tab 栏 (Pill Tab Theme: Purple) -->
    <div class="neo-tabs theme-purple">
      <button v-for="tab in mainTabs" :key="tab.key" class="neo-tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <!-- ============ Tab 1: 配置项管理 ============ -->
    <div v-if="activeTab === 'items'" class="tab-content cmdb-items-layout">
      <!-- 左侧资源树 -->
      <div class="cmdb-resource-tree-panel">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <span style="font-weight:600;color:var(--text-primary,#e2e8f0);font-size:14px;cursor:pointer;" @click="clearTreeFilter" title="点击查看全部"><el-icon style="margin-right:4px;vertical-align:-2px;"><Connection /></el-icon>业务资源树</span>
          <el-button v-if="canManageCi" link type="primary" size="small" @click="openNodeDialog()">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <el-tree ref="treeRef" :data="resourceTree" :props="{label: 'name', children: 'children'}" node-key="id" @node-click="onNodeClick" highlight-current style="background:transparent;flex:1;overflow-y:auto;" :expand-on-click-node="false" default-expand-all>
          <template #default="{ node, data }">
            <div style="flex:1;display:flex;justify-content:space-between;align-items:center;font-size:13px;padding-right:8px;" class="custom-tree-node">
              <span>
                <el-icon v-if="data.node_type === 'biz'" style="color:#8b5cf6;margin-right:4px;"><Files /></el-icon>
                <el-icon v-else style="color:#10b981;margin-right:4px;"><Monitor /></el-icon>
                {{ node.label }}
              </span>
              <span class="tree-actions" @click.stop v-show="node.isCurrent || true">
                <el-button v-if="canManageCi && data.node_type === 'biz'" link type="success" style="padding:0;height:auto;" @click="openNodeDialog(null, data.id)"><el-icon><Plus /></el-icon></el-button>
                <el-button v-if="canManageCi" link type="primary" style="padding:0;margin-left:8px;height:auto;" @click="openNodeDialog(data)"><el-icon><Edit /></el-icon></el-button>
                <el-popconfirm v-if="canManageCi" title="确定删除?" @confirm="delNode(data)">
                  <template #reference><el-button link type="danger" style="padding:0;margin-left:8px;height:auto;"><el-icon><Delete /></el-icon></el-button></template>
                </el-popconfirm>
              </span>
            </div>
          </template>
        </el-tree>
      </div>

      <!-- 右侧主体 -->
      <div class="cmdb-items-main">
      <!-- 工具栏 -->
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <el-select v-model="filterType" placeholder="CI 类型" clearable style="width:130px" size="small" @change="fetchItems">
            <el-option v-for="t in ciTypes" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
          <el-select v-model="filterBusiness" placeholder="业务线" clearable style="width:120px" size="small" @change="fetchItems">
            <el-option v-for="b in bizLines" :key="b" :label="b" :value="b" />
          </el-select>
          <el-select v-model="filterEnv" placeholder="环境" clearable style="width:90px" size="small" @change="fetchItems">
            <el-option label="生产" value="prod" /><el-option label="测试" value="test" /><el-option label="开发" value="dev" />
          </el-select>
          <el-select v-model="filterStatus" placeholder="状态" clearable style="width:110px" size="small" @change="fetchItems">
            <el-option label="运行中" value="active" /><el-option label="已停用" value="inactive" />
            <el-option label="维护中" value="maintenance" /><el-option label="已下线" value="decommissioned" />
          </el-select>
          <el-input v-model="searchText" placeholder="搜索名称/IP/负责人" clearable style="width:200px" size="small" @clear="fetchItems" @keyup.enter="fetchItems">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>
        <div style="display:flex;gap:8px;">
          <el-button v-if="canManageCi" size="small" @click="openTypeDialog">管理类型</el-button>
          <el-button v-if="canManageCi" type="primary" size="small" @click="openItemDialog()"><el-icon><Plus /></el-icon> 新增配置项</el-button>
        </div>
      </div>

      <!-- 统计卡片 -->
      <div class="cmdb-stats-row" v-if="itemStats.total">
        <div class="cmdb-stat-card" v-for="tp in itemStats.by_type" :key="tp.ci_type__name">
          <div class="stat-dot" :style="{background: tp.ci_type__color}"></div>
          <div class="stat-info">
            <div class="stat-val">{{ tp.count }}</div>
            <div class="stat-label">{{ tp.ci_type__name }}</div>
          </div>
        </div>
      </div>

      <!-- 表格 -->
      <el-table :data="items" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="180">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='active'?'running':row.status==='maintenance'?'restarting':'exited'"></span>
              <el-icon :style="{color: row.ci_type_color}"><component :is="row.ci_type_icon" /></el-icon>
              <span style="font-weight:600">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="ci_type_name" label="类型" width="100">
          <template #default="{ row }"><el-tag size="small" :color="row.ci_type_color" style="color:#fff;border:none;">{{ row.ci_type_name }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="business_line" label="业务线" width="120" show-overflow-tooltip />
        <el-table-column prop="environment_display" label="环境" width="80">
          <template #default="{ row }"><el-tag size="small" :type="row.environment==='prod'?'danger':row.environment==='test'?'warning':'info'">{{ row.environment_display || envLabel(row.environment) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="IP" width="130">
          <template #default="{ row }">{{ row.attributes?.ip_address || '-' }}</template>
        </el-table-column>
        <el-table-column label="规格" width="120">
          <template #default="{ row }">
            <span v-if="row.attributes?.cpu" style="font-size:12px">{{ row.attributes.cpu }}C/{{ row.attributes.memory_gb }}G</span>
            <span v-else style="color:#94a3b8;font-size:12px">-</span>
          </template>
        </el-table-column>
        <el-table-column label="月成本" width="100">
          <template #default="{ row }"><span style="font-weight:600;color:#f59e0b">¥{{ row.attributes?.monthly_cost || 0 }}</span></template>
        </el-table-column>
        <el-table-column prop="admin_user" label="负责人" width="90">
          <template #default="{ row }">{{ row.admin_user || '-' }}</template>
        </el-table-column>
        <el-table-column prop="status_display" label="状态" width="80">
          <template #default="{ row }"><el-tag size="small" :type="row.status==='active'?'success':row.status==='maintenance'?'warning':'danger'">{{ row.status_display }}</el-tag></template>
        </el-table-column>
        <el-table-column v-if="canManageCi" label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openItemDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除此配置项？" @confirm="delItem(row)">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px;">
        <el-pagination size="small" background layout="prev,pager,next" :total="itemsTotal" :page-size="20" v-model:current-page="itemsPage" @current-change="fetchItems" />
      </div>
      </div>
    </div>

    <!-- ============ Tab 2: ???? ============ -->
    <div v-if="activeTab === 'topology'" class="tab-content">
      <CmdbTopologyPanel
        :ci-types="ciTypes"
        :resource-tree="resourceTree"
        :can-manage="canManageCi"
        @edit-ci="openTopologyItemEditor"
      />
    </div>

    <!-- ============ Tab 3: 成本分析 ============ -->
    <div v-if="activeTab === 'cost'" class="tab-content">
      <div class="cost-toolbar">
        <el-date-picker
          v-model="costMonth"
          type="month"
          value-format="YYYY-MM"
          placeholder="选择月份"
          style="width:160px"
          @change="fetchCostReport"
        />
        <el-button size="small" @click="fetchCostReport">刷新</el-button>
      </div>

      <div class="cost-summary-row">
        <div class="cost-card cost-card-total">
          <div class="cost-card-icon">💰</div>
          <div class="cost-card-body">
            <div class="cost-card-val">¥{{ formatCost(costReport.total_monthly_cost) }}</div>
            <div class="cost-card-label">月度总成本</div>
          </div>
        </div>
        <div class="cost-card cost-card-biz">
          <div class="cost-card-icon">🏢</div>
          <div class="cost-card-body">
            <div class="cost-card-val">{{ (costReport.by_business || []).length }}</div>
            <div class="cost-card-label">业务线数量</div>
          </div>
        </div>
        <div class="cost-card cost-card-top">
          <div class="cost-card-icon">🔥</div>
          <div class="cost-card-body">
            <div class="cost-card-val">{{ topCostBiz }}</div>
            <div class="cost-card-label">最高成本业务线</div>
          </div>
        </div>
        <div class="cost-card cost-card-items">
          <div class="cost-card-icon">📊</div>
          <div class="cost-card-body">
            <div class="cost-card-val">{{ (costReport.top_cost_items || []).length }}</div>
            <div class="cost-card-label">高成本资源数</div>
          </div>
        </div>
      </div>

      <div class="cost-charts-row">
        <div class="cost-chart-box">
          <div class="chart-title">💼 业务线成本分布</div>
          <div class="chart-bars">
            <div v-for="b in (costReport.by_business || [])" :key="b.business_line" class="bar-item">
              <div class="bar-label">{{ b.business_line }}</div>
              <div class="bar-track">
                <div class="bar-fill bar-fill-biz" :style="{ width: barWidth(b.total_cost, maxBizCost) + '%' }"></div>
              </div>
              <div class="bar-value">¥{{ formatCost(b.total_cost) }}</div>
            </div>
            <div v-if="!(costReport.by_business || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
        <div class="cost-chart-box">
          <div class="chart-title">🌐 环境成本分布</div>
          <div class="chart-bars">
            <div v-for="e in (costReport.by_environment || [])" :key="e.environment" class="bar-item">
              <div class="bar-label">{{ envLabel(e.environment) }}</div>
              <div class="bar-track">
                <div class="bar-fill bar-fill-env" :style="{ width: barWidth(e.total_cost, maxEnvCost) + '%' }"></div>
              </div>
              <div class="bar-value">¥{{ formatCost(e.total_cost) }}</div>
            </div>
            <div v-if="!(costReport.by_environment || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
      </div>

      <div class="cost-chart-box" style="margin-top:16px;">
        <div class="chart-title">📈 近 6 月成本趋势</div>
        <div class="trend-grid">
          <div v-for="point in (costReport.cost_trend || [])" :key="point.period" class="trend-item">
            <div class="trend-bar">
              <div class="trend-fill" :style="{ height: trendHeight(point.total, maxTrendCost) + '%' }"></div>
            </div>
            <div class="trend-label">{{ point.period }}</div>
            <div class="trend-value">¥{{ formatCost(point.total) }}</div>
          </div>
        </div>
      </div>

      <div class="cost-chart-box" style="margin-top:16px;">
        <div class="chart-title">🏆 成本 Top 10 资源</div>
        <el-table :data="costReport.top_cost_items || []" stripe size="small" style="width:100%">
          <el-table-column prop="name" label="资源名称" min-width="180" />
          <el-table-column prop="type_name" label="类型" width="100" />
          <el-table-column prop="business_line" label="业务线" width="120" />
          <el-table-column prop="environment" label="环境" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.environment === 'prod' ? 'danger' : row.environment === 'test' ? 'warning' : 'info'">
                {{ envLabel(row.environment) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="provider" label="供应商" width="120" />
          <el-table-column prop="monthly_cost" label="月成本" width="120">
            <template #default="{ row }"><span style="font-weight:700;color:#f59e0b;">¥{{ formatCost(row.monthly_cost) }}</span></template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- ============ Tab 4: 资源优化 ============ -->
    <div v-if="activeTab === 'optimize'" class="tab-content">
      <div class="cost-summary-row">
        <div class="cost-card cost-card-total" style="background:linear-gradient(135deg,#10b981 0%,#059669 100%)">
          <div class="cost-card-icon">⚡</div>
          <div class="cost-card-body">
            <div class="cost-card-val">¥{{ formatCost(optimization.total_potential_saving) }}</div>
            <div class="cost-card-label">潜在月节省</div>
          </div>
        </div>
        <div class="cost-card" style="background:linear-gradient(135deg,#f59e0b 0%,#d97706 100%)">
          <div class="cost-card-icon">📋</div>
          <div class="cost-card-body">
            <div class="cost-card-val">{{ optimization.suggestion_count || 0 }}</div>
            <div class="cost-card-label">优化建议</div>
          </div>
        </div>
      </div>

      <div v-if="!(optimization.suggestions||[]).length && !loading" class="empty-state">
        <el-icon :size="64" style="color:#94a3b8;margin-bottom:12px"><CircleCheck /></el-icon>
        <div style="font-size:16px;font-weight:600;color:#64748b;">暂无优化建议</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">所有资源运行良好，无需优化</div>
      </div>

      <div v-for="s in (optimization.suggestions || [])" :key="s.ci_id + s.type" class="opt-card" :class="'opt-' + s.severity">
        <div class="opt-icon">
          <span v-if="s.type==='downsize'">📉</span>
          <span v-else-if="s.type==='reclaim'">♻️</span>
          <span v-else>🧹</span>
        </div>
        <div class="opt-body">
          <div class="opt-title">{{ s.title }}</div>
          <div class="opt-detail">{{ s.detail }}</div>
        </div>
        <div class="opt-saving">
          <div class="opt-saving-val">¥{{ formatCost(s.potential_saving) }}/月</div>
          <el-tag :type="s.severity==='danger'?'danger':s.severity==='warning'?'warning':'info'" size="small">{{ s.severity==='danger'?'高优先':'中优先' }}</el-tag>
        </div>
      </div>
    </div>

    <!-- ============ Tab 5: 资源申请 ============ -->
    <div v-if="activeTab === 'requests'" class="tab-content">
      <div style="display:flex;justify-content:space-between;margin-bottom:12px;">
        <el-select v-model="reqStatusFilter" placeholder="状态筛选" clearable style="width:120px" size="small" @change="fetchRequests">
          <el-option label="待审批" value="pending" /><el-option label="已批准" value="approved" />
          <el-option label="已拒绝" value="rejected" /><el-option label="已完成" value="completed" />
        </el-select>
        <el-button v-if="canSubmitRequests" type="primary" size="small" @click="openRequestDialog"><el-icon><Plus /></el-icon> 新建申请</el-button>
      </div>
      <el-table :data="requests" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="title" label="申请标题" min-width="200">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='pending'?'restarting':row.status==='approved'?'running':'exited'"></span>
              <span style="font-weight:600">{{ row.title }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="resource_type" label="资源类型" width="100" />
        <el-table-column prop="specification" label="规格" width="140" show-overflow-tooltip />
        <el-table-column prop="business_line" label="业务线" width="120" />
        <el-table-column prop="environment_display" label="环境" width="80">
          <template #default="{ row }"><el-tag size="small" :type="row.environment==='production'?'danger':'info'">{{ row.environment_display }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="requester" label="申请人" width="80" />
        <el-table-column prop="status_display" label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status==='pending'?'warning':row.status==='approved'?'success':row.status==='completed'?'':'danger'">{{ row.status_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="申请时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="canApproveRequests" label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <template v-if="canApproveRequests && row.status==='pending'">
              <el-button link type="success" size="small" @click="doApprove(row)">批准</el-button>
              <el-button link type="danger" size="small" @click="doReject(row)">拒绝</el-button>
            </template>
            <el-button v-if="canApproveRequests && row.status==='approved'" link type="primary" size="small" @click="doComplete(row)">标记完成</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 配置项新增/编辑弹窗 ============ -->
    <el-dialog v-if="canManageCi" v-model="itemDialogVisible" :title="editingItemId ? '编辑配置项' : '新增配置项'" width="90%" style="max-width:640px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="itemForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="itemForm.name" placeholder="如 order-service-01" /></el-form-item>
        <el-form-item label="CI 类型">
          <el-select v-model="itemForm.ci_type" placeholder="选择类型" style="width:100%">
            <el-option v-for="t in ciTypes" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <div style="display:flex;gap:12px;">
          <el-form-item label="业务线" style="flex:1">
            <el-select v-model="itemForm.business_line" placeholder="选择业务线" clearable filterable style="width:100%" @change="itemForm.environment = ''">
              <el-option v-for="node in resourceTree.filter(n => n.node_type === 'biz')" :key="node.id" :label="node.name" :value="node.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="环境" style="flex:1">
            <el-select v-model="itemForm.environment" style="width:100%" placeholder="请先选择业务线" :disabled="!itemForm.business_line">
              <el-option v-for="env in getEnvOptionsForItemForm()" :key="env.id" :label="env.name" :value="env.name" />
            </el-select>
          </el-form-item>
        </div>
        <div style="display:flex;gap:12px;">
          <el-form-item label="IP" style="flex:1"><el-input v-model="itemForm.attributes.ip_address" placeholder="10.0.0.1" /></el-form-item>
          <el-form-item label="状态" style="flex:1">
            <el-select v-model="itemForm.status" style="width:100%">
              <el-option label="运行中" value="active" /><el-option label="已停用" value="inactive" />
              <el-option label="维护中" value="maintenance" /><el-option label="已下线" value="decommissioned" />
            </el-select>
          </el-form-item>
        </div>
        <div style="display:flex;gap:12px;">
          <el-form-item label="云厂商" style="flex:1"><el-input v-model="itemForm.attributes.cloud_provider" placeholder="阿里云" /></el-form-item>
          <el-form-item label="区域" style="flex:1"><el-input v-model="itemForm.attributes.region" placeholder="cn-beijing" /></el-form-item>
        </div>
        <div style="display:flex;gap:12px;">
          <el-form-item label="CPU (核)" style="flex:1"><el-input-number v-model="itemForm.attributes.cpu" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="内存 (GB)" style="flex:1"><el-input-number v-model="itemForm.attributes.memory_gb" :min="0" :precision="1" style="width:100%" /></el-form-item>
          <el-form-item label="磁盘 (GB)" style="flex:1"><el-input-number v-model="itemForm.attributes.disk_gb" :min="0" :precision="0" style="width:100%" /></el-form-item>
        </div>
        <div style="display:flex;gap:12px;">
          <el-form-item label="实例规格" style="flex:1"><el-input v-model="itemForm.attributes.instance_type" placeholder="ecs.c6.xlarge" /></el-form-item>
          <el-form-item label="月成本 (¥)" style="flex:1"><el-input-number v-model="itemForm.attributes.monthly_cost" :min="0" :precision="2" style="width:100%" /></el-form-item>
        </div>
        <el-form-item label="负责人"><el-input v-model="itemForm.admin_user" placeholder="张三" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="itemForm.attributes.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="itemDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveItem" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ 业务资源树节点管理的弹窗 ============ -->
    <el-dialog v-if="canManageCi" v-model="nodeDialogVisible" :title="editingNodeId ? '编辑节点' : '新增节点'" width="400px" top="15vh" append-to-body destroy-on-close>
      <el-form :model="nodeForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="nodeForm.name" placeholder="节点名称" />
        </el-form-item>
        <el-form-item label="节点类型" v-if="!editingNodeId">
          <el-radio-group v-model="nodeForm.node_type">
            <el-radio label="biz">业务线</el-radio>
            <el-radio label="env">环境</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="nodeForm.sort_order" :min="0" style="width:100%"/>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nodeDialogVisible = false" size="small">取消</el-button>
        <el-button type="primary" @click="saveNode" :loading="saving" size="small">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ CI 类型管理弹窗 ============ -->
    <el-dialog v-if="canManageCi" v-model="typeDialogVisible" title="管理 CI 类型" width="90%" style="max-width:500px;" top="5vh" append-to-body destroy-on-close>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <el-input v-model="newTypeName" placeholder="新类型名称" size="small" style="flex:1" />
        <el-button type="primary" size="small" @click="addType" :disabled="!newTypeName">添加</el-button>
      </div>
      <el-table :data="ciTypes" stripe size="small">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="ci_count" label="CI 数" width="70" />
        <el-table-column v-if="canManageCi" label="操作" width="80">
          <template #default="{ row }">
            <el-popconfirm title="确定删除?" @confirm="delType(row)" v-if="!row.built_in">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
            <span v-else style="font-size:12px;color:#94a3b8">内置</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- ============ 关系管理弹窗 ============ -->
    <el-dialog v-if="canSubmitRequests" v-model="requestDialogVisible" title="新建资源申请" width="90%" style="max-width:560px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="requestForm" label-width="80px">
        <el-form-item label="标题"><el-input v-model="requestForm.title" placeholder="申请标题" /></el-form-item>
        <div style="display:flex;gap:12px;">
          <el-form-item label="资源类型" style="flex:1"><el-input v-model="requestForm.resource_type" placeholder="ECS / RDS / Redis" /></el-form-item>
          <el-form-item label="规格" style="flex:1"><el-input v-model="requestForm.specification" placeholder="4C8G SSD100G" /></el-form-item>
        </div>
        <div style="display:flex;gap:12px;">
          <el-form-item label="业务线" style="flex:1"><el-input v-model="requestForm.business_line" /></el-form-item>
          <el-form-item label="环境" style="flex:1">
            <el-select v-model="requestForm.environment" style="width:100%">
              <el-option label="生产" value="production" /><el-option label="预发布" value="staging" />
              <el-option label="测试" value="testing" /><el-option label="开发" value="development" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="申请原因"><el-input v-model="requestForm.reason" type="textarea" :rows="3" placeholder="请说明用途和原因" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="requestDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRequest" :loading="saving">提交申请</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Search, CircleCheck, Files, Monitor, Edit, Delete, Connection } from '@element-plus/icons-vue'
import CmdbTopologyPanel from '@/components/cmdb/CmdbTopologyPanel.vue'
import { useAuthStore } from '@/stores/auth'
import {
  getCITypes, createCIType, deleteCIType,
  getConfigItems, createConfigItem, updateConfigItem, deleteConfigItem, getConfigItemStats,
  getResourceRequests, createResourceRequest, approveRequest, rejectRequest, completeRequest,
  getCmdbCostReport, getCmdbOptimization,
  getResourceNodeTree, createResourceNode, updateResourceNode, deleteResourceNode
} from '@/api/modules/cmdb'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const canViewCi = computed(() => authStore.hasPermission('cmdb.ci.view'))
const canManageCi = computed(() => authStore.hasPermission('cmdb.ci.manage'))
const canViewTopology = computed(() => authStore.hasPermission('cmdb.topology.view'))
const canViewCost = computed(() => authStore.hasPermission('cmdb.cost.view'))
const canSubmitRequests = computed(() => authStore.hasPermission('cmdb.request.submit'))
const canApproveRequests = computed(() => authStore.hasPermission('cmdb.request.approve'))

const mainTabs = computed(() => [
  canViewCi.value && { key: 'items', label: '配置项管理', icon: 'Grid' },
  canViewTopology.value && { key: 'topology', label: '资源地图', icon: 'Share' },
  canViewCost.value && { key: 'cost', label: '成本分析', icon: 'TrendCharts' },
  canViewCost.value && { key: 'optimize', label: '资源优化', icon: 'Lightning' },
  canViewCi.value && { key: 'requests', label: '资源申请', icon: 'Ticket' },
].filter(Boolean))

const activeTab = ref('items')

function getDefaultTab() {
  return mainTabs.value[0]?.key || 'items'
}

function normalizeTab(tab) {
  return mainTabs.value.some(item => item.key === tab) ? tab : getDefaultTab()
}
const loading = ref(false)
const saving = ref(false)

// ====== CI Types ======
const ciTypes = ref([])
async function fetchTypes() {
  try { ciTypes.value = await getCITypes() } catch(e) {}
}

// ====== 资源树 ======
const treeRef = ref(null)
const resourceTree = ref([])
const bizLines = computed(() => resourceTree.value
  .filter(node => node.node_type === 'biz')
  .map(node => node.name))
const nodeDialogVisible = ref(false)
const nodeForm = ref({})
const editingNodeId = ref(null)

function clearTreeFilter() {
  filterBusiness.value = null
  filterEnv.value = null
  if (treeRef.value) treeRef.value.setCurrentKey(null)
  fetchItems()
}

async function fetchResourceTree() {
  try { resourceTree.value = await getResourceNodeTree() } catch (e) {}
}

function openNodeDialog(nodeData = null, parentId = null) {
  if (!canManageCi.value) return
  if (nodeData) {
    editingNodeId.value = nodeData.id
    nodeForm.value = { ...nodeData }
  } else {
    editingNodeId.value = null
    nodeForm.value = { name: '', node_type: parentId ? 'env' : 'biz', parent: parentId, sort_order: 0 }
  }
  nodeDialogVisible.value = true
}

async function saveNode() {
  if (!canManageCi.value) return
  if (!nodeForm.value.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    if (editingNodeId.value) {
      await updateResourceNode(editingNodeId.value, nodeForm.value)
    } else {
      await createResourceNode(nodeForm.value)
    }
    ElMessage.success('保存成功')
    nodeDialogVisible.value = false
    fetchResourceTree()
  } catch(e) { ElMessage.error('保存失败') }
  saving.value = false
}

async function delNode(data) {
  if (!canManageCi.value) return
  try { await deleteResourceNode(data.id); ElMessage.success('已删除'); fetchResourceTree() } catch(e) { ElMessage.error('删除失败') }
}

function onNodeClick(data) {
  if (data.node_type === 'biz') {
    filterBusiness.value = data.name
    filterEnv.value = null
  } else if (data.node_type === 'env') {
    let parentBiz = null
    for (const biz of resourceTree.value) {
      if ((biz.children || []).some(e => e.id === data.id)) {
        parentBiz = biz.name
        break
      }
    }
    filterBusiness.value = parentBiz
    filterEnv.value = data.name
  }
  fetchItems()
}

// ====== Tab: 配置项管理 ======
const items = ref([])
const itemsTotal = ref(0)
const itemsPage = ref(1)
const filterType = ref(null)
const filterEnv = ref(null)
const filterBusiness = ref(null)
const filterStatus = ref(null)
const searchText = ref('')
const itemStats = ref({})

async function fetchItems() {
  loading.value = true
  try {
    const params = { page: itemsPage.value }
    if (filterType.value) params.ci_type = filterType.value
    if (filterEnv.value) params.environment = filterEnv.value
    if (filterBusiness.value) params.business_line = filterBusiness.value
    if (filterStatus.value) params.status = filterStatus.value
    if (searchText.value) params.search = searchText.value
    const res = await getConfigItems(params)
    items.value = res.results || res
    itemsTotal.value = res.count || items.value.length
    fetchItemStats(params)
  } catch(e) {}
  loading.value = false
}

async function fetchItemStats(params = {}) {
  try { itemStats.value = await getConfigItemStats(params) } catch(e) {}
}

// Item CRUD
const itemDialogVisible = ref(false)
const editingItemId = ref(null)
const itemForm = ref({})

function getEnvOptionsForItemForm() {
  if (!itemForm.value.business_line) return []
  const bizNode = resourceTree.value.find(n => n.name === itemForm.value.business_line && n.node_type === 'biz')
  return bizNode ? (bizNode.children || []) : []
}

function openItemDialog(item) {
  if (!canManageCi.value) return
  if (item) {
    editingItemId.value = item.id
    itemForm.value = { ...item, attributes: item.attributes || {} }
  } else {
    editingItemId.value = null
    itemForm.value = { name:'', ci_type:null, business_line:'', environment:'prod', status:'active', admin_user:'', attributes: { ip_address:'', cloud_provider:'', region:'', instance_type:'', cpu:0, memory_gb:0, disk_gb:0, monthly_cost:0, description:'' } }
  }
  itemDialogVisible.value = true
}

async function saveItem() {
  if (!canManageCi.value) return
  if (!itemForm.value.name) return ElMessage.warning('请填写名称')
  if (!itemForm.value.ci_type) return ElMessage.warning('请选择 CI 类型')
  saving.value = true
  try {
    if (editingItemId.value) {
      await updateConfigItem(editingItemId.value, itemForm.value)
      ElMessage.success('已更新')
    } else {
      await createConfigItem(itemForm.value)
      ElMessage.success('已创建')
    }
    itemDialogVisible.value = false
    fetchItems(); fetchItemStats()
  } catch(e) { ElMessage.error('操作失败') }
  saving.value = false
}

async function delItem(row) {
  if (!canManageCi.value) return
  try { await deleteConfigItem(row.id); ElMessage.success('已删除'); fetchItems(); fetchItemStats() } catch(e) { ElMessage.error('删除失败') }
}

// CI Type dialog
const typeDialogVisible = ref(false)
const newTypeName = ref('')
function openTypeDialog() {
  if (!canManageCi.value) return
  typeDialogVisible.value = true
}
async function addType() {
  if (!canManageCi.value) return
  if (!newTypeName.value) return
  try { await createCIType({ name: newTypeName.value }); ElMessage.success('已添加'); newTypeName.value = ''; fetchTypes() } catch(e) { ElMessage.error('添加失败') }
}
async function delType(row) {
  if (!canManageCi.value) return
  try { await deleteCIType(row.id); ElMessage.success('已删除'); fetchTypes() } catch(e) { ElMessage.error('该类型下有配置项，无法删除') }
}

// ====== Tab: 资源地图 ======
function openTopologyItemEditor(item) {
  if (!canManageCi.value) return
  openItemDialog(item)
}

function getCurrentMonth() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  return `${now.getFullYear()}-${month}`
}

const costMonth = ref(getCurrentMonth())
const costReport = ref({})
async function fetchCostReport() {
  loading.value = true
  try { costReport.value = await getCmdbCostReport({ month: costMonth.value }) } catch(e) {}
  loading.value = false
}
const topCostBiz = computed(() => {
  const biz = (costReport.value.by_business || [])[0]
  return biz ? biz.business_line : '-'
})
const maxBizCost = computed(() => Math.max(...(costReport.value.by_business || []).map(b => parseFloat(b.total_cost) || 0), 1))
const maxEnvCost = computed(() => Math.max(...(costReport.value.by_environment || []).map(e => parseFloat(e.total_cost) || 0), 1))
const maxTrendCost = computed(() => Math.max(...(costReport.value.cost_trend || []).map(point => parseFloat(point.total) || 0), 1))

function barWidth(val, max) { return max ? Math.max((parseFloat(val) / max) * 100, 2) : 2 }
function trendHeight(val, max) { return max ? Math.max((parseFloat(val) / max) * 100, 8) : 8 }
function formatCost(v) { return v ? parseFloat(v).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }) : '0' }
function envLabel(env) {
  return {
    prod: '生产',
    test: '测试',
    dev: '开发',
    production: '生产',
    staging: '预发布',
    testing: '测试',
    development: '开发',
  }[env] || env
}

// ====== Tab: 资源优化 ======
const optimization = ref({})
async function fetchOptimization() {
  loading.value = true
  try { optimization.value = await getCmdbOptimization({ month: costMonth.value }) } catch(e) {}
  loading.value = false
}

// ====== Tab: 资源申请 ======
const requests = ref([])
const reqStatusFilter = ref(null)
const requestDialogVisible = ref(false)
const requestForm = ref({})

async function fetchRequests() {
  loading.value = true
  try {
    const params = {}
    if (reqStatusFilter.value) params.status = reqStatusFilter.value
    const res = await getResourceRequests(params)
    requests.value = res.results || res
  } catch(e) {}
  loading.value = false
}

function openRequestDialog() {
  if (!canSubmitRequests.value) return
  requestForm.value = { title: '', resource_type: '', specification: '', business_line: '', environment: 'testing', reason: '' }
  requestDialogVisible.value = true
}
async function saveRequest() {
  if (!canSubmitRequests.value) return
  if (!requestForm.value.title || !requestForm.value.resource_type) return ElMessage.warning('请填写标题和资源类型')
  saving.value = true
  try { await createResourceRequest(requestForm.value); ElMessage.success('申请已提交'); requestDialogVisible.value = false; fetchRequests() } catch(e) { ElMessage.error('提交失败') }
  saving.value = false
}
async function doApprove(row) {
  if (!canApproveRequests.value) return
  try { await approveRequest(row.id, {}); ElMessage.success('已批准'); fetchRequests() } catch(e) { ElMessage.error('操作失败') }
}
async function doReject(row) {
  if (!canApproveRequests.value) return
  try { await rejectRequest(row.id, {}); ElMessage.success('已拒绝'); fetchRequests() } catch(e) { ElMessage.error('操作失败') }
}
async function doComplete(row) {
  if (!canApproveRequests.value) return
  try { await completeRequest(row.id); ElMessage.success('已完成'); fetchRequests() } catch(e) { ElMessage.error('操作失败') }
}

function formatTime(t) { return t ? new Date(t).toLocaleString('zh-CN') : '' }

// ====== Tab 切换 ======
function loadTabData(tab) {
  if (tab === 'items' && canViewCi.value) fetchItems()
  else if (tab === 'cost' && canViewCost.value) fetchCostReport()
  else if (tab === 'optimize' && canViewCost.value) fetchOptimization()
  else if (tab === 'requests' && canViewCi.value) fetchRequests()
}

function switchTab(tab) {
  const nextTab = normalizeTab(tab)
  if (activeTab.value === nextTab) return
  activeTab.value = nextTab
}

watch(mainTabs, (tabs) => {
  if (!tabs.length) return
  const routeTab = typeof route.query.tab === 'string' ? route.query.tab : ''
  const nextTab = normalizeTab(routeTab || activeTab.value)
  if (activeTab.value !== nextTab) {
    activeTab.value = nextTab
    return
  }
  if (routeTab !== nextTab) {
    router.replace({ query: { ...route.query, tab: nextTab } })
  }
}, { immediate: true })

watch(() => route.query.tab, (tab) => {
  const nextTab = normalizeTab(typeof tab === 'string' ? tab : '')
  if (activeTab.value !== nextTab) {
    activeTab.value = nextTab
  }
})

watch(activeTab, (tab) => {
  if (!tab) return
  if (route.query.tab !== tab) {
    router.replace({ query: { ...route.query, tab } })
  }
  loadTabData(tab)
}, { immediate: true })

onMounted(() => {
  if (canViewCi.value || canViewTopology.value) {
    fetchTypes()
    fetchResourceTree()
  }
})
</script>

<style scoped>
/* ====== 自定义树节点 ====== */
.custom-tree-node { transition: background 0.2s; border-radius: 4px; }
.custom-tree-node:hover { background: rgba(139,92,246,0.05); }
.tree-actions { opacity: 0; transition: opacity 0.2s; }
.el-tree-node__content:hover .tree-actions { opacity: 1; }
.cmdb-items-layout { display: flex; gap: 16px; }
.cmdb-resource-tree-panel {
  width: 188px;
  flex: 0 0 188px;
  border-right: 1px solid rgba(139,92,246,0.15);
  padding-right: 12px;
  display: flex;
  flex-direction: column;
}
.cmdb-items-main { flex: 1; min-width: 0; }

@media (max-width: 1200px) {
  .cmdb-resource-tree-panel {
    width: 176px;
    flex-basis: 176px;
  }
}

@media (max-width: 900px) {
  .cmdb-items-layout {
    flex-direction: column;
  }

  .cmdb-resource-tree-panel {
    width: 100%;
    flex-basis: auto;
    border-right: none;
    border-bottom: 1px solid rgba(139,92,246,0.15);
    padding-right: 0;
    padding-bottom: 12px;
  }
}

/* ====== 统计卡片行 ====== */
.cmdb-stats-row {
  display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap;
}
.cmdb-stat-card {
  display: flex; align-items: center; gap: 10px;
  background: var(--card-bg, #1e293b); border-radius: 10px; padding: 10px 16px;
  min-width: 110px; border: 1px solid rgba(139,92,246,0.15);
}
.stat-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.stat-val { font-size: 20px; font-weight: 700; color: var(--text-primary, #e2e8f0); }
.stat-label { font-size: 11px; color: #94a3b8; }

/* ====== 拓扑容器 ====== */
.topo-container {
  position: relative; background: var(--card-bg, #1e293b); border-radius: 12px;
  border: 1px solid rgba(139,92,246,0.15); min-height: 500px; overflow: hidden;
}
.topo-canvas { display: block; width: 100%; }
.topo-legend {
  position: absolute; top: 12px; right: 12px;
  background: rgba(15,23,42,0.85); border-radius: 8px; padding: 10px 14px;
  font-size: 12px; color: #94a3b8; min-width: 100px;
  backdrop-filter: blur(8px); border: 1px solid rgba(139,92,246,0.15);
}
.legend-title { font-weight: 700; color: #e2e8f0; margin-bottom: 6px; }
.legend-item { display: flex; align-items: center; gap: 6px; margin: 4px 0; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; }
.legend-line { width: 16px; height: 0; border-top: 2px; display: inline-block; border-color: #94a3b8; }
.legend-divider { height: 1px; background: rgba(148,163,184,0.2); margin: 6px 0; }
.topo-tooltip {
  position: absolute; background: rgba(15,23,42,0.92); border-radius: 8px; padding: 10px 14px;
  color: #e2e8f0; font-size: 13px; pointer-events: none; z-index: 10;
  backdrop-filter: blur(8px); border: 1px solid rgba(139,92,246,0.2);
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}

/* ====== 成本卡片 ====== */
.cost-toolbar { display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 12px; }
.cost-summary-row { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.cost-card {
  display: flex; align-items: center; gap: 14px; flex: 1; min-width: 200px;
  border-radius: 12px; padding: 18px 20px; color: #fff;
}
.cost-card-total { background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%); }
.cost-card-biz { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }
.cost-card-top { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); }
.cost-card-items { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
.cost-card-icon { font-size: 28px; }
.cost-card-val { font-size: 22px; font-weight: 700; }
.cost-card-label { font-size: 12px; opacity: 0.85; }

.cost-charts-row { display: flex; gap: 16px; flex-wrap: wrap; }
.cost-chart-box {
  flex: 1; min-width: 300px; background: var(--card-bg, #1e293b); border-radius: 12px;
  padding: 16px 20px; border: 1px solid rgba(139,92,246,0.12);
}
.chart-title { font-weight: 700; font-size: 14px; margin-bottom: 14px; color: var(--text-primary, #e2e8f0); }
.chart-bars { display: flex; flex-direction: column; gap: 10px; }
.bar-item { display: flex; align-items: center; gap: 10px; }
.bar-label { font-size: 12px; color: #94a3b8; width: 70px; text-align: right; flex-shrink: 0; }
.bar-track { flex: 1; height: 18px; background: rgba(148,163,184,0.1); border-radius: 9px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 9px; transition: width 0.5s ease; }
.bar-fill-biz { background: linear-gradient(90deg, #8b5cf6, #a78bfa); }
.bar-fill-env { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.bar-value { font-size: 12px; font-weight: 600; color: #f59e0b; width: 80px; }
.empty-chart { text-align: center; padding: 30px; color: #64748b; }
.trend-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 12px; align-items: end; min-height: 220px; }
.trend-item { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.trend-bar {
  width: 100%; max-width: 56px; height: 140px; display: flex; align-items: end; justify-content: center;
  padding: 6px; border-radius: 10px; background: rgba(148,163,184,0.08);
}
.trend-fill {
  width: 100%; border-radius: 8px 8px 4px 4px;
  background: linear-gradient(180deg, #22c55e 0%, #14b8a6 100%);
  transition: height 0.4s ease;
}
.trend-label { font-size: 12px; color: #94a3b8; }
.trend-value { font-size: 12px; font-weight: 600; color: var(--text-primary, #e2e8f0); }

/* ====== 优化建议 ====== */
.opt-card {
  display: flex; align-items: center; gap: 16px;
  background: var(--card-bg, #1e293b); border-radius: 12px; padding: 16px 20px;
  margin-bottom: 10px; border-left: 4px solid; transition: transform 0.15s;
}
.opt-card:hover { transform: translateX(4px); }
.opt-warning { border-left-color: #f59e0b; }
.opt-danger { border-left-color: #ef4444; }
.opt-info { border-left-color: #3b82f6; }
.opt-icon { font-size: 28px; }
.opt-body { flex: 1; }
.opt-title { font-weight: 700; font-size: 14px; color: var(--text-primary, #e2e8f0); }
.opt-detail { font-size: 12px; color: #94a3b8; margin-top: 4px; }
.opt-saving { text-align: right; }
.opt-saving-val { font-size: 18px; font-weight: 700; color: #10b981; margin-bottom: 4px; }

.empty-state { text-align: center; padding: 60px 20px; }

/* ====== 通用脉冲 (复用现有) ====== */
.state-pulse { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.state-pulse.running { background: #10b981; box-shadow: 0 0 6px #10b981; animation: pulse-green 2s infinite; }
.state-pulse.restarting { background: #f59e0b; box-shadow: 0 0 6px #f59e0b; animation: pulse-yellow 2s infinite; }
.state-pulse.exited { background: #64748b; }
@keyframes pulse-green { 0%,100% { box-shadow: 0 0 4px #10b981; } 50% { box-shadow: 0 0 12px #10b981; } }
@keyframes pulse-yellow { 0%,100% { box-shadow: 0 0 4px #f59e0b; } 50% { box-shadow: 0 0 12px #f59e0b; } }

.fade-in { animation: fadeInUp 0.3s ease; }
@keyframes fadeInUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
</style>
