<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>🗄️ CMDB 资产管理</h2>
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

    <!-- ============ Tab 2: 资源地图 ============ -->
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
          @change="refreshCostDashboard"
        />
        <el-button size="small" @click="refreshCostDashboard">刷新</el-button>
      </div>

      <div class="cost-summary-row">
        <div v-for="item in costSummaryCards" :key="item.label" class="cost-card" :class="item.className">
          <div class="cost-card-body">
            <div class="cost-card-val">{{ item.value }}</div>
            <div class="cost-card-label">{{ item.label }}</div>
          </div>
        </div>
      </div>

      <div class="cost-insight-row">
        <div v-for="item in costInsightCards" :key="item.label" class="cost-insight-card" :class="'tone-' + item.tone">
          <div class="cost-insight-label">{{ item.label }}</div>
          <div class="cost-insight-value">{{ item.value }}</div>
          <div class="cost-insight-detail">{{ item.detail }}</div>
        </div>
      </div>

      <div class="cost-brief-row">
        <div class="cost-chart-box cost-brief-box">
          <div class="chart-title">本月成本结论</div>
          <div class="focus-list">
            <div v-for="item in costFocusPoints" :key="item.title" class="focus-item">
              <div class="focus-item-title">{{ item.title }}</div>
              <div class="focus-item-detail">{{ item.detail }}</div>
            </div>
          </div>
        </div>
        <div class="cost-chart-box cost-brief-box">
          <div class="chart-title">供应商集中度</div>
          <div class="provider-focus-list">
            <div v-for="item in providerFocusList" :key="item.provider" class="provider-focus-item">
              <div class="provider-focus-main">
                <div class="provider-focus-name">{{ item.provider }}</div>
                <div class="provider-focus-detail">月成本 &yen;{{ formatCost(item.total_cost) }}</div>
              </div>
              <div class="provider-focus-share">{{ formatPercent(item.share) }}</div>
            </div>
            <div v-if="!providerFocusList.length" class="empty-chart">暂无供应商成本数据</div>
          </div>
        </div>
      </div>

      <div class="cost-charts-row">
        <div class="cost-chart-box">
          <div class="chart-title">业务线成本分布</div>
          <div class="chart-bars">
            <div v-for="b in (costReport.by_business || [])" :key="b.business_line" class="bar-item">
              <div class="bar-label">{{ b.business_line }}</div>
              <div class="bar-track">
                <div class="bar-fill bar-fill-biz" :style="{ width: barWidth(b.total_cost, maxBizCost) + '%' }"></div>
              </div>
              <div class="bar-value">&yen;{{ formatCost(b.total_cost) }}</div>
            </div>
            <div v-if="!(costReport.by_business || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
        <div class="cost-chart-box">
          <div class="chart-title">供应商成本分布</div>
          <div class="chart-bars">
            <div v-for="p in (costReport.by_provider || [])" :key="p.provider" class="bar-item">
              <div class="bar-label wide">{{ p.provider }}</div>
              <div class="bar-track">
                <div class="bar-fill bar-fill-provider" :style="{ width: barWidth(p.total_cost, maxProviderCost) + '%' }"></div>
              </div>
              <div class="bar-value">&yen;{{ formatCost(p.total_cost) }}</div>
            </div>
            <div v-if="!(costReport.by_provider || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
      </div>

      <div class="cost-charts-row" style="margin-top:16px;">
        <div class="cost-chart-box">
          <div class="chart-title">环境成本分布</div>
          <div class="chart-bars">
            <div v-for="e in (costReport.by_environment || [])" :key="e.environment" class="bar-item">
              <div class="bar-label">{{ envLabel(e.environment) }}</div>
              <div class="bar-track">
                <div class="bar-fill bar-fill-env" :style="{ width: barWidth(e.total_cost, maxEnvCost) + '%' }"></div>
              </div>
              <div class="bar-value">&yen;{{ formatCost(e.total_cost) }}</div>
            </div>
            <div v-if="!(costReport.by_environment || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
        <div class="cost-chart-box">
          <div class="chart-title">资源类型成本分布</div>
          <div class="chart-bars">
            <div v-for="t in (costReport.by_type || [])" :key="t.type_name" class="bar-item">
              <div class="bar-label wide">{{ t.type_name }}</div>
              <div class="bar-track">
                <div class="bar-fill bar-fill-type" :style="{ width: barWidth(t.total_cost, maxTypeCost) + '%' }"></div>
              </div>
              <div class="bar-value">&yen;{{ formatCost(t.total_cost) }}</div>
            </div>
            <div v-if="!(costReport.by_type || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
      </div>

      <div class="cost-trend-row">
        <div class="cost-chart-box cost-trend-box">
          <div class="chart-title">近 6 月成本趋势</div>
          <div class="trend-grid">
            <div v-for="point in (costReport.cost_trend || [])" :key="point.period" class="trend-item">
              <div class="trend-bar">
                <div class="trend-fill" :style="{ height: trendHeight(point.total, maxTrendCost) + '%' }"></div>
              </div>
              <div class="trend-label">{{ point.period }}</div>
              <div class="trend-value">&yen;{{ formatCost(point.total) }}</div>
              <div v-if="point.projected_total >= 0" class="trend-subvalue">优化后 &yen;{{ formatCost(point.projected_total) }}</div>
            </div>
          </div>
        </div>
        <div class="cost-chart-box cost-preview-box">
          <div class="chart-title">优化收益预览</div>
          <div class="preview-summary">
            <div class="preview-summary-item">
              <span>建议数</span>
              <strong>{{ costReport.optimization_preview?.suggestion_count || 0 }}</strong>
            </div>
            <div class="preview-summary-item">
              <span>节省占比</span>
              <strong>{{ formatPercent(costReport.optimization_preview?.saving_rate) }}</strong>
            </div>
            <div class="preview-summary-item">
              <span>预计月节省</span>
              <strong>&yen;{{ formatCost(costReport.optimization_preview?.total_potential_saving) }}</strong>
            </div>
          </div>
          <div class="cost-preview-list">
            <div v-for="item in (costReport.recommendations_preview || [])" :key="item.ci_id + item.type" class="cost-preview-item">
              <div class="cost-preview-main">
                <div class="cost-preview-title">{{ item.title }}</div>
                <div class="cost-preview-meta">{{ item.business_line }} · {{ item.ci_type }} · {{ item.admin_user }}</div>
              </div>
              <div class="cost-preview-saving">&yen;{{ formatCost(item.potential_saving) }}/月</div>
            </div>
            <div v-if="!(costReport.recommendations_preview || []).length" class="empty-chart">暂无可展示的优化建议</div>
          </div>
        </div>
      </div>

      <div class="cost-chart-box" style="margin-top:16px;">
        <div class="risk-toolbar">
          <div class="risk-toolbar-filters">
            <el-select v-model="costRiskFilterLevel" placeholder="风险等级" clearable size="small" style="width:110px">
              <el-option label="高风险" value="高" />
              <el-option label="中风险" value="中" />
              <el-option label="低风险" value="低" />
            </el-select>
            <el-select v-model="costRiskFilterStatus" placeholder="处置状态" clearable size="small" style="width:120px">
              <el-option label="待本周处理" value="urgent" />
              <el-option label="待排期执行" value="pending" />
              <el-option label="处理中" value="in_progress" />
              <el-option label="已完成" value="done" />
              <el-option label="持续观察" value="observe" />
            </el-select>
            <el-select v-model="costRiskSortKey" size="small" style="width:150px">
              <el-option label="按当前月成本排序" value="monthly_cost" />
              <el-option label="按节省金额排序" value="potential_saving" />
              <el-option label="按风险等级排序" value="risk_level" />
            </el-select>
          </div>
          <div class="risk-toolbar-meta">共 {{ filteredCostRiskTable.length }} 条风险项</div>
        </div>
        <div class="chart-title">成本风险清单</div>
        <el-table :data="filteredCostRiskTable" stripe size="small" style="width:100%">
          <el-table-column prop="name" label="资源名称" min-width="180" />
          <el-table-column prop="business_line" label="业务线" width="110" />
          <el-table-column prop="owner" label="责任人" width="120" show-overflow-tooltip />
          <el-table-column prop="risk_level" label="风险等级" width="96">
            <template #default="{ row }">
              <el-tag size="small" :type="row.risk_tag_type">{{ row.risk_level }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status_label" label="处置状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.status_tag_type">{{ row.status_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="monthly_cost" label="当前月成本" width="120">
            <template #default="{ row }"><span style="font-weight:700;color:#f59e0b;">&yen;{{ formatCost(row.monthly_cost) }}</span></template>
          </el-table-column>
          <el-table-column prop="potential_saving" label="预计月节省" width="120">
            <template #default="{ row }"><span style="font-weight:700;color:#10b981;">&yen;{{ formatCost(row.potential_saving) }}</span></template>
          </el-table-column>
          <el-table-column prop="action_hint" label="建议动作" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="opt-action-hint">{{ row.action_hint }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

    </div>

    <!-- ============ Tab 4: 资源优化 ============ -->
    <div v-if="activeTab === 'optimize'" class="tab-content">
      <div class="cost-summary-row">
        <div v-for="item in optimizationSummaryCards" :key="item.label" class="cost-card" :class="item.className">
          <div class="cost-card-body">
            <div class="cost-card-val">{{ item.value }}</div>
            <div class="cost-card-label">{{ item.label }}</div>
          </div>
        </div>
      </div>

      <div class="cost-insight-row">
        <div v-for="item in optimizationInsightCards" :key="item.label" class="cost-insight-card" :class="'tone-' + item.tone">
          <div class="cost-insight-label">{{ item.label }}</div>
          <div class="cost-insight-value">{{ item.value }}</div>
          <div class="cost-insight-detail">{{ item.detail }}</div>
        </div>
      </div>

      <div class="cost-charts-row">
        <div class="cost-chart-box">
          <div class="chart-title">节省来源拆分</div>
          <div class="chart-bars">
            <div v-for="item in (optimization.by_type || [])" :key="item.type" class="bar-item">
              <div class="bar-label wide">{{ item.label }}</div>
              <div class="bar-track">
                <div class="bar-fill bar-fill-saving" :style="{ width: barWidth(item.total_saving, maxOptimizationTypeSaving) + '%' }"></div>
              </div>
              <div class="bar-value">&yen;{{ formatCost(item.total_saving) }}</div>
            </div>
            <div v-if="!(optimization.by_type || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
        <div class="cost-chart-box">
          <div class="chart-title">优先级分布</div>
          <div class="severity-grid">
            <div v-for="item in (optimization.by_severity || [])" :key="item.severity" class="severity-card" :class="'severity-' + item.severity">
              <div class="severity-title">{{ item.label }}</div>
              <div class="severity-count">{{ item.count }} 项</div>
              <div class="severity-saving">&yen;{{ formatCost(item.total_saving) }}</div>
            </div>
            <div v-if="!(optimization.by_severity || []).length" class="empty-chart">暂无数据</div>
          </div>
        </div>
      </div>

      <div class="cost-chart-box" style="margin-top:16px;">
        <div class="chart-title">本月先做这几项</div>
        <div class="cost-preview-list">
          <div v-for="item in (optimization.quick_wins || [])" :key="item.ci_id + item.type + '-quick'" class="cost-preview-item">
            <div class="cost-preview-main">
              <div class="cost-preview-title">{{ item.title }}</div>
              <div class="cost-preview-meta">{{ item.type_label }} · {{ item.severity_label }} · {{ item.business_line }}</div>
            </div>
            <div class="cost-preview-saving">&yen;{{ formatCost(item.potential_saving) }}/月</div>
          </div>
          <div v-if="!(optimization.quick_wins || []).length" class="empty-chart">暂无可执行的 quick win</div>
        </div>
      </div>

      <div class="cost-trend-row" style="margin-top:16px;">
        <div class="cost-chart-box">
          <div class="chart-title">落地执行节奏</div>
          <div class="execution-plan">
            <div v-for="item in optimizationExecutionPlan" :key="item.stage" class="execution-step">
              <div class="execution-stage">{{ item.stage }}</div>
              <div class="execution-title">{{ item.title }}</div>
              <div class="execution-detail">{{ item.detail }}</div>
              <div class="execution-metrics">
                <span>{{ item.count }} 项建议</span>
                <strong>&yen;{{ formatCost(item.saving) }}</strong>
              </div>
            </div>
          </div>
        </div>
        <div class="cost-chart-box cost-preview-box">
          <div class="chart-title">节省排行榜</div>
          <div class="leaderboard-list">
            <div v-for="(item, index) in optimizationLeaderboard" :key="item.ci_id + item.type + '-rank'" class="leaderboard-item">
              <div class="leaderboard-rank">{{ index + 1 }}</div>
              <div class="leaderboard-main">
                <div class="leaderboard-title">{{ item.ci_name }}</div>
                <div class="leaderboard-detail">{{ item.type_label }} · {{ item.business_line }} · {{ item.admin_user }}</div>
              </div>
              <div class="leaderboard-saving">&yen;{{ formatCost(item.potential_saving) }}</div>
            </div>
            <div v-if="!optimizationLeaderboard.length" class="empty-chart">暂无排行榜数据</div>
          </div>
        </div>
      </div>

      <div v-if="!(optimization.suggestions||[]).length && !loading" class="empty-state">
        <el-icon :size="64" style="color:#94a3b8;margin-bottom:12px"><CircleCheck /></el-icon>
        <div style="font-size:16px;font-weight:600;color:#64748b;">暂无优化建议</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;">所有资源运行良好，无需优化</div>
      </div>

      <div v-if="optimizationSuggestionsDetailed.length" class="opt-filter-bar">
        <div class="risk-toolbar-filters">
          <el-select v-model="optimizationFilterSeverity" placeholder="优先级" clearable size="small" style="width:110px">
            <el-option label="高优先" value="danger" />
            <el-option label="中优先" value="warning" />
            <el-option label="治理项" value="info" />
          </el-select>
          <el-select v-model="optimizationFilterType" placeholder="建议类型" clearable size="small" style="width:130px">
            <el-option label="资源回收" value="reclaim" />
            <el-option label="定时启停" value="schedule" />
            <el-option label="规格缩容" value="downsize" />
            <el-option label="存储分层" value="storage" />
            <el-option label="归属治理" value="governance" />
          </el-select>
          <el-select v-model="optimizationFilterExecution" placeholder="落地状态" clearable size="small" style="width:120px">
            <el-option label="待排期执行" value="pending" />
            <el-option label="待本周处理" value="urgent" />
            <el-option label="处理中" value="in_progress" />
            <el-option label="已完成" value="done" />
          </el-select>
          <el-select v-model="optimizationSortKey" size="small" style="width:150px">
            <el-option label="按节省金额排序" value="potential_saving" />
            <el-option label="按优先级排序" value="severity" />
            <el-option label="按回收周期排序" value="recovery_period" />
          </el-select>
        </div>
        <div class="risk-toolbar-meta">当前展示 {{ filteredOptimizationSuggestions.length }} / {{ optimizationSuggestionsDetailed.length }} 条建议</div>
      </div>

      <div v-for="s in filteredOptimizationSuggestions" :key="s.ci_id + s.type" class="opt-card" :class="'opt-' + s.severity">
        <div class="opt-icon">{{ optimizationIcon(s.type) }}</div>
        <div class="opt-body">
          <div class="opt-title-row">
            <div class="opt-title">{{ s.title }}</div>
            <div class="opt-tags">
              <el-tag size="small" effect="plain">{{ s.type_label }}</el-tag>
              <el-tag size="small" :type="s.severity==='danger'?'danger':s.severity==='warning'?'warning':'info'">{{ s.severity_label }}</el-tag>
            </div>
          </div>
          <div class="opt-detail">{{ s.detail }}</div>
          <div class="opt-meta-row">
            <span>{{ s.business_line }}</span>
            <span>{{ envLabel(s.environment) }}</span>
            <span>{{ s.ci_type }}</span>
            <span>{{ s.admin_user }}</span>
          </div>
          <div class="opt-action">建议动作：{{ s.action }}</div>
          <div class="opt-evidence">判断依据：{{ s.evidence }}</div>
          <div class="opt-plan-row">
            <div class="opt-plan-item">
              <span class="opt-plan-label">执行人</span>
              <strong>{{ s.executor }}</strong>
            </div>
            <div class="opt-plan-item">
              <span class="opt-plan-label">预计回收周期</span>
              <strong>{{ s.recovery_period }}</strong>
            </div>
            <div class="opt-plan-item">
              <span class="opt-plan-label">落地状态</span>
              <el-tag size="small" effect="plain" :type="s.execution_status_type">{{ s.execution_status }}</el-tag>
            </div>
          </div>
          <div class="opt-card-actions">
            <el-button size="small" @click="markSuggestionStatus(s, 'in_progress')">标记处理中</el-button>
            <el-button size="small" type="success" @click="markSuggestionStatus(s, 'done')">标记完成</el-button>
            <el-button size="small" link @click="markSuggestionStatus(s, 'pending')">重置</el-button>
          </div>
        </div>
        <div class="opt-saving">
          <div class="opt-metric-label">当前月成本</div>
          <div class="opt-cost-now">&yen;{{ formatCost(s.monthly_cost) }}</div>
          <div class="opt-metric-label">预计月节省</div>
          <div class="opt-saving-val">&yen;{{ formatCost(s.potential_saving) }}/月</div>
          <div class="opt-metric-label">优化后</div>
          <div class="opt-cost-after">&yen;{{ formatCost(s.optimized_monthly_cost) }}/月</div>
        </div>
      </div>

      <div class="cost-chart-box" style="margin-top:16px;">
        <div class="chart-title">已完成节省归档</div>
        <div class="archive-summary-row">
          <div class="archive-summary-item">
            <span>已完成建议</span>
            <strong>{{ completedSuggestions.length }} 项</strong>
          </div>
          <div class="archive-summary-item">
            <span>已锁定月节省</span>
            <strong>&yen;{{ formatCost(completedSavingsSummary.monthly) }}</strong>
          </div>
          <div class="archive-summary-item">
            <span>折算年化收益</span>
            <strong>&yen;{{ formatCost(completedSavingsSummary.annual) }}</strong>
          </div>
        </div>
        <div class="archive-list">
          <div v-for="item in completedSuggestions" :key="item.ci_id + item.type + '-done'" class="archive-item">
            <div class="archive-item-main">
              <div class="archive-item-title">{{ item.ci_name }}</div>
              <div class="archive-item-detail">{{ item.type_label }} · {{ item.business_line }} · {{ item.executor }} · 完成于 {{ formatArchiveTime(item.completed_at) }}</div>
            </div>
            <div class="archive-item-metrics">
              <span>月节省 &yen;{{ formatCost(item.potential_saving) }}</span>
              <strong>优化后 &yen;{{ formatCost(item.optimized_monthly_cost) }}</strong>
            </div>
          </div>
          <div v-if="!completedSuggestions.length" class="empty-chart">当前还没有归档完成的优化建议</div>
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
const optimization = ref({})
const optimizationExecutionState = ref({})
const costRiskFilterLevel = ref('')
const costRiskFilterStatus = ref('')
const costRiskSortKey = ref('monthly_cost')
const optimizationFilterSeverity = ref('')
const optimizationFilterType = ref('')
const optimizationFilterExecution = ref('')
const optimizationSortKey = ref('potential_saving')

function getSuggestionStorageKey() {
  return `cmdb-optimization-status:${costMonth.value}`
}

function loadSuggestionStatusState() {
  try {
    optimizationExecutionState.value = JSON.parse(localStorage.getItem(getSuggestionStorageKey()) || '{}')
  } catch (e) {
    optimizationExecutionState.value = {}
  }
}

function persistSuggestionStatusState() {
  localStorage.setItem(getSuggestionStorageKey(), JSON.stringify(optimizationExecutionState.value))
}

function suggestionKey(item) {
  return `${item.ci_id}:${item.type}`
}

function getSuggestionState(item) {
  return optimizationExecutionState.value[suggestionKey(item)]
}

async function refreshCostDashboard() {
  loading.value = true
  try {
    const [reportResult, optimizationResult] = await Promise.allSettled([
      getCmdbCostReport({ month: costMonth.value }),
      getCmdbOptimization({ month: costMonth.value }),
    ])
    if (reportResult.status === 'fulfilled') {
      costReport.value = reportResult.value || {}
    }
    if (optimizationResult.status === 'fulfilled') {
      optimization.value = optimizationResult.value || {}
    }
    loadSuggestionStatusState()
  } catch (e) {
  } finally {
    loading.value = false
  }
}

async function fetchCostReport() {
  await refreshCostDashboard()
}

async function fetchOptimization() {
  await refreshCostDashboard()
}

function toNumber(value) {
  const parsed = parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function sumBy(items, field) {
  return (items || []).reduce((total, item) => total + toNumber(item?.[field]), 0)
}

const costSummary = computed(() => {
  const total = toNumber(costReport.value.total_monthly_cost)
    || sumBy(costReport.value.by_business, 'total_cost')
    || sumBy(costReport.value.top_cost_items, 'monthly_cost')
  const potentialSaving = toNumber(costReport.value.total_potential_saving)
    || toNumber(costReport.value.optimization_preview?.total_potential_saving)
    || toNumber(optimization.value.total_potential_saving)
  const optimizedMonthlyCost = toNumber(costReport.value.optimized_monthly_cost)
    || toNumber(costReport.value.optimization_preview?.optimized_monthly_cost)
    || toNumber(optimization.value.optimized_monthly_cost)
    || Math.max(total - potentialSaving, 0)
  const annualizedSaving = toNumber(costReport.value.annualized_saving)
    || toNumber(costReport.value.optimization_preview?.annualized_saving)
    || toNumber(optimization.value.annualized_saving)
    || (potentialSaving * 12)
  const topBusiness = (costReport.value.by_business || [])[0] || {}
  const topProvider = (costReport.value.by_provider || [])[0] || {}
  const nonProdCost = toNumber(costReport.value.non_prod_cost_total)
    || (costReport.value.by_environment || [])
      .filter(item => ['dev', 'test', 'development', 'testing'].includes(item.environment))
      .reduce((totalCost, item) => totalCost + toNumber(item.total_cost), 0)
  return {
    total,
    potentialSaving,
    optimizedMonthlyCost,
    annualizedSaving,
    savingRate: toNumber(costReport.value.saving_rate)
      || toNumber(costReport.value.optimization_preview?.saving_rate)
      || toNumber(optimization.value.saving_rate),
    topBusinessLine: costReport.value.top_business_line || topBusiness.business_line || '-',
    topBusinessCost: toNumber(costReport.value.top_business_cost) || toNumber(topBusiness.total_cost),
    topProvider: costReport.value.top_provider || topProvider.provider || '-',
    topProviderCost: toNumber(costReport.value.top_provider_cost) || toNumber(topProvider.total_cost),
    nonProdCost,
    nonProdCostRatio: toNumber(costReport.value.non_prod_cost_ratio) || (total ? (nonProdCost / total) * 100 : 0),
    suggestionCount: toNumber(costReport.value.optimization_preview?.suggestion_count)
      || toNumber(optimization.value.suggestion_count)
      || (optimization.value.suggestions || []).length,
  }
})

const optimizationSummary = computed(() => {
  const total = toNumber(optimization.value.total_monthly_cost) || costSummary.value.total
  const potentialSaving = toNumber(optimization.value.total_potential_saving)
    || costSummary.value.potentialSaving
    || sumBy(optimization.value.suggestions, 'potential_saving')
  const optimizedMonthlyCost = toNumber(optimization.value.optimized_monthly_cost)
    || costSummary.value.optimizedMonthlyCost
    || Math.max(total - potentialSaving, 0)
  const suggestionCount = toNumber(optimization.value.suggestion_count)
    || (optimization.value.suggestions || []).length
    || costSummary.value.suggestionCount
  return {
    total,
    potentialSaving,
    optimizedMonthlyCost,
    suggestionCount,
  }
})

const costSummaryCards = computed(() => ([
  { label: '月度总成本', value: `¥${formatCost(costSummary.value.total)}`, className: 'cost-card-total' },
  { label: '本月可优化空间', value: `¥${formatCost(costSummary.value.potentialSaving)}`, className: 'cost-card-saving' },
  { label: '优化后预计月成本', value: `¥${formatCost(costSummary.value.optimizedMonthlyCost)}`, className: 'cost-card-optimized' },
  { label: '年化可节省', value: `¥${formatCost(costSummary.value.annualizedSaving)}`, className: 'cost-card-annual' },
]))

const optimizationSummaryCards = computed(() => ([
  { label: '当前覆盖月成本', value: `¥${formatCost(optimizationSummary.value.total)}`, className: 'cost-card-total optimize-card-total' },
  { label: '潜在月节省', value: `¥${formatCost(optimizationSummary.value.potentialSaving)}`, className: 'cost-card-saving' },
  { label: '优化后预计月成本', value: `¥${formatCost(optimizationSummary.value.optimizedMonthlyCost)}`, className: 'cost-card-optimized' },
  { label: '待处理优化建议', value: `${optimizationSummary.value.suggestionCount} 项`, className: 'cost-card-annual' },
]))

const optimizationInsightCards = computed(() => {
  const quickWins = optimization.value.quick_wins || []
  const topSuggestion = quickWins[0] || optimization.value.suggestions?.[0]
  const dangerGroup = (optimization.value.by_severity || []).find(item => item.severity === 'danger') || {}
  const topBusiness = (optimization.value.by_business || [])[0] || {}
  const quickWinSaving = quickWins.reduce((total, item) => total + toNumber(item.potential_saving), 0)
  return [
    {
      label: '高优先节省池',
      value: `¥${formatCost(dangerGroup.total_saving)}`,
      detail: `${dangerGroup.count || 0} 项高优先建议，建议先处理可直接回收或缩容的资源。`,
      tone: 'danger',
    },
    {
      label: '首要优化业务线',
      value: topBusiness.business_line || '-',
      detail: `预计可释放 ¥${formatCost(topBusiness.total_saving)} / 月，优先安排该业务线做成本 review。`,
      tone: 'warning',
    },
    {
      label: 'Quick Win 收益',
      value: `¥${formatCost(quickWinSaving)}`,
      detail: `前 ${quickWins.length || 0} 项建议合计节省空间，适合本月直接落地。`,
      tone: 'success',
    },
    {
      label: '最大单项机会',
      value: topSuggestion ? `¥${formatCost(topSuggestion.potential_saving)}` : '-',
      detail: topSuggestion ? `${topSuggestion.ci_name}：${topSuggestion.type_label}，优化后月成本 ¥${formatCost(topSuggestion.optimized_monthly_cost)}。` : '当前没有可展示的单项优化建议。',
      tone: 'info',
    },
  ]
})

const costFocusPoints = computed(() => {
  const preview = costReport.value.recommendations_preview || []
  const headline = preview[0]
  return [
    {
      title: '成本重心集中在核心业务',
      detail: `${costSummary.value.topBusinessLine} 当前月成本 ¥${formatCost(costSummary.value.topBusinessCost)}，仍是本月最需要跟进的预算池。`,
    },
    {
      title: '非生产资源有明显压缩空间',
      detail: `测试与开发环境当前占用 ¥${formatCost(costSummary.value.nonProdCost)}，建议优先落实定时启停和空闲资源回收。`,
    },
    {
      title: '本月最值得先落地的动作',
      detail: headline ? `${headline.title}，预计可节省 ¥${formatCost(headline.potential_saving)} / 月。` : '当前暂无可展示的优化动作。',
    },
  ]
})

const providerFocusList = computed(() => {
  const total = costSummary.value.total || 1
  return (costReport.value.by_provider || []).slice(0, 4).map(item => ({
    ...item,
    share: (toNumber(item.total_cost) / total) * 100,
  }))
})

const optimizationExecutionPlan = computed(() => {
  const suggestions = optimization.value.suggestions || []
  const stages = [
    {
      stage: '第 1 周',
      title: '先做直接省钱的 quick win',
      items: suggestions.slice(0, 2),
    },
    {
      stage: '第 2 周',
      title: '处理缩容与定时启停',
      items: suggestions.slice(2, 5),
    },
    {
      stage: '第 3 周',
      title: '补齐治理并安排持续 review',
      items: suggestions.slice(5, 9),
    },
  ]
  return stages.map(stage => {
    const saving = stage.items.reduce((total, item) => total + toNumber(item.potential_saving), 0)
    return {
      stage: stage.stage,
      title: stage.title,
      count: stage.items.length,
      saving,
      detail: stage.items.length
        ? stage.items.map(item => item.ci_name).slice(0, 3).join('、')
        : '暂无待安排项',
    }
  })
})

const optimizationLeaderboard = computed(() => (optimization.value.suggestions || []).slice(0, 5))
const optimizationSuggestionsDetailed = computed(() => (optimization.value.suggestions || []).map(item => {
  const execution = executionStatusFor(item)
  const rawState = getSuggestionState(item)
  return {
    ...item,
    executor: item.admin_user || '待认领',
    recovery_period: recoveryPeriodFor(item),
    execution_status: execution.label,
    execution_status_type: execution.type,
    execution_status_code: execution.code,
    completed_at: typeof rawState === 'object' ? rawState.updated_at : '',
  }
}))
const costRiskTable = computed(() => {
  const suggestionMap = new Map((optimization.value.suggestions || []).map(item => [item.ci_id, item]))
  return (costReport.value.top_cost_items || []).map(item => {
    const suggestion = suggestionMap.get(item.ci_id)
    const execution = suggestion ? executionStatusFor(suggestion) : { code: 'observe', label: '持续观察', type: '' }
    const risk = riskLevelFor(toNumber(item.monthly_cost), toNumber(suggestion?.potential_saving), item.environment, suggestion?.severity)
    return {
      ...item,
      owner: suggestion?.admin_user || '待认领',
      potential_saving: toNumber(suggestion?.potential_saving),
      action_hint: suggestion?.action || '纳入月度账单 review，确认是否存在缩容或回收机会',
      risk_level: risk.label,
      risk_tag_type: risk.type,
      status_code: execution.code,
      status_label: execution.label,
      status_tag_type: execution.type,
    }
  })
})
const filteredCostRiskTable = computed(() => {
  const levelOrder = { 高: 3, 中: 2, 低: 1 }
  const rows = costRiskTable.value.filter(item => {
    if (costRiskFilterLevel.value && item.risk_level !== costRiskFilterLevel.value) return false
    if (costRiskFilterStatus.value && item.status_code !== costRiskFilterStatus.value) return false
    return true
  })
  return [...rows].sort((a, b) => {
    if (costRiskSortKey.value === 'potential_saving') return toNumber(b.potential_saving) - toNumber(a.potential_saving)
    if (costRiskSortKey.value === 'risk_level') return (levelOrder[b.risk_level] || 0) - (levelOrder[a.risk_level] || 0)
    return toNumber(b.monthly_cost) - toNumber(a.monthly_cost)
  })
})
const filteredOptimizationSuggestions = computed(() => {
  const severityOrder = { danger: 3, warning: 2, info: 1 }
  const periodOrder = { '1-3 天': 1, '1 周内': 2, '2 周内': 3, '2-4 周': 4, '本月内': 5 }
  const rows = optimizationSuggestionsDetailed.value.filter(item => {
    if (optimizationFilterSeverity.value && item.severity !== optimizationFilterSeverity.value) return false
    if (optimizationFilterType.value && item.type !== optimizationFilterType.value) return false
    if (optimizationFilterExecution.value === 'urgent' && item.execution_status !== '待本周处理') return false
    if (optimizationFilterExecution.value && optimizationFilterExecution.value !== 'urgent' && item.execution_status_code !== optimizationFilterExecution.value) return false
    return true
  })
  return [...rows].sort((a, b) => {
    if (optimizationSortKey.value === 'severity') return (severityOrder[b.severity] || 0) - (severityOrder[a.severity] || 0)
    if (optimizationSortKey.value === 'recovery_period') return (periodOrder[a.recovery_period] || 99) - (periodOrder[b.recovery_period] || 99)
    return toNumber(b.potential_saving) - toNumber(a.potential_saving)
  })
})
const completedSuggestions = computed(() => optimizationSuggestionsDetailed.value
  .filter(item => item.execution_status_code === 'done')
  .sort((a, b) => new Date(b.completed_at || 0).getTime() - new Date(a.completed_at || 0).getTime()))
const completedSavingsSummary = computed(() => {
  const monthly = completedSuggestions.value.reduce((total, item) => total + toNumber(item.potential_saving), 0)
  return {
    monthly,
    annual: monthly * 12,
  }
})

const topCostBiz = computed(() => costSummary.value.topBusinessLine)
const maxBizCost = computed(() => Math.max(...(costReport.value.by_business || []).map(b => parseFloat(b.total_cost) || 0), 1))
const maxEnvCost = computed(() => Math.max(...(costReport.value.by_environment || []).map(e => parseFloat(e.total_cost) || 0), 1))
const maxTypeCost = computed(() => Math.max(...(costReport.value.by_type || []).map(t => parseFloat(t.total_cost) || 0), 1))
const maxProviderCost = computed(() => Math.max(...(costReport.value.by_provider || []).map(p => parseFloat(p.total_cost) || 0), 1))
const maxTrendCost = computed(() => Math.max(...(costReport.value.cost_trend || []).map(point => Math.max(parseFloat(point.total) || 0, parseFloat(point.projected_total) || 0)), 1))
const maxOptimizationTypeSaving = computed(() => Math.max(...(optimization.value.by_type || []).map(item => parseFloat(item.total_saving) || 0), 1))
const costInsightCards = computed(() => {
  const topBusinessShare = costSummary.value.total
    ? (costSummary.value.topBusinessCost / costSummary.value.total) * 100
    : 0
  return [
    {
      label: '最高成本业务线',
      value: topCostBiz.value,
      detail: `月成本 ¥${formatCost(costSummary.value.topBusinessCost)}，占比 ${formatPercent(topBusinessShare)}`,
      tone: 'warning',
    },
    {
      label: '非生产环境成本',
      value: `¥${formatCost(costSummary.value.nonProdCost)}`,
      detail: `占总成本 ${formatPercent(costSummary.value.nonProdCostRatio)}，适合优先启用定时启停`,
      tone: 'info',
    },
    {
      label: '主要供应商',
      value: costSummary.value.topProvider,
      detail: `当前月成本 ¥${formatCost(costSummary.value.topProviderCost)}，便于按供应商做折扣谈判`,
      tone: 'success',
    },
    {
      label: '优化建议覆盖',
      value: `${costSummary.value.suggestionCount} 项`,
      detail: `优化后预计月成本 ¥${formatCost(costSummary.value.optimizedMonthlyCost)}，可节省 ${formatPercent(costSummary.value.savingRate)}`,
      tone: 'danger',
    },
  ]
})

function barWidth(val, max) { return max ? Math.max((parseFloat(val) / max) * 100, 2) : 2 }
function trendHeight(val, max) { return max ? Math.max((parseFloat(val) / max) * 100, 8) : 8 }
function formatCost(v) { return toNumber(v).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }) }
function formatPercent(v) {
  const value = parseFloat(v) || 0
  return `${value.toLocaleString('zh-CN', { minimumFractionDigits: value % 1 ? 1 : 0, maximumFractionDigits: 1 })}%`
}
function formatArchiveTime(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function executionStatusFor(item) {
  const rawState = getSuggestionState(item)
  const code = (typeof rawState === 'string' ? rawState : rawState?.status) || (item?.severity === 'danger' ? 'urgent' : 'pending')
  const statusMap = {
    urgent: { code: 'urgent', label: '待本周处理', type: 'danger' },
    pending: { code: 'pending', label: item?.type === 'governance' ? '待补齐信息' : item?.type === 'storage' ? '待制定方案' : '待排期执行', type: item?.type === 'governance' ? 'info' : 'warning' },
    in_progress: { code: 'in_progress', label: '处理中', type: 'warning' },
    done: { code: 'done', label: '已完成', type: 'success' },
  }
  return statusMap[code] || statusMap.pending
}
function recoveryPeriodFor(item) {
  if (item?.type === 'reclaim') return '1-3 天'
  if (item?.type === 'schedule') return '1 周内'
  if (item?.type === 'downsize') return item?.environment === 'prod' ? '2 周内' : '1 周内'
  if (item?.type === 'storage') return '2-4 周'
  return '本月内'
}
function riskLevelFor(cost, saving, environment, severity) {
  if (severity === 'danger' || cost >= 1500 || saving >= 500) return { label: '高', type: 'danger' }
  if (environment !== 'prod' || cost >= 700 || saving >= 200) return { label: '中', type: 'warning' }
  return { label: '低', type: 'info' }
}
function markSuggestionStatus(item, status) {
  optimizationExecutionState.value = {
    ...optimizationExecutionState.value,
    [suggestionKey(item)]: {
      status,
      updated_at: new Date().toISOString(),
    },
  }
  persistSuggestionStatusState()
  const labelMap = {
    urgent: '已标记为待本周处理',
    pending: '已重置为待排期执行',
    in_progress: '已标记为处理中',
    done: '已标记为已完成',
  }
  ElMessage.success(labelMap[status] || '状态已更新')
}
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
function optimizationIcon(type) {
  return {
    reclaim: 'RC',
    schedule: 'TM',
    downsize: 'RS',
    storage: 'ST',
    governance: 'GV',
  }[type] || 'OP'
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
  display: flex; align-items: center; justify-content: flex-start; flex: 1; min-width: 220px;
  border-radius: 16px; padding: 18px 20px; color: #fff;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.14);
}
.cost-card-total { background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%); }
.cost-card-saving { background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%); }
.cost-card-optimized { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
.cost-card-annual { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); }
.optimize-card-total { background: linear-gradient(135deg, #0f766e 0%, #115e59 100%); }
.cost-card-body { min-width: 0; }
.cost-card-val { font-size: 22px; font-weight: 700; }
.cost-card-label { font-size: 12px; opacity: 0.9; }

.cost-insight-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.cost-insight-card {
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--card-bg, #1e293b);
  border: 1px solid rgba(139,92,246,0.12);
}
.cost-insight-card.tone-warning { border-color: rgba(245, 158, 11, 0.28); }
.cost-insight-card.tone-info { border-color: rgba(59, 130, 246, 0.24); }
.cost-insight-card.tone-success { border-color: rgba(16, 185, 129, 0.24); }
.cost-insight-card.tone-danger { border-color: rgba(239, 68, 68, 0.24); }
.cost-insight-label { font-size: 12px; color: #94a3b8; margin-bottom: 8px; }
.cost-insight-value { font-size: 18px; font-weight: 700; color: var(--text-primary, #e2e8f0); }
.cost-insight-detail { margin-top: 6px; font-size: 12px; color: #94a3b8; line-height: 1.6; }

.cost-brief-row {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.cost-brief-box { min-width: 0; }
.focus-list,
.provider-focus-list,
.leaderboard-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.focus-item,
.provider-focus-item,
.leaderboard-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(148,163,184,0.08);
}
.focus-item {
  align-items: flex-start;
  flex-direction: column;
}
.focus-item-title,
.provider-focus-name,
.leaderboard-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #e2e8f0);
}
.focus-item-detail,
.provider-focus-detail,
.leaderboard-detail {
  font-size: 12px;
  line-height: 1.6;
  color: #94a3b8;
}
.provider-focus-main,
.leaderboard-main {
  min-width: 0;
  flex: 1;
}
.provider-focus-share,
.leaderboard-saving {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 700;
  color: #f8fafc;
}
.risk-toolbar,
.opt-filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.risk-toolbar-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.risk-toolbar-meta {
  font-size: 12px;
  color: #94a3b8;
}
.owner-board,
.archive-list,
.owner-workbench {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.owner-card,
.archive-item,
.owner-workbench-card {
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(148,163,184,0.08);
}
.owner-card-header,
.archive-item,
.owner-workbench-header {
  display: flex;
  justify-content: space-between;
  gap: 14px;
}
.owner-card-name,
.archive-item-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #e2e8f0);
}
.owner-card-meta,
.archive-item-detail {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
}
.owner-card-saving,
.archive-item-metrics strong {
  font-size: 16px;
  font-weight: 700;
  color: #10b981;
  white-space: nowrap;
}
.owner-card-list {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}
.owner-card-task {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(15,23,42,0.18);
  color: #cbd5e1;
  font-size: 12px;
}
.owner-card-task strong,
.archive-item-metrics span {
  color: #f8fafc;
}
.archive-summary-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.archive-summary-item {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(148,163,184,0.08);
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: #94a3b8;
}
.archive-summary-item strong {
  color: #f8fafc;
  font-size: 15px;
}
.archive-item-main {
  min-width: 0;
  flex: 1;
}
.owner-workbench-tasks {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}
.owner-workbench-task {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(15,23,42,0.18);
}
.owner-workbench-main {
  min-width: 0;
  flex: 1;
}
.owner-workbench-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
  white-space: nowrap;
  color: #f8fafc;
  font-size: 12px;
}
.archive-item-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
  font-size: 12px;
  color: #cbd5e1;
}

.cost-charts-row,
.cost-trend-row { display: flex; gap: 16px; flex-wrap: wrap; }
.cost-chart-box {
  flex: 1; min-width: 300px; background: var(--card-bg, #1e293b); border-radius: 16px;
  padding: 16px 20px; border: 1px solid rgba(139,92,246,0.12);
}
.cost-trend-box { min-width: 420px; }
.cost-preview-box { min-width: 320px; }
.chart-title { font-weight: 700; font-size: 14px; margin-bottom: 14px; color: var(--text-primary, #e2e8f0); }
.chart-bars { display: flex; flex-direction: column; gap: 10px; }
.bar-item { display: flex; align-items: center; gap: 10px; }
.bar-label { font-size: 12px; color: #94a3b8; width: 86px; text-align: right; flex-shrink: 0; }
.bar-label.wide { width: 110px; }
.bar-track { flex: 1; height: 18px; background: rgba(148,163,184,0.1); border-radius: 9px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 9px; transition: width 0.5s ease; }
.bar-fill-biz { background: linear-gradient(90deg, #8b5cf6, #a78bfa); }
.bar-fill-env { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.bar-fill-provider { background: linear-gradient(90deg, #06b6d4, #67e8f9); }
.bar-fill-type { background: linear-gradient(90deg, #f59e0b, #fcd34d); }
.bar-fill-saving { background: linear-gradient(90deg, #10b981, #34d399); }
.bar-value { font-size: 12px; font-weight: 600; color: #f59e0b; width: 92px; text-align: right; }
.empty-chart { text-align: center; padding: 30px; color: #64748b; }
.trend-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 12px; align-items: end; min-height: 220px; }
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
.trend-subvalue { font-size: 11px; color: #10b981; }

.preview-summary {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.preview-summary-item {
  flex: 1;
  min-width: 120px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(148,163,184,0.08);
  color: #cbd5e1;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
}
.preview-summary-item strong { color: #f8fafc; font-size: 14px; }
.cost-preview-list { display: flex; flex-direction: column; gap: 10px; }
.cost-preview-item {
  display: flex; justify-content: space-between; gap: 12px; align-items: center;
  padding: 12px 14px; border-radius: 12px; background: rgba(148,163,184,0.08);
}
.cost-preview-main { min-width: 0; }
.cost-preview-title { font-size: 13px; font-weight: 600; color: var(--text-primary, #e2e8f0); }
.cost-preview-meta { margin-top: 4px; font-size: 12px; color: #94a3b8; }
.cost-preview-saving { color: #10b981; font-size: 13px; font-weight: 700; white-space: nowrap; }

.severity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}
.severity-card {
  padding: 14px;
  border-radius: 14px;
  background: rgba(148,163,184,0.08);
  border: 1px solid transparent;
}
.severity-danger { border-color: rgba(239, 68, 68, 0.24); }
.severity-warning { border-color: rgba(245, 158, 11, 0.24); }
.severity-info { border-color: rgba(59, 130, 246, 0.24); }
.severity-title { font-size: 13px; font-weight: 600; color: var(--text-primary, #e2e8f0); }
.severity-count { margin-top: 8px; font-size: 12px; color: #94a3b8; }
.severity-saving { margin-top: 6px; font-size: 16px; font-weight: 700; color: #10b981; }

.execution-plan {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.execution-step {
  padding: 14px;
  border-radius: 14px;
  background: rgba(148,163,184,0.08);
  border: 1px solid rgba(148,163,184,0.12);
}
.execution-stage {
  display: inline-flex;
  align-items: center;
  margin-bottom: 10px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(59,130,246,0.18);
  color: #bfdbfe;
  font-size: 11px;
  font-weight: 700;
}
.execution-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #e2e8f0);
}
.execution-detail {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #94a3b8;
  min-height: 38px;
}
.execution-metrics {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: #cbd5e1;
}
.execution-metrics strong {
  font-size: 14px;
  color: #10b981;
}
.leaderboard-item {
  align-items: center;
}
.leaderboard-rank {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f59e0b 0%, #f97316 100%);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}
.opt-plan-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.opt-plan-item {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(148,163,184,0.08);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.opt-plan-label {
  font-size: 11px;
  color: #94a3b8;
}
.opt-plan-item strong {
  color: #f8fafc;
  font-size: 13px;
  font-weight: 600;
}
.opt-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

/* ====== 优化建议 ====== */
.opt-card {
  display: flex; align-items: stretch; gap: 16px;
  background: var(--card-bg, #1e293b); border-radius: 16px; padding: 16px 20px;
  margin-bottom: 12px; border-left: 4px solid; transition: transform 0.15s;
}
.opt-card:hover { transform: translateX(4px); }
.opt-warning { border-left-color: #f59e0b; }
.opt-danger { border-left-color: #ef4444; }
.opt-info { border-left-color: #3b82f6; }
.opt-icon {
  width: 52px; height: 52px; border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  font-size: 24px; background: rgba(148,163,184,0.08); flex-shrink: 0;
}
.opt-body { flex: 1; min-width: 0; }
.opt-title-row {
  display: flex; justify-content: space-between; gap: 12px; align-items: flex-start;
}
.opt-tags { display: flex; gap: 8px; flex-wrap: wrap; }
.opt-title { font-weight: 700; font-size: 15px; color: var(--text-primary, #e2e8f0); }
.opt-detail { font-size: 12px; color: #94a3b8; margin-top: 6px; line-height: 1.7; }
.opt-meta-row {
  display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px;
  font-size: 12px; color: #cbd5e1;
}
.opt-meta-row span {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(148,163,184,0.08);
}
.opt-action,
.opt-evidence {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.7;
}
.opt-action,
.opt-action-hint {
  color: var(--el-text-color-regular, #475569);
  font-weight: 600;
}
.opt-evidence { color: #94a3b8; }
.opt-saving {
  width: 160px;
  flex-shrink: 0;
  padding-left: 16px;
  border-left: 1px dashed rgba(148,163,184,0.2);
}
.opt-metric-label { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
.opt-cost-now,
.opt-cost-after,
.opt-saving-val { font-size: 18px; font-weight: 700; margin-bottom: 10px; }
.opt-cost-now {
  color: #f59e0b;
  text-shadow: none;
}
.opt-saving-val { color: #10b981; }
.opt-cost-after { color: #38bdf8; }

@media (max-width: 900px) {
  .cost-card {
    min-width: 100%;
  }

  .cost-chart-box,
  .cost-trend-box,
  .cost-preview-box {
    min-width: 100%;
  }

  .cost-brief-row {
    grid-template-columns: 1fr;
  }

  .owner-card-header,
  .archive-item,
  .owner-workbench-header,
  .owner-workbench-task {
    flex-direction: column;
  }

  .archive-item-metrics,
  .owner-workbench-metrics {
    align-items: flex-start;
  }

  .opt-plan-row {
    grid-template-columns: 1fr;
  }

  .bar-label,
  .bar-label.wide {
    width: 76px;
  }

  .opt-card {
    flex-direction: column;
  }

  .opt-saving {
    width: 100%;
    padding-left: 0;
    border-left: none;
    border-top: 1px dashed rgba(148,163,184,0.2);
    padding-top: 12px;
  }
}

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
