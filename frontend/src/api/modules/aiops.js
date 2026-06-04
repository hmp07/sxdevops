import request from '../request'

const AIOPS_CHAT_TIMEOUT = 120000
const AIOPS_MODEL_TEST_TIMEOUT = 45000

export const getAIOpsBootstrap = () => request.get('/aiops/bootstrap/')
export const getAIOpsKnowledgeGraph = (params) => request.get('/aiops/knowledge-graph/', { params })
export const getAIOpsKnowledgeEnvironments = (params) => request.get('/aiops/knowledge-environments/', { params })
export const getAIOpsKnowledgeEnvironmentCatalog = () => request.get('/aiops/knowledge-environments/catalog/')
export const createAIOpsKnowledgeEnvironment = (data) => request.post('/aiops/knowledge-environments/', data)
export const updateAIOpsKnowledgeEnvironment = (id, data) => request.patch(`/aiops/knowledge-environments/${id}/`, data)
export const deleteAIOpsKnowledgeEnvironment = (id) => request.delete(`/aiops/knowledge-environments/${id}/`)

export const getAIOpsSessions = (params) => request.get('/aiops/sessions/', { params })
export const createAIOpsSession = (data) => request.post('/aiops/sessions/', data)
export const deleteAIOpsSession = (id) => request.post(`/aiops/sessions/${id}/delete_session/`)
export const getAIOpsMessages = (id) => request.get(`/aiops/sessions/${id}/messages/`)
export const sendAIOpsMessage = (id, data) => request.post(`/aiops/sessions/${id}/send_message/`, data, { timeout: AIOPS_CHAT_TIMEOUT })
export const sendAIOpsMessageAsync = (id, data) => request.post(`/aiops/sessions/${id}/send_message_async/`, data, { timeout: 20000 })

export const confirmAIOpsAction = (id) => request.post(`/aiops/actions/${id}/confirm/`)
export const cancelAIOpsAction = (id) => request.post(`/aiops/actions/${id}/cancel/`)

export const getAIOpsConfig = () => request.get('/aiops/admin/config/')
export const updateAIOpsConfig = (data) => request.put('/aiops/admin/config/', data)
export const getAIOpsActions = () => request.get('/aiops/admin/actions/')
export const getAIOpsAuditOverview = () => request.get('/aiops/admin/audit/overview/')
export const getAIOpsAuditSessions = (params) => request.get('/aiops/admin/audit/sessions/', { params })
export const deleteAIOpsAuditSession = (id) => request.delete(`/aiops/admin/audit/sessions/${id}/`)
export const bulkDeleteAIOpsAuditSessions = (session_ids) => request.post('/aiops/admin/audit/sessions/bulk-delete/', { session_ids })
export const getAIOpsAuditToolInvocations = (params) => request.get('/aiops/admin/audit/tool-invocations/', { params })
export const deleteAIOpsAuditToolInvocation = (id) => request.delete(`/aiops/admin/audit/tool-invocations/${id}/`)
export const bulkDeleteAIOpsAuditToolInvocations = (invocation_ids) => request.post('/aiops/admin/audit/tool-invocations/bulk-delete/', { invocation_ids })
export const getAIOpsAuditActions = (params) => request.get('/aiops/admin/audit/actions/', { params })
export const deleteAIOpsAuditAction = (id) => request.delete(`/aiops/admin/audit/actions/${id}/`)
export const bulkDeleteAIOpsAuditActions = (action_ids) => request.post('/aiops/admin/audit/actions/bulk-delete/', { action_ids })

export const getAIOpsProviders = () => request.get('/aiops/admin/providers/')
export const getAIOpsProviderPresets = () => request.get('/aiops/admin/providers/presets/')
export const createAIOpsProvider = (data) => request.post('/aiops/admin/providers/', data)
export const updateAIOpsProvider = (id, data) => request.patch(`/aiops/admin/providers/${id}/`, data)
export const deleteAIOpsProvider = (id) => request.delete(`/aiops/admin/providers/${id}/`)
export const testAIOpsProvider = (id) => request.post(`/aiops/admin/providers/${id}/test_connection/`, null, { timeout: AIOPS_MODEL_TEST_TIMEOUT })
export const listAIOpsProviderModels = (id, params) => request.get(`/aiops/admin/providers/${id}/models/`, { params, timeout: AIOPS_MODEL_TEST_TIMEOUT })

export const getAIOpsMcpServers = () => request.get('/aiops/admin/mcp-servers/')
export const createAIOpsMcpServer = (data) => request.post('/aiops/admin/mcp-servers/', data)
export const updateAIOpsMcpServer = (id, data) => request.patch(`/aiops/admin/mcp-servers/${id}/`, data)
export const deleteAIOpsMcpServer = (id) => request.delete(`/aiops/admin/mcp-servers/${id}/`)
export const testAIOpsMcpServer = (id) => request.post(`/aiops/admin/mcp-servers/${id}/test_connection/`)
export const listAIOpsMcpTools = (id) => request.get(`/aiops/admin/mcp-servers/${id}/list_tools/`)

export const getAIOpsSkills = () => request.get('/aiops/admin/skills/')
export const createAIOpsSkill = (data) => request.post('/aiops/admin/skills/', data)
export const updateAIOpsSkill = (id, data) => request.patch(`/aiops/admin/skills/${id}/`, data)
export const deleteAIOpsSkill = (id) => request.delete(`/aiops/admin/skills/${id}/`)
