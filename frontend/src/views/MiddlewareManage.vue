<template>
  <div class="fade-in middleware-page" :class="`middleware-page--${moduleKey}`">
    <section class="hero panel middleware-hero">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="release-header-icon middleware-header-icon"><el-icon><component :is="moduleHeroIcon" /></el-icon></span>
          <h2>{{ moduleMeta.title }}</h2>
          <p class="subtitle inline-subtitle">{{ moduleMeta.subtitle }}</p>
        </div>
      </div>
      <div class="hero-actions header-actions">
        <el-tag effect="plain" :type="statusTagType(moduleStatus)">状态：{{ moduleStatusLabel }}</el-tag>
        <el-tag type="info" effect="plain">最近更新：{{ formattedUpdatedAt }}</el-tag>
        <el-button :loading="loading" @click="refreshData">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <div class="stats-grid release-stats middleware-stats">
      <div
        v-for="card in summaryCards"
        :key="card.label"
        class="stat-card release-stat-card middleware-stat-card"
        :class="card.tone"
      >
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
        <div class="middleware-stat-meta">{{ card.meta }}</div>
      </div>
    </div>

    <div v-if="currentAlerts.length" class="middleware-alert-strip">
      <span class="middleware-alert-strip__label">运行提示</span>
      <el-tooltip
        v-for="(alert, index) in currentAlerts.slice(0, 2)"
        :key="`${alert.title}-${index}`"
        :content="alert.message"
        placement="top"
        effect="light"
        :show-after="120"
      >
        <el-tag
          size="small"
          effect="light"
          :type="summaryAlertTagType(alert.level)"
          class="middleware-alert-strip__tag"
        >
          {{ compactAlertMessage(alert.message) }}
        </el-tag>
      </el-tooltip>
      <el-popover v-if="currentAlerts.length > 2" placement="bottom-end" :width="320" trigger="hover">
        <template #reference>
          <el-button link type="primary">+{{ currentAlerts.length - 2 }} 更多</el-button>
        </template>
        <div class="alert-popover">
          <div v-for="(alert, index) in currentAlerts" :key="`all-${index}`" class="alert-popover__item">
            <el-tag size="small" :type="summaryAlertTagType(alert.level)">{{ alert.title }}</el-tag>
            <span>{{ alert.message }}</span>
          </div>
        </div>
      </el-popover>
    </div>

    <div class="neo-tabs theme-blue middleware-tabs">
      <button v-for="tab in mainTabs" :key="tab.key" class="neo-tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <el-card shadow="never" class="section-card toolbar-card">
      <div class="toolbar-grid">
        <el-input v-model="filters.search" clearable :placeholder="searchPlaceholder" class="toolbar-control" />
        <el-select v-model="filters.environment" class="toolbar-control">
          <el-option label="全部环境" value="all" />
          <el-option v-for="item in environmentOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="filters.state" class="toolbar-control">
          <el-option v-for="item in stateOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <div class="toolbar-actions">
          <el-button v-if="canManageMiddleware && activeTab !== 'runtime'" @click="openImportDialog">
            <el-icon><UploadFilled /></el-icon>
            导入模板
          </el-button>
          <el-button v-if="canManageMiddleware && activeTab === 'clusters'" type="primary" @click="openClusterDialog">
            <el-icon><Plus /></el-icon>
            新增集群
          </el-button>
          <el-button v-if="canManageMiddleware && activeTab === 'instances'" type="primary" @click="openInstanceDialog">
            <el-icon><Plus /></el-icon>
            {{ instanceButtonLabel }}
          </el-button>
        </div>
      </div>
    </el-card>

    <template v-if="moduleKey === 'redis'">
      <el-card v-if="activeTab === 'clusters'" shadow="never" class="section-card">
        <template #header><div class="section-title">Redis 集群管理</div></template>
        <el-table :data="filteredRedisClusters" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="集群" min-width="160" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="mode" label="模式" min-width="140" />
          <el-table-column prop="slot_coverage" label="槽位覆盖" width="120" />
          <el-table-column label="资源" min-width="180">
            <template #default="{ row }"><div>内存 {{ row.memory_total_gb }} GB</div><div>命中率 {{ row.hit_rate }}%</div></template>
          </el-table-column>
          <el-table-column label="吞吐" width="140"><template #default="{ row }">{{ formatNumber(row.ops_per_sec) }} ops/s</template></el-table-column>
          <el-table-column v-if="canManageMiddleware" label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="info" @click="openDetailDrawer('cluster', row)">详情</el-button>
              <el-button link type="primary" @click="openClusterDialog(row)">编辑</el-button>
              <el-popconfirm title="确认删除该集群？" @confirm="deleteResource('cluster', row.id)">
                <template #reference><el-button link type="danger">删除</el-button></template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card v-if="activeTab === 'instances'" shadow="never" class="section-card">
        <template #header><div class="section-title">Redis 实例管理</div></template>
        <el-table :data="filteredRedisInstances" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="实例" min-width="170" />
          <el-table-column prop="cluster" label="集群" min-width="140" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="role" label="角色" width="100"><template #default="{ row }"><el-tag :type="row.role === 'master' ? 'danger' : 'success'" size="small">{{ row.role }}</el-tag></template></el-table-column>
          <el-table-column prop="endpoint" label="地址" min-width="170" />
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="负载" min-width="150"><template #default="{ row }"><div>QPS {{ formatNumber(row.qps) }}</div><div>连接 {{ formatNumber(row.connections) }}</div></template></el-table-column>
          <el-table-column label="复制 / 持久化" min-width="160"><template #default="{ row }"><div>延迟 {{ row.replication_delay_ms }}ms</div><div>{{ row.persistence }}</div></template></el-table-column>
          <el-table-column prop="last_sync" label="最近同步" width="150" />
          <el-table-column v-if="canManageMiddleware" label="操作" width="330" fixed="right">
            <template #default="{ row }">
              <el-button link type="info" @click="openDetailDrawer('instance', row)">详情</el-button>
              <el-button link type="info" @click="openInstanceDialog(row)">编辑</el-button>
              <el-button link type="primary" :loading="isActing('redis', row.id, 'restart')" @click="handleAction('redis', row.id, 'restart')">重启</el-button>
              <el-button v-if="row.role === 'replica'" link type="warning" :loading="isActing('redis', row.id, 'promote')" @click="handleAction('redis', row.id, 'promote')">提升主库</el-button>
              <el-button v-if="row.role === 'replica'" link type="success" :loading="isActing('redis', row.id, 'resync')" @click="handleAction('redis', row.id, 'resync')">重同步</el-button>
              <el-popconfirm title="确认删除该实例？" @confirm="deleteResource('instance', row.id)">
                <template #reference><el-button link type="danger">删除</el-button></template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <div v-if="activeTab === 'runtime'" class="stack-grid">
        <div class="runtime-chart-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">QPS 趋势</div></template>
            <div ref="redisQpsChartRef" class="runtime-chart"></div>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">命中率 / 内存使用</div></template>
            <div ref="redisCapacityChartRef" class="runtime-chart"></div>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">复制延迟对比</div></template>
            <div ref="redisDelayChartRef" class="runtime-chart"></div>
          </el-card>
        </div>
        <div class="dual-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">热点 Key 风险</div></template>
            <el-table :data="filteredRedisHotKeys" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="key" label="Key" min-width="210" />
              <el-table-column prop="cluster" label="集群" min-width="120" />
              <el-table-column prop="ops_per_sec" label="OPS/s" width="100"><template #default="{ row }">{{ formatNumber(row.ops_per_sec) }}</template></el-table-column>
              <el-table-column prop="memory_kb" label="内存" width="100"><template #default="{ row }">{{ formatNumber(row.memory_kb) }} KB</template></el-table-column>
              <el-table-column prop="risk" label="风险" width="100"><template #default="{ row }"><el-tag :type="riskTagType(row.risk)" size="small">{{ row.risk }}</el-tag></template></el-table-column>
            </el-table>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">运行事件</div></template>
            <div class="timeline-list">
              <div v-for="event in redis.events || []" :key="event.id" class="timeline-item">
                <div class="timeline-dot" :class="`timeline-dot--${event.level}`"></div>
                <div class="timeline-content"><div class="timeline-top"><span class="timeline-title">{{ event.title }}</span><span class="timeline-time">{{ event.time }}</span></div><div class="timeline-detail">{{ event.detail }}</div></div>
              </div>
            </div>
          </el-card>
        </div>
      </div>
    </template>

    <template v-else-if="moduleKey === 'rocketmq'">
      <el-card v-if="activeTab === 'clusters'" shadow="never" class="section-card">
        <template #header><div class="section-title">RocketMQ 集群管理</div></template>
        <el-table :data="filteredRocketmqClusters" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="集群" min-width="150" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="规模" min-width="140"><template #default="{ row }"><div>NameServer {{ row.nameserver_count }}</div><div>Broker {{ row.broker_count }}</div></template></el-table-column>
          <el-table-column label="吞吐" width="120"><template #default="{ row }">{{ formatNumber(row.tps) }} TPS</template></el-table-column>
          <el-table-column prop="topic_count" label="Topic 数" width="110" />
          <el-table-column v-if="canManageMiddleware" label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="info" @click="openDetailDrawer('cluster', row)">详情</el-button>
              <el-button link type="primary" @click="openClusterDialog(row)">编辑</el-button>
              <el-popconfirm title="确认删除该集群？" @confirm="deleteResource('cluster', row.id)">
                <template #reference><el-button link type="danger">删除</el-button></template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card v-if="activeTab === 'instances'" shadow="never" class="section-card">
        <template #header><div class="section-title">Broker 管理</div></template>
        <el-table :data="filteredRocketmqBrokers" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="Broker" min-width="140" />
          <el-table-column prop="cluster" label="集群" min-width="120" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="role" label="角色" width="100"><template #default="{ row }"><el-tag :type="row.role === 'master' ? 'danger' : 'info'" size="small">{{ row.role }}</el-tag></template></el-table-column>
          <el-table-column prop="endpoint" label="地址" min-width="170" />
          <el-table-column label="负载" min-width="150"><template #default="{ row }"><div>TPS {{ formatNumber(row.tps) }}</div><div>Topic {{ row.topic_count }}</div></template></el-table-column>
          <el-table-column label="容量" min-width="150"><template #default="{ row }"><div>磁盘 {{ row.disk_usage }}%</div><div>积压 {{ formatNumber(row.consumer_lag) }}</div></template></el-table-column>
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column v-if="canManageMiddleware" label="操作" width="300" fixed="right"><template #default="{ row }"><el-button link type="info" @click="openDetailDrawer('instance', row)">详情</el-button><el-button link type="info" @click="openInstanceDialog(row)">编辑</el-button><el-button link type="primary" :loading="isActing('rocketmq', row.id, 'restart')" @click="handleAction('rocketmq', row.id, 'restart')">重启</el-button><el-button link type="warning" :loading="isActing('rocketmq', row.id, 'rebalance')" @click="handleAction('rocketmq', row.id, 'rebalance')">Rebalance</el-button><el-popconfirm title="确认删除该 Broker？" @confirm="deleteResource('instance', row.id)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm></template></el-table-column>
        </el-table>
      </el-card>

      <div v-if="activeTab === 'runtime'" class="stack-grid">
        <div class="runtime-chart-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">TPS 趋势</div></template>
            <div ref="rocketmqTpsChartRef" class="runtime-chart"></div>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">消费积压对比</div></template>
            <div ref="rocketmqLagChartRef" class="runtime-chart"></div>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">磁盘 / 死信风险</div></template>
            <div ref="rocketmqRiskChartRef" class="runtime-chart"></div>
          </el-card>
        </div>
        <div class="dual-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">消费组积压</div></template>
            <el-table :data="filteredRocketmqGroups" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="group" label="消费组" min-width="150" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="topic" label="Topic" min-width="160" />
              <el-table-column prop="clients" label="客户端" width="88" />
              <el-table-column prop="retry" label="重试" width="80" />
              <el-table-column prop="lag" label="积压" width="100"><template #default="{ row }"><span :class="{ 'warning-text': row.lag >= 1000 }">{{ formatNumber(row.lag) }}</span></template></el-table-column>
            </el-table>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">Topic 演示数据</div></template>
            <el-table :data="filteredRocketmqTopics" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="name" label="Topic" min-width="180" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="messages_24h" label="24h 消息量" width="120" />
              <el-table-column prop="retention_hours" label="保留时长" width="110"><template #default="{ row }">{{ row.retention_hours }} h</template></el-table-column>
              <el-table-column prop="dead_letter" label="死信" width="90"><template #default="{ row }"><span :class="{ 'warning-text': row.dead_letter >= 100 }">{{ row.dead_letter }}</span></template></el-table-column>
            </el-table>
          </el-card>
        </div>
        <el-card shadow="never" class="section-card">
          <template #header><div class="section-title">运行事件</div></template>
          <div class="timeline-list">
            <div v-for="event in rocketmq.events || []" :key="event.id" class="timeline-item"><div class="timeline-dot" :class="`timeline-dot--${event.level}`"></div><div class="timeline-content"><div class="timeline-top"><span class="timeline-title">{{ event.title }}</span><span class="timeline-time">{{ event.time }}</span></div><div class="timeline-detail">{{ event.detail }}</div></div></div>
          </div>
        </el-card>
      </div>
    </template>

    <template v-else>
      <el-card v-if="activeTab === 'clusters'" shadow="never" class="section-card">
        <template #header><div class="section-title">Elasticsearch 集群管理</div></template>
        <el-table :data="filteredEsClusters" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="集群" min-width="150" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="health" label="健康度" width="100"><template #default="{ row }"><el-tag :type="healthTagType(row.health)" size="small">{{ row.health }}</el-tag></template></el-table-column>
          <el-table-column prop="nodes" label="节点数" width="90" />
          <el-table-column prop="indices" label="索引数" width="90" />
          <el-table-column prop="storage" label="存储" width="110" />
          <el-table-column label="查询能力" min-width="160"><template #default="{ row }"><div>QPS {{ formatNumber(row.qps) }}</div><div>未分配分片 {{ row.unassigned_shards }}</div></template></el-table-column>
          <el-table-column v-if="canManageMiddleware" label="操作" width="330" fixed="right"><template #default="{ row }"><el-button link type="info" @click="openDetailDrawer('cluster', row)">详情</el-button><el-button link type="info" @click="openClusterDialog(row)">编辑</el-button><el-button link type="warning" :loading="isActing('elasticsearch', row.id, 'reroute')" @click="handleAction('elasticsearch', row.id, 'reroute')">Reroute</el-button><el-button link type="primary" :loading="isActing('elasticsearch', row.id, 'rollover')" @click="handleAction('elasticsearch', row.id, 'rollover')">Rollover</el-button><el-popconfirm title="确认删除该集群？" @confirm="deleteResource('cluster', row.id)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm></template></el-table-column>
        </el-table>
      </el-card>

      <el-card v-if="activeTab === 'instances'" shadow="never" class="section-card">
        <template #header><div class="section-title">节点管理</div></template>
        <el-table :data="filteredEsNodes" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="节点" min-width="150" />
          <el-table-column prop="cluster" label="集群" min-width="120" />
          <el-table-column prop="role" label="角色" min-width="140" />
          <el-table-column prop="endpoint" label="地址" min-width="170" />
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'online' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="资源" min-width="170"><template #default="{ row }"><div>Heap {{ row.heap_usage }}%</div><div>CPU {{ row.cpu_usage }}% / 磁盘 {{ row.disk_usage }}%</div></template></el-table-column>
          <el-table-column v-if="canManageMiddleware" label="操作" width="260" fixed="right"><template #default="{ row }"><el-button link type="info" @click="openDetailDrawer('instance', row)">详情</el-button><el-button link type="info" @click="openInstanceDialog(row)">编辑</el-button><el-button link type="primary" :loading="isActing('elasticsearch', row.id, 'restart_node')" @click="handleAction('elasticsearch', row.id, 'restart_node')">重启节点</el-button><el-popconfirm title="确认删除该节点？" @confirm="deleteResource('instance', row.id)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm></template></el-table-column>
        </el-table>
      </el-card>

      <div v-if="activeTab === 'runtime'" class="stack-grid">
        <div class="runtime-chart-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">查询 QPS 趋势</div></template>
            <div ref="esQpsChartRef" class="runtime-chart"></div>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">节点资源画像</div></template>
            <div ref="esResourceChartRef" class="runtime-chart"></div>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">任务与分片治理</div></template>
            <div ref="esTaskChartRef" class="runtime-chart"></div>
          </el-card>
        </div>
        <div class="dual-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">索引状态</div></template>
            <el-table :data="filteredEsIndices" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="name" label="索引" min-width="220" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="healthTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
              <el-table-column prop="docs" label="文档数" width="100" />
              <el-table-column prop="size" label="大小" width="100" />
              <el-table-column prop="lifecycle" label="生命周期" width="100" />
            </el-table>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">后台任务</div></template>
            <el-table :data="filteredEsTasks" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="name" label="任务" min-width="160" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="progress" label="进度" width="160"><template #default="{ row }"><el-progress :percentage="row.progress" :status="taskProgressStatus(row.status)" :stroke-width="8" /></template></el-table-column>
              <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="taskTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
            </el-table>
          </el-card>
        </div>
        <el-card shadow="never" class="section-card">
          <template #header><div class="section-title">运行事件</div></template>
          <div class="timeline-list">
            <div v-for="event in elasticsearch.events || []" :key="event.id" class="timeline-item"><div class="timeline-dot" :class="`timeline-dot--${event.level}`"></div><div class="timeline-content"><div class="timeline-top"><span class="timeline-title">{{ event.title }}</span><span class="timeline-time">{{ event.time }}</span></div><div class="timeline-detail">{{ event.detail }}</div></div></div>
          </div>
        </el-card>
      </div>
    </template>

    <el-dialog v-model="clusterDialogVisible" :title="clusterDialogTitle" width="560px" append-to-body destroy-on-close>
      <el-form :model="clusterForm" label-width="110px">
        <el-form-item label="集群名称" required><el-input v-model="clusterForm.name" placeholder="请输入集群名称" /></el-form-item>
        <el-form-item label="环境"><el-select v-model="clusterForm.environment" style="width:100%"><el-option label="prod" value="prod" /><el-option label="test" value="test" /><el-option label="dev" value="dev" /></el-select></el-form-item>
        <template v-if="moduleKey === 'redis'"><el-form-item label="集群状态"><el-select v-model="clusterForm.status" style="width:100%"><el-option label="healthy" value="healthy" /><el-option label="warning" value="warning" /></el-select></el-form-item><el-form-item label="模式"><el-select v-model="clusterForm.mode" style="width:100%"><el-option label="Redis Cluster" value="Redis Cluster" /><el-option label="Sentinel" value="Sentinel" /><el-option label="Master / Replica" value="Master / Replica" /></el-select></el-form-item><el-form-item label="槽位覆盖"><el-input v-model="clusterForm.slot_coverage" placeholder="16384/16384" /></el-form-item><el-form-item label="内存容量"><el-input-number v-model="clusterForm.memory_total_gb" :min="1" style="width:100%" /></el-form-item><el-form-item label="目标吞吐"><el-input-number v-model="clusterForm.ops_per_sec" :min="0" style="width:100%" /></el-form-item><el-form-item label="命中率"><el-input-number v-model="clusterForm.hit_rate" :min="1" :max="100" :precision="1" style="width:100%" /></el-form-item></template>
        <template v-else-if="moduleKey === 'rocketmq'"><el-form-item label="集群状态"><el-select v-model="clusterForm.status" style="width:100%"><el-option label="healthy" value="healthy" /><el-option label="warning" value="warning" /></el-select></el-form-item><el-form-item label="NameServer"><el-input-number v-model="clusterForm.nameserver_count" :min="1" style="width:100%" /></el-form-item><el-form-item label="目标 TPS"><el-input-number v-model="clusterForm.tps" :min="0" style="width:100%" /></el-form-item><el-form-item label="Topic 数"><el-input-number v-model="clusterForm.topic_count" :min="0" style="width:100%" /></el-form-item></template>
        <template v-else><el-form-item label="健康度"><el-select v-model="clusterForm.health" style="width:100%"><el-option label="green" value="green" /><el-option label="yellow" value="yellow" /><el-option label="red" value="red" /></el-select></el-form-item><el-form-item label="存储规模"><el-input v-model="clusterForm.storage" placeholder="例如 1.2TB" /></el-form-item><el-form-item label="目标 QPS"><el-input-number v-model="clusterForm.qps" :min="0" style="width:100%" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="clusterDialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitCluster">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="instanceDialogVisible" :title="instanceDialogTitle" width="560px" append-to-body destroy-on-close>
      <el-form :model="instanceForm" label-width="110px">
        <el-form-item label="所属集群" required><el-select v-model="instanceForm.cluster" style="width:100%"><el-option v-for="item in clusterOptions" :key="item.name" :label="item.name" :value="item.name" /></el-select></el-form-item>
        <el-form-item :label="instanceNameLabel" required><el-input v-model="instanceForm.name" placeholder="请输入名称" /></el-form-item>
        <el-form-item label="环境"><el-select v-model="instanceForm.environment" style="width:100%"><el-option label="prod" value="prod" /><el-option label="test" value="test" /><el-option label="dev" value="dev" /></el-select></el-form-item>
        <el-form-item :label="roleLabel"><el-input v-model="instanceForm.role" placeholder="请输入角色" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="instanceForm.endpoint" placeholder="IP:Port" /></el-form-item>
        <template v-if="moduleKey === 'redis'"><el-form-item label="状态"><el-select v-model="instanceForm.status" style="width:100%"><el-option label="healthy" value="healthy" /><el-option label="warning" value="warning" /></el-select></el-form-item><el-form-item label="版本"><el-input v-model="instanceForm.version" /></el-form-item><el-form-item label="内存使用率"><el-input-number v-model="instanceForm.memory_usage" :min="0" :max="100" style="width:100%" /></el-form-item><el-form-item label="QPS"><el-input-number v-model="instanceForm.qps" :min="0" style="width:100%" /></el-form-item><el-form-item label="连接数"><el-input-number v-model="instanceForm.connections" :min="0" style="width:100%" /></el-form-item><el-form-item label="复制延迟"><el-input-number v-model="instanceForm.replication_delay_ms" :min="0" style="width:100%" /></el-form-item><el-form-item label="持久化"><el-input v-model="instanceForm.persistence" /></el-form-item></template>
        <template v-else-if="moduleKey === 'rocketmq'"><el-form-item label="状态"><el-select v-model="instanceForm.status" style="width:100%"><el-option label="healthy" value="healthy" /><el-option label="warning" value="warning" /></el-select></el-form-item><el-form-item label="版本"><el-input v-model="instanceForm.version" /></el-form-item><el-form-item label="TPS"><el-input-number v-model="instanceForm.tps" :min="0" style="width:100%" /></el-form-item><el-form-item label="Topic 数"><el-input-number v-model="instanceForm.topic_count" :min="0" style="width:100%" /></el-form-item><el-form-item label="磁盘使用率"><el-input-number v-model="instanceForm.disk_usage" :min="0" :max="100" style="width:100%" /></el-form-item><el-form-item label="消费积压"><el-input-number v-model="instanceForm.consumer_lag" :min="0" style="width:100%" /></el-form-item></template>
        <template v-else><el-form-item label="状态"><el-select v-model="instanceForm.status" style="width:100%"><el-option label="online" value="online" /><el-option label="offline" value="offline" /></el-select></el-form-item><el-form-item label="Heap"><el-input-number v-model="instanceForm.heap_usage" :min="0" :max="100" style="width:100%" /></el-form-item><el-form-item label="CPU"><el-input-number v-model="instanceForm.cpu_usage" :min="0" :max="100" style="width:100%" /></el-form-item><el-form-item label="磁盘"><el-input-number v-model="instanceForm.disk_usage" :min="0" :max="100" style="width:100%" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="instanceDialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitInstance">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="importDialogVisible" :title="`导入${activeTab === 'clusters' ? '集群' : '实例'}模板`" width="460px" append-to-body destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="模板选择">
          <el-select v-model="importTemplateKey" style="width:100%" placeholder="请选择模板">
            <el-option v-for="item in importTemplateOptions" :key="item.key" :label="item.label" :value="item.key" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="importDialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitImportTemplate">导入</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailDrawerVisible" :title="detailTitle" size="760px">
      <div v-if="detailRecord" class="detail-drawer">
        <el-descriptions :column="2" border>
          <el-descriptions-item v-for="item in detailDescriptions" :key="item[0]" :label="item[0]">{{ item[1] }}</el-descriptions-item>
        </el-descriptions>
        <div class="detail-section-head">趋势图</div>
        <div ref="detailChartRef" class="detail-chart"></div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { RefreshRight, Grid, Monitor, Histogram, Plus, UploadFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getMiddlewareOverview, runMiddlewareAction } from '@/api/modules/middleware'
