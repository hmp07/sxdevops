<template>
  <div class="aiops-config-page">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="hero-icon"><el-icon><ChatDotSquare /></el-icon></span>
          <h2>智能体配置</h2>
          <p class="page-desc inline-subtitle">统一管理智能助手的策略、MCP、Skill、模型提供商与审计能力。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading.page" @click="loadAll">刷新</el-button>
        <el-button size="small" type="primary" :loading="saving.config" @click="saveConfig">保存策略</el-button>
      </div>
    </section>

    <div class="stats-grid release-stats">
      <div class="stat-card release-stat-card">
        <div class="stat-value">{{ providers.length }}</div>
        <div class="stat-label">模型提供商</div>
      </div>
      <div class="stat-card release-stat-card success-card">
        <div class="stat-value">{{ enabledMcpCount }}</div>
        <div class="stat-label">启用中的 MCP</div>
      </div>
      <div class="stat-card release-stat-card warning-card">
        <div class="stat-value">{{ enabledSkillCount }}</div>
        <div class="stat-label">启用中的 Skill</div>
      </div>
      <div class="stat-card release-stat-card">
        <div class="stat-value">{{ auditOverview.sessions_today || 0 }}</div>
        <div class="stat-label">今日会话数</div>
      </div>
    </div>

    <div class="runtime-strip">
      <el-icon><InfoFilled /></el-icon>
      <span>模型 Key 加密保存；高风险动作默认二次确认；MCP 与 Skill 受控接入。</span>
    </div>

    <section class="tabs-card">
      <el-tabs v-model="activeTab" class="event-like-tabs">
        <el-tab-pane name="strategy">
          <template #label>
            <span class="tab-label"><el-icon><Setting /></el-icon>智能体策略</span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="mcp">
          <template #label>
            <span class="tab-label"><el-icon><Connection /></el-icon>MCP</span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="skills">
          <template #label>
            <span class="tab-label"><el-icon><Tools /></el-icon>Skill</span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="im">
          <template #label>
            <span class="tab-label"><el-icon><Message /></el-icon>IM 接入</span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="providers">
          <template #label>
            <span class="tab-label"><el-icon><Cpu /></el-icon>模型提供商</span>
          </template>
        </el-tab-pane>
        <el-tab-pane name="audit">
          <template #label>
            <span class="tab-label"><el-icon><Tickets /></el-icon>审计</span>
          </template>
        </el-tab-pane>
      </el-tabs>
    </section>

    <section class="panel">
      <template v-if="activeTab === 'strategy'">
        <div class="config-grid">
          <div class="config-section">
            <div class="section-title">基础策略</div>
            <el-form :model="configForm" label-width="118px">
              <el-form-item label="默认提供商">
                <el-select v-model="configForm.default_provider_id" clearable style="width:100%">
                  <el-option
                    v-for="provider in providers"
                    :key="provider.id"
                    :label="providerOptionLabel(provider)"
                    :value="provider.id"
                    :disabled="!provider.runtime_ready"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="欢迎语">
                <el-input v-model="configForm.welcome_message" />
              </el-form-item>
              <el-form-item label="建议问题">
                <el-select v-model="configForm.suggested_questions" multiple filterable allow-create default-first-option style="width:100%" />
              </el-form-item>
              <el-form-item label="启用 MCP">
                <el-select v-model="configForm.enabled_mcp_server_ids" multiple collapse-tags collapse-tags-tooltip style="width:100%">
                  <el-option v-for="item in mcpServers" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="启用 Skill">
                <el-select v-model="configForm.enabled_skill_ids" multiple collapse-tags collapse-tags-tooltip style="width:100%">
                  <el-option v-for="item in skills" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="系统提示语">
                <el-input v-model="configForm.system_prompt" type="textarea" :rows="8" />
              </el-form-item>
            </el-form>
          </div>
          <div class="config-section">
            <div class="section-title">运行与安全</div>
            <div class="switch-list">
              <div class="switch-item">
                <span>启用机器人</span>
                <el-switch v-model="configForm.is_enabled" />
              </div>
              <div class="switch-item">
                <span>允许执行动作</span>
                <el-switch v-model="configForm.allow_action_execution" />
              </div>
              <div class="switch-item">
                <span>执行前确认</span>
                <el-switch v-model="configForm.require_confirmation" />
              </div>
              <div class="switch-item">
                <span>展示证据来源</span>
                <el-switch v-model="configForm.show_evidence" />
              </div>
              <div class="switch-item">
                <span>允许关联分析</span>
                <el-switch v-model="configForm.allow_analysis" />
              </div>
            </div>
            <el-form :model="configForm" label-width="118px" style="margin-top:8px;">
              <el-form-item label="历史消息窗口">
                <el-input-number v-model="configForm.max_history_messages" :min="4" :max="40" />
              </el-form-item>
            </el-form>
          </div>
        </div>
      </template>

      <template v-else-if="activeTab === 'im'">
        <div class="empty-panel">
          <div class="section-title">IM 接入</div>
          <div class="empty-copy">功能预留，暂未开发。</div>
        </div>
      </template>

      <template v-else-if="activeTab === 'providers'">
        <div class="section-toolbar">
          <el-button size="small" type="primary" @click="openProviderDialog()">新增提供商</el-button>
        </div>
        <el-table :data="providers" stripe>
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="provider_type" label="类型" width="150" />
          <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip />
          <el-table-column prop="default_model" label="默认模型" width="160" />
          <el-table-column label="Key" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.has_api_key ? 'success' : 'info'">{{ row.has_api_key ? '已配置' : '未配置' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可用性" width="118">
            <template #default="{ row }">
              <el-tooltip :content="providerRuntimeHint(row)" placement="top" :disabled="row.runtime_ready">
                <el-tag size="small" :type="providerRuntimeTagType(row)">{{ providerRuntimeLabel(row) }}</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openProviderDialog(row)">编辑</el-button>
              <el-button link type="success" @click="handleTestProvider(row)">测试</el-button>
              <el-button link type="danger" @click="handleDeleteProvider(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="activeTab === 'mcp'">
        <div class="section-toolbar">
          <el-button size="small" type="primary" @click="openMcpDialog()">新增 MCP</el-button>
        </div>
        <el-table :data="mcpServers" stripe>
          <el-table-column prop="name" label="名称" min-width="150" />
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :class="['type-tag', `type-tag--${row.server_type || 'http'}`]">
                {{ formatMcpType(row.server_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="endpoint_or_command" label="地址或命令" min-width="240" show-overflow-tooltip />
          <el-table-column label="启用工具" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ formatEnabledTools(row.tool_whitelist) }}</template>
          </el-table-column>
          <el-table-column label="运行保护" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="mcpRuntimeMode(row).type">{{ mcpRuntimeMode(row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openMcpDialog(row)">编辑</el-button>
              <el-button link type="success" @click="handleTestMcp(row)">测试</el-button>
              <el-button link @click="handleListMcpTools(row)">工具</el-button>
              <el-button link type="danger" :disabled="row.is_builtin" @click="handleDeleteMcp(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="activeTab === 'skills'">
        <div class="section-toolbar">
          <el-button size="small" type="primary" @click="openSkillDialog()">新增 Skill</el-button>
        </div>
        <el-table :data="skills" stripe>
          <el-table-column prop="name" label="名称" min-width="150" />
          <el-table-column prop="slug" label="标识" width="140" />
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :class="['type-tag', `type-tag--${getSkillTypeClass(row)}`]">
                {{ formatSkillType(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" min-width="240" />
          <el-table-column label="启用" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openSkillDialog(row)">编辑</el-button>
              <el-button link type="danger" :disabled="row.is_builtin" @click="handleDeleteSkill(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else>
        <div class="audit-grid">
          <div class="audit-card">
            <span>今日会话</span>
            <strong>{{ auditOverview.sessions_today || 0 }}</strong>
          </div>
          <div class="audit-card">
            <span>今日消息</span>
            <strong>{{ auditOverview.messages_today || 0 }}</strong>
          </div>
          <div class="audit-card">
            <span>今日动作</span>
            <strong>{{ auditOverview.actions_today || 0 }}</strong>
          </div>
          <div class="audit-card">
            <span>失败动作</span>
            <strong>{{ auditOverview.failed_actions_today || 0 }}</strong>
          </div>
        </div>
        <div class="audit-section">
          <div class="section-toolbar audit-toolbar">
            <div class="section-title" style="margin-bottom:0;">最近会话</div>
            <div class="audit-toolbar-actions">
              <span class="audit-hint">展示全部历史，可翻页查看</span>
              <el-button
                v-if="canManageAudit"
                size="small"
                type="danger"
                plain
                :disabled="!selectedAuditSessionIds.length"
                @click="handleBatchDeleteAuditSessions"
              >
                批量删除
              </el-button>
            </div>
          </div>
          <el-table :data="auditSessions" stripe size="small" @selection-change="handleAuditSessionSelectionChange">
            <el-table-column v-if="canManageAudit" type="selection" width="42" />
            <el-table-column prop="title" label="会话标题" min-width="220" show-overflow-tooltip />
            <el-table-column prop="username" label="用户" width="120" />
            <el-table-column prop="message_count" label="消息数" width="90" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="last_message_at" label="最后消息" min-width="180" />
            <el-table-column v-if="canManageAudit" label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" @click="handleDeleteAuditSession(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-row">
            <el-pagination
              v-model:current-page="auditSessionPagination.page"
              :page-size="auditSessionPagination.pageSize"
              :total="auditSessionPagination.total"
              layout="total, prev, pager, next"
              @current-change="loadAuditSessions"
            />
          </div>
        </div>
        <div class="audit-section">
          <div class="section-title">最近工具调用</div>
          <el-table :data="auditTools.slice(0, 8)" stripe size="small">
            <el-table-column prop="tool_name" label="工具" width="180" />
            <el-table-column prop="username" label="用户" width="120" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="latency_ms" label="耗时(ms)" width="110" />
            <el-table-column prop="created_at" label="时间" min-width="180" />
          </el-table>
        </div>
        <div class="audit-section">
          <div class="section-title">最近动作</div>
          <el-table :data="auditActions.slice(0, 8)" stripe size="small">
            <el-table-column prop="title" label="动作标题" min-width="180" />
            <el-table-column prop="risk_level_display" label="风险" width="100" />
            <el-table-column prop="status_display" label="状态" width="120" />
            <el-table-column prop="confirmed_by" label="确认人" width="120" />
            <el-table-column prop="updated_at" label="更新时间" min-width="180" />
          </el-table>
        </div>
      </template>
    </section>

    <el-dialog v-model="providerDialogVisible" :title="providerForm.id ? '编辑提供商' : '新增提供商'" width="760px" destroy-on-close>
      <el-form :model="providerForm" label-width="102px">
        <el-form-item label="名称"><el-input v-model="providerForm.name" /></el-form-item>
        <el-form-item label="类型"><el-select v-model="providerForm.provider_type" style="width:100%"><el-option label="OpenAI Compatible" value="openai_compatible" /></el-select></el-form-item>
        <el-form-item label="供应商预设">
          <el-select v-model="selectedProviderPreset" filterable clearable placeholder="选择 DeepSeek / 智谱 GLM / MiniMax 等预设" style="width:100%" @change="applyProviderPreset">
            <el-option v-for="item in providerPresets" :key="item.key" :label="item.name" :value="item.key">
              <span>{{ item.name }}</span>
              <span class="provider-preset-option">{{ item.default_model || '自定义模型' }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <div v-if="selectedProviderPresetDetail" class="provider-preset-card">
          <strong>{{ selectedProviderPresetDetail.name }}</strong>
          <span>{{ selectedProviderPresetDetail.notes }}</span>
          <a v-if="selectedProviderPresetDetail.docs_url" :href="selectedProviderPresetDetail.docs_url" target="_blank" rel="noreferrer">查看官方文档</a>
        </div>
        <el-form-item label="Base URL"><el-input v-model="providerForm.base_url" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="providerForm.api_key" type="password" show-password :placeholder="providerApiKeyPlaceholder" /></el-form-item>
        <div class="model-discovery-strip">
          <el-button size="small" :loading="saving.models" :disabled="!providerForm.id" @click="handleListProviderModels">
            拉取模型列表
          </el-button>
          <span v-if="!providerForm.id" class="model-discovery-hint">新增提供商请先保存后再拉取模型。</span>
          <span v-else-if="providerModelRecommendation" class="model-discovery-hint">
            推荐 {{ providerModelRecommendation.model }}
            <el-tag size="small" :type="providerModelRecommendation.supports_tool_calling ? 'success' : 'warning'">
              {{ providerModelRecommendation.supports_tool_calling ? 'Tool Calling 可用' : '已验证文本' }}
            </el-tag>
            <el-button link type="primary" @click="applyRecommendedModel">一键填入</el-button>
          </span>
          <span v-else-if="providerModels.length" class="model-discovery-hint">已拉取 {{ providerModels.length }} 个模型，可在下方选择。</span>
        </div>
        <div class="dialog-grid">
          <el-form-item label="默认模型">
            <el-select v-model="providerForm.default_model" filterable allow-create default-first-option style="width:100%">
              <el-option v-for="item in providerModels" :key="item.id" :label="formatProviderModelLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="备用模型">
            <el-select v-model="providerForm.backup_model" filterable allow-create default-first-option clearable style="width:100%">
              <el-option v-for="item in providerModels" :key="item.id" :label="formatProviderModelLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="温度"><el-input-number v-model="providerForm.temperature" :min="0" :max="2" :step="0.1" /></el-form-item>
          <el-form-item label="最大 Tokens"><el-input-number v-model="providerForm.max_tokens" :min="100" :max="16000" :step="100" /></el-form-item>
          <el-form-item label="超时"><el-input-number v-model="providerForm.timeout_seconds" :min="5" :max="120" /></el-form-item>
          <el-form-item label="启用"><el-switch v-model="providerForm.is_enabled" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.provider" @click="saveProvider">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mcpDialogVisible" :title="mcpForm.id ? '编辑 MCP' : '新增 MCP'" width="680px" destroy-on-close>
      <el-form :model="mcpForm" label-width="102px">
        <el-form-item label="名称"><el-input v-model="mcpForm.name" /></el-form-item>
        <el-form-item label="类型"><el-select v-model="mcpForm.server_type" style="width:100%"><el-option label="HTTP" value="http" /><el-option label="STDIO" value="stdio" /><el-option label="平台内置" value="platform_builtin" /></el-select></el-form-item>
        <el-form-item label="地址或命令"><el-input v-model="mcpForm.endpoint_or_command" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="mcpForm.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="鉴权配置"><el-input v-model="mcpForm.auth_config_text" type="textarea" :rows="5" placeholder='例如：{"headers":{"Authorization":"Bearer xxx"},"env":{"TOKEN":"xxx"}}' /></el-form-item>
        <div v-if="mcpForm.server_type !== 'platform_builtin'" class="mcp-guard-card">
          <strong>外部 MCP 运行保护</strong>
          <span>默认只读过滤 create/update/delete/run 等写入工具；STDIO 只继承安全系统环境变量，业务凭据请显式放入 auth_config.env。</span>
        </div>
        <div v-if="mcpForm.server_type !== 'platform_builtin'" class="dialog-grid">
          <el-form-item label="写操作">
            <el-switch v-model="mcpAllowWrite" active-text="允许写工具" inactive-text="只读过滤" />
          </el-form-item>
          <el-form-item label="超时秒数">
            <el-input-number v-model="mcpTimeoutSeconds" :min="5" :max="300" />
          </el-form-item>
        </div>
        <el-form-item label="启用工具"><el-select v-model="mcpForm.tool_whitelist" multiple filterable allow-create default-first-option style="width:100%" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="mcpForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mcpDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.mcp" @click="saveMcp">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="skillDialogVisible" :title="skillForm.id ? '编辑 Skill' : '新增 Skill'" width="760px" destroy-on-close>
      <div v-if="skillForm.id" class="skill-detail-card">
        <div class="skill-detail-title">Skill 详情</div>
        <div class="skill-detail-meta">
          <span>名称：{{ skillForm.name || '--' }}</span>
          <span>标识：{{ skillForm.slug || '--' }}</span>
          <span>类型：{{ formatSkillType(skillForm) }}</span>
        </div>
        <div class="skill-detail-desc">{{ skillForm.description || '暂无描述' }}</div>
      </div>
      <el-form :model="skillForm" label-width="102px">
        <div class="dialog-grid">
          <el-form-item label="名称"><el-input v-model="skillForm.name" /></el-form-item>
          <el-form-item label="标识"><el-input v-model="skillForm.slug" /></el-form-item>
        </div>
        <el-form-item label="来源"><el-select v-model="skillForm.source_type" style="width:100%"><el-option label="平台内置" value="inline" /><el-option label="本地文件" value="local" /></el-select></el-form-item>
        <el-form-item label="描述"><el-input v-model="skillForm.description" /></el-form-item>
        <el-form-item label="允许角色"><el-select v-model="skillForm.allowed_role_codes" multiple filterable allow-create default-first-option style="width:100%" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="skillForm.content" type="textarea" :rows="8" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="skillForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="skillDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.skill" @click="saveSkill">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mcpToolsDialogVisible" title="MCP 工具列表" width="760px" destroy-on-close>
      <div class="section-title" style="margin-bottom:12px;">{{ currentMcpToolsTitle || '工具列表' }}</div>
      <div v-if="mcpToolDiagnostics.length" class="mcp-diagnostic-list">
        <div v-for="item in mcpToolDiagnostics" :key="`${item.name}-${item.status}`" class="mcp-diagnostic-item">
          <el-tag size="small" :type="mcpDiagnosticType(item.status)">{{ mcpDiagnosticLabel(item.status) }}</el-tag>
          <span>{{ item.name }}：{{ item.message || `发现 ${item.tool_count || 0} 个工具` }}</span>
        </div>
      </div>
      <el-table :data="mcpToolsList" stripe max-height="420">
        <el-table-column prop="name" label="工具名" min-width="180" />
        <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
        <el-table-column label="参数" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ formatMcpToolSchema(row) }}</template>
        </el-table-column>
        <el-table-column label="安全提示" width="120">
          <template #default="{ row }">
            <el-tag v-if="row._meta?.description_warnings?.length" size="small" type="warning">需复核</el-tag>
            <span v-else class="muted-text">--</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!mcpToolsList.length" class="session-empty">暂无工具</div>
      <template #footer>
        <el-button @click="mcpToolsDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ChatDotSquare, Connection, Cpu, InfoFilled, Message, Setting, Tickets, Tools } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  createAIOpsMcpServer,
  createAIOpsProvider,
  createAIOpsSkill,
  bulkDeleteAIOpsAuditSessions,
  deleteAIOpsAuditSession,
  deleteAIOpsMcpServer,
  deleteAIOpsProvider,
  deleteAIOpsSkill,
  getAIOpsAuditActions,
  getAIOpsAuditOverview,
  getAIOpsAuditSessions,
  getAIOpsAuditToolInvocations,
  getAIOpsConfig,
  getAIOpsProviderPresets,
  getAIOpsMcpServers,
  getAIOpsProviders,
  getAIOpsSkills,
  listAIOpsProviderModels,
  listAIOpsMcpTools,
  testAIOpsProvider,
  testAIOpsMcpServer,
  updateAIOpsConfig,
  updateAIOpsMcpServer,
  updateAIOpsProvider,
  updateAIOpsSkill,
} from '@/api/modules/aiops'

const activeTab = ref('strategy')
const authStore = useAuthStore()
const loading = reactive({ page: false })
const saving = reactive({ config: false, provider: false, models: false, mcp: false, skill: false })

const providers = ref([])
const providerPresets = ref([])
const mcpServers = ref([])
const skills = ref([])
const auditOverview = ref({})
const auditSessions = ref([])
const auditTools = ref([])
const auditActions = ref([])
const selectedAuditSessionIds = ref([])
const auditSessionPagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
})

const configForm = reactive({
  default_provider_id: null,
  system_prompt: '',
  welcome_message: '',
  suggested_questions: [],
  enabled_mcp_server_ids: [],
  enabled_skill_ids: [],
  is_enabled: true,
  allow_action_execution: true,
  require_confirmation: true,
  show_evidence: true,
  allow_analysis: true,
  max_history_messages: 12,
})

const providerDialogVisible = ref(false)
const mcpDialogVisible = ref(false)
const skillDialogVisible = ref(false)
const mcpToolsDialogVisible = ref(false)

const providerForm = reactive({})
const providerModels = ref([])
const providerModelRecommendation = ref(null)
const selectedProviderPreset = ref('')
const mcpForm = reactive({})
const skillForm = reactive({})
const mcpToolsList = ref([])
const mcpToolDiagnostics = ref([])
const currentMcpToolsTitle = ref('')

const enabledMcpCount = computed(() => mcpServers.value.filter(item => item.is_enabled).length)
const enabledSkillCount = computed(() => skills.value.filter(item => item.is_enabled).length)
const canManageAudit = computed(() => authStore.hasPermission('aiops.audit.manage'))
const selectedProviderPresetDetail = computed(() => providerPresets.value.find(item => item.key === selectedProviderPreset.value) || null)
const providerApiKeyPlaceholder = computed(() => {
  const preset = selectedProviderPresetDetail.value
  if (preset?.api_key_placeholder) return providerForm.id ? `留空则保留原值；${preset.api_key_placeholder}` : preset.api_key_placeholder
  return providerForm.id ? '留空则保留原值' : 'API Key'
})
const mcpAuthConfig = computed(() => {
  try {
    const raw = mcpForm.auth_config_text?.trim()
    return raw ? JSON.parse(raw) : {}
  } catch (error) {
    return mcpForm.auth_config && typeof mcpForm.auth_config === 'object' ? mcpForm.auth_config : {}
  }
})
const mcpAllowWrite = computed({
  get: () => Boolean(mcpAuthConfig.value.allow_write),
  set: (value) => updateMcpAuthConfig({ allow_write: Boolean(value) }),
})
const mcpTimeoutSeconds = computed({
  get: () => Number(mcpAuthConfig.value.timeout_seconds || 20),
  set: (value) => updateMcpAuthConfig({ timeout_seconds: Number(value || 20) }),
})

function formatMcpType(serverType) {
  if (serverType === 'platform_builtin') return '平台内置'
  if (serverType === 'stdio') return 'STDIO'
  return 'HTTP'
}

function updateMcpAuthConfig(patch) {
  const nextConfig = { ...mcpAuthConfig.value, ...patch }
  mcpForm.auth_config = nextConfig
  mcpForm.auth_config_text = JSON.stringify(nextConfig, null, 2)
}

function mcpRuntimeMode(row = {}) {
  if (row.server_type === 'platform_builtin') return { label: '平台内置', type: 'success' }
  return row.auth_config?.allow_write ? { label: '可写', type: 'warning' } : { label: '只读', type: 'info' }
}

function mcpDiagnosticType(status) {
  if (status === 'connected') return 'success'
  if (status === 'failed') return 'danger'
  return 'info'
}

function mcpDiagnosticLabel(status) {
  if (status === 'connected') return '已连接'
  if (status === 'failed') return '失败'
  return '未知'
}

function formatMcpToolSchema(row = {}) {
  const properties = row.inputSchema?.properties || {}
  const names = Object.keys(properties)
  if (!names.length) return '无参数'
  return names.slice(0, 6).join('、') + (names.length > 6 ? '…' : '')
}

function formatSkillSource(row = {}) {
  if (row.is_builtin || row.source_type === 'inline') return '平台内置'
  return '本地文件'
}

function formatSkillType(row = {}) {
  return formatSkillSource(row)
}

function getSkillTypeClass(row = {}) {
  return row.is_builtin || row.source_type === 'inline' ? 'platform_builtin' : 'local'
}

function formatEnabledTools(tools) {
  if (!Array.isArray(tools) || !tools.length) return '--'
  return tools.join('、')
}

function formatProviderModelLabel(item = {}) {
  const owner = item.owned_by ? ` · ${item.owned_by}` : ''
  return `${item.id}${owner}`
}

function providerOptionLabel(provider = {}) {
  if (provider.runtime_ready) return provider.name
  return `${provider.name}（${provider.is_enabled ? '待配置' : '停用'}）`
}

function providerRuntimeTagType(row = {}) {
  if (row.runtime_ready) return 'success'
  return row.is_enabled ? 'warning' : 'info'
}

function providerRuntimeLabel(row = {}) {
  if (row.runtime_ready) return '可用'
  return row.is_enabled ? '待配置' : '停用'
}

function providerRuntimeHint(row = {}) {
  if (row.runtime_ready) return '可作为智能助手运行模型'
  return row.setup_hint || (row.is_enabled ? '请补全模型配置后使用' : '当前已停用，启用后可作为运行模型')
}

function detectProviderPreset(provider = {}) {
  const baseUrl = (provider.base_url || '').toLowerCase()
  if (baseUrl.includes('deepseek')) return 'deepseek'
  if (baseUrl.includes('bigmodel') || /^glm-/i.test(provider.default_model || '')) return 'zhipu_glm'
  if (baseUrl.includes('minimax') || /^minimax/i.test(provider.default_model || '')) return 'minimax'
  return ''
}

function applyProviderPreset(key) {
  const preset = providerPresets.value.find(item => item.key === key)
  if (!preset) return
  Object.assign(providerForm, {
    name: providerForm.name || preset.name,
    provider_type: preset.provider_type || 'openai_compatible',
    base_url: preset.base_url || providerForm.base_url,
    default_model: preset.default_model || providerForm.default_model,
    backup_model: preset.backup_model || providerForm.backup_model,
    temperature: preset.temperature ?? providerForm.temperature,
    max_tokens: preset.max_tokens || providerForm.max_tokens,
    timeout_seconds: preset.timeout_seconds || providerForm.timeout_seconds,
  })
  providerModels.value = []
  providerModelRecommendation.value = null
}

function resetProviderForm() {
  Object.assign(providerForm, {
    id: null,
    name: '',
    provider_type: 'openai_compatible',
    base_url: '',
    api_key: '',
    default_model: '',
    backup_model: '',
    temperature: 0.2,
    max_tokens: 1200,
    timeout_seconds: 30,
    is_enabled: true,
  })
  selectedProviderPreset.value = ''
}

function resetMcpForm() {
  Object.assign(mcpForm, {
    id: null,
    name: '',
    server_type: 'http',
    endpoint_or_command: '',
    description: '',
    auth_config: {},
    auth_config_text: '{}',
    tool_whitelist: [],
    is_enabled: true,
  })
  mcpToolDiagnostics.value = []
}

function resetSkillForm() {
  Object.assign(skillForm, {
    id: null,
    name: '',
    slug: '',
    source_type: 'inline',
    description: '',
    content: '',
    allowed_role_codes: [],
    is_enabled: true,
  })
}

function applyConfig(payload = {}) {
  Object.assign(configForm, {
    default_provider_id: payload.default_provider?.id || null,
    system_prompt: payload.system_prompt || '',
    welcome_message: payload.welcome_message || '',
    suggested_questions: payload.suggested_questions || [],
    enabled_mcp_server_ids: payload.enabled_mcp_server_ids || [],
    enabled_skill_ids: payload.enabled_skill_ids || [],
    is_enabled: payload.is_enabled ?? true,
    allow_action_execution: payload.allow_action_execution ?? true,
    require_confirmation: payload.require_confirmation ?? true,
    show_evidence: payload.show_evidence ?? true,
    allow_analysis: payload.allow_analysis ?? true,
    max_history_messages: payload.max_history_messages || 12,
  })
}

async function loadAll() {
  loading.page = true
  try {
    const [config, providerData, presetData, mcpData, skillData, auditData, toolData, actionData] = await Promise.all([
      getAIOpsConfig(),
      getAIOpsProviders(),
      getAIOpsProviderPresets(),
      getAIOpsMcpServers(),
      getAIOpsSkills(),
      getAIOpsAuditOverview(),
      getAIOpsAuditToolInvocations(),
      getAIOpsAuditActions(),
    ])
    applyConfig(config)
    providers.value = providerData || []
    providerPresets.value = presetData?.presets || []
    mcpServers.value = mcpData || []
    skills.value = skillData || []
    auditOverview.value = auditData || {}
    auditTools.value = toolData.results || toolData || []
    auditActions.value = actionData.results || actionData || []
    await loadAuditSessions(auditSessionPagination.page)
  } finally {
    loading.page = false
  }
}

async function loadAuditSessions(page = 1) {
  try {
    const sessionData = await getAIOpsAuditSessions({ page })
    auditSessionPagination.page = page
    auditSessionPagination.total = sessionData.count || 0
    auditSessions.value = sessionData.results || sessionData || []
    selectedAuditSessionIds.value = []
  } catch (error) {
    const message = String(error?.response?.data?.detail || '')
    if (page > 1 && message.includes('无效页面')) {
      return loadAuditSessions(page - 1)
    }
    throw error
  }
}

async function saveConfig() {
  saving.config = true
  try {
    await updateAIOpsConfig({ ...configForm })
    ElMessage.success('智能体策略已保存')
    await loadAll()
  } finally {
    saving.config = false
  }
}

function openProviderDialog(row) {
  resetProviderForm()
  providerModels.value = []
  providerModelRecommendation.value = null
  if (row) {
    Object.assign(providerForm, row, { api_key: '' })
    selectedProviderPreset.value = detectProviderPreset(row)
  }
  providerDialogVisible.value = true
}

async function saveProvider() {
  saving.provider = true
  try {
    const payload = { ...providerForm }
    if (!payload.api_key) delete payload.api_key
    if (providerForm.id) await updateAIOpsProvider(providerForm.id, payload)
    else await createAIOpsProvider(payload)
    providerDialogVisible.value = false
    ElMessage.success('模型提供商已保存')
    await loadAll()
  } finally {
    saving.provider = false
  }
}

async function handleTestProvider(row) {
  try {
    const result = await testAIOpsProvider(row.id)
    ElMessage.success(result.message)
  } catch (error) {
    ElMessage.error(error.response?.data?.message || row.setup_hint || '模型测试失败')
  } finally {
    await loadAll()
  }
}

async function handleListProviderModels() {
  if (!providerForm.id) {
    ElMessage.warning('请先保存提供商后再拉取模型列表')
    return
  }
  if (providerForm.api_key) {
    ElMessage.warning('检测到 API Key 尚未保存，请先保存后再拉取模型列表')
    return
  }
  saving.models = true
  try {
    const result = await listAIOpsProviderModels(providerForm.id, { probe: true })
    providerModels.value = result.models || []
    providerModelRecommendation.value = result.recommendation || null
    if (result.catalog_error) {
      ElMessage.warning(result.fallback_used ? `模型列表接口不可用，已回退到已配置模型：${result.catalog_error}` : result.catalog_error)
    }
    if (providerModelRecommendation.value?.model) {
      providerForm.default_model = providerModelRecommendation.value.model
      ElMessage.success(providerModelRecommendation.value.message || `已推荐 ${providerModelRecommendation.value.model}`)
    } else if (providerModels.value.length) {
      ElMessage.success(`已拉取 ${providerModels.value.length} 个模型`)
    } else {
      ElMessage.warning('未从供应商返回模型列表')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '拉取模型列表失败')
  } finally {
    saving.models = false
  }
}

function applyRecommendedModel() {
  if (!providerModelRecommendation.value?.model) return
  providerForm.default_model = providerModelRecommendation.value.model
  const fallback = providerModels.value.find(item => item.id !== providerModelRecommendation.value.model)?.id || providerForm.backup_model
  providerForm.backup_model = fallback || ''
  ElMessage.success('已填入推荐模型，保存后生效')
}

async function handleDeleteProvider(row) {
  await ElMessageBox.confirm(`确认删除模型提供商 ${row.name} 吗？`, '删除确认', { type: 'warning' })
  await deleteAIOpsProvider(row.id)
  ElMessage.success('模型提供商已删除')
  await loadAll()
}

function openMcpDialog(row) {
  resetMcpForm()
  if (row) Object.assign(mcpForm, row, { auth_config_text: JSON.stringify(row.auth_config || {}, null, 2) })
  mcpDialogVisible.value = true
}

async function handleTestMcp(row) {
  const result = await testAIOpsMcpServer(row.id)
  ElMessage.success(result.message || 'MCP 连接成功')
}

async function handleListMcpTools(row) {
  const result = await listAIOpsMcpTools(row.id)
  currentMcpToolsTitle.value = `${row.name} / ${result.count || 0} 个工具`
  mcpToolsList.value = result.tools || []
  mcpToolDiagnostics.value = result.diagnostics || []
  mcpToolsDialogVisible.value = true
}

async function saveMcp() {
  saving.mcp = true
  try {
    const payload = { ...mcpForm }
    try {
      payload.auth_config = payload.auth_config_text?.trim() ? JSON.parse(payload.auth_config_text) : {}
    } catch (error) {
      ElMessage.error('鉴权配置不是合法 JSON')
      return
    }
    delete payload.auth_config_text
    if (mcpForm.id) await updateAIOpsMcpServer(mcpForm.id, payload)
    else await createAIOpsMcpServer(payload)
    mcpDialogVisible.value = false
    ElMessage.success('MCP 配置已保存')
    await loadAll()
  } finally {
    saving.mcp = false
  }
}

async function handleDeleteMcp(row) {
  await ElMessageBox.confirm(`确认删除 MCP ${row.name} 吗？`, '删除确认', { type: 'warning' })
  await deleteAIOpsMcpServer(row.id)
  ElMessage.success('MCP 已删除')
  await loadAll()
}

function openSkillDialog(row) {
  resetSkillForm()
  if (row) Object.assign(skillForm, row)
  skillDialogVisible.value = true
}

async function saveSkill() {
  saving.skill = true
  try {
    if (skillForm.id) await updateAIOpsSkill(skillForm.id, { ...skillForm })
    else await createAIOpsSkill({ ...skillForm })
    skillDialogVisible.value = false
    ElMessage.success('Skill 已保存')
    await loadAll()
  } finally {
    saving.skill = false
  }
}

async function handleDeleteSkill(row) {
  await ElMessageBox.confirm(`确认删除 Skill ${row.name} 吗？`, '删除确认', { type: 'warning' })
  await deleteAIOpsSkill(row.id)
  ElMessage.success('Skill 已删除')
  await loadAll()
}

async function handleDeleteAuditSession(row) {
  await ElMessageBox.confirm(`确认删除会话《${row.title}》吗？该操作不可恢复。`, '删除确认', { type: 'warning' })
  await deleteAIOpsAuditSession(row.id)
  const shouldFallbackPage = auditSessions.value.length === 1 && auditSessionPagination.page > 1
  ElMessage.success('会话已删除')
  await Promise.all([
    getAIOpsAuditOverview().then((data) => {
      auditOverview.value = data || {}
    }),
    loadAuditSessions(shouldFallbackPage ? auditSessionPagination.page - 1 : auditSessionPagination.page),
  ])
}

function handleAuditSessionSelectionChange(rows) {
  selectedAuditSessionIds.value = rows.map((item) => item.id)
}

async function handleBatchDeleteAuditSessions() {
  if (!selectedAuditSessionIds.value.length) return
  await ElMessageBox.confirm(`确认批量删除已选中的 ${selectedAuditSessionIds.value.length} 个会话吗？该操作不可恢复。`, '批量删除确认', { type: 'warning' })
  const shouldFallbackPage = selectedAuditSessionIds.value.length === auditSessions.value.length && auditSessionPagination.page > 1
  const deletedCount = selectedAuditSessionIds.value.length
  await bulkDeleteAIOpsAuditSessions(selectedAuditSessionIds.value)
  ElMessage.success(`已删除 ${deletedCount} 个会话`)
  await Promise.all([
    getAIOpsAuditOverview().then((data) => {
      auditOverview.value = data || {}
    }),
    loadAuditSessions(shouldFallbackPage ? auditSessionPagination.page - 1 : auditSessionPagination.page),
  ])
}

onMounted(async () => {
  resetProviderForm()
  resetMcpForm()
  resetSkillForm()
  await loadAll()
})
</script>

<style scoped>
.aiops-config-page{display:flex;flex-direction:column;gap:8px}
.panel{background:linear-gradient(180deg,#fff 0%,#fffdf8 100%);border:1px solid rgba(148,163,184,.16);border-radius:20px;box-shadow:0 12px 28px rgba(15,23,42,.05);padding:14px 16px}
.hero,.release-hero-copy,.release-hero-title-row,.hero-actions,.config-grid,.switch-list,.section-toolbar,.audit-grid{display:flex;gap:8px}
.hero-actions{align-items:center;flex-wrap:wrap}
.hero-actions :deep(.el-button){min-height:38px;padding:0 16px;border-radius:12px}
.hero{align-items:center;justify-content:space-between;background:linear-gradient(135deg,#fff7ed 0%,#f8fbff 100%)}
.release-hero-title-row{align-items:center}
.release-hero-title-inline{flex-wrap:wrap}
.hero-icon{width:42px;height:42px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;color:#fff;background:linear-gradient(135deg,#0f766e,#0ea5e9)}
.hero h2{margin:0;font-size:24px;color:#0f172a}
.page-desc.inline-subtitle{margin:0;color:#64748b;font-size:13px;line-height:1.6}
.stats-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.release-stat-card{position:relative;min-height:76px;padding:14px 16px;border-radius:16px;background:linear-gradient(145deg,#ffffff 0%,#f6faff 100%);border:1px solid rgba(148,163,184,.16);box-shadow:0 12px 26px rgba(15,23,42,.05);overflow:hidden}.release-stat-card::after{content:'';position:absolute;inset:auto -24px -30px auto;width:108px;height:108px;border-radius:50%;background:radial-gradient(circle,rgba(64,158,255,.16) 0%,rgba(64,158,255,0) 70%)}.stat-value{position:relative;font-size:28px;font-weight:700;color:#0f172a}.stat-label{position:relative;margin-top:6px;color:#64748b;font-size:13px}.success-card::after{background:radial-gradient(circle,rgba(16,185,129,.18) 0%,rgba(16,185,129,0) 70%)}.warning-card::after{background:radial-gradient(circle,rgba(245,158,11,.18) 0%,rgba(245,158,11,0) 70%)}
.runtime-strip{display:flex;align-items:center;gap:0;padding:8px 11px;border-radius:10px;background:linear-gradient(90deg,rgba(59,130,246,.08) 0%,rgba(14,165,233,.04) 100%);color:#64748b;border:1px solid rgba(59,130,246,.14);font-size:12px;line-height:1.45;margin-top:-10px}.runtime-strip :deep(.el-icon){display:none}
.tabs-card{display:flex;align-items:flex-start;width:100%;padding:4px;border:1px solid rgba(148,163,184,.16);border-radius:12px;background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(248,250,252,.9));box-shadow:0 12px 26px rgba(15,23,42,.04)}.event-like-tabs{width:100%}.event-like-tabs :deep(.el-tabs__header){margin:0}.event-like-tabs :deep(.el-tabs__nav-wrap){display:block;max-width:100%;padding:0;border:0;border-radius:0;background:transparent;box-shadow:none}.event-like-tabs :deep(.el-tabs__nav-wrap::after),.event-like-tabs :deep(.el-tabs__active-bar){display:none}.event-like-tabs :deep(.el-tabs__content){display:none}.event-like-tabs :deep(.el-tabs__nav-scroll){overflow:visible}.event-like-tabs :deep(.el-tabs__nav){display:flex;gap:8px;border:0}.event-like-tabs :deep(.el-tabs__item){min-height:38px;height:38px;padding:0 20px!important;border-radius:8px;color:#4e5969;font-size:13px;font-weight:700;line-height:38px}.event-like-tabs :deep(.el-tabs__item:hover){background:rgba(51,112,255,.06);color:#245bdb}.event-like-tabs :deep(.el-tabs__item.is-active){background:#e8f0ff;color:#245bdb;box-shadow:inset 0 0 0 1px rgba(51,112,255,.08)}.tab-label{display:inline-flex;align-items:center;gap:6px}.tab-label :deep(.el-icon){font-size:15px}
.config-grid{align-items:flex-start}.config-section{flex:1;padding:8px 0}.section-title{font-size:14px;font-weight:700;color:#0f172a;margin-bottom:8px}.switch-list{flex-direction:column}.switch-item{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0}
.section-toolbar{justify-content:flex-end;margin-bottom:8px}.dialog-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 10px}.audit-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.audit-card{padding:16px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;display:flex;flex-direction:column;gap:8px}.audit-card strong{font-size:28px;color:#0f172a}
.model-discovery-strip{display:flex;align-items:center;gap:8px;margin:-2px 0 12px 102px;padding:8px 10px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0}
.model-discovery-hint{display:inline-flex;align-items:center;gap:6px;color:#64748b;font-size:12px;line-height:1.4}
.provider-preset-option{float:right;margin-left:18px;color:#94a3b8;font-size:12px}
.provider-preset-card{display:flex;align-items:center;gap:10px;margin:-4px 0 12px 102px;padding:9px 11px;border-radius:12px;background:linear-gradient(135deg,#f8fafc,#eff6ff);border:1px solid #dbeafe;color:#475569;font-size:12px;line-height:1.5}
.provider-preset-card strong{color:#0f172a;font-size:13px}.provider-preset-card a{color:#2563eb;text-decoration:none}
.mcp-guard-card{display:flex;flex-direction:column;gap:4px;margin:-2px 0 12px 102px;padding:10px 12px;border-radius:12px;background:linear-gradient(135deg,#f8fafc,#fff7ed);border:1px solid #e2e8f0;color:#64748b;font-size:12px;line-height:1.5}
.mcp-guard-card strong{color:#0f172a;font-size:13px}
.mcp-diagnostic-list{display:flex;flex-direction:column;gap:6px;margin-bottom:10px;padding:10px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0}
.mcp-diagnostic-item{display:flex;align-items:center;gap:8px;color:#475569;font-size:12px;line-height:1.5}
.muted-text{color:#94a3b8}
.audit-section{margin-top:8px}
.audit-toolbar{justify-content:space-between;align-items:center}
.audit-toolbar-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.audit-hint{color:#64748b;font-size:12px}
.pagination-row{display:flex;justify-content:flex-end;margin-top:10px}
.empty-panel{padding:18px 4px 8px}
.empty-copy{min-height:120px;padding:16px 18px;border-radius:14px;background:linear-gradient(180deg,#fff 0%,#f8fafc 100%);border:1px dashed rgba(148,163,184,.35);color:#64748b;font-size:13px;line-height:1.8}
.skill-detail-card{margin-bottom:16px;padding:12px 14px;border-radius:14px;background:linear-gradient(145deg,#fff7ed 0%,#f8fafc 100%);border:1px solid rgba(148,163,184,.2)}
.skill-detail-title{font-size:14px;font-weight:700;color:#0f172a;margin-bottom:8px}
.skill-detail-meta{display:flex;flex-wrap:wrap;gap:8px 16px;color:#475569;font-size:13px}
.skill-detail-desc{margin-top:8px;color:#64748b;font-size:13px;line-height:1.6}
.type-tag{border-width:1px}
.type-tag--platform_builtin{color:#166534;border-color:#86efac;background:#f0fdf4}
.type-tag--stdio{color:#1d4ed8;border-color:#93c5fd;background:#eff6ff}
.type-tag--http{color:#92400e;border-color:#fcd34d;background:#fffbeb}
.type-tag--local{color:#7c3aed;border-color:#c4b5fd;background:#f5f3ff}
@media (max-width: 960px){.stats-grid,.audit-grid,.dialog-grid{grid-template-columns:1fr}.config-grid{flex-direction:column}}
.hero.panel { border-radius: 20px; }
</style>



