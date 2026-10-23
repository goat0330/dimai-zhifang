const P6_API = '/p6/api/v1'
const P6_DYNAMIC_API = `${P6_API}/dynamic`

const getP6Json = async (path, base = P6_DYNAMIC_API, signal) => {
  const response = await fetch(`${base}${path}`, { signal })
  if (!response.ok) {
    throw new Error(`宜昌动态风险数据读取失败（${response.status}）`)
  }
  return response.json()
}

export const getP6StaticUnit = ({ slopeUnitId } = {}) => (
  getP6Json(`/units/${encodeURIComponent(slopeUnitId)}`, P6_API)
)

export const getP6DynamicLatest = (scenario = 'dynamic') => (
  getP6Json(`/latest?scenario=${encodeURIComponent(scenario)}`)
)

export const getP6DynamicCounties = ({ scenario = 'dynamic', snapshotId } = {}) => {
  const params = new URLSearchParams({ scenario })
  if (snapshotId) params.set('snapshot_id', snapshotId)
  return getP6Json(`/counties?${params}`)
}

export const getP6DynamicUnit = ({ slopeUnitId, scenario = 'dynamic', snapshotId } = {}) => {
  const params = new URLSearchParams({ scenario })
  if (snapshotId) params.set('snapshot_id', snapshotId)
  return getP6Json(`/units/${encodeURIComponent(slopeUnitId)}?${params}`)
}

export const getP6Units = ({ county, limit = 250, offset = 0, signal } = {}) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (county) params.set('county', county)
  return getP6Json(`/units?${params}`, P6_API, signal)
}

export const getP6DynamicUnits = ({ county, r_grade, limit = 1000, offset = 0, scenario = 'dynamic', snapshotId, signal } = {}) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), scenario })
  if (county) params.set('county', county)
  if (r_grade) params.set('r_grade', r_grade)
  if (snapshotId) params.set('snapshot_id', snapshotId)
  return getP6Json(`/units?${params}`, P6_DYNAMIC_API, signal)
}
export const getP6DynamicTileUrl = ({ scenario = 'dynamic', snapshotId } = {}) => {
  const params = new URLSearchParams({ scenario })
  if (snapshotId) params.set('snapshot_id', snapshotId)
  params.set('tile_revision', '4')
  return `${window.location.origin}${P6_DYNAMIC_API}/tiles/{z}/{x}/{y}.pbf?${params}`
}

