<template>
  <div class="risk-evaluation-page">
    <!-- 风险概览与地图并排展示，左侧面板收起后地图自动扩展。 -->
    <section
      class="map-area"
      :class="{
        'is-left-collapsed': leftCollapsed,
        'is-right-panel-open': rightPanelExpanded,
      }"
      aria-label="地图区域"
    >
      <MarsMap
        ref="marsMapRef"
        :enable-risk-evaluation-point-layers="true"
        :default-show-area-boundary="false"
        @onload="handleMapLoaded"
        @risk-point-position="handleRiskPointPosition"
        @select-area="handleMapAreaSelect"
        @select-map-point="handleMapPointSelect"
      >
        <template #overlay>
          <Transition name="risk-layer-status">
            <div
              v-if="mapLoadingText"
              class="risk-layer-loading"
              role="status"
              aria-live="polite"
            >
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>{{ mapLoadingText }}</span>
            </div>
          </Transition>
          <RiskSlopeMapPopup
            :visible="Boolean(selectedSlope && riskPointPosition)"
            :slope="selectedSlope || {}"
            :position="riskPointPosition"
            @close="closeSlopePopup"
            @risk-analysis="openRiskAnalysis"
          />
          <MonitorPointPopup
            v-if="selectedMapPoint?.type === 'monitor' && riskPointPosition"
            class="risk-evaluation-entity-popup"
            :style="mapEntityPopupStyle"
            :detail="monitorPopupDetail"
            @close="closeMapPointPopup"
          />
          <HazardDetailPopup
            v-if="selectedMapPoint?.type === 'hazard' && riskPointPosition"
            class="risk-evaluation-entity-popup"
            :style="mapEntityPopupStyle"
            :data="hazardPopupData"
            variant="map"
            @close="closeMapPointPopup"
          />
          <GroupDefenseMapPopup
            v-if="selectedMapPoint?.type === 'report' && riskPointPosition"
            class="risk-evaluation-entity-popup report-entity-popup"
            :style="mapEntityPopupStyle"
            :report="reportPopupData"
            :photos="reportPopupPhotos"
            @close="closeMapPointPopup"
          />
          <MapOverlayControls
            ref="mapOverlayControlsRef"
            class="risk-map-controls"
            :class="{
              'is-detail-open': rightPanelExpanded,
            }"
            v-model:risk-levels="riskDataset.activeRiskLevels.value"
            v-model:risk-mode="riskDataset.filters.riskMode"
            :show-risk-mode="true"
            :default-visible-layers="['hazard_point', 'report_disaster']"
            :include-yichang-layers="true"
            :include-slope-unit-layer="true"
            :include-report-layer="true"
            @zoom-in="marsMapRef?.handleZoomIn()"
            @zoom-out="marsMapRef?.handleZoomOut()"
            @locate-home="marsMapRef?.flyToHome()"
            @change-base-map="marsMapRef?.changeBaseMap($event)"
            @toggle-imagery-label="marsMapRef?.toggleImageryLabel($event)"
            @change-layer="handleRiskEvaluationLayerChange"
          />
        </template>
      </MarsMap>

      <div class="left-panel-wrapper" :class="{ 'is-collapsed': leftCollapsed }">
        <div class="left-panel-stack" :class="{ 'is-collapsed': leftCollapsed }">
          <RiskOverviewPanel
            ref="riskOverviewPanelRef"
            class="stack-panel overview-panel-layer"
            :dataset="riskDataset"
            :p6-driven="true"
            :p6-risk-data="p6RiskData"
            :p6-exposure="p6Exposure"
            @show-detail="showSlopeList"
            @open-risk-report="openRiskReport"
            @select-area="handleOverviewAreaSelect"
            @date-change="handleOverviewDateChange"
          />
          <RiskSlopePanel
            class="stack-panel slope-panel-layer"
            :class="{ 'is-visible': panelMode === 'slope-list' }"
            :dataset="riskDataset"
            :p6-driven="true"
            :p6-snapshot-id="p6RiskData?.snapshot?.snapshot_id || ''"
            @back="showOverview"
            @locate="handleSlopeLocate"
            @risk-analysis="openRiskAnalysis"
          />
        </div>
      </div>

      <div
        class="right-panel-clip"
        :class="{ 'is-collapsed': rightPanelCollapsed }"
      >
        <RiskAnalysisAgent
          class="right-agent-panel"
          :class="{ 'is-collapsed': riskAnalysisCollapsed }"
          :visible="riskAnalysisVisible"
          :slope="selectedSlope || {}"
          @close="closeRiskAnalysis"
        />
        <RiskReportAgent
          class="right-agent-panel"
          :class="{ 'is-collapsed': riskReportCollapsed }"
          :visible="riskReportVisible"
          @close="closeRiskReport"
          @complete="openDynamicRiskReport"
        />
      </div>

    </section>

    <!-- 概览面板展开/收起按钮：置于 map-area 外层，避免被地图容器裁切，使按钮在收起时可居中跨越分界线 -->
    <button
      class="collapse-trigger left-trigger"
      :class="{ 'is-collapsed': leftCollapsed }"
      :title="leftCollapsed ? `展开${activePanelName}` : `收起${activePanelName}`"
      @click="toggleLeftCollapse"
    >
      <img :src="leftCollapsed ? rightArrow : leftArrow" alt="" />
    </button>

    <button
      v-if="rightPanelVisible"
      class="collapse-trigger right-trigger"
      :class="{ 'is-collapsed': rightPanelCollapsed }"
      type="button"
      :title="rightTriggerTitle"
      @click="toggleRightPanel"
    >
      <img :src="rightPanelCollapsed ? leftArrow : rightArrow" alt="" />
    </button>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import MarsMap from '@/components/MarsMap/index.vue'