import echarts from '@/lib/echarts'

const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const actingKey = ref('')
const activeTab = ref('clusters')
const filters = ref({ search: '', environment: 'all', state: 'all' })
const payload = ref(createDefaultPayload())
const clusterDialogVisible = ref(false)
const instanceDialogVisible = ref(false)
const clusterDialogMode = ref('create')
const instanceDialogMode = ref('create')
const editingClusterId = ref('')
const editingInstanceId = ref('')
const importDialogVisible = ref(false)
const importTemplateKey = ref('')
const detailDrawerVisible = ref(false)
const detailRecord = ref(null)
const detailKind = ref('cluster')
const clusterForm = ref(createClusterForm())
const instanceForm = ref(createInstanceForm())
const detailChartRef = ref(null)
const redisQpsChartRef = ref(null)
const redisCapacityChartRef = ref(null)
const redisDelayChartRef = ref(null)
const rocketmqTpsChartRef = ref(null)
const rocketmqLagChartRef = ref(null)
const rocketmqRiskChartRef = ref(null)
const esQpsChartRef = ref(null)
const esResourceChartRef = ref(null)
const esTaskChartRef = ref(null)
const TAB_STORAGE_PREFIX = 'middleware-active-tab-'
let detailChart = null
const runtimeCharts = new Map()

