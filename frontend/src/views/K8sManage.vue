<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>☸️ K8s 集群管理</h2>
      <div class="k8s-toolbar" v-if="activeTab !== 'clusters'">
        <div class="cluster-selector-group">
          <span class="toolbar-label"><el-icon><Connection /></el-icon> 当前集群</span>
          <el-select v-model="selectedClusterId" placeholder="选择集群" @change="onClusterChange" style="width: 150px" class="industrial-select" popper-class="industrial-popper">
            <el-option v-for="c in clusters" :key="c.id" :label="c.name" :value="c.id">
              <div style="display:flex;align-items:center;gap:8px;font-weight:600;">
                <span class="state-pulse" :class="c.status==='connected'?'running':'exited'"></span> {{ c.name }}
              </div>
            </el-option>
          </el-select>
        </div>
        
        <div class="namespace-selector-group" v-if="needsNamespace">
          <span class="toolbar-label"><el-icon><FolderOpened /></el-icon> NS</span>
          <el-select v-model="selectedNamespace" placeholder="命名空间" @change="fetchCurrentTab" style="width: 100px" class="industrial-select" popper-class="industrial-popper">
            <el-option label="[ 全部命名空间 ]" value="_all" />
            <el-option v-for="ns in namespaces" :key="ns.name" :label="ns.name" :value="ns.name" />
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

    <!-- ============ 集群管理 ============ -->
    <div v-if="activeTab === 'clusters'" class="tab-content">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <el-button v-if="canManageK8s" type="primary" size="small" @click="openClusterDialog()"><el-icon><Plus /></el-icon> 添加集群</el-button>
      </div>
      <el-table :data="clusters" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="集群名称" min-width="160">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='connected'?'running':'exited'"></span>
              <span style="font-weight:600">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="api_server" label="API Server" min-width="220" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status==='connected'?'success':'danger'" size="small">{{ row.status==='connected'?'运行中':'未连接' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column v-if="canManageK8s" label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="testCluster(row)">测试连接</el-button>
            <el-button link type="info" size="small" @click="openClusterDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除该集群？" @confirm="delCluster(row)">
              <template #reference><el-button link type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 节点管理 ============ -->
    <div v-if="activeTab === 'nodes'" class="tab-content">
      <el-table :data="nodes" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="节点名称" min-width="180">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='Ready'?'running':'exited'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }"><el-tag :type="row.status==='Ready'?'success':'danger'" size="small">{{ row.status==='Ready'?'就绪':'未就绪' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="roles" label="角色" width="120">
          <template #default="{ row }"><el-tag size="small" type="info">{{ row.roles }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="version" label="Kubelet版本" width="120" />
        <el-table-column prop="internal_ip" label="内部IP" width="140" />
        <el-table-column label="CPU/内存" width="150">
          <template #default="{ row }">
            <div style="font-size:12px">CPU: <b>{{ row.cpu }}</b></div>
            <div style="font-size:12px">Memory: <b>{{ row.memory }}</b></div>
          </template>
        </el-table-column>
        <el-table-column prop="os_image" label="系统" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('node', row.name)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('node', row.name)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 命名空间 ============ -->
    <div v-if="activeTab === 'namespaces'" class="tab-content">
      <el-table :data="nsData" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="命名空间名称" min-width="200">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='Active'?'running':'exited'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.status==='Active'?'success':'danger'" size="small">{{ row.status==='Active'?'活跃':'终止' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="created" label="创建时间" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('namespace', row.name)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 工作负载 ============ -->
    <div v-if="activeTab === 'workloads'" class="tab-content">
      <div class="neo-sub-tabs theme-blue">
        <button v-for="st in workloadSubTabs" :key="st" class="neo-sub-tab-btn" :class="{ active: workloadSub === st }" @click="workloadSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <!-- Deployment -->
      <el-table v-if="workloadSub==='Deployment'" :data="deployments" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.ready_replicas===row.replicas?'running':'restarting'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column label="副本" width="100"><template #default="{ row }"><span :style="{color:row.ready_replicas===row.replicas?'#10b981':'#f59e0b',fontWeight:600}">{{ row.ready_replicas }}/{{ row.replicas }}</span></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 Pod (状态/日志)" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-log" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9);" @click="showPodDetail('deployment', row.name, row.namespace)"><el-icon :size="14"><Menu /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('deployment', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('deployment', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <!-- StatefulSet -->
      <el-table v-if="workloadSub==='StatefulSet'" :data="statefulsets" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.ready_replicas===row.replicas?'running':'restarting'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column label="副本" width="100"><template #default="{ row }"><span :style="{color:row.ready_replicas===row.replicas?'#10b981':'#f59e0b',fontWeight:600}">{{ row.ready_replicas }}/{{ row.replicas }}</span></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 Pod (状态/日志)" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-log" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9);" @click="showPodDetail('statefulset', row.name, row.namespace)"><el-icon :size="14"><Menu /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('statefulset', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('statefulset', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <!-- DaemonSet -->
      <el-table v-if="workloadSub==='DaemonSet'" :data="daemonsets" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.ready===row.desired?'running':'restarting'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column label="就绪" width="100"><template #default="{ row }"><span :style="{color:row.ready===row.desired?'#10b981':'#f59e0b',fontWeight:600}">{{ row.ready }}/{{ row.desired }}</span></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="240" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 Pod (状态/日志)" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-log" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9);" @click="showPodDetail('daemonset', row.name, row.namespace)"><el-icon :size="14"><Menu /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('daemonset', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('daemonset', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <!-- Job -->
      <el-table v-if="workloadSub==='Job'" :data="jobs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="220">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='Complete'?'running':'restarting'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="completions" label="完成数" width="100" />
        <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status==='Complete'?'success':'warning'" size="small">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="images" label="镜像" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 Pod (状态/日志)" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-log" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9);" @click="showPodDetail('job', row.name, row.namespace)"><el-icon :size="14"><Menu /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('job', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('job', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <!-- CronJob -->
      <el-table v-if="workloadSub==='CronJob'" :data="cronjobs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="200">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.suspend?'exited':'running'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="schedule" label="调度" width="140"><template #default="{ row }"><code style="font-size:12px;background:#f1f5f9;padding:2px 6px;border-radius:3px">{{ row.schedule }}</code></template></el-table-column>
        <el-table-column label="暂停" width="70"><template #default="{ row }"><el-tag :type="row.suspend?'danger':'success'" size="small">{{ row.suspend?'是':'否' }}</el-tag></template></el-table-column>
        <el-table-column prop="last_schedule" label="上次调度" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 Pod (状态/日志)" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-log" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9);" @click="showPodDetail('cronjob', row.name, row.namespace)"><el-icon :size="14"><Menu /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('cronjob', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('cronjob', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <!-- ============ 网络管理 ============ -->
    <div v-if="activeTab === 'network'" class="tab-content">
      <div class="neo-sub-tabs theme-blue">
        <button v-for="st in ['Service','Ingress']" :key="st" class="neo-sub-tab-btn" :class="{ active: networkSub === st }" @click="networkSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <el-table v-if="networkSub==='Service'" :data="services" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="200">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="'running'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="type" label="类型" width="110"><template #default="{ row }"><el-tag size="small" :type="row.type==='LoadBalancer'?'warning':row.type==='NodePort'?'success':'info'">{{ row.type }}</el-tag></template></el-table-column>
        <el-table-column prop="cluster_ip" label="Cluster IP" width="140" />
        <el-table-column prop="ports" label="端口" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('service', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('service', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-table v-if="networkSub==='Ingress'" :data="ingresses" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="180">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="'running'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="class" label="Ingress Class" width="120" />
        <el-table-column prop="hosts" label="域名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="address" label="地址" width="140" />
        <el-table-column prop="ports" label="端口" width="100" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('ingress', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('ingress', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 存储管理 ============ -->
    <div v-if="activeTab === 'storage'" class="tab-content">
      <div class="neo-sub-tabs theme-blue">
        <button v-for="st in ['PV','PVC','StorageClass']" :key="st" class="neo-sub-tab-btn" :class="{ active: storageSub === st }" @click="storageSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <el-table v-if="storageSub==='PV'" :data="pvs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="200">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='Bound'?'running':row.status==='Available'?'running':'warning'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="capacity" label="容量" width="90" />
        <el-table-column prop="access_modes" label="访问模式" width="100" />
        <el-table-column prop="reclaim_policy" label="回收策略" width="100" />
        <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status==='Bound'?'success':row.status==='Available'?'info':'warning'" size="small">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="claim" label="绑定声明" min-width="250" show-overflow-tooltip />
        <el-table-column prop="storage_class" label="存储类" width="120" />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('pv', row.name)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-table v-if="storageSub==='PVC'" :data="pvcs" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="240">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='Bound'?'running':'warning'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status==='Bound'?'success':'warning'" size="small">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="capacity" label="容量" width="90" />
        <el-table-column prop="access_modes" label="访问模式" width="100" />
        <el-table-column prop="storage_class" label="存储类" width="120" />
        <el-table-column prop="volume" label="PV" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('pvc', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('pvc', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-table v-if="storageSub==='StorageClass'" :data="storageclasses" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="160">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="'running'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
              <el-tag v-if="row.is_default" type="primary" size="small" style="margin-left:6px">默认</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="provisioner" label="Provisioner" min-width="220" show-overflow-tooltip />
        <el-table-column prop="reclaim_policy" label="回收策略" width="100" />
        <el-table-column prop="binding_mode" label="绑定模式" width="180" />
        <el-table-column label="允许扩展" width="90"><template #default="{ row }"><el-tag :type="row.allow_expansion?'success':'info'" size="small">{{ row.allow_expansion?'是':'否' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('storageclass', row.name)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 配置管理 ============ -->
    <div v-if="activeTab === 'config'" class="tab-content">
      <div class="neo-sub-tabs theme-blue">
        <button v-for="st in ['ConfigMap','Secret']" :key="st" class="neo-sub-tab-btn" :class="{ active: configSub === st }" @click="configSub = st; fetchCurrentTab()">{{ st }}</button>
      </div>
      <el-table v-if="configSub==='ConfigMap'" :data="configmaps" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="250">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="'running'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="data_count" label="数据条目" width="100" />
        <el-table-column prop="created" label="创建时间" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('configmap', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-table v-if="configSub==='Secret'" :data="secrets" stripe v-loading="loading" style="width:100%">
        <el-table-column prop="name" label="名称" min-width="250">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="'running'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:13px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="namespace" label="命名空间" width="130" />
        <el-table-column prop="type" label="类型" min-width="240"><template #default="{ row }"><code style="font-size:11px;background:#f1f5f9;padding:2px 6px;border-radius:3px">{{ row.type }}</code></template></el-table-column>
        <el-table-column prop="data_count" label="数据条目" width="100" />
        <el-table-column prop="created" label="创建时间" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('secret', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
<!-- PLACEHOLDER_2 -->    <!-- ============ 集群弹窗 ============ -->
    <el-dialog v-model="clusterDialogVisible" :title="editingClusterId ? '编辑集群' : '添加 K8s 集群'" width="90%" style="max-width:600px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="clusterForm" label-width="110px">
        <el-form-item label="集群名称"><el-input v-model="clusterForm.name" placeholder="例如 prod-cluster" /></el-form-item>
        <el-form-item label="API Server"><el-input v-model="clusterForm.api_server" placeholder="例如 https://10.0.0.1:6443 (可选)" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="clusterForm.description" placeholder="集群用途描述" /></el-form-item>
        <el-form-item label="KubeConfig"><el-input v-model="clusterForm.kubeconfig" type="textarea" :rows="12" placeholder="粘贴 kubeconfig YAML 内容" style="font-family:monospace;font-size:12px;" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="clusterDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCluster" :loading="savingCluster">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ YAML 查看弹窗 ============ -->
    <el-dialog v-model="yamlDialogVisible" :title="'📄 YAML - ' + yamlResourceName" width="90%" style="max-width:800px;" top="3vh" append-to-body destroy-on-close>
      <div class="yaml-viewer-toolbar">
        <span class="yaml-viewer-badge">{{ yamlResourceType }}</span>
        <el-button size="small" type="primary" plain @click="copyYaml"><el-icon><DocumentCopy /></el-icon> 复制</el-button>
      </div>
      <div class="yaml-viewer-container" v-loading="yamlLoading">
        <pre class="yaml-viewer-code"><code>{{ yamlContent }}</code></pre>
      </div>
    </el-dialog>

    <!-- ============ Pod 详情弹窗 ============ -->
    <el-dialog v-model="podDialogVisible" :title="'🔲 Pod 列表 - ' + podWorkloadName" width="95%" style="max-width:1200px;" top="3vh" append-to-body destroy-on-close>
      <el-table :data="podList" stripe v-loading="podLoading" style="width:100%" size="small">
        <el-table-column prop="name" label="Pod 名称" min-width="280">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="state-pulse" :class="row.status==='Running'?'running':row.status==='Pending'?'restarting':'exited'"></span>
              <span style="font-weight:600;font-family:'Cascadia Code','Consolas',monospace;font-size:12px;">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status==='Running'?'success':row.status==='Pending'?'warning':'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="restarts" label="重启" width="70">
          <template #default="{ row }">
            <span :style="{color: row.restarts > 0 ? '#f59e0b' : '#10b981', fontWeight: 600}">{{ row.restarts }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="node" label="节点" width="120" show-overflow-tooltip />
        <el-table-column label="IP 地址" width="160">
          <template #default="{ row }">
            <div style="font-size:11px;line-height:1.6">
              <div>Pod: <b style="color:#3b82f6">{{ row.pod_ip || '-' }}</b></div>
              <div>Host: <span style="color:#64748b">{{ row.host_ip || '-' }}</span></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="资源" width="150">
          <template #default="{ row }">
            <div style="font-size:11px;line-height:1.6">
              <div>CPU: <el-tag size="small" type="info" style="font-size:11px">{{ row.cpu_request }}</el-tag></div>
              <div>Mem: <el-tag size="small" type="info" style="font-size:11px">{{ row.memory_request }}</el-tag></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="age" label="运行时间" width="90">
          <template #default="{ row }">
            <span style="font-family:monospace;font-size:12px;color:#64748b">{{ row.age }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <div style="display:flex;gap:6px;">
              <el-tooltip content="查看日志" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-log" @click="showPodLog(row.name, row.namespace, row.containers)"><el-icon :size="14"><Monitor /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看 YAML" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-yaml" @click="showYaml('pod', row.name, row.namespace)"><el-icon :size="14"><Document /></el-icon></button>
              </el-tooltip>
              <el-tooltip content="查看事件" placement="top" :show-after="500">
                <button class="pod-op-btn pod-op-event" @click="showEvents('pod', row.name, row.namespace)"><el-icon :size="14"><Bell /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- ============ 日志查看弹窗 ============ -->
    <el-dialog v-model="logDialogVisible" :title="'🖥️ 日志 - ' + logPodName" width="90%" style="max-width:900px;" top="3vh" append-to-body destroy-on-close>
      <div class="log-viewer-toolbar">
        <div style="display:flex;align-items:center;gap:10px;">
          <span class="yaml-viewer-badge" style="background:linear-gradient(135deg,#10b981,#059669)">{{ logContainer }}</span>
          <el-select v-if="logContainers.length > 1" v-model="logContainer" size="small" style="width:140px" @change="fetchPodLog">
            <el-option v-for="c in logContainers" :key="c" :label="c" :value="c" />
          </el-select>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:12px;color:#94a3b8">行数:</span>
          <el-select v-model="logTailLines" size="small" style="width:80px" @change="fetchPodLog">
            <el-option :value="50" label="50" /><el-option :value="100" label="100" /><el-option :value="200" label="200" /><el-option :value="500" label="500" />
          </el-select>
          <el-button size="small" type="primary" plain @click="copyLogContent"><el-icon><DocumentCopy /></el-icon> 复制</el-button>
        </div>
      </div>
      <div class="log-viewer-container" v-loading="logLoading" ref="logContainerRef">
        <pre class="log-viewer-code">{{ logContent }}</pre>
      </div>
    </el-dialog>

    <!-- ============ 事件查看弹窗 ============ -->
    <el-dialog v-model="eventsDialogVisible" :title="'🔔 事件 - ' + eventsResourceName" width="90%" style="max-width:800px;" top="3vh" append-to-body destroy-on-close>
      <div v-loading="eventsLoading" style="min-height:120px;">
        <div v-if="eventsList.length === 0 && !eventsLoading" style="text-align:center;padding:40px;color:#94a3b8;">
          <el-icon :size="48" style="margin-bottom:12px;opacity:0.4"><Bell /></el-icon>
          <div>暂无事件</div>
        </div>
        <div v-else class="events-timeline">
          <div v-for="(ev, i) in eventsList" :key="i" class="event-item" :class="ev.type === 'Warning' ? 'event-warning' : 'event-normal'">
            <div class="event-indicator"></div>
            <div class="event-body">
              <div class="event-header">
                <el-tag :type="ev.type==='Warning'?'warning':''" size="small" effect="dark" style="font-size:11px">{{ ev.type }}</el-tag>
                <span class="event-reason">{{ ev.reason }}</span>
                <span v-if="ev.count > 1" class="event-count">×{{ ev.count }}</span>
                <span class="event-time">{{ formatEventTime(ev.last_time) }}</span>
              </div>
              <div class="event-message">{{ ev.message }}</div>
              <div class="event-source" v-if="ev.source">{{ ev.source }}</div>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template><script setup>import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { DocumentCopy, Document, Monitor, Bell, Plus, Connection, FolderOpened, Menu } from '@element-plus/icons-vue'
import {
  getK8sClusters, createK8sCluster, updateK8sCluster, deleteK8sCluster,
  testK8sConnection, getK8sNamespaces,
  getK8sPods, getK8sServices, getK8sDeployments, restartK8sPod,
  getK8sNodes, getK8sStatefulSets, getK8sDaemonSets, getK8sJobs, getK8sCronJobs,
  getK8sIngresses, getK8sPVs, getK8sPVCs, getK8sStorageClasses,
  getK8sConfigMaps, getK8sSecrets, getK8sResourceYaml,
  getK8sWorkloadPods, getK8sPodLogs, getK8sResourceEvents,
} from '@/api/modules/container'

const authStore = useAuthStore()
const canManageK8s = computed(() => authStore.hasPermission('ops.k8s.manage'))

const mainTabs = [
  { key: 'clusters',   label: '集群管理', icon: 'OfficeBuilding' },
  { key: 'nodes',      label: '节点管理', icon: 'Monitor' },
  { key: 'namespaces', label: '命名空间', icon: 'FolderOpened' },
  { key: 'workloads',  label: '工作负载', icon: 'Cpu' },
  { key: 'network',    label: '网络管理', icon: 'Connection' },
  { key: 'storage',    label: '存储管理', icon: 'Coin' },
  { key: 'config',     label: '配置管理', icon: 'Setting' },
]

const activeTab = ref('clusters')
const loading = ref(false)

// ====== 集群 ======
const clusters = ref([])
const selectedClusterId = ref(null)
const selectedNamespace = ref('_all')
const namespaces = ref([])

const needsNamespace = computed(() => ['namespaces', 'workloads', 'network', 'config'].includes(activeTab.value) || (activeTab.value === 'storage' && storageSub.value === 'PVC'))

// ====== 各 Tab 数据 ======
const nodes = ref([])
const nsData = ref([])
const deployments = ref([])
const statefulsets = ref([])
const daemonsets = ref([])
const jobs = ref([])
const cronjobs = ref([])
const services = ref([])
const ingresses = ref([])
const pvs = ref([])
const pvcs = ref([])
const storageclasses = ref([])
const configmaps = ref([])
const secrets = ref([])

// ====== Sub-tabs ======
const workloadSubTabs = ['Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob']
const workloadSub = ref('Deployment')
const networkSub = ref('Service')
const storageSub = ref('PV')
const configSub = ref('ConfigMap')

// ====== 切换 Tab ======
function switchTab(tab) {
  activeTab.value = tab
  if (tab === 'clusters') {
    fetchClusters()
  } else if (selectedClusterId.value) {
    fetchCurrentTab()
  }
}

async function fetchClusters() {
  loading.value = true
  try {
    const res = await getK8sClusters()
    clusters.value = res.results || res
    
    // 默认选择第一个集群
    if (clusters.value.length > 0 && !selectedClusterId.value) {
      selectedClusterId.value = clusters.value[0].id
      if (activeTab.value !== 'clusters') {
        onClusterChange()
      }
    }
  } catch (e) { /* */ }
  loading.value = false
}

async function onClusterChange() {
  namespaces.value = []
  if (!selectedClusterId.value) return
  try { namespaces.value = await getK8sNamespaces(selectedClusterId.value) } catch (e) { /* */ }
  fetchCurrentTab()
}

async function fetchCurrentTab() {
  if (!selectedClusterId.value && activeTab.value !== 'clusters') return
  loading.value = true
  const id = selectedClusterId.value
  const ns = selectedNamespace.value
  try {
    switch (activeTab.value) {
      case 'nodes': nodes.value = await getK8sNodes(id); break
      case 'namespaces': nsData.value = await getK8sNamespaces(id); break
      case 'workloads':
        if (workloadSub.value === 'Deployment') deployments.value = await getK8sDeployments(id, ns)
        else if (workloadSub.value === 'StatefulSet') statefulsets.value = await getK8sStatefulSets(id, ns)
        else if (workloadSub.value === 'DaemonSet') daemonsets.value = await getK8sDaemonSets(id, ns)
        else if (workloadSub.value === 'Job') jobs.value = await getK8sJobs(id, ns)
        else if (workloadSub.value === 'CronJob') cronjobs.value = await getK8sCronJobs(id, ns)
        break
      case 'network':
        if (networkSub.value === 'Service') services.value = await getK8sServices(id, ns)
        else ingresses.value = await getK8sIngresses(id, ns)
        break
      case 'storage':
        if (storageSub.value === 'PV') pvs.value = await getK8sPVs(id)
        else if (storageSub.value === 'PVC') pvcs.value = await getK8sPVCs(id, ns)
        else storageclasses.value = await getK8sStorageClasses(id)
        break
      case 'config':
        if (configSub.value === 'ConfigMap') configmaps.value = await getK8sConfigMaps(id, ns)
        else secrets.value = await getK8sSecrets(id, ns)
        break
    }
  } catch (e) {
    ElMessage.error('获取数据失败')
  }
  loading.value = false
}

// ====== 集群 CRUD ======
const clusterDialogVisible = ref(false)
const editingClusterId = ref(null)
const savingCluster = ref(false)
const clusterForm = ref({ name: '', api_server: '', description: '', kubeconfig: '' })

function openClusterDialog(cluster) {
  if (!canManageK8s.value) return
  if (cluster) {
    editingClusterId.value = cluster.id
    clusterForm.value = { name: cluster.name, api_server: cluster.api_server, description: cluster.description, kubeconfig: '' }
  } else {
    editingClusterId.value = null
    clusterForm.value = { name: '', api_server: '', description: '', kubeconfig: '' }
  }
  clusterDialogVisible.value = true
}

async function saveCluster() {
  if (!canManageK8s.value) return
  if (!clusterForm.value.name) return ElMessage.warning('请填写集群名称')
  if (!clusterForm.value.kubeconfig && !editingClusterId.value) return ElMessage.warning('请粘贴 KubeConfig')
  savingCluster.value = true
  try {
    const data = { ...clusterForm.value }
    if (!data.kubeconfig) delete data.kubeconfig
    if (editingClusterId.value) {
      await updateK8sCluster(editingClusterId.value, data)
      ElMessage.success('集群已更新')
    } else {
      await createK8sCluster(data)
      ElMessage.success('集群已添加')
    }
    clusterDialogVisible.value = false
    fetchClusters()
  } catch (e) { /* */ }
  savingCluster.value = false
}

async function testCluster(row) {
  if (!canManageK8s.value) return
  try {
    const res = await testK8sConnection(row.id)
    if (res.success) ElMessage.success(res.message)
    else ElMessage.error(res.message)
    fetchClusters()
  } catch (e) { ElMessage.error('连接测试失败') }
}

async function delCluster(row) {
  if (!canManageK8s.value) return
  try {
    await deleteK8sCluster(row.id)
    ElMessage.success('集群已删除')
    fetchClusters()
  } catch (e) { ElMessage.error('删除失败') }
}

// ====== YAML 查看 ======
const yamlDialogVisible = ref(false)
const yamlContent = ref('')
const yamlResourceName = ref('')
const yamlResourceType = ref('')
const yamlLoading = ref(false)

async function showYaml(type, name, namespace) {
  if (!selectedClusterId.value) return ElMessage.warning('请先选择集群')
  yamlResourceType.value = type
  yamlResourceName.value = name
  yamlContent.value = ''
  yamlDialogVisible.value = true
  yamlLoading.value = true
  try {
    const ns = namespace || selectedNamespace.value || 'default'
    const res = await getK8sResourceYaml(selectedClusterId.value, type, name, ns)
    yamlContent.value = res.yaml || res
  } catch (e) {
    yamlContent.value = '# 获取 YAML 失败'
    ElMessage.error('获取 YAML 失败')
  }
  yamlLoading.value = false
}

function copyYaml() {
  navigator.clipboard.writeText(yamlContent.value).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

// ====== Pod 详情 ======
const podDialogVisible = ref(false)
const podWorkloadName = ref('')
const podList = ref([])
const podLoading = ref(false)

async function showPodDetail(workloadType, name, namespace) {
  if (!selectedClusterId.value) return ElMessage.warning('请先选择集群')
  podWorkloadName.value = name
  podList.value = []
  podDialogVisible.value = true
  podLoading.value = true
  try {
    const ns = namespace || selectedNamespace.value || 'default'
    podList.value = await getK8sWorkloadPods(selectedClusterId.value, workloadType, name, ns)
  } catch (e) {
    ElMessage.error('获取 Pod 列表失败')
  }
  podLoading.value = false
}

// ====== Pod 日志 ======
const logDialogVisible = ref(false)
const logPodName = ref('')
const logContent = ref('')
const logContainer = ref('')
const logContainers = ref([])
const logTailLines = ref(200)
const logLoading = ref(false)
const logPodNs = ref('default')
const logContainerRef = ref(null)

function showPodLog(podName, namespace, containers) {
  logPodName.value = podName
  logPodNs.value = namespace || 'default'
  logContainers.value = containers || ['main']
  logContainer.value = logContainers.value[0]
  logContent.value = ''
  logDialogVisible.value = true
  fetchPodLog()
}

async function fetchPodLog() {
  logLoading.value = true
  try {
    const res = await getK8sPodLogs(selectedClusterId.value, logPodName.value, logPodNs.value, logContainer.value, logTailLines.value)
    logContent.value = res.logs || ''
    await nextTick()
    if (logContainerRef.value) {
      logContainerRef.value.scrollTop = logContainerRef.value.scrollHeight
    }
  } catch (e) {
    logContent.value = '# 获取日志失败'
    ElMessage.error('获取日志失败')
  }
  logLoading.value = false
}

function copyLogContent() {
  navigator.clipboard.writeText(logContent.value).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => { ElMessage.error('复制失败') })
}

// ====== 事件查看 ======
const eventsDialogVisible = ref(false)
const eventsResourceName = ref('')
const eventsList = ref([])
const eventsLoading = ref(false)

async function showEvents(type, name, namespace) {
  if (!selectedClusterId.value) return ElMessage.warning('请先选择集群')
  eventsResourceName.value = `${type}/${name}`
  eventsList.value = []
  eventsDialogVisible.value = true
  eventsLoading.value = true
  try {
    const ns = namespace || selectedNamespace.value || 'default'
    eventsList.value = await getK8sResourceEvents(selectedClusterId.value, type, name, ns)
  } catch (e) {
    ElMessage.error('获取事件失败')
  }
  eventsLoading.value = false
}

function formatEventTime(iso) {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    const now = new Date()
    const diff = Math.floor((now - d) / 1000)
    if (diff < 60) return `${diff}秒前`
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
    return `${Math.floor(diff / 86400)}天前`
  } catch { return iso }
}

// ====== 初始化 ======
onMounted(() => { fetchClusters() })
</script>