import MapOverlayControls from '@/components/MapOverlayControls/index.vue'
import RiskOverviewPanel from '@/components/RiskOverviewPanel/index.vue'
import RiskSlopePanel from '@/components/RiskSlopePanel/index.vue'
import RiskSlopeMapPopup from '@/components/RiskSlopeMapPopup/index.vue'
import MonitorPointPopup from '@/views/monitor/components/MonitorPointPopup.vue'
import HazardDetailPopup from '@/views/hazardReview/components/HazardDetailPopup.vue'
import GroupDefenseMapPopup from '@/components/GroupDefenseMapPopup/index.vue'
import RiskAnalysisAgent from '@/components/RiskAnalysisAgent/index.vue'
import RiskReportAgent from '@/components/RiskReportAgent/index.vue'
import leftArrow from '@/assets/imgs/left-arr.png'
import rightArrow from '@/assets/imgs/right-arr.png'
import { useRiskDataset } from '@/components/RiskSlopePanel/useRiskDataset.js'
import { useP6SlopeUnitLayer } from '@/components/MarsMap/useP6SlopeUnitLayer.js'
import {
  getP6DynamicCounties,
  getP6DynamicLatest,
  getP6DynamicUnit,
  getP6StaticUnit,
} from '@/api/p6Dynamic.js'
import { getMonitorDetailById } from '@/api/common.js'
import { getDeviceDataDetail } from '@/api/device.js'
import { getDisReportDetail } from '@/api/reportDisaster.js'
import { getPhotoUrls, getCenter } from '@/utils/index.js'
import {
  buildDeviceStatus,
  buildMonitorPointMetrics,
  monitorPointDetail,
} from '@/views/monitor/config.js'
import {
  formatRiskSlope,
  getDynamicRiskLevelLabel,
  getSusceptibilityLevelLabel,
  normalizeRiskLevel,
} from '@/utils/riskEvaluation.js'

defineOptions({ name: 'RiskEvaluation' })

