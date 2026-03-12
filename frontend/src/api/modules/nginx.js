import request from '@/api/request'

// ========== Nginx 环境 ==========
export function getNginxEnvironments() {
  return request({ url: '/nginx/envs/', method: 'get' })
}
export function createNginxEnvironment(data) {
  return request({ url: '/nginx/envs/', method: 'post', data })
}
export function updateNginxEnvironment(id, data) {
  return request({ url: `/nginx/envs/${id}/`, method: 'put', data })
}
export function deleteNginxEnvironment(id) {
  return request({ url: `/nginx/envs/${id}/`, method: 'delete' })
}
export function testNginxConnection(id) {
  return request({ url: `/nginx/envs/${id}/test_connection/`, method: 'post' })
}

// ========== Nginx 证书 ==========
export function getNginxCerts() {
  return request({ url: '/nginx/certs/', method: 'get' })
}
export function createNginxCert(data) {
  return request({ url: '/nginx/certs/', method: 'post', data })
}
export function updateNginxCert(id, data) {
  return request({ url: `/nginx/certs/${id}/`, method: 'put', data })
}
export function deleteNginxCert(id) {
  return request({ url: `/nginx/certs/${id}/`, method: 'delete' })
}
export function linkCertEnv(id, environmentId) {
  return request({ url: `/nginx/certs/${id}/link_env/`, method: 'post', data: { environment_id: environmentId } })
}
export function unlinkCertEnv(id, environmentId) {
  return request({ url: `/nginx/certs/${id}/unlink_env/`, method: 'post', data: { environment_id: environmentId } })
}
export function pushCertAll(id) {
  return request({ url: `/nginx/certs/${id}/push_all/`, method: 'post' })
}

// ========== Nginx 域名 ==========
export function getNginxDomains(params) {
  return request({ url: '/nginx/domains/', method: 'get', params })
}
export function createNginxDomain(data) {
  return request({ url: '/nginx/domains/', method: 'post', data })
}
export function updateNginxDomain(id, data) {
  return request({ url: `/nginx/domains/${id}/`, method: 'put', data })
}
export function deleteNginxDomain(id) {
  return request({ url: `/nginx/domains/${id}/`, method: 'delete' })
}
export function deployDomainConf(id) {
  return request({ url: `/nginx/domains/${id}/deploy_conf/`, method: 'post' })
}
export function previewDomainConf(id) {
  return request({ url: `/nginx/domains/${id}/preview_conf/`, method: 'get' })
}

// ========== Nginx 路由 ==========
export function getNginxRoutes(params) {
  return request({ url: '/nginx/routes/', method: 'get', params })
}
export function createNginxRoute(data) {
  return request({ url: '/nginx/routes/', method: 'post', data })
}
export function updateNginxRoute(id, data) {
  return request({ url: `/nginx/routes/${id}/`, method: 'put', data })
}
export function deleteNginxRoute(id) {
  return request({ url: `/nginx/routes/${id}/`, method: 'delete' })
}