const MODULE_META = {
  redis: { badge: 'Middleware / Redis', title: 'Redis 管理', subtitle: '查看集群、实例、热点 Key 与复制状态的演示数据。', bannerTitle: '缓存高可用与热点治理', bannerDesc: '聚焦复制延迟、热点 Key 和主从切换场景。' },
  rocketmq: { badge: 'Middleware / RocketMQ', title: 'RocketMQ 管理', subtitle: '查看 Broker、消费组积压与 Topic 演示数据。', bannerTitle: '消息链路与积压处理', bannerDesc: '聚焦 Broker 负载、消费积压和 Rebalance 演示。' },
  elasticsearch: { badge: 'Middleware / Elasticsearch', title: 'Elasticsearch 管理', subtitle: '查看集群健康度、节点负载、索引和任务演示数据。', bannerTitle: '检索集群健康治理', bannerDesc: '聚焦未分配分片、节点负载和索引 rollover。' },
}

function createDefaultPayload() {
  return {
    updated_at: '', overview: { modules: [] },
    redis: { summary: {}, alerts: [], clusters: [], instances: [], hot_keys: [], events: [] },
    rocketmq: { summary: {}, alerts: [], clusters: [], brokers: [], consumer_groups: [], topics: [], events: [] },
    elasticsearch: { summary: {}, alerts: [], clusters: [], nodes: [], indices: [], tasks: [], events: [] },
  }
}
function createClusterForm() { return { name: '', environment: 'test', status: 'healthy', health: 'green', mode: 'Redis Cluster', slot_coverage: '16384/16384', memory_total_gb: 32, ops_per_sec: 0, hit_rate: 98.6, nameserver_count: 2, tps: 0, topic_count: 0, storage: '1.2TB', qps: 0 } }
function createInstanceForm() { return { cluster: '', name: '', environment: 'test', role: 'master', endpoint: '', version: '', qps: 1200, connections: 96, persistence: 'AOF', memory_usage: 48, replication_delay_ms: 0, tps: 900, topic_count: 16, disk_usage: 42, consumer_lag: 0, status: 'healthy', heap_usage: 36, cpu_usage: 22 } }

