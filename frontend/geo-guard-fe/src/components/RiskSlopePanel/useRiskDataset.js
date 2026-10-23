import { computed, onScopeDispose, reactive, shallowRef, ref, watch, provide } from 'vue'
import dayjs from 'dayjs'
import { debounce } from 'lodash-es'
import { getRiskAssessmentList, resolveRiskAssessmentPage } from '@/api/riskEvaluation.js'
import { getP6Units } from '@/api/p6Dynamic.js'
import {
  formatRiskSlope,
  getDynamicRiskLevelLabel,
  getRiskSlopeSelectionKey,
  getSusceptibilityLevelLabel,
  normalizeRiskLevel,
} from '@/utils/riskEvaluation.js'
import { SLOPE_UNIT_KEY } from '@/utils/enum.js'

// Symbol.for 在 Vite 热更新后仍保持同一标识，避免兄弟面板取不到共享数据。
export const RISK_DATASET_KEY = Symbol.for('geo-guard:risk-dataset')

// 行政级别直接映射参数名，不根据显示名称推测级别。
export const riskRegionParams = (selected) => {
  const key = SLOPE_UNIT_KEY[selected?.level]
  if (!key || !selected?.name) return {}
  return { [key]: selected.name }
}

export const useRiskDataset = ({ autoLoad = true, p6Static = false } = {}) => {
  const filters = reactive({
    slopeUnitId: '',
    riskMode: 'dynamic',
    dynamicRiskLevels: [5, 4],
    staticRiskLevels: [5, 4, 3, 2, 1],
    assessmentDate: dayjs().format('YYYY-MM-DD'),
  })
  const activeRiskLevels = computed({
    get: () => filters.riskMode === 'static' ? filters.staticRiskLevels : filters.dynamicRiskLevels,
    set: (levels) => {
      if (filters.riskMode === 'static') filters.staticRiskLevels = levels
      else filters.dynamicRiskLevels = levels
    },
  })
  const region = shallowRef({ city: '宜昌市' })
  const rows = shallowRef([])
  const initialLoading = ref(false)
  const loadError = ref('')
  const activeSlopeUnitId = ref('')
  const activeSlopeKey = ref('')
  let version = 0
  let controller
  const formattedRows = computed(() => rows.value.map((row) => {
    const levelValue = normalizeRiskLevel(filters.riskMode === 'static'
      ? row?.susceptibilityLevel ?? row?.s_grade ?? row?.S?.grade ?? row?.slopeUnit?.susceptibilityLevel
      : row?.dynamicRiskLevel ?? row?.r_grade ?? row?.R?.grade)
    const level = filters.riskMode === 'static'
      ? getSusceptibilityLevelLabel(levelValue)
      : getDynamicRiskLevelLabel(levelValue)
    return {
      ...formatRiskSlope(row),
      riskMode: filters.riskMode,
      level,
      levelValue,
      virtualId: String(row.id ?? row.slopeUnitId ?? row.slope_unit_id ?? ''),
    }
  }))
  const slopeItems = computed(() => {
    if (!activeRiskLevels.value.length) return []

    return formattedRows.value.filter(
      (item) =>
        activeRiskLevels.value.includes(item.levelValue) &&
        (!filters.slopeUnitId || String(item.slopeUnitId).includes(filters.slopeUnitId.trim())),
    )
  })
  const search = async () => {
    const requestVersion = ++version
    controller?.abort()
    controller = new AbortController()
    const signal = controller.signal
    initialLoading.value = true
    loadError.value = ''
    rows.value = []
    if (activeRiskLevels.value.length === 0) {
      initialLoading.value = false
      return
    }
    try {
      if (p6Static && filters.riskMode === 'static') {
        const pageSize = 250
        const firstPage = await getP6Units({
          county: region.value.county,
          limit: pageSize,
          offset: 0,
          signal,
        })
        const offsets = Array.from(
          { length: Math.ceil(Math.max(0, Number(firstPage.total || 0) - pageSize) / pageSize) },
          (_, index) => (index + 1) * pageSize,
        )
        const pages = await Promise.all(offsets.map((offset) => getP6Units({
          county: region.value.county,
          limit: pageSize,
          offset,
          signal,
        })))
        if (signal.aborted || requestVersion !== version) return
        rows.value = [firstPage, ...pages].flatMap((page) => page.items || [])
        return
      }
      const baseParams = {
        ...region.value,
        assessmentDate: filters.assessmentDate,
        withSlopeUnit: true,
      }
      let allRows
      if (filters.riskMode === 'static') {
        // 静态风险按正式接口字段 susceptibilityLevel 查询斜坡单元。
        const responses = await Promise.all(activeRiskLevels.value.map((level) =>
          getRiskAssessmentList({ ...baseParams, susceptibilityLevel: level }, { signal }),
        ))
        if (signal.aborted || requestVersion !== version) return
        allRows = responses.flatMap((response) => (
          Array.isArray(response) ? response : resolveRiskAssessmentPage(response).rows
        ))
      } else {
        // 不传分页参数返回全量评价记录；pageSize=10000 会让服务端超时。
        const response = await getRiskAssessmentList({
          ...baseParams,
          dynamicRiskLevels: [...activeRiskLevels.value],
        }, { signal })
        if (signal.aborted || requestVersion !== version) return
        allRows = Array.isArray(response) ? response : resolveRiskAssessmentPage(response).rows
      }
      if (requestVersion === version) rows.value = allRows
    } catch (error) {
      if (requestVersion === version && !signal.aborted) {
        loadError.value = '风险数据加载失败，请点击查询重试'
        console.error('风险图层获取失败', error)
      }
    } finally {
      if (requestVersion === version) initialLoading.value = false
    }
  }
  const setRegion = (selected) => {
    const next = riskRegionParams(selected)
    if (JSON.stringify(next) !== JSON.stringify(region.value)) region.value = next
  }
  const reset = () => {
    filters.slopeUnitId = ''
    filters.dynamicRiskLevels = [5, 4]
    filters.staticRiskLevels = [5, 4, 3, 2, 1]
    filters.assessmentDate = dayjs().format('YYYY-MM-DD')
  }
  if (autoLoad) watch([region, () => filters.assessmentDate], search, { immediate: true })
  // 连续勾选风险等级时合并请求，避免每次选择都重新加载全量数据。
  const debouncedRiskSearch = debounce(search, 1500)
  if (autoLoad) {
    watch([
      () => filters.riskMode,
      () => [...activeRiskLevels.value].sort((a, b) => a - b).join(','),
    ], debouncedRiskSearch)
  }
  onScopeDispose(() => {
    debouncedRiskSearch.cancel()
    version += 1
    controller?.abort()
  })
  const dataset = {
    filters,
    activeRiskLevels,
    region,
    rows,
    slopeItems,
    initialLoading,
    loadError,
    activeSlopeUnitId,
    activeSlopeKey,
    search,
    reset,
    setRegion,
    setActiveSlope: (slope) => {
      activeSlopeUnitId.value = slope?.slopeUnitId ?? ''
      activeSlopeKey.value = getRiskSlopeSelectionKey(slope)
    },
    handleScroll: () => {},
    listStatus: computed(() => (slopeItems.value.length ? `共 ${slopeItems.value.length} 个斜坡单元` : '')),
  }
  provide(RISK_DATASET_KEY, dataset)
  return dataset
}