const riskDataset = useRiskDataset({ autoLoad: false, p6Static: true })
const riskLayer = useP6SlopeUnitLayer((slope) => handleSlopeLocate(slope))
const p6RiskData = ref(null)
const p6Exposure = ref({})

const leftCollapsed = ref(false)
const panelMode = ref('overview')
const marsMapRef = ref(null)
const mapOverlayControlsRef = ref(null)
const riskOverviewPanelRef = ref(null)
const selectedSlope = ref(null)
const riskPointPosition = ref(null)
const selectedMapPoint = ref(null)
const hazardPopupData = ref({})
const monitorPopupDetail = ref({ ...monitorPointDetail })
const reportPopupData = ref(null)
const reportPopupPhotos = ref([])
const riskAnalysisVisible = ref(false)
const riskAnalysisCollapsed = ref(false)
const riskReportVisible = ref(false)
const riskReportCollapsed = ref(false)
const router = useRouter()

let isSyncingFromOverview = false

const handleOverviewAreaSelect = async (areaResult) => {
  const selected = areaResult?.selected
  if (!selected) return
  closeSlopePopup()
  closeRiskAnalysis()
  riskDataset.setRegion(selected)

  isSyncingFromOverview = true
  // 联动地图：通过 AreaSearch 飞行定位并重绘行政区划
  try {
    const areaSearch = marsMapRef.value?.getAreaSearch()
    if (areaSearch) {
      if (typeof areaSearch.handleSearchSelect === 'function') {
        await areaSearch.handleSearchSelect(selected.id || selected)
      } else if (typeof areaSearch.loadAndDrawBoundary === 'function') {
        await areaSearch.loadAndDrawBoundary(selected, true)
      }
      // 双重保障：确保平滑飞行定位立即响应
      if (typeof areaSearch.flyToRegionCenter === 'function') {
        areaSearch.flyToRegionCenter(selected)
      }
    }
  } catch (err) {
    console.warn('联动地图行政区划失败:', err)
  } finally {
    setTimeout(() => {
      isSyncingFromOverview = false
    }, 200)
  }
}

const handleMapAreaSelect = (data) => {
  if (data?.selected) {
    closeSlopePopup()
    closeRiskAnalysis()
    riskDataset.setRegion(data.selected)
  }
  if (isSyncingFromOverview) return
  // 图上选择了地区后，概览面板同步展示对应地区并重新调用接口获取数据
  if (data?.selected) {
    riskOverviewPanelRef.value?.selectArea(data)
  }
}

const handleOverviewDateChange = (date) => {
  if (date) {
    closeSlopePopup()
    closeRiskAnalysis()
    riskDataset.filters.assessmentDate = date
  }
}

const activePanelName = computed(() => panelMode.value === 'slope-list' ? '斜坡单元列表' : '风险概览')
const rightPanelVisible = computed(() => riskAnalysisVisible.value || riskReportVisible.value)
const rightPanelCollapsed = computed(() => (
  riskAnalysisVisible.value ? riskAnalysisCollapsed.value : riskReportCollapsed.value
))
const rightPanelExpanded = computed(() => rightPanelVisible.value && !rightPanelCollapsed.value)
const rightTriggerTitle = computed(() => {
  const panelName = riskAnalysisVisible.value ? '风险评价智能体' : '今日风险分析'
  return rightPanelCollapsed.value ? `展开${panelName}` : `收起${panelName}`
})
const mapLoadingText = computed(() => {
  const riskName = riskDataset.filters.riskMode === 'static' ? '静态风险' : '动态风险'
  if (riskDataset.initialLoading.value) return `正在获取${riskName}数据...`
  if (riskLayer.rendering.value) return `正在渲染${riskName}图层...`
  return ''
})

watch(() => riskDataset.filters.riskMode, () => {
  closeSlopePopup()
  closeRiskAnalysis()
})