const moduleKey = computed(() => route.meta.moduleKey || 'redis')
const moduleMeta = computed(() => MODULE_META[moduleKey.value] || MODULE_META.redis)
const redis = computed(() => payload.value.redis)
const rocketmq = computed(() => payload.value.rocketmq)
const elasticsearch = computed(() => payload.value.elasticsearch)
const currentModule = computed(() => payload.value[moduleKey.value] || {})
const currentAlerts = computed(() => currentModule.value.alerts || [])
const moduleStatus = computed(() => currentModule.value.summary?.module_status || 'healthy')
const moduleStatusLabel = computed(() => ({ healthy: '健康', warning: '告警', critical: '风险' }[moduleStatus.value] || moduleStatus.value))
const formattedUpdatedAt = computed(() => String(payload.value.updated_at || '--').replace('T', ' ').slice(0, 16))
const canManageMiddleware = computed(() => authStore.hasPermission('ops.middleware.manage'))
const moduleHeroIcon = computed(() => (moduleKey.value === 'rocketmq' ? Histogram : moduleKey.value === 'elasticsearch' ? Grid : Monitor))
const mainTabs = computed(() => [{ key: 'clusters', label: '集群管理', icon: Grid }, { key: 'instances', label: moduleKey.value === 'rocketmq' ? 'Broker 管理' : moduleKey.value === 'elasticsearch' ? '节点管理' : '实例管理', icon: Monitor }, { key: 'runtime', label: '运行视图', icon: Histogram }])
const searchPlaceholder = computed(() => {
  const mapping = {
    redis: { clusters: '搜索集群 / 模式', instances: '搜索实例 / 集群 / 地址', runtime: '搜索热点 Key / 集群 / 风险' },
    rocketmq: { clusters: '搜索集群 / 环境', instances: '搜索 Broker / 集群 / 地址', runtime: '搜索消费组 / Topic / 集群' },
    elasticsearch: { clusters: '搜索集群 / 存储', instances: '搜索节点 / 集群 / 地址', runtime: '搜索索引 / 任务 / 集群' },
  }
  return mapping[moduleKey.value][activeTab.value]
})
const instanceButtonLabel = computed(() => moduleKey.value === 'rocketmq' ? '新增 Broker' : moduleKey.value === 'elasticsearch' ? '新增节点' : '新增实例')
const clusterDialogTitle = computed(() => `${clusterDialogMode.value === 'create' ? '新增' : '编辑'}${moduleMeta.value.title.replace(' 管理', '')}集群`)
const instanceDialogTitle = computed(() => `${instanceDialogMode.value === 'create' ? '新增' : '编辑'}${moduleKey.value === 'rocketmq' ? 'Broker' : moduleKey.value === 'elasticsearch' ? '节点' : 'Redis 实例'}`)
const instanceNameLabel = computed(() => moduleKey.value === 'rocketmq' ? 'Broker 名称' : moduleKey.value === 'elasticsearch' ? '节点名称' : '实例名称')
const roleLabel = computed(() => moduleKey.value === 'elasticsearch' ? '节点角色' : '角色')
const clusterOptions = computed(() => currentModule.value.clusters || [])
const importTemplateOptions = computed(() => {
  const mapping = {
    redis: {
      clusters: [{ key: 'ha-read', label: '高可用读写模板' }, { key: 'session', label: '会话缓存模板' }],
      instances: [{ key: 'master', label: '主节点模板' }, { key: 'replica', label: '副本节点模板' }],
    },
    rocketmq: {
      clusters: [{ key: 'trade', label: '交易消息模板' }, { key: 'audit', label: '审计链路模板' }],
      instances: [{ key: 'master', label: '主 Broker 模板' }, { key: 'slave', label: '从 Broker 模板' }],
    },
    elasticsearch: {
      clusters: [{ key: 'search', label: '搜索集群模板' }, { key: 'logs', label: '日志集群模板' }],
      instances: [{ key: 'hot', label: '热节点模板' }, { key: 'warm', label: '温节点模板' }],
    },
  }
  return mapping[moduleKey.value][activeTab.value] || []
})
const importScope = computed(() => activeTab.value === 'clusters' ? 'cluster' : 'instance')
const detailTitle = computed(() => detailRecord.value ? `${detailRecord.value.name || detailRecord.value.cluster || '详情'} 运行详情` : '详情')
const detailDescriptions = computed(() => {
  if (!detailRecord.value) return []
  const row = detailRecord.value
  if (detailKind.value === 'cluster') {
    if (moduleKey.value === 'redis') return [['环境', row.environment], ['状态', row.status], ['模式', row.mode], ['槽位覆盖', row.slot_coverage], ['内存容量', `${row.memory_total_gb} GB`], ['命中率', `${row.hit_rate}%`]]
    if (moduleKey.value === 'rocketmq') return [['环境', row.environment], ['状态', row.status], ['NameServer', row.nameserver_count], ['Broker 数', row.broker_count], ['TPS', formatNumber(row.tps)], ['Topic 数', row.topic_count]]
    return [['环境', row.environment], ['健康度', row.health], ['节点数', row.nodes], ['索引数', row.indices], ['存储', row.storage], ['QPS', formatNumber(row.qps)]]
  }
  if (moduleKey.value === 'redis') return [['集群', row.cluster], ['环境', row.environment], ['角色', row.role], ['状态', row.status], ['版本', row.version], ['地址', row.endpoint]]
  if (moduleKey.value === 'rocketmq') return [['集群', row.cluster], ['环境', row.environment], ['角色', row.role], ['状态', row.status], ['版本', row.version], ['地址', row.endpoint]]
  return [['集群', row.cluster], ['角色', row.role], ['状态', row.status], ['Heap', `${row.heap_usage}%`], ['CPU', `${row.cpu_usage}%`], ['地址', row.endpoint]]
})

