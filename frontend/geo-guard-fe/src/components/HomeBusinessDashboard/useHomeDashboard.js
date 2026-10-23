import { onMounted, ref } from 'vue'
import { getP6DynamicCounties, getP6DynamicLatest } from '@/api/p6Dynamic.js'
import { DASHBOARD_SNAPSHOT } from './dashboardSnapshot.js'

/**
 * 灾害类型英文枚举到中文标签的统一映射表
 */
export const HAZARD_TYPE_LABEL_MAP = {
  LANDSLIDE: '滑坡',
  COLLAPSE: '崩塌',
  UNSTABLE_SLOPE: '不稳定斜坡',
  SUBSIDENCE: '地面塌陷',
  DEBRIS_FLOW: '泥石流',
}

/**
 * 将后端返回的灾害类型英文枚举格式化为展示中文
 * @param {string} val 原始类型标识
 * @returns {string} 中文标签
 */
export const formatHazardType = (val) => {
  if (!val) return ''
  return HAZARD_TYPE_LABEL_MAP[val] || val
}

/**
 * 安全解析数值：若为 null/undefined/无法解析为有效数字，返回 null
 * @param {*} val 待解析值
 * @returns {number|null}
 */
export const toFiniteNumber = (val) => {
  if (val === null || val === undefined || val === '') return null
  const num = Number(val)
  return Number.isFinite(num) ? num : null
}

/**
 * 首页聚合业务看板 Composable
 */
export const useHomeDashboard = () => {
  const loading = ref(false)
  const cumulative = ref(DASHBOARD_SNAPSHOT.homepage.cumulative)
  const today = ref(DASHBOARD_SNAPSHOT.homepage.today)
  const riskTrend = ref(DASHBOARD_SNAPSHOT.homepage.riskTrend)

  const createRiskTrend = () => ({
    dates: [...DASHBOARD_SNAPSHOT.homepage.riskTrend.dates],
    counts: Object.fromEntries(
      Object.entries(DASHBOARD_SNAPSHOT.homepage.riskTrend.counts)
        .map(([level, values]) => [level, [...values]]),
    ),
  })

  const fetchDashboard = async () => {
    loading.value = true
    try {
      cumulative.value = DASHBOARD_SNAPSHOT.homepage.cumulative
      today.value = DASHBOARD_SNAPSHOT.homepage.today
      riskTrend.value = createRiskTrend()
      const latest = await getP6DynamicLatest('dynamic')
      const counties = await getP6DynamicCounties({
        scenario: 'dynamic',
        snapshotId: latest?.snapshot?.snapshot_id,
      })
      const counts = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }
      counties.items?.forEach((county) => {
        for (let level = 1; level <= 5; level += 1) {
          counts[level] += Number(county[`r${level}`] || 0)
        }
      })
      today.value = {
        ...today.value,
        keyRiskTotal: counts[5] + counts[4],
        veryHighRiskCount: counts[5],
        highRiskCount: counts[4],
      }
      const trend = createRiskTrend()
      riskTrend.value = {
        ...trend,
        counts: Object.fromEntries(
          Object.entries(trend.counts).map(([level, values]) => [
            level,
            [...values.slice(0, -1), counts[level]],
          ]),
        ),
      }
    } catch {
      today.value = DASHBOARD_SNAPSHOT.homepage.today
      riskTrend.value = createRiskTrend()
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    fetchDashboard()
  })

  return {
    cumulative,
    fetchDashboard,
    loading,
    riskTrend,
    today,
  }
}