watch([
  () => riskDataset.filters.riskMode,
  () => riskDataset.activeRiskLevels.value.join(','),
  () => p6RiskData.value?.snapshot?.snapshot_id,
], ([mode, , snapshotId]) => {
  riskLayer.setStyle({
    mode,
    levels: riskDataset.activeRiskLevels.value,
    nextSnapshotId: snapshotId,
  })
}, { immediate: true })

const loadP6Overview = async () => {
  try {
    const latest = await getP6DynamicLatest('dynamic')
    const snapshot = latest.snapshot
    const response = await getP6DynamicCounties({
      scenario: 'dynamic',
      snapshotId: snapshot.snapshot_id,
    })
    const counties = response.items || []
    const counts = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }
    counties.forEach((county) => {
      for (const level of [1, 2, 3, 4, 5]) {
        counts[level] += Number(county[`r${level}`] || 0)
      }
    })
    const unitCount = Number(snapshot.unit_count || counties.reduce(
      (sum, county) => sum + Number(county.total_units || 0),
      0,
    ))
    p6RiskData.value = { snapshot, unitCount, counts, counties }
    p6Exposure.value = { slopeUnitCount: unitCount }
  } catch (error) {
    console.error('读取宜昌风险数据失败', error)
    ElMessage.error('宜昌风险数据暂时无法读取')
  }
}

onMounted(() => {
  void loadP6Overview()
})

const mapEntityPopupStyle = computed(() => {
  const position = riskPointPosition.value
  return position
    ? { left: `${position.x}px`, top: `${position.y - 10}px` }
    : {}
})

let mapPointRequestId = 0

const handleMapPointSelect = async ({ type, item } = {}) => {
  if (!item || !['hazard', 'monitor', 'report'].includes(type)) return
  const point = type === 'report'
    ? getCenter(item.checkCenter)
    : {
        lng: Number(item.longitude ?? item.lon ?? item.lng),
        lat: Number(item.latitude ?? item.lat),
        alt: Number(item.altitude ?? item.height),
      }
  const lng = Number(point?.lng)
  const lat = Number(point?.lat)
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return

  const requestId = ++mapPointRequestId
  closeSlopePopup()
  closeRiskAnalysis()
  closeRiskReport()
  selectedMapPoint.value = { type, item }
  riskPointPosition.value = null
  reportPopupPhotos.value = []
  if (type === 'monitor') {
    monitorPopupDetail.value = {
      ...monitorPointDetail,
      name: item.monitorPointName || item.name || '--',
      code: item.monitorPointNum || item.code || '',
      info: [
        { label: '地理位置：', value: item.address || item.location || '', span: 2 },
        { label: '预警等级：', value: item.warningLevelName || item.warningLevel || '' },
        { label: '预警时间：', value: item.warningTime || '', span: 2 },
      ].filter((row) => row.value),
    }
  } else if (type === 'report') {
    reportPopupData.value = item
  }
  if (type === 'hazard') {
    const data = { ...item, ...(item.detail || {}) }
    hazardPopupData.value = {
      ...data,
      name: data.name || data.hazardPointName || data.pointName || '--',
      level: data.level || data.riskLevelName || data.riskLevel || '',
      address: data.address || data.location || data.checkCenterLocation || '',
      threatObject: data.threatObject || data.mainThreatObject || '',
      threatenedHouseholds: data.threatenedHouseholds ?? data.threatHouseholds,
      threatenedPeople: data.threatenedPeople ?? data.threatPeople ?? data.threatenedPopulation,
      potentialEconomicLoss: data.potentialEconomicLoss ?? data.economicLoss ?? data.threatenedPropertyValue,
      emergencyContact: data.emergencyContact || data.contactName || '',
      emergencyPhone: data.emergencyPhone || data.contactPhone || '',
      reportDate: data.reportDate || data.createDate || data.createdTime || '',
      confirmTime: data.confirmTime || data.checkTime || '',
      supplementDescription: data.supplementDescription || data.description || '',
      threatPeople: data.threatPeople ?? data.threatenedPopulation ?? '--',
      threatProperty: data.threatProperty ?? data.threatenedPropertyValue ?? '--',
      stabilityNow: data.stabilityNow ?? '--',
      stabilityForecast: data.stabilityForecast ?? '--',
      code: data.code || data.hazardPointCode || '--',
      disasterTime: data.disasterTime || '--',
    }
  }

  await marsMapRef.value?.showRiskPoint({ lng, lat, alt: Number(point?.alt) || 0 }, {
    flyTo: false,
    alwaysVisible: true,
  })
  if (requestId !== mapPointRequestId) return

  if (type === 'monitor') {
    const monitorId = item.monitorPointId || item.id
    const detail = monitorId ? await getMonitorDetailById(monitorId).catch(() => null) : null
    if (requestId !== mapPointRequestId) return
    const monitor = { ...item, ...(detail || {}) }
    const deviceId = monitor.sensorId || monitor.deviceId
    monitorPopupDetail.value = {
      ...monitorPointDetail,
      name: monitor.monitorPointName || monitor.name || '--',
      code: monitor.monitorPointNum || monitor.code || '',
      info: [
        { label: '地理位置：', value: monitor.address || monitor.location || '', span: 2 },
        { label: '预警等级：', value: monitor.warningLevelName || monitor.warningLevel || '' },
        { label: '预警时间：', value: monitor.warningTime || '', span: 2 },
      ].filter((row) => row.value),
      deviceStatus: buildDeviceStatus(monitor.deviceStatus),
    }
    if (deviceId) {
      const deviceData = await getDeviceDataDetail(deviceId).catch(() => null)
      if (requestId !== mapPointRequestId || !deviceData) return
      monitorPopupDetail.value = {
        ...monitorPopupDetail.value,
        ...buildMonitorPointMetrics(deviceData),
        deviceStatus: buildDeviceStatus(deviceData.deviceStatus ?? monitor.deviceStatus),
      }
    }
  } else if (type === 'report') {
    let report = item
    const reportId = item.id || item.reportId
    if (reportId) {
      report = { ...item, ...(await getDisReportDetail(reportId).catch(() => null) || {}) }
    }
    if (requestId !== mapPointRequestId) return
    reportPopupData.value = report
    const photoIds = report.photos || report.photoIds || report.scenePhotos
    if (photoIds) {
      reportPopupPhotos.value = await getPhotoUrls(photoIds).catch(() => []) || []
    }
  }
}