const environmentOptions = computed(() => {
  const values = []
  const push = value => { if (value && !values.includes(value)) values.push(value) }
  ;(currentModule.value.clusters || []).forEach(item => push(item.environment))
  ;(currentModule.value.instances || []).forEach(item => push(item.environment))
  ;(currentModule.value.brokers || []).forEach(item => push(item.environment))
  ;(currentModule.value.nodes || []).forEach(item => push(clusterEnvironment(item.cluster)))
  return values
})
const stateOptions = computed(() => moduleKey.value === 'elasticsearch' ? [{ label: '全部健康度', value: 'all' }, { label: 'green', value: 'green' }, { label: 'yellow', value: 'yellow' }, { label: 'red', value: 'red' }] : [{ label: '全部状态', value: 'all' }, { label: 'healthy', value: 'healthy' }, { label: 'warning', value: 'warning' }])
const summaryCards = computed(() => moduleKey.value === 'redis'
  ? [
      { label: '集群数', value: redis.value.summary.cluster_count || 0, meta: '缓存集群', tone: '' },
      { label: '实例数', value: redis.value.summary.instance_count || 0, meta: '实例节点', tone: 'warning-card' },
      { label: '峰值 QPS', value: formatNumber(redis.value.summary.peak_qps), meta: '当前演示峰值', tone: 'success-card' },
      { label: '热点 Key', value: redis.value.summary.hot_key_count || 0, meta: '待治理项', tone: 'danger-card' },
    ]
  : moduleKey.value === 'rocketmq'
    ? [
        { label: '集群数', value: rocketmq.value.summary.cluster_count || 0, meta: '消息集群', tone: '' },
        { label: 'Broker 数', value: rocketmq.value.summary.broker_count || 0, meta: '节点规模', tone: 'warning-card' },
        { label: '峰值 TPS', value: formatNumber(rocketmq.value.summary.peak_tps), meta: '当前演示峰值', tone: 'success-card' },
        { label: 'Topic 数', value: rocketmq.value.summary.topic_count || 0, meta: '业务 Topic', tone: 'danger-card' },
      ]
    : [
        { label: '集群数', value: elasticsearch.value.summary.cluster_count || 0, meta: '检索集群', tone: '' },
        { label: '节点数', value: elasticsearch.value.summary.node_count || 0, meta: '数据节点', tone: 'warning-card' },
        { label: '峰值 QPS', value: formatNumber(elasticsearch.value.summary.peak_qps), meta: '当前查询峰值', tone: 'success-card' },
        { label: '索引数', value: elasticsearch.value.summary.index_count || 0, meta: '索引规模', tone: 'danger-card' },
      ])

const filteredRedisClusters = computed(() => applyCommonFilter(redis.value.clusters || [], item => [item.name, item.mode], item => item.status, item => item.environment))
const filteredRedisInstances = computed(() => applyCommonFilter(redis.value.instances || [], item => [item.name, item.cluster, item.endpoint, item.role], item => item.status, item => item.environment))
const filteredRedisHotKeys = computed(() => applyCommonFilter(redis.value.hot_keys || [], item => [item.key, item.cluster, item.risk], () => 'all', item => clusterEnvironment(item.cluster)))
const filteredRocketmqClusters = computed(() => applyCommonFilter(rocketmq.value.clusters || [], item => [item.name], item => item.status, item => item.environment))
const filteredRocketmqBrokers = computed(() => applyCommonFilter(rocketmq.value.brokers || [], item => [item.name, item.cluster, item.endpoint, item.role], item => item.status, item => item.environment))
const filteredRocketmqGroups = computed(() => applyCommonFilter(rocketmq.value.consumer_groups || [], item => [item.group, item.topic, item.cluster], item => item.status, item => clusterEnvironment(item.cluster)))
const filteredRocketmqTopics = computed(() => applyCommonFilter(rocketmq.value.topics || [], item => [item.name, item.cluster], () => 'all', item => clusterEnvironment(item.cluster)))
const filteredEsClusters = computed(() => applyCommonFilter(elasticsearch.value.clusters || [], item => [item.name, item.storage], item => item.health, item => item.environment))
const filteredEsNodes = computed(() => applyCommonFilter(elasticsearch.value.nodes || [], item => [item.name, item.cluster, item.role, item.endpoint], () => 'all', item => clusterEnvironment(item.cluster)))
const filteredEsIndices = computed(() => applyCommonFilter(elasticsearch.value.indices || [], item => [item.name, item.cluster, item.lifecycle], item => item.status, item => clusterEnvironment(item.cluster)))
const filteredEsTasks = computed(() => applyCommonFilter(elasticsearch.value.tasks || [], item => [item.name, item.cluster, item.status], () => 'all', item => clusterEnvironment(item.cluster)))

