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
export function toggleDomainSSL(id, enable) {
  return request({ url: `/nginx/domains/${id}/toggle_ssl/`, method: 'post', data: { enable } })
}
export function deployCert(id, data) {
  return request({ url: `/nginx/domains/${id}/deploy_cert/`, method: 'post', data })
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
