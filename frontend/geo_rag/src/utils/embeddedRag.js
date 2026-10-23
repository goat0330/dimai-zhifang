const RAG_API_PREFIXES = [
  '/api/knowledge',
  '/api/evaluation',
  '/api/workspace/knowledge',
  '/api/system/ocr',
  '/api/system/config'
]
const RAG_WORKSPACE_PATHS = ['/api/workspace/tree', '/api/workspace/directory']
const EMBEDDED_RAG_READ_ONLY_PATHS = ['/api/system/model-providers/models/v2']
const MODEL_PROVIDER_API_ROOT = '/api/system/model-providers'

export const EMBEDDED_RAG_ROUTE = '/extensions?tab=knowledge'

export function isEmbeddedRagMode() {
  if (typeof window === 'undefined') return false
  if (new URLSearchParams(window.location?.search || '').get('embed') === 'rag') return true
  if (window.parent === window) return false

  const [path, query = ''] = (window.location?.hash || '').replace(/^#/, '').split('?')
  return (
    /^\/extensions\/knowledgebase(?:\/|$)/.test(path) ||
    (path === '/extensions' && new URLSearchParams(query).get('tab') === 'knowledge')
  )
}

export function isEmbeddedRagRoute(path) {
  return path === '/extensions' || /^\/extensions\/knowledgebase(?:\/|$)/.test(path)
}

export function isEmbeddedRagApiPath(url, origin = 'http://localhost', method = 'GET') {
  let target
  let pathname
  try {
    target = new URL(url, origin)
    if (target.origin !== new URL(origin).origin) return false
    pathname = target.pathname
  } catch {
    return false
  }

  const readOnlyModelList =
    method.toUpperCase() === 'GET' &&
    EMBEDDED_RAG_READ_ONLY_PATHS.includes(pathname) &&
    ['chat', 'embedding', 'rerank'].includes(target.searchParams.get('model_type'))

  const requestMethod = method.toUpperCase()
  const providerIdPath = new RegExp(`^${MODEL_PROVIDER_API_ROOT}/[a-zA-Z0-9_-]+$`).test(pathname)
  const remoteModelsPath = new RegExp(`^${MODEL_PROVIDER_API_ROOT}/[a-zA-Z0-9_-]+/remote-models$`).test(pathname)
  const providerManagement =
    (pathname === MODEL_PROVIDER_API_ROOT && ['GET', 'POST'].includes(requestMethod)) ||
    (providerIdPath && ['GET', 'PUT', 'DELETE'].includes(requestMethod)) ||
    (remoteModelsPath && requestMethod === 'GET') ||
    (pathname === `${MODEL_PROVIDER_API_ROOT}/models/status` && requestMethod === 'GET') ||
    (pathname === `${MODEL_PROVIDER_API_ROOT}/models/cache/refresh` && requestMethod === 'POST')

  return readOnlyModelList || providerManagement ||
    RAG_WORKSPACE_PATHS.includes(pathname) ||
    RAG_API_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

export function isEmbeddedRagApi(url, method = 'GET') {
  return isEmbeddedRagMode() && isEmbeddedRagApiPath(url, window.location.origin, method)
}

export function getEmbeddedRagAuthHeaders(storage, clientId = 'geo-local', tokenKey = 'bwy-token') {
  const token = storage.getItem(tokenKey)
  return token ? { [tokenKey]: token, clientid: clientId } : { clientid: clientId }
}