function clusterEnvironment(clusterName) { const clusters = currentModule.value.clusters || []; return clusters.find(item => item.name === clusterName)?.environment || 'prod' }
function applyCommonFilter(items, fields, stateGetter, envGetter) { const keyword = String(filters.value.search || '').trim().toLowerCase(); return items.filter(item => (!keyword || fields(item).some(value => String(value || '').toLowerCase().includes(keyword))) && (filters.value.environment === 'all' || envGetter(item) === filters.value.environment) && (filters.value.state === 'all' || stateGetter(item) === filters.value.state)) }
function formatNumber(value) { if (value == null || value === '') return '--'; return Number(value).toLocaleString('zh-CN') }
function statusTagType(status) { return { healthy: 'success', online: 'success', warning: 'warning', critical: 'danger', error: 'danger' }[status] || 'info' }
function healthTagType(status) { return { green: 'success', yellow: 'warning', red: 'danger' }[status] || 'info' }
function riskTagType(risk) { return { high: 'danger', medium: 'warning', low: 'info' }[risk] || 'info' }
function taskTagType(status) { return { completed: 'success', running: 'warning', warning: 'danger' }[status] || 'info' }
function taskProgressStatus(status) { return status === 'warning' ? 'exception' : status === 'completed' ? 'success' : '' }
function summaryAlertTagType(level) { return { warning: 'warning', danger: 'danger', success: 'success' }[level] || 'info' }
function compactAlertMessage(message) { const text = String(message || '').trim(); return text.length <= 24 ? text : `${text.slice(0, 24)}...` }
function isActing(module, targetId, action) { return actingKey.value === `${module}:${targetId}:${action}` }
function switchTab(tabKey) { activeTab.value = tabKey; resetFilters(); localStorage.setItem(`${TAB_STORAGE_PREFIX}${moduleKey.value}`, tabKey) }
function resetFilters() { filters.value = { search: '', environment: 'all', state: 'all' } }
function openClusterDialog(row = null) {
  clusterDialogMode.value = row ? 'edit' : 'create'
  editingClusterId.value = row?.id || ''
  clusterForm.value = row ? { ...createClusterForm(), ...row } : createClusterForm()
  clusterDialogVisible.value = true
}
function openInstanceDialog(row = null) {
  instanceDialogMode.value = row ? 'edit' : 'create'
  editingInstanceId.value = row?.id || ''
  instanceForm.value = row ? { ...createInstanceForm(), ...row } : createInstanceForm()
  instanceForm.value.cluster = instanceForm.value.cluster || clusterOptions.value[0]?.name || ''
  if (!row && moduleKey.value === 'rocketmq') instanceForm.value.role = 'master'
  if (!row && moduleKey.value === 'elasticsearch') instanceForm.value.role = 'data_hot,ingest'
  if (!row && moduleKey.value === 'elasticsearch') instanceForm.value.status = 'online'
  if (!row && moduleKey.value === 'elasticsearch') instanceForm.value.endpoint = '127.0.0.1:9200'
  if (!row && moduleKey.value === 'rocketmq') instanceForm.value.endpoint = '127.0.0.1:10911'
  if (!row && moduleKey.value === 'redis') instanceForm.value.endpoint = '127.0.0.1:6379'
  instanceDialogVisible.value = true
}
function openImportDialog() {
  importTemplateKey.value = importTemplateOptions.value[0]?.key || ''
  importDialogVisible.value = true
}
function openDetailDrawer(kind, row) {
  detailKind.value = kind
  detailRecord.value = row
  detailDrawerVisible.value = true
  nextTick(() => renderDetailChart())
}
function buildTrendSeries(record) {
  const labels = ['00:00', '02:00', '04:00', '06:00', '08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00']
  const base = detailKind.value === 'cluster'
    ? (moduleKey.value === 'redis' ? Number(record.ops_per_sec || 0) : moduleKey.value === 'rocketmq' ? Number(record.tps || 0) : Number(record.qps || 0))
    : (moduleKey.value === 'redis' ? Number(record.qps || 0) : moduleKey.value === 'rocketmq' ? Number(record.tps || 0) : Number(record.heap_usage || 0))
  const values = labels.map((_, index) => Math.max(Math.round(base * (0.62 + index * 0.045 + ((index % 3) - 1) * 0.03)), 0))
  return { labels, values }
}
function createChartGradient(topColor, bottomColor) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: topColor },
    { offset: 1, color: bottomColor },
  ])
}
function buildMiniLineOption(labels, values, color, fillTop) {
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 16, top: 30, bottom: 24 },
    xAxis: { type: 'category', boundaryGap: false, data: labels, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(148,163,184,.16)' } } },
    series: [{
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: values,
      lineStyle: { width: 3, color },
      areaStyle: { color: createChartGradient(fillTop, 'rgba(255,255,255,.04)') },
    }],
  }
}
function buildBarOption(labels, values, colors, unit = '') {
  return {
    tooltip: {
      trigger: 'axis',
      formatter: params => `${params[0]?.axisValue || ''}<br/>${params[0]?.value ?? '--'}${unit}`,
    },
    grid: { left: 42, right: 16, top: 30, bottom: 24 },
    xAxis: { type: 'category', data: labels, axisTick: { show: false }, axisLabel: { interval: 0 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(148,163,184,.16)' } } },
    series: [{
      type: 'bar',
      barWidth: 26,
      data: values.map((value, index) => ({
        value,
        itemStyle: {
          borderRadius: [8, 8, 0, 0],
          color: Array.isArray(colors)
            ? createChartGradient(colors[index % colors.length][0], colors[index % colors.length][1])
            : colors,
        },
      })),
    }],
  }
}
function buildHorizontalBarOption(labels, values, colors, unit = '') {
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: params => `${params[0]?.name || ''}<br/>${params[0]?.value ?? '--'}${unit}`,
    },
    grid: { left: 92, right: 20, top: 20, bottom: 18 },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(148,163,184,.16)' } } },
    yAxis: { type: 'category', data: labels, axisTick: { show: false } },
    series: [{
      type: 'bar',
      barWidth: 18,
      data: values.map((value, index) => ({
        value,
        itemStyle: {
          borderRadius: [0, 8, 8, 0],
          color: Array.isArray(colors)
            ? createChartGradient(colors[index % colors.length][0], colors[index % colors.length][1])
            : colors,
        },
      })),
    }],
  }
}
function buildGroupedBarOption(labels, series) {
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, textStyle: { color: '#64748b' } },
    grid: { left: 42, right: 20, top: 40, bottom: 24 },
    xAxis: { type: 'category', data: labels, axisTick: { show: false }, axisLabel: { interval: 0 } },
    yAxis: { type: 'value', max: 100, splitLine: { lineStyle: { color: 'rgba(148,163,184,.16)' } }, axisLabel: { formatter: '{value}%' } },
    series: series.map(item => ({
      name: item.name,
      type: 'bar',
      barMaxWidth: 18,
      data: item.data,
      itemStyle: { borderRadius: [8, 8, 0, 0], color: createChartGradient(item.colors[0], item.colors[1]) },
    })),
  }
}
function buildDonutOption(name, value, color, total = 100) {
  const safeValue = Math.max(Math.min(Number(value || 0), total), 0)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}' },
    graphic: [{
      type: 'text',
      left: 'center',
      top: '43%',
      style: { text: `${safeValue}%`, textAlign: 'center', fill: '#0f172a', fontSize: 24, fontWeight: 700 },
    }, {
      type: 'text',
      left: 'center',
      top: '57%',
      style: { text: name, textAlign: 'center', fill: '#64748b', fontSize: 12 },
    }],
    series: [{
      type: 'pie',
      radius: ['58%', '76%'],
      center: ['50%', '52%'],
      silent: true,
      label: { show: false },
      data: [
        { value: safeValue, name, itemStyle: { color: createChartGradient(color[0], color[1]), borderRadius: 10 } },
        { value: Math.max(total - safeValue, 0), name: 'remaining', itemStyle: { color: 'rgba(226,232,240,.7)' } },
      ],
    }],
  }
}
function initRuntimeChart(key, targetRef, option) {
  if (!targetRef?.value) return
  const chart = echarts.init(targetRef.value)
  chart.setOption(option)
  runtimeCharts.set(key, chart)
}
function disposeRuntimeCharts() {
  runtimeCharts.forEach(chart => chart.dispose())
  runtimeCharts.clear()
}
function renderRuntimeCharts() {
  disposeRuntimeCharts()
  if (activeTab.value !== 'runtime') return

  if (moduleKey.value === 'redis') {
    const instances = redis.value.instances || []
    const hotKeys = filteredRedisHotKeys.value || []
    const qpsLabels = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']
    const totalQps = instances.reduce((sum, item) => sum + Number(item.qps || 0), 0)
    const qpsValues = qpsLabels.map((_, index) => Math.max(Math.round(totalQps * (0.68 + index * 0.09 + ((index % 2) ? 0.03 : -0.02))), 0))
    initRuntimeChart('redis-qps', redisQpsChartRef, buildMiniLineOption(qpsLabels, qpsValues, '#10b981', 'rgba(16,185,129,.28)'))

    const clusterNames = (redis.value.clusters || []).map(item => item.name)
    const hitRateValues = (redis.value.clusters || []).map(item => Number(item.hit_rate || 0))
    const avgMemoryUsage = clusterNames.map(name => {
      const clusterInstances = instances.filter(item => item.cluster === name)
      if (!clusterInstances.length) return 0
      return Math.round(clusterInstances.reduce((sum, item) => sum + Number(item.memory_usage || 0), 0) / clusterInstances.length)
    })
    initRuntimeChart('redis-capacity', redisCapacityChartRef, buildGroupedBarOption(clusterNames, [
      { name: '命中率', data: hitRateValues, colors: ['#34d399', '#10b981'] },
      { name: '内存使用', data: avgMemoryUsage, colors: ['#60a5fa', '#2563eb'] },
    ]))

    const instanceNames = instances.map(item => item.name)
    const delayValues = instances.map(item => Number(item.replication_delay_ms || 0))
    initRuntimeChart('redis-delay', redisDelayChartRef, buildBarOption(instanceNames, delayValues, [
      ['#facc15', '#f59e0b'],
      ['#fb7185', '#ef4444'],
      ['#38bdf8', '#0ea5e9'],
    ], ' ms'))
    return
  }

  if (moduleKey.value === 'rocketmq') {
    const brokers = rocketmq.value.brokers || []
    const groups = filteredRocketmqGroups.value || []
    const topics = filteredRocketmqTopics.value || []
    const timeLabels = ['09:00', '11:00', '13:00', '15:00', '17:00', '19:00']
    const totalTps = brokers.reduce((sum, item) => sum + Number(item.tps || 0), 0)
    const tpsValues = timeLabels.map((_, index) => Math.max(Math.round(totalTps * (0.58 + index * 0.08 + ((index % 3) - 1) * 0.03)), 0))
    initRuntimeChart('rocketmq-tps', rocketmqTpsChartRef, buildMiniLineOption(timeLabels, tpsValues, '#f97316', 'rgba(249,115,22,.26)'))

    initRuntimeChart('rocketmq-lag', rocketmqLagChartRef, buildHorizontalBarOption(
      groups.map(item => item.group),
      groups.map(item => Number(item.lag || 0)),
      [
        ['#fb7185', '#ef4444'],
        ['#fdba74', '#f97316'],
        ['#38bdf8', '#0ea5e9'],
      ],
      ' 条'
    ))

    const riskLabels = brokers.map(item => item.name)
    initRuntimeChart('rocketmq-risk', rocketmqRiskChartRef, buildGroupedBarOption(riskLabels, [
      { name: '磁盘占用', data: brokers.map(item => Number(item.disk_usage || 0)), colors: ['#fdba74', '#f97316'] },
      { name: '死信量', data: brokers.map(item => {
        const topic = topics.find(entry => entry.cluster === item.cluster)
        return Math.min(Number(topic?.dead_letter || 0), 100)
      }), colors: ['#f87171', '#dc2626'] },
    ]))
    return
  }

  const clusters = elasticsearch.value.clusters || []
  const nodes = elasticsearch.value.nodes || []
  const tasks = filteredEsTasks.value || []
  const qpsLabels = ['00:00', '06:00', '10:00', '14:00', '18:00', '22:00']
  const totalQps = clusters.reduce((sum, item) => sum + Number(item.qps || 0), 0)
  const qpsValues = qpsLabels.map((_, index) => Math.max(Math.round(totalQps * (0.54 + index * 0.09 + ((index % 2) ? 0.04 : -0.01))), 0))
  initRuntimeChart('es-qps', esQpsChartRef, buildMiniLineOption(qpsLabels, qpsValues, '#7c3aed', 'rgba(124,58,237,.26)'))

  initRuntimeChart('es-resource', esResourceChartRef, buildGroupedBarOption(
    nodes.map(item => item.name),
    [
      { name: 'Heap', data: nodes.map(item => Number(item.heap_usage || 0)), colors: ['#a78bfa', '#7c3aed'] },
      { name: 'CPU', data: nodes.map(item => Number(item.cpu_usage || 0)), colors: ['#38bdf8', '#0284c7'] },
      { name: '磁盘', data: nodes.map(item => Number(item.disk_usage || 0)), colors: ['#34d399', '#059669'] },
    ]
  ))

  const avgProgress = tasks.length ? Math.round(tasks.reduce((sum, item) => sum + Number(item.progress || 0), 0) / tasks.length) : 0
  initRuntimeChart('es-task', esTaskChartRef, buildDonutOption('任务进度', avgProgress, ['#8b5cf6', '#7c3aed']))
}
function renderDetailChart() {
  if (!detailDrawerVisible.value || !detailRecord.value || !detailChartRef.value) return
  const { labels, values } = buildTrendSeries(detailRecord.value)
  if (!detailChart) detailChart = echarts.init(detailChartRef.value)
  detailChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', boundaryGap: false, data: labels },
    yAxis: { type: 'value' },
    series: [{
      type: 'line',
      smooth: true,
      data: values,
      lineStyle: { width: 3, color: 'var(--module-primary)' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(59,130,246,0.35)' },
          { offset: 1, color: 'rgba(59,130,246,0.04)' },
        ]),
      },
      showSymbol: false,
    }],
  })
}
function handleResize() {
  detailChart?.resize()
  runtimeCharts.forEach(chart => chart.resize())
}

