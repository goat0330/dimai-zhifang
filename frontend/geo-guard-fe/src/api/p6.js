async function request(path) {
  const response = await fetch(`/p6${path}`)
  const result = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(result.detail || result.message || `宜昌风险数据请求失败（HTTP ${response.status}）`)
  }
  return result
}

export const getStaticCounties = () => request('/api/v1/counties')
export const getDatasetInfo = () => request('/api/v1/info')
export const getDynamicStatus = () => request('/api/v1/dynamic/status')
export const getDynamicLatest = (scenario = 'dynamic') => request(`/api/v1/dynamic/latest?scenario=${scenario}`)
export const getDynamicCounties = (scenario = 'dynamic') => request(`/api/v1/dynamic/counties?scenario=${scenario}`)