const closeMapPointPopup = () => {
  mapPointRequestId += 1
  selectedMapPoint.value = null
  reportPopupData.value = null
  reportPopupPhotos.value = []
  riskPointPosition.value = null
  marsMapRef.value?.clearRiskPoint()
}


const toggleLeftCollapse = () => {
  leftCollapsed.value = !leftCollapsed.value
}

const showSlopeList = () => {
  leftCollapsed.value = false
  panelMode.value = 'slope-list'
  // 进入斜坡单元列表时显示当前风险类型的全部等级。
  riskDataset.activeRiskLevels.value = [5, 4, 3, 2, 1]
}

const showOverview = () => {
  panelMode.value = 'overview'
  // 返回概览时恢复动态风险默认等级，静态易发性保留全部等级。
  riskDataset.activeRiskLevels.value = riskDataset.filters.riskMode === 'static'
    ? [5, 4, 3, 2, 1]
    : [5, 4]
  closeSlopePopup()
  closeRiskAnalysis()
  selectedSlope.value = null
  riskDataset.setActiveSlope(null)
}

let slopeLocateRequestId = 0

const handleSlopeLocate = async (slope) => {
  const slopeUnitId = String(slope?.slopeUnitId || slope?.slope_unit_id || slope?.id || '').trim()
  if (!slopeUnitId) {
    closeSlopePopup()
    ElMessage.warning('斜坡单元编号缺失')
    return
  }

  const requestId = ++slopeLocateRequestId
  let formatted
  try {
    const [staticUnit, dynamicResponse] = await Promise.all([
      getP6StaticUnit({ slopeUnitId }),
      getP6DynamicUnit({
        slopeUnitId,
        scenario: 'dynamic',
        snapshotId: p6RiskData.value?.snapshot?.snapshot_id,
      }),
    ])
    if (requestId !== slopeLocateRequestId) return
    const dynamicUnit = dynamicResponse?.item || dynamicResponse
    const raw = {
      ...staticUnit,
      ...(slope?.raw || {}),
      ...(slope || {}),
      ...(dynamicUnit || {}),
      slopeUnitId,
      slope_unit_id: slopeUnitId,
    }
    const levelValue = normalizeRiskLevel(riskDataset.filters.riskMode === 'static'
      ? raw.S?.grade ?? raw.s_grade
      : raw.r_dynamic_grade ?? raw.R?.overall?.grade)
    formatted = {
      ...formatRiskSlope({
        ...raw,
        dynamicRiskLevel: riskDataset.filters.riskMode === 'static'
          ? raw.S?.grade ?? raw.s_grade
          : raw.r_dynamic_grade ?? raw.R?.overall?.grade,
      }),
      level: riskDataset.filters.riskMode === 'static'
        ? getSusceptibilityLevelLabel(levelValue)
        : getDynamicRiskLevelLabel(levelValue),
      levelValue,
      riskMode: riskDataset.filters.riskMode,
      virtualId: slopeUnitId,
      raw,
    }
  } catch (error) {
    if (requestId === slopeLocateRequestId) {
      console.error('读取斜坡单元详情失败', error)
      ElMessage.warning('斜坡单元详情暂时无法读取')
    }
    return
  }

  const lng = Number(formatted.lng)
  const lat = Number(formatted.lat)
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    closeSlopePopup()
    ElMessage.warning('当前斜坡单元暂无点位坐标')
    return
  }

  // 坐标有效且能够展示业务弹窗时，才设置选中并高亮
  selectedSlope.value = formatted
  riskDataset.setActiveSlope(formatted)
  riskPointPosition.value = null
  marsMapRef.value?.showRiskPoint(
    { lng, lat, alt: Number(formatted.alt) || 0 },
    {
      flyTo: true,
      width: 30,
      height: 34,
      // 高亮面贴地绘制时关闭定位标记的深度检测，避免图标被覆盖。
      alwaysVisible: true,
    },
  )
}