async function refreshData() {
  loading.value = true
  try {
    payload.value = await getMiddlewareOverview()
    await nextTick()
    renderRuntimeCharts()
  } finally {
    loading.value = false
  }
}

async function handleAction(module, targetId, action) {
  actingKey.value = `${module}:${targetId}:${action}`
  try {
    const response = await runMiddlewareAction(module, targetId, action)
    payload.value = response.data
    ElMessage.success(response.message || '操作成功')
  } finally {
    actingKey.value = ''
  }
}

async function submitCluster() {
  submitting.value = true
  try {
    const action = clusterDialogMode.value === 'create' ? 'create_cluster' : 'update_cluster'
    const response = await runMiddlewareAction(moduleKey.value, editingClusterId.value, action, clusterForm.value)
    payload.value = response.data
    clusterDialogVisible.value = false
    ElMessage.success(response.message || '保存集群成功')
  } finally {
    submitting.value = false
  }
}

async function submitInstance() {
  submitting.value = true
  try {
    const action = instanceDialogMode.value === 'create' ? 'create_instance' : 'update_instance'
    const response = await runMiddlewareAction(moduleKey.value, editingInstanceId.value, action, instanceForm.value)
    payload.value = response.data
    instanceDialogVisible.value = false
    ElMessage.success(response.message || '保存实例成功')
  } finally {
    submitting.value = false
  }
}

