import { getCenter } from '@/utils/index.js'

export const RISK_GRADE_NAMES = {
  1: '低',
  2: '较低',
  3: '中',
  4: '较高',
  5: '高',
}

export const RISK_GRADE_COLORS = {
  1: '#3561FA',
  2: '#8FB6F6',
  3: '#F9C568',
  4: '#FF7C3A',
  5: '#E23030',
}

/** 支持接口整数等级以及 S1–S5、H1–H5、E1–E5、R1–R5 字段值；0 和空值表示未评价。 */
export const normalizeRiskLevel = (level) => {
  if (level === null || level === undefined || level === '') return null
  const match = String(level).trim().match(/^[SHER]?([1-5])$/i)
  return match ? Number(match[1]) : null
}

export const DYNAMIC_RISK_LEVEL_OPTIONS = [
  { label: '高风险', value: 5 },
  { label: '较高风险', value: 4 },
  { label: '中风险', value: 3 },
  { label: '较低风险', value: 2 },
  { label: '低风险', value: 1 },
]

/** 地图默认展示较高及高风险斜坡单元。 */
export const DEFAULT_DYNAMIC_RISK_LEVELS = [5, 4]

export const getRiskLevelName = (level) => RISK_GRADE_NAMES[normalizeRiskLevel(level)] ?? ''

/** 动态风险等级 -> 文案，未匹配返回空串 */
export const getDynamicRiskLevelLabel = (level) => {
  const name = getRiskLevelName(level)
  return name ? `${name}风险` : ''
}

/** 静态易发性等级 -> 文案 */
export const getSusceptibilityLevelLabel = (level) => {
  const name = getRiskLevelName(level)
  return name ? `${name}易发` : ''
}

/** 风险等级 -> 主题色 */
export const getDynamicRiskLevelColor = (level) => {
  return RISK_GRADE_COLORS[normalizeRiskLevel(level)] ?? '#878898'
}

/** 评价记录优先使用记录 ID，缺失时退回斜坡单元 ID。 */
export const getRiskSlopeSelectionKey = (slope) => {
  const recordId = String(slope?.id ?? '').trim()
  return recordId || String(slope?.slopeUnitId ?? '').trim()
}

const SQUARE_METERS_PER_KM2 = 1_000_000

/** 斜坡单元面积：库内单位为平方米，UI 展示 km² */
export const toKm2 = (area) => {
  const value = Number(area)
  if (!Number.isFinite(value)) return ''
  return Number((value / SQUARE_METERS_PER_KM2).toFixed(2))
}

/** 坐标字段容错：非法值返回 undefined，保证下游 Number.isFinite 判断生效 */
const toCoordinate = (value) => {
  const num = Number(value)
  return Number.isFinite(num) ? num : undefined
}

/**
 * 格式化斜坡单元名称：在编号/名称后追加“斜坡单元”，若已有则不重复追加
 * @param {string|number} name
 * @returns {string}
 */
export const formatSlopeName = (name) => {
  const raw = String(name ?? '').trim()
  if (!raw) return ''
  if (raw.endsWith('斜坡单元') || raw.endsWith('斜坡')) return raw
  return `${raw}斜坡单元`
}

/**
 * 格式化斜坡单元地址：优先取 village-street，单字段存在时取该字段，无数据时返回 '--'
 * @param {object} slopeUnit
 * @returns {string}
 */
export const formatSlopeAddress = (slopeUnit) => {
  const village = slopeUnit?.village?.trim?.() || ''
  const street = slopeUnit?.street?.trim?.() || ''
  if (village && street) return `${village}-${street}`
  return village || street || '--'
}

/**
 * 风险评价列表行 -> 列表卡片 / 地图弹窗视图模型
 * 接口未返回的字段一律留空，不做数据伪造。
 * @param {object} row DzRiskAssessmentVo
 */
export const formatRiskSlope = (row) => {
  const slopeUnit = row?.slopeUnit ?? null
  const level = normalizeRiskLevel(
    row?.dynamicRiskLevel ?? row?.r_dynamic_grade ?? row?.r_grade ?? row?.R?.overall?.grade ?? row?.R?.grade,
  )
  const center = getCenter(slopeUnit?.center)
  const rawName =
    slopeUnit?.name ||
    row?.name ||
    slopeUnit?.slopeName ||
    row?.slopeName ||
    slopeUnit?.slopeUnitName ||
    row?.slopeUnitName ||
    row?.slope_unit_id ||
    ''
  const slopeUnitId = row?.slopeUnitId ?? row?.slope_unit_id ?? ''
  const rawCode = rawName || slopeUnitId

  return {
    // 评价记录ID，后续接入评价过程时作为入参
    id: row?.id ?? slopeUnitId,
    slopeUnitId,
    name: rawName || slopeUnitId,
    slopeUnitName: rawName || slopeUnitId,
    code: formatSlopeName(rawCode) || '未知斜坡单元',
    rawCode,
    level: getDynamicRiskLevelLabel(level),
    levelValue: level,
    street: slopeUnit?.street || '',
    village: slopeUnit?.village || '',
    address: formatSlopeAddress(slopeUnit) === '--' ? (row?.county || '--') : formatSlopeAddress(slopeUnit),
    county: row?.county || '',
    updateTime: row?.createDate || '',
    area: toKm2(slopeUnit?.area),
    // 若列表项带有人口底数与建筑数量则直接映射，其余由弹窗详情接口补充
    population: slopeUnit?.populationCount != null ? slopeUnit.populationCount : '',
    buildings: slopeUnit?.buildingCount != null ? slopeUnit.buildingCount : '',
    contact: '',
    rainfallTrend: [],
    lng: toCoordinate(center?.lng ?? row?.unit_lon ?? row?.longitude ?? row?.lng),
    lat: toCoordinate(center?.lat ?? row?.unit_lat ?? row?.latitude ?? row?.lat),
    alt: toCoordinate(center?.height ?? row?.unit_alt ?? row?.altitude ?? row?.alt) ?? 0,
    raw: row ?? {},
  }
}