const closeSlopePopup = () => {
  slopeLocateRequestId += 1
  riskPointPosition.value = null
  marsMapRef.value?.clearRiskPoint()
  // 若右侧风险分析智能体弹窗未展开，则取消斜坡单元高亮
  if (!riskAnalysisVisible.value) {
    selectedSlope.value = null
    riskDataset.setActiveSlope(null)
  }
}

const openRiskAnalysis = (slope) => {
  if (slope) {
    void handleSlopeLocate(slope)
  }
  closeRiskReport()
  riskAnalysisVisible.value = true
  riskAnalysisCollapsed.value = false
}

const closeRiskAnalysis = () => {
  riskAnalysisVisible.value = false
  riskAnalysisCollapsed.value = false
  // 若地图气泡弹窗也未显示，关闭智能体弹窗时同步取消高亮
  if (!riskPointPosition.value) {
    selectedSlope.value = null
    riskDataset.setActiveSlope(null)
  }
}

const openRiskReport = () => {
  closeRiskAnalysis()
  riskReportVisible.value = true
  riskReportCollapsed.value = false
}

const closeRiskReport = () => {
  riskReportVisible.value = false
  riskReportCollapsed.value = false
}

const toggleRightPanel = () => {
  if (riskAnalysisVisible.value) {
    riskAnalysisCollapsed.value = !riskAnalysisCollapsed.value
    return
  }
  riskReportCollapsed.value = !riskReportCollapsed.value
}

const openDynamicRiskReport = () => {
  router.push({
    name: 'DynamicRiskReport',
    query: { date: dayjs().format('YYYY-MM-DD') },
  })
}