async function submitImportTemplate() {
  if (!importTemplateKey.value) {
    ElMessage.warning('请选择模板')
    return
  }
  submitting.value = true
  try {
    const response = await runMiddlewareAction(moduleKey.value, '', 'import_template', {
      scope: importScope.value,
      template_key: importTemplateKey.value,
    })
    payload.value = response.data
    importDialogVisible.value = false
    ElMessage.success(response.message || '模板导入成功')
  } finally {
    submitting.value = false
  }
}

async function deleteResource(kind, targetId) {
  const action = kind === 'cluster' ? 'delete_cluster' : 'delete_instance'
  const response = await runMiddlewareAction(moduleKey.value, targetId, action)
  payload.value = response.data
  ElMessage.success(response.message || '删除成功')
}

watch(detailDrawerVisible, visible => {
  if (!visible && detailChart) {
    detailChart.dispose()
    detailChart = null
  }
  if (visible) nextTick(() => renderDetailChart())
})
watch(moduleKey, () => {
  const storedTab = localStorage.getItem(`${TAB_STORAGE_PREFIX}${moduleKey.value}`)
  activeTab.value = ['clusters', 'instances', 'runtime'].includes(storedTab) ? storedTab : 'clusters'
  actingKey.value = ''
  resetFilters()
}, { immediate: true })
watch([activeTab, moduleKey, payload], async () => {
  await nextTick()
  renderRuntimeCharts()
})

onMounted(async () => {
  await refreshData()
  window.addEventListener('resize', handleResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (detailChart) detailChart.dispose()
  disposeRuntimeCharts()
})
</script>

<style scoped>
.middleware-page { --module-primary: #2563eb; --module-soft: rgba(37, 99, 235, 0.08); }
.middleware-page--redis { --module-primary: #10b981; --module-soft: rgba(16, 185, 129, 0.1); }
.middleware-page--rocketmq { --module-primary: #f97316; --module-soft: rgba(249, 115, 22, 0.1); }
.middleware-page--elasticsearch { --module-primary: #7c3aed; --module-soft: rgba(124, 58, 237, 0.1); }
.panel { background: linear-gradient(180deg, #fff 0%, #f8fbff 100%); border: 1px solid #dbe4f0; border-radius: 24px; box-shadow: 0 14px 34px rgba(15,23,42,.06); padding: 14px 22px; }
.hero { background: linear-gradient(135deg, #fff7ed 0%, #f8fbff 100%); display: flex; gap: 12px; justify-content: space-between; }
.hero h2 { color: #0f172a; margin: 0; }
.subtitle { color: #475569; margin: 10px 0 0; max-width: 620px; }
.hero-actions { display: flex; gap: 12px; }
.release-hero-title-row { display: flex; align-items: center; gap: 12px; }
.release-hero-title-inline { flex-wrap: wrap; }
.inline-subtitle { margin: 0; max-width: none; font-size: 13px; line-height: 1.45; }
.release-header-icon { width: 42px; height: 42px; border-radius: 14px; display: inline-flex; align-items: center; justify-content: center; font-size: 20px; color: #fff; background: linear-gradient(135deg, #409eff, #36cfc9); box-shadow: 0 10px 20px rgba(64,158,255,.2); }
.middleware-header-icon { background: linear-gradient(135deg, var(--module-primary), color-mix(in srgb, var(--module-primary) 62%, white)); box-shadow: 0 10px 20px color-mix(in srgb, var(--module-primary) 22%, white); }
.middleware-hero { margin-bottom: 16px; }
.header-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.release-stats { gap: 16px; }
.middleware-stats { margin-bottom: 16px; }
.release-stat-card { position: relative; min-height: 76px; background: linear-gradient(145deg, #ffffff 0%, #f6faff 100%); border: 1px solid rgba(148,163,184,.18); box-shadow: 0 16px 34px rgba(15,23,42,.07); text-align: left; padding: 12px 16px; overflow: hidden; width: 100%; color: inherit; }
.release-stat-card::after { content: ''; position: absolute; inset: auto -24px -30px auto; width: 108px; height: 108px; border-radius: 50%; background: radial-gradient(circle, rgba(64,158,255,.16) 0%, rgba(64,158,255,0) 70%); }
.warning-card::after { background: radial-gradient(circle, rgba(245,158,11,.18) 0%, rgba(245,158,11,0) 70%); }
.success-card::after { background: radial-gradient(circle, rgba(16,185,129,.18) 0%, rgba(16,185,129,0) 70%); }
.danger-card::after { background: radial-gradient(circle, rgba(239,68,68,.18) 0%, rgba(239,68,68,0) 70%); }
.middleware-stat-card { border-color: color-mix(in srgb, var(--module-primary) 12%, rgba(148,163,184,.18)); }
.middleware-stat-card .stat-value { font-size: 26px; line-height: 1.05; color: #0f172a; }
.middleware-stat-card .stat-label { margin-top: 4px; color: #64748b; }
.middleware-stat-meta { margin-top: 6px; color: #94a3b8; font-size: 12px; }
.middleware-alert-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; padding: 10px 12px; border-radius: 12px; background: rgba(248,250,252,.88); border: 1px solid rgba(148,163,184,.18); }
.middleware-alert-strip__label { font-size: 12px; font-weight: 700; color: #475569; }
.middleware-alert-strip__tag { max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
.alert-popover { display: flex; flex-direction: column; gap: 8px; }
.alert-popover__item { display: flex; gap: 8px; align-items: flex-start; color: #334155; line-height: 1.5; }
.dual-grid, .runtime-chart-grid { display: grid; gap: 16px; margin-bottom: 16px; }
.stack-grid { display: grid; gap: 16px; }
.dual-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.runtime-chart-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.middleware-tabs { margin-bottom: 16px; }
.toolbar-card { margin-bottom: 16px; }
.toolbar-grid { display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 12px; align-items: center; }
.toolbar-control { width: 100%; }
.toolbar-actions { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.section-card { margin-bottom: 16px; border-radius: 16px; }
.section-title { font-weight: 700; color: var(--text-primary); }
.detail-drawer { display: grid; gap: 16px; }
.detail-section-head { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.detail-chart { width: 100%; height: 300px; border-radius: 16px; background: linear-gradient(180deg, rgba(248,250,252,.86), rgba(255,255,255,.96)); }
.runtime-chart { width: 100%; height: 260px; border-radius: 16px; background: linear-gradient(180deg, rgba(248,250,252,.86), rgba(255,255,255,.98)); }
.timeline-list { display: flex; flex-direction: column; gap: 14px; }
.timeline-item { display: flex; gap: 12px; align-items: flex-start; }
.timeline-dot { width: 10px; height: 10px; margin-top: 7px; border-radius: 50%; background: #94a3b8; box-shadow: 0 0 0 4px rgba(148,163,184,.12); }
.timeline-dot--info { background: var(--module-primary); box-shadow: 0 0 0 4px color-mix(in srgb, var(--module-primary) 18%, white); }
.timeline-dot--warning { background: #f59e0b; box-shadow: 0 0 0 4px rgba(245,158,11,.16); }
.timeline-content { flex: 1; min-width: 0; padding-bottom: 10px; border-bottom: 1px dashed rgba(148,163,184,.24); }
.timeline-top { display: flex; justify-content: space-between; gap: 12px; }
.timeline-title { color: var(--text-primary); font-weight: 700; }
.timeline-time { color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
.timeline-detail { margin-top: 6px; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.warning-text { color: #d97706; font-weight: 700; }
@media (max-width: 1280px) { .runtime-chart-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 1024px) { .dual-grid, .toolbar-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 768px) { .hero, .timeline-top { flex-direction: column; } .header-actions { width: 100%; } .dual-grid, .toolbar-grid, .runtime-chart-grid { grid-template-columns: 1fr; } .toolbar-actions { justify-content: flex-start; } }
</style>