const handleRiskPointPosition = (position) => {
  if (!position) {
    riskPointPosition.value = null
    return
  }
  riskPointPosition.value = position
}

const handleMapLoaded = () => {
  riskLayer.attach(marsMapRef.value?.getMap())
  const layers = mapOverlayControlsRef.value?.getData()?.layerOptions || []
  for (const layer of layers) {
    if (layer.checked) {
      handleRiskEvaluationLayerChange({ ...layer, layers })
    }
  }
}

const handleRiskEvaluationLayerChange = (layer) => {
  if (layer?.key === 'slope_unit') {
    riskLayer.setVisible(layer.checked)
    return
  }
  marsMapRef.value?.handleLayerChange(layer)
}
</script>

<style lang="less" scoped>
.risk-evaluation-page {
  position: relative;
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  max-height: 100%;
  min-height: 100%;
  display: flex;
  overflow: visible;
  box-sizing: border-box;
  padding: 0;
  background: transparent;
  font-family: inherit;
}

.risk-evaluation-entity-popup {
  position: absolute;
  z-index: 12;
  transform: translate(-50%, -100%);
}

.risk-evaluation-page :deep(input) {
  font-family: inherit;
}

/* 左侧面板与地图保留 12px 透明间距，露出底层背景图。 */
.map-area {
  position: relative;
  flex: 1 1 0;
  min-width: 0;
  height: 100%;
  min-height: 100%;
  padding-left: 472px;
  background: transparent;
  overflow: visible;
  box-sizing: border-box;
  transform: translateZ(0);
  isolation: isolate;
  transition: padding-left 0.28s cubic-bezier(0.4, 0, 0.2, 1),
              padding-right 0.28s cubic-bezier(0.4, 0, 0.2, 1);

  &.is-left-collapsed {
    padding-left: 0;
  }

  &.is-right-panel-open {
    padding-right: 0;

    :deep(.compass) {
      right: 487px;
    }
  }

  :deep(.compass) {
    transition: right 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  }
}

.risk-layer-loading {
  position: absolute;
  top: 20px;
  left: 50%;
  z-index: 24;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid #DCEDFF;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 4px 16px rgba(34, 37, 39, 0.12);
  color: #222527;
  font-size: 14px;
  line-height: 20px;
  pointer-events: none;
  transform: translateX(-50%);

  .el-icon {
    width: 18px;
    height: 18px;
    color: #007BFF;
    font-size: 18px;
  }
}

.risk-layer-status-enter-active,
.risk-layer-status-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.risk-layer-status-enter-from,
.risk-layer-status-leave-to {
  opacity: 0;
  transform: translate(-50%, -8px);
}

/* 左侧面板裁剪容器：严格约束在 x >= 0 范围，彻底防止向左滑动收起时溢出覆盖菜单栏 */
.left-panel-wrapper {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 480px;
  max-width: calc(100% - 32px);
  overflow: hidden;
  pointer-events: none;
  z-index: 10;
  visibility: visible;
  transition: visibility 0s linear 0s;

  &.is-collapsed {
    visibility: hidden;
    pointer-events: none;
    transition: visibility 0s linear 0.28s;
  }
}

/* 风险情况概览独立占据左侧，不再覆盖地图。 */
.left-panel-stack {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 10;
  width: 460px;
  max-width: 100%;
  background: #ffffff;
  border-radius: 16px;
  overflow: hidden;
  box-sizing: border-box;
  transform: translateX(0);
  opacity: 1;
  pointer-events: auto;
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
              opacity 0.28s cubic-bezier(0.4, 0, 0.2, 1);

  &.is-collapsed {
    transform: translateX(-100%);
    opacity: 0;
    pointer-events: none;
  }
}

.stack-panel {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background: #ffffff;
}

.overview-panel-layer {
  z-index: 1;
}

.slope-panel-layer {
  z-index: 2;
  opacity: 0;
  transform: translateX(-100%);
  pointer-events: none;
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;

  &.is-visible {
    opacity: 1;
    transform: translateX(0);
    pointer-events: auto;
  }
}

/* 收起/展开通用按钮 */
.collapse-trigger {
  position: absolute;
  top: 50%;
  width: 20px;
  height: 72px;
  padding: 0;
  box-sizing: border-box;
  border: 1px solid #cccccc66;
  border-radius: 17px;
  background: #ffffff;
  cursor: pointer;
  transform: translateY(-50%);
}

.collapse-trigger:hover {
  box-shadow: 0 2px 8px rgba(0, 123, 255, 0.16);
}

.collapse-trigger img {
  display: block;
  width: 14px;
  height: 14px;
  margin: 0 auto;
  object-fit: contain;
}

/* 左侧概览面板收起按钮：使用与面板完全一致的 GPU transform 贝塞尔曲线，杜绝延迟脱节 */
.left-trigger {
  left: 0;
  z-index: 100;
  transform: translateY(-50%) translateX(450px);
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.2s ease;
}

.left-trigger.is-collapsed {
  transform: translateY(-50%) translateX(-10px);
}

/* 右侧面板裁剪容器：盖在地图上，超出部分进行裁剪，防止页面产生横向滚动条 */
.right-panel-clip {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  width: 500px;
  z-index: 15;
  overflow: hidden;
  pointer-events: none;
  visibility: visible;
  transition: visibility 0s linear 0s;

  &.is-collapsed {
    visibility: hidden;
    transition: visibility 0s linear 0.28s;
  }
}

/* 右侧智能体面板盖在地图上，交互与复盘详情保持一致，左侧圆角与阴影独立浮层展示 */
.right-agent-panel {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  width: 480px;
  box-sizing: border-box;
  background: #ffffff;
  border-radius: 20px 0 0 20px !important;
  border: 1px solid #d5dbe0 !important;
  border-right: none !important;
  box-shadow: -4px 0 24px rgba(47, 95, 186, 0.12) !important;
  pointer-events: auto;
  opacity: 1;
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
              opacity 0.28s ease,
              visibility 0s linear 0s;

  :deep(.agent-header) {
    border-radius: 20px 0 0 0;
  }

  &.is-collapsed {
    visibility: hidden;
    opacity: 0;
    transform: translateX(100%);
    pointer-events: none;
    transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
                opacity 0.28s ease,
                visibility 0s linear 0.28s;
  }
}

.right-trigger {
  right: 0;
  z-index: 100;
  transform: translateY(-50%) translateX(-470px);
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.2s ease;
}

.right-trigger.is-collapsed {
  transform: translateY(-50%) translateX(10px);
}

/* 地图右侧组件避让：当右侧弹窗打开时向左自适应平移，避免被右侧弹窗盖住 */
:deep(.risk-map-controls) {
  .filter-groups,
  .map-tools {
    transition: right 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  }

  &.is-detail-open {
    .filter-groups,
    .map-tools {
      right: 496px;
    }
  }
}

@media (max-width: 1366px) {
  .left-panel-wrapper {
    width: 480px;
  }

  .left-panel-stack {
    width: 460px;
  }

  .left-trigger {
    transform: translateY(-50%) translateX(450px);
  }

  .left-trigger.is-collapsed {
    transform: translateY(-50%) translateX(-10px);
  }

  .right-panel-clip {
    width: 460px;
  }

  .right-agent-panel {
    width: 440px !important;
  }

  .right-trigger {
    transform: translateY(-50%) translateX(-430px);

    &.is-collapsed {
      transform: translateY(-50%) translateX(10px);
    }
  }

  :deep(.risk-map-controls.is-detail-open) {
    .filter-groups,
    .map-tools {
      right: 456px;
    }
  }

  .map-area.is-right-panel-open {
    :deep(.compass) {
      right: 447px;
    }
  }
}
</style>
