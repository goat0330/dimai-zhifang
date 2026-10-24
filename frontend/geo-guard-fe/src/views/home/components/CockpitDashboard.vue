<template>
  <section class="cockpit-dashboard" :class="{ 'is-resizing': Boolean(activeResize) }" aria-label="地灾智能驾驶舱">
    <div ref="dashboardGridRef" class="dashboard-grid" :style="dashboardGridStyle">
      <aside ref="leftColumnRef" class="left-column" aria-label="业务与风险概览">
        <section class="business-card panel-card">
          <div class="panel-heading">
            <h2>业务概览</h2>
          </div>
          <div class="metric-grid">
            <div v-for="item in businessMetrics" :key="item.label" class="metric-item">
              <span class="metric-label">{{ item.label }}</span>
              <strong :class="item.tone">{{ item.value }}<small>{{ item.unit }}</small></strong>
              <span v-if="item.note" class="metric-note">{{ item.note }}</span>
            </div>
          </div>
        </section>

        <section class="risk-card panel-card" aria-label="宜昌风险态势">
          <RiskOverviewPanel
            ref="riskOverviewPanelRef"
            :dataset="riskDataset"
            :p6-driven="true"
            :p6-risk-data="p6RiskData"
            :p6-exposure="DASHBOARD_SNAPSHOT.p6Exposure"
            :hide-summary-heading="true"
            @show-detail="router.push({ name: 'RiskEval' })"
            @open-risk-report="router.push({ name: 'DynamicRiskReport' })"
            @select-area="handleOverviewAreaSelect"
            @date-change="handleOverviewDateChange"
          >
            <template #supplemental>
              <section class="risk-supplemental-device" aria-label="设备类型分布">
                <div class="risk-supplemental-heading">
                  <h2>设备类型</h2>
                </div>
                <DeviceTypeList :items="deviceTypeItems" />
              </section>
              <section class="risk-supplemental-ai" aria-label="AI研判结果">
                <GroupDefenseOverview :risk-only="true" :risk-levels="p6RiskData.counts" />
              </section>
            </template>
          </RiskOverviewPanel>
        </section>

      </aside>

      <div
        class="column-resize-handle"
        :class="{ 'is-active': activeResize === 'left' }"
        role="separator"
        aria-label="调整左侧列宽"
        aria-orientation="vertical"
        tabindex="0"
        @pointerdown="startResize($event, 'left')"
        @keydown="handleResizeKeydown($event, 'left')"
      ></div>

      <main ref="mapWorkspaceRef" class="map-workspace" :style="mapWorkspaceStyle" aria-label="地图与事件工作台">
        <section
          ref="mapStageRef"
          class="map-stage"
          :class="{ 'popup-needs-down-placement': popupVisible && mapPointPosition && mapPointPosition.y < 390 }"
          aria-label="宜昌三维地灾地图"
        >
          <MarsMap
            ref="marsMapRef"
            class="cockpit-map"
            :default-center="mapCenter"
            :show-area-search="false"
            @onload="handleMapLoaded"
            @risk-point-position="handleRiskPointPosition"
            @select-area="handleMapAreaSelect"
            @select-map-point="handleMapPointSelect"
          >
            <template #overlay>
              <MapOverlayControls
                ref="mapOverlayControlsRef"
                :risk-levels="riskDataset.activeRiskLevels.value"
                v-model:risk-mode="riskDataset.filters.riskMode"
                :show-risk-mode="true"
                risk-position="left"
                risk-title="灾害分级"
                :include-yichang-layers="true"
                :include-slope-unit-layer="true"
                @update:risk-levels="riskDataset.activeRiskLevels.value = $event"
                @zoom-in="marsMapRef?.handleZoomIn()"
                @zoom-out="marsMapRef?.handleZoomOut()"
                @locate-home="marsMapRef?.flyToHome()"
                @change-base-map="marsMapRef?.changeBaseMap($event)"
                @toggle-imagery-label="marsMapRef?.toggleImageryLabel($event)"
                @change-layer="handleMapLayerChange($event)"
              />
              <div v-if="riskDataLoading || riskLayerRendering" class="map-loading" role="status">
                正在加载斜坡单元数据…
              </div>
              <ReviewMapPopup
                :visible="popupVisible && Boolean(mapPointPosition) && Boolean(selectedEvent)"
                :event="selectedEvent || {}"
                :position="mapPointPosition"
              primary-action-label="风险研判"
                @close="closeMapPopup"
              @detail="startRiskAssessment"
              />
            </template>
          </MarsMap>
        </section>

        <div
          class="row-resize-handle"
          :class="{ 'is-active': activeResize === 'map' }"
          role="separator"
          aria-label="调整地图高度"
          aria-orientation="horizontal"
          tabindex="0"
          @pointerdown="startResize($event, 'map')"
          @keydown="handleResizeKeydown($event, 'map')"
        ></div>

        <section class="workbench panel-card" aria-label="事件工作台">
          <header class="workbench-header">
            <div class="panel-heading">
              <h2>事件工作台</h2>
            </div>
            <div class="event-name-filter" role="search">
              <label for="cockpit-event-name">事件名称：</label>
              <el-input
                id="cockpit-event-name"
                v-model="eventNameKeyword"
                clearable
                placeholder="请输入关键字"
                @keyup.enter="searchCockpitEvents"
              />
              <el-button type="primary" @click="searchCockpitEvents">查询</el-button>
              <el-button @click="resetCockpitEventSearch">重置</el-button>
            </div>
          </header>
          <ReviewEventList
            ref="reviewEventListRef"
            class="cockpit-event-list"
            :hide-keyword-filter="true"
            :events="cockpitEvents"
            :active-id="selectedEvent?.id"
            :loading="false"
            :loading-more="false"
            :has-more="false"
            :total="cockpitEvents.length"
            @select="selectEvent"
            @locate="selectEvent"
          />
        </section>

        <Transition name="detail-fade">
          <div v-if="eventDetailVisible && detailEvent" class="event-detail-mask" @click.self="eventDetailVisible = false">
            <ReviewEventDetail
              class="event-detail-dialog"
              :event="detailEvent"
              @close="eventDetailVisible = false"
              @feedback="showUnavailableAction('当前对象暂不支持资料提交')"
              @report="showUnavailableAction('当前对象暂无可生成的复盘报告')"
            />
          </div>
        </Transition>
      </main>

      <div
        class="column-resize-handle right-column-resize-handle"
        :class="{ 'is-active': activeResize === 'right' }"
        role="separator"
        aria-label="调整右侧列宽"
        aria-orientation="vertical"
        tabindex="0"
        @pointerdown="startResize($event, 'right')"
        @keydown="handleResizeKeydown($event, 'right')"
      ></div>

      <aside ref="assistantColumnRef" class="assistant-column" aria-label="地灾智能助手">
        <section class="assistant-intro" :style="{ '--assistant-lines': `url(${assistantLines})` }">
          <div class="assistant-intro-content">
            <div class="assistant-brandline">
              <strong>脉知</strong>
              <span aria-hidden="true">|</span>
              <h2>地脉智防智能助手</h2>
            </div>
            <section class="assistant-priority-compact" aria-label="当前事件上下文">
              <div class="assistant-priority-compact-heading">
                <span class="assistant-priority-heading-dot" aria-hidden="true">›</span>
                <span>当前事件上下文</span>
              </div>
              <div class="assistant-priority-event-row">
                <span class="assistant-priority-alert" aria-hidden="true">!</span>
                <button class="assistant-priority-link" type="button" @click="enterPriorityEvent">
                  {{ priorityEvent?.eventName || '暂无优先事件' }}
                </button>
                <span class="assistant-risk-tag">{{ priorityEventRisk }}</span>
              </div>
              <div class="assistant-priority-meta">
                <span>发生位置：{{ priorityEventLocation }}</span>
                <span>事件类型：{{ priorityEventType }}</span>
                <span>当前节点：{{ priorityEventStage }}</span>
                <span>待处理：{{ priorityEventPending }}</span>
              </div>
              <div class="assistant-priority-next-row">
                <div class="assistant-priority-next-copy">
                  <p>下一步：{{ priorityEventNextStep }}</p>
                  <p>责任人：{{ priorityEventOwner }}</p>
                </div>
                <button class="assistant-priority-enter" type="button" @click="enterPriorityEvent">进入事件</button>
              </div>
            </section>
          </div>
          <img
            class="assistant-mascot"
            :src="maizhiAvatar"
            alt="脉知"
          />
        </section>

        <section class="assistant-chat panel-card" aria-label="脉知对话">
          <div class="assistant-welcome" aria-label="脉知欢迎语">
            <img :src="maizhiAvatar" alt="脉知" />
            <p>您好，我是脉知，可综合地形影像、事件清单与专家经验，协助开展风险分析、预警研判与应急处置。</p>
          </div>
          <div class="assistant-chat-content">
            <ChatBox
              ref="chatBoxRef"
              v-model="chatMessages"
              :assistant-avatar="maizhiAvatar"
              :yichang-qa-enabled="true"
              input-placeholder="请输入您的问题..."
            />
            <div class="assistant-suggestion-row">
              <button class="assistant-suggestion" type="button" @click="submitAssistantSuggestion">
                {{ assistantSuggestion }}
              </button>
              <button class="assistant-suggestion-refresh" type="button" aria-label="切换建议问题" title="换一个建议" @click="rotateAssistantSuggestion">
                <img :src="assistantRefreshIcon" alt="" />
              </button>
            </div>
          </div>
        </section>
      </aside>
    </div>

  </section>
</template>

<script setup>
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import MarsMap from '@/components/MarsMap/index.vue'
import MapOverlayControls from '@/components/MapOverlayControls/index.vue'
import RiskOverviewPanel from '@/components/RiskOverviewPanel/index.vue'
import GroupDefenseOverview from '@/components/GroupDefenseOverview/index.vue'
import DeviceTypeList from '@/views/monitor/components/DeviceTypeList.vue'
import ReviewEventList from '@/components/ReviewEventList/index.vue'
import ReviewMapPopup from '@/components/ReviewMapPopup/index.vue'
import ReviewEventDetail from '@/components/ReviewEventDetail/index.vue'
import RiskAnalysisAgent from '@/components/RiskAnalysisAgent/index.vue'
import DisposalPlanCard from '@/components/CockpitWorkflow/DisposalPlanCard.vue'
import ChatBox from '@/components/ChatBox/index.vue'
import { Components } from '@/components/ChatBox/config.js'
import { useRiskDataset } from '@/components/RiskSlopePanel/useRiskDataset.js'
import { useP6SlopeUnitLayer } from '@/components/MarsMap/useP6SlopeUnitLayer.js'
import { getP6DynamicCounties, getP6DynamicLatest, getP6DynamicUnit, getP6StaticUnit } from '@/api/p6Dynamic.js'
import { DASHBOARD_SNAPSHOT } from '@/components/HomeBusinessDashboard/dashboardSnapshot.js'
import { getRiskAssessmentList, resolveRiskAssessmentPage } from '@/api/riskEvaluation.js'
import assistantLines from '@/assets/images/home/hero-city-lines.png'
import maizhiAvatar from '@/assets/imgs/home/maizhi-avatar.png'
import assistantRefreshIcon from '@/assets/imgs/chatBox/refresh/refresh.svg?url'
import { useRoute, useRouter } from 'vue-router'

defineOptions({ name: 'CockpitDashboard' })

const route = useRoute()
const router = useRouter()
const TASK_DISPATCH_CONTEXT_KEY = 'geoGuard:cockpit:task-dispatch:context'

function storeTaskDispatchContext(context) {
  const value = JSON.stringify(context)
  try {
    sessionStorage.setItem(TASK_DISPATCH_CONTEXT_KEY, value)
    localStorage.setItem(TASK_DISPATCH_CONTEXT_KEY, value)
  } catch (_) {}
}

function makeTaskDispatchContext(event, extra = {}) {
  const eventId = String(event.id || '')
  const eventName = event.eventName || event.title || ''
  const location = event.displayAddress || event.location || ''
  const occurrenceTime = event.occurrenceTime || event.discoveryTime || ''
  return {
    eventKey: String(event.id || event.slopeUnitId || event.slope_unit_id || ''),
    sourceEventId: eventId,
    event_id: eventId,
    eventName,
    title: eventName,
    eventType: event.eventTypeName || event.disasterType || '',
    eventTypeName: event.eventTypeName || event.disasterType || '',
    location,
    displayAddress: location,
    occurrenceTime,
    discoveryAt: occurrenceTime,
    discoverySource: event.discoverySource || event.source || event.eventTypeName || '驾驶舱事件记录',
    discoverySummary: event.disposalOverview || event.description || '',
    riskLevel: event.eventLevelName || event.scaleLevel || event.riskLevelName || '',
    slopeUnitId: event.slopeUnitId || event.slope_unit_id || '',
    planHandleId: event.planHandleId || event.handleId || event.defRespPlanId || '',
    ...extra,
  }
}

function readTaskDispatchContexts() {
  return [sessionStorage, localStorage].map((storage) => {
    try {
      return JSON.parse(storage.getItem(TASK_DISPATCH_CONTEXT_KEY) || '{}')
    } catch (_) {
      return {}
    }
  })
}

const mapCenter = {
  lng: 111.13,
  lat: 30.6,
  alt: 320000,
  pitch: -75,
  heading: 0,
  roll: 0,
}
const riskDataset = useRiskDataset({ autoLoad: false })
riskDataset.filters.dynamicRiskLevels = [5, 4, 3, 2, 1]
const riskOverviewPanelRef = ref(null)
const dashboardGridRef = ref(null)
const leftColumnRef = ref(null)
const mapWorkspaceRef = ref(null)
const mapStageRef = ref(null)
const assistantColumnRef = ref(null)
const marsMapRef = ref(null)
const mapOverlayControlsRef = ref(null)
const chatBoxRef = ref(null)
const leftColumnTrack = ref('')
const rightColumnTrack = ref('')
const mapTrack = ref('')
const activeResize = ref('')
const selectedEvent = ref(null)
const reviewEventListRef = ref(null)
const eventNameKeyword = ref('')
const selectedRiskAssessment = ref(null)
const riskFlowStartedFor = ref('')
const planFlowStartedFor = ref('')
const popupVisible = ref(false)
const mapPointPosition = ref(null)
const eventDetailVisible = ref(false)
const cockpitEvents = ref([
  {
    id: 'cockpit-event-001',
    eventName: '秭归县水田坝乡滑坡险情',
    title: '秭归县水田坝乡滑坡险情',
    eventTypeName: '滑坡',
    scaleLevel: '待研判',
    reviewStatusName: '待核实',
    occurrenceTime: '2026-10-13 09:20',
    displayAddress: '宜昌市秭归县水田坝乡',
    detailedAddress: '湖北省宜昌市秭归县水田坝乡',
    threatObject: '周边居民点及乡村道路',
    disposalOverview: '巡查发现坡体出现变形迹象，已安排现场核查并持续关注降雨变化。',
    scenePhotoCount: 2,
    investigationReportCount: 1,
    hazardPointId: '420527108005000001',
    slopeUnitId: 'YCSV2_000660',
    spatialRefStatus: 'candidate_unverified',
    lng: 110.8121,
    lat: 30.8718,
    mapPointType: 'hazard',
    currentNodeName: '现场核查',
    pendingDuration: '2小时',
    nextStep: '持续巡查并复核坡体变化',
    responsiblePerson: '属地巡查人员',
  },
  {
    id: 'cockpit-event-002',
    eventName: '兴山县高桥乡斜坡位移异常',
    title: '兴山县高桥乡斜坡位移异常',
    eventTypeName: '斜坡变形',
    scaleLevel: '中风险',
    reviewStatusName: '处理中',
    occurrenceTime: '2026-10-13 08:45',
    displayAddress: '宜昌市兴山县高桥乡',
    detailedAddress: '湖北省宜昌市兴山县高桥乡',
    threatObject: '坡脚居民点及通村道路',
    disposalOverview: '监测数据出现位移变化，已开展现场复核并加密巡查。',
    scenePhotoCount: 1,
    investigationReportCount: 0,
    lng: 110.76,
    lat: 31.34,
  },
  {
    id: 'cockpit-event-003',
    eventName: '夷陵区黄花镇崩塌隐患',
    title: '夷陵区黄花镇崩塌隐患',
    eventTypeName: '崩塌',
    scaleLevel: '中风险',
    reviewStatusName: '已处置',
    occurrenceTime: '2026-10-12 17:10',
    displayAddress: '宜昌市夷陵区黄花镇',
    detailedAddress: '湖北省宜昌市夷陵区黄花镇',
    threatObject: '沿线道路及附近住户',
    disposalOverview: '已完成隐患点巡查和坡面清理，后续纳入常态监测。',
    scenePhotoCount: 2,
    investigationReportCount: 1,
    lng: 111.43,
    lat: 30.98,
  },
  {
    id: 'cockpit-event-004',
    eventName: '五峰桂竹园危岩体现场巡查',
    title: '五峰桂竹园危岩体现场巡查',
    eventTypeName: '危岩体',
    scaleLevel: '中风险',
    reviewStatusName: '待核实',
    occurrenceTime: '2026-10-12 14:30',
    displayAddress: '宜昌市五峰土家族自治县桂竹园',
    detailedAddress: '湖北省宜昌市五峰土家族自治县桂竹园',
    threatObject: '周边居民点及乡村道路',
    disposalOverview: '现场巡查发现坡面局部裂缝，需结合调查记录进一步研判。',
    scenePhotoCount: 2,
    investigationReportCount: 0,
    longitude: 110.67,
    latitude: 30.20,
    lng: 110.67,
    lat: 30.20,
    mapPointType: 'hazard',
  },
  {
    id: 'cockpit-event-005',
    eventName: '秭归县组合监测点',
    title: '秭归县组合监测点',
    eventTypeName: '监测设备',
    scaleLevel: '中风险',
    reviewStatusName: '监测中',
    occurrenceTime: '2026-10-12 14:00',
    displayAddress: '宜昌市秭归县',
    detailedAddress: '湖北省宜昌市秭归县',
    threatObject: '坡体及周边居民点',
    disposalOverview: '持续监测雨量、位移与库水位变化，监测数据纳入日常分析。',
    scenePhotoCount: 0,
    investigationReportCount: 0,
    longitude: 110.98,
    latitude: 30.83,
    lng: 110.98,
    lat: 30.83,
    mapPointType: 'monitor',
  },
])

function searchCockpitEvents() {
  reviewEventListRef.value?.setKeyword(eventNameKeyword.value)
}

function resetCockpitEventSearch() {
  eventNameKeyword.value = ''
  reviewEventListRef.value?.resetFilters()
}
const assistantSuggestions = [
  '生成今日重点事件处置建议',
  '分析当前优先事件的风险与处置重点',
  '汇总当前事件待办并建议处理顺序',
]
const assistantSuggestionIndex = ref(0)
const assistantSuggestion = computed(() => assistantSuggestions[assistantSuggestionIndex.value])

const riskLayer = useP6SlopeUnitLayer(handleSlopeSelect)
const p6Snapshot = ref(null)
const p6Counties = ref([])
const p6Loading = ref(true)
const p6RiskData = computed(() => {
  if (!p6Snapshot.value) {
    return {
      snapshot: null,
      unitCount: DASHBOARD_SNAPSHOT.p6Exposure.slopeUnitCount,
      counts: DASHBOARD_SNAPSHOT.p6RiskCounts,
      counties: [],
    }
  }
  const counts = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }
  p6Counties.value.forEach((county) => {
    for (let level = 1; level <= 5; level += 1) counts[level] += Number(county[`r${level}`] || 0)
  })
  return {
    snapshot: p6Snapshot.value,
    unitCount: Number(p6Snapshot.value.unit_count || p6Counties.value.reduce((sum, county) => sum + Number(county.total_units || 0), 0)),
    counts,
    counties: p6Counties.value,
  }
})
const businessMetrics = computed(() => {
  const counts = p6RiskData.value.counts
  const highRisk = Number(counts[5] || 0)
  const relativelyHighRisk = Number(counts[4] || 0)
  const business = DASHBOARD_SNAPSHOT.business
  return [
    { label: '重点风险', value: highRisk + relativelyHighRisk, unit: '处', note: `高风险 ${highRisk} · 较高 ${relativelyHighRisk}`, tone: 'danger' },
    { label: '待核验隐患', value: business.pendingHazardCount, unit: '项', note: `需优先处理 ${business.priorityPendingCount} 项`, tone: 'primary' },
    { label: '设备在线率', value: business.monitorOnlineRate, unit: '%', note: `在线 ${business.monitorDeviceOnlineCount} · 离线 ${business.monitorDeviceOfflineCount}`, tone: 'success' },
    { label: '监测设备告警', value: business.monitorAlarmCount, unit: '条', note: `已处置 ${business.alarmCompletedCount} · 待处置 ${business.alarmUnprocessedCount}`, tone: 'warning' },
  ]
})
const deviceTypeItems = DASHBOARD_SNAPSHOT.business.deviceTypes
const riskDataLoading = computed(() => p6Loading.value)
const riskLayerRendering = computed(() => riskLayer.rendering.value)
const priorityEvent = computed(() => selectedEvent.value || cockpitEvents.value[0] || null)
const priorityEventRisk = computed(() => priorityEvent.value?.eventLevelName || priorityEvent.value?.scaleLevel || priorityEvent.value?.riskLevelName || '--')
const priorityEventLocation = computed(() => priorityEvent.value?.displayAddress || priorityEvent.value?.location || '--')
const priorityEventType = computed(() => priorityEvent.value?.eventTypeName || priorityEvent.value?.disasterType || '--')
const priorityEventStage = computed(() => priorityEvent.value?.currentNodeName || priorityEvent.value?.currentNode || priorityEvent.value?.stageName || '--')
const priorityEventPending = computed(() => priorityEvent.value?.pendingDuration ?? priorityEvent.value?.pendingTime ?? '--')
const priorityEventNextStep = computed(() => priorityEvent.value?.nextStep || priorityEvent.value?.nextAction || '--')
const priorityEventOwner = computed(() => priorityEvent.value?.responsiblePerson || priorityEvent.value?.ownerName || '--')
const dashboardGridStyle = computed(() => ({
  '--cockpit-left-track': leftColumnTrack.value || null,
  '--cockpit-right-track': rightColumnTrack.value || null,
}))
const mapWorkspaceStyle = computed(() => ({ '--cockpit-map-track': mapTrack.value || null }))
const detailEvent = computed(() => selectedEvent.value ? { ...selectedEvent.value, id: undefined } : null)
const chatMessages = ref([])

function makeBubble(type, content) {
  return {
    comp: Components.BUBBLE,
    props: { type, avatarSrc: maizhiAvatar, message: { content, completed: true }, gap: 22 },
  }
}

function updateAssistant(event) {
  const address = event.displayAddress || event.location || '宜昌市'
  const riskLevel = event.eventLevelName || event.scaleLevel || '待核实'
  const summary = event.isSlopeUnit
    ? `### 斜坡单元风险评价\n\n- **单元编号：** ${event.slopeUnitId}\n- **所在区域：** ${address}\n- **静态易发性：** ${event.staticSusceptibility || '暂无评价'}\n- **动态危险性：** ${event.dynamicHazard || '暂无评价'}\n- **承灾体暴露度：** ${event.exposureLevel || '暂无评价'}\n- **动态风险：** ${riskLevel}\n- **24小时降雨：** ${event.rainfall24h || '--'}\n- **评价时点：** ${event.assessmentTime || '--'}`
    : `### 当前分析对象\n\n- **对象：** ${event.eventName || event.title || '地图点位'}\n- **位置：** ${address}\n- **风险等级：** ${riskLevel}`
  chatMessages.value = [makeBubble(1, summary)]
}

function selectEvent(event) {
  if (!event) return
  selectedEvent.value = { ...event }
  storeTaskDispatchContext(makeTaskDispatchContext(selectedEvent.value))
  selectedRiskAssessment.value = event.riskAssessment || (event.riskAssessmentId ? {
    id: event.riskAssessmentId,
    slopeUnitId: event.slopeUnitId || event.slope_unit_id,
    raw: event.riskAssessmentData || {},
  } : null)
  riskFlowStartedFor.value = ''
  planFlowStartedFor.value = ''
  riskDataset.setActiveSlope(null)
  popupVisible.value = true
  mapPointPosition.value = null
  eventDetailVisible.value = false
  updateAssistant(selectedEvent.value)
  const lng = Number(event.lng)
  const lat = Number(event.lat)
  if (Number.isFinite(lng) && Number.isFinite(lat)) {
    marsMapRef.value?.showRiskPoint(
      { lng, lat, alt: Number(event.alt) || 0 },
      { sampleTerrain: false, flyTo: true, alwaysVisible: true },
    )
  }
}

function handleMapPointSelect(payload) {
  const type = payload?.type || 'hazard'
  const item = payload?.item || {}
  const record = cockpitEvents.value.find((event) => String(event.id) === String(item.id))
  if (record) {
    selectEvent(record)
    return
  }
  const longitude = Number(item.longitude ?? item.lon ?? item.lng)
  const latitude = Number(item.latitude ?? item.lat)
  const name = item.hazardPointName || item.hazard_point_name || item.monitorPointName || item.monitor_point_name || item.pointName || item.name || item.deviceName || '地图点位'
  selectEvent({
    ...item,
    id: String(item.id || item.hazardPointId || item.hazard_point_id || item.monitorPointId || item.monitor_point_id || `${type}-${name}`),
    eventName: name,
    title: name,
    eventTypeName: type === 'monitor' ? '监测点' : '隐患点',
    displayAddress: item.address || item.location || item.county || '宜昌市',
    location: item.address || item.location || item.county || '宜昌市',
    lng: longitude,
    lat: latitude,
  })
}

function locateEvent(event) {
  selectEvent(event)
}

function makeP6RiskAssessment(slopeUnitId, staticUnit, dynamicResult) {
  const item = dynamicResult?.item
  const snapshot = dynamicResult?.snapshot
  if (!staticUnit || !item || !snapshot || String(item.slope_unit_id || item.slopeUnitId) !== String(slopeUnitId)) return null
  const id = `p6-${snapshot.snapshot_id}-${slopeUnitId}`
  return {
    id,
    slopeUnitId,
    name: `${staticUnit.county || '宜昌市'} ${slopeUnitId}`,
    raw: {
      id,
      slopeUnitId,
      name: `${staticUnit.county || '宜昌市'} ${slopeUnitId}`,
      p6StaticUnit: staticUnit,
      p6DynamicItem: item,
      p6Snapshot: snapshot,
      riskSource: 'current_slope_unit_evaluation',
    },
  }
}

async function handleSlopeSelect(slope) {
  const slopeUnitId = String(slope?.slopeUnitId || slope?.slope_unit_id || '')
  if (!slopeUnitId) return
  const [loaded, staticUnit] = await Promise.all([
    getP6DynamicUnit({ slopeUnitId, snapshotId: p6Snapshot.value?.snapshot_id }).catch((error) => {
      console.error('读取斜坡单元动态评价失败', error)
      return null
    }),
    getP6StaticUnit({ slopeUnitId }).catch((error) => {
      console.error('读取斜坡单元基础评价失败', error)
      return null
    }),
  ])
  const unit = loaded?.item || slope
  const lng = Number(unit?.unit_lon ?? slope?.unit_lon ?? slope?.lng)
  const lat = Number(unit?.unit_lat ?? slope?.unit_lat ?? slope?.lat)
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return
  const name = slopeUnitId
  const dynamicGrade = String(unit?.r_dynamic_grade || slope?.r_dynamic_grade || '')
  const dynamicLevel = Number(dynamicGrade.match(/[1-5]/)?.[0])
  const staticGrade = String(unit?.s_grade || slope?.s_grade || '')
  const hazardGrade = String(unit?.h_dynamic_grade || slope?.h_dynamic_grade || '')
  const exposureGrade = String(unit?.e_grade || slope?.e_grade || '')
  const gradeName = (grade) => {
    const value = Number(String(grade || '').match(/[1-5]/)?.[0])
    return value ? `${['', '低', '较低', '中', '较高', '高'][value]}${grade.startsWith('S') ? '易发性' : grade.startsWith('H') ? '危险性' : grade.startsWith('E') ? '暴露度' : '风险'}` : '暂无评价'
  }
  const event = {
    id: `risk-${slopeUnitId}`,
    slopeUnitId,
    title: name,
    eventName: name,
    eventTypeName: '斜坡单元',
    disasterType: '斜坡单元',
    eventLevelName: dynamicLevel ? `${['', '低', '较低', '中', '较高', '高'][dynamicLevel]}风险` : '暂无动态风险评价',
    scaleLevel: dynamicLevel ? `${['', '低', '较低', '中', '较高', '高'][dynamicLevel]}风险` : '暂无动态风险评价',
    reviewStatusName: '斜坡单元评价',
    occurrenceTime: loaded?.snapshot?.as_of_local || p6Snapshot.value?.as_of_local || '',
    assessmentTime: loaded?.snapshot?.as_of_local || p6Snapshot.value?.as_of_local || '',
    displayAddress: unit?.county || slope?.county || '宜昌市',
    location: unit?.county || slope?.county || '宜昌市',
    detailedAddress: unit?.county || slope?.county || '宜昌市',
    staticSusceptibility: gradeName(staticGrade),
    dynamicHazard: gradeName(hazardGrade),
    exposureLevel: gradeName(exposureGrade),
    rainfall24h: Number.isFinite(Number(unit?.rain_past24h_mm)) ? `${Number(unit.rain_past24h_mm).toFixed(1)} mm` : '',
    threatObject: `静态易发性 ${gradeName(staticGrade)} · 动态危险性 ${gradeName(hazardGrade)}`,
    disposalOverview: `动态风险 ${dynamicLevel ? `${['', '低', '较低', '中', '较高', '高'][dynamicLevel]}风险` : '暂无评价'}；承灾体暴露度 ${gradeName(exposureGrade)}；过去24小时模式降雨 ${Number.isFinite(Number(unit?.rain_past24h_mm)) ? `${Number(unit.rain_past24h_mm).toFixed(1)} mm` : '暂无数据'}。`,
    description: '该斜坡单元的等级来自宜昌市风险评价数据。',
    lng,
    lat,
    alt: 0,
    isSlopeUnit: true,
  }
  selectedRiskAssessment.value = makeP6RiskAssessment(slopeUnitId, staticUnit, loaded) || { ...slope, slopeUnitId, raw: slope?.raw || slope }
  riskFlowStartedFor.value = ''
  planFlowStartedFor.value = ''
  selectedEvent.value = event
  riskDataset.setActiveSlope({ ...slope, slopeUnitId })
  popupVisible.value = true
  mapPointPosition.value = null
  eventDetailVisible.value = false
  updateAssistant(event)
  marsMapRef.value?.showRiskPoint(
    { lng, lat, alt: 0 },
    { sampleTerrain: false, flyTo: true, alwaysVisible: true, radius: 8000, pitch: -60 },
  )
}

function handleMapLoaded() {
  marsMapRef.value?.setCockpitBusinessPoints(cockpitEvents.value.filter((event) => event.mapPointType))
  riskLayer.attach(marsMapRef.value?.getMap())
  riskLayer.setStyle({
    mode: riskDataset.filters.riskMode,
    levels: riskDataset.activeRiskLevels.value,
    nextSnapshotId: p6Snapshot.value?.snapshot_id,
  })
  const layers = mapOverlayControlsRef.value?.getData?.().layerOptions || []
  layers.filter((layer) => layer.checked).forEach((layer) => {
    handleMapLayerChange({ ...layer, layers })
  })
}

function handleMapLayerChange(layer) {
  if (layer?.key === 'slope_unit') {
    riskLayer.setVisible(layer.checked)
    return
  }
  marsMapRef.value?.handleLayerChange(layer)
}

function handleRiskPointPosition(position) {
  mapPointPosition.value = position || null
}

function closeMapPopup() {
  popupVisible.value = false
  mapPointPosition.value = null
  marsMapRef.value?.clearRiskPoint()
  riskDataset.setActiveSlope(null)
}

async function startRiskAssessment() {
  const event = selectedEvent.value
  if (!event) return
  let assessment = selectedRiskAssessment.value
  let assessmentId = assessment?.id || assessment?.raw?.id
  const slopeUnitId = assessment?.slopeUnitId || assessment?.slope_unit_id || event.slopeUnitId || event.slope_unit_id
  if (!assessmentId && slopeUnitId) {
    try {
      const result = await getRiskAssessmentList({
        slopeUnitId,
        assessmentDate: riskDataset.filters.assessmentDate,
        withSlopeUnit: true,
      })
      const rows = Array.isArray(result) ? result : resolveRiskAssessmentPage(result).rows
      const row = rows.find((item) => String(item.slopeUnitId || item.slope_unit_id) === String(slopeUnitId))
      if (row) {
        assessment = { ...row, slopeUnitId: row.slopeUnitId || slopeUnitId, raw: row }
        assessmentId = row.id
        selectedRiskAssessment.value = assessment
      }
    } catch (error) {
      console.error('查询当前斜坡单元风险评价记录失败', error)
    }
  }
  if (!assessmentId && slopeUnitId) {
    try {
      const [staticUnit, dynamicResult] = await Promise.all([
        getP6StaticUnit({ slopeUnitId }),
        getP6DynamicUnit({ slopeUnitId, snapshotId: p6Snapshot.value?.snapshot_id }),
      ])
      assessment = makeP6RiskAssessment(slopeUnitId, staticUnit, dynamicResult)
      assessmentId = assessment?.id
      if (assessment) selectedRiskAssessment.value = assessment
    } catch (error) {
      console.error('读取当前斜坡单元评价失败', error)
    }
  }
  if (selectedEvent.value?.id !== event.id) return
  const eventKey = String(event.id || assessment?.slopeUnitId || '')
  if (!assessmentId) {
    chatMessages.value.push(makeBubble(1, `当前事件“${event.eventName || event.title || '地图点位'}”尚未关联有效的斜坡单元风险评价记录，暂时不能运行风险研判。请先关联斜坡单元，并确认该单元已有当前评价记录。`))
    return
  }
  if (riskFlowStartedFor.value === eventKey) return
  riskFlowStartedFor.value = eventKey
  chatMessages.value.push(makeBubble(1, `正在读取“${event.eventName || event.title || '当前斜坡单元'}”的风险评价与降雨数据。`))
  chatMessages.value.push({
    comp: 'RISK_ANALYSIS_AGENT',
    components: markRaw(RiskAnalysisAgent),
    props: {
      visible: true,
      slope: assessment,
      inline: true,
      showClose: false,
      workflowActions: true,
      onWorkflowConfirm: (result) => handleRiskAnalysisConfirmed(event, assessment, result),
    },
  })
}

function openEventDetail() {
  eventDetailVisible.value = Boolean(selectedEvent.value)
}

function handleRiskAnalysisConfirmed(event, assessment, result) {
  if (!event || !result?.riskLevelValue || result.riskLevelValue < 3) return
  if (selectedEvent.value?.id !== event.id || planFlowStartedFor.value === String(event.id)) return
  planFlowStartedFor.value = String(event.id)
  const slopeUnitId = result.slopeUnitId || assessment?.slopeUnitId || ''
  chatMessages.value.push(makeBubble(1, `人工已确认风险研判结果：${result.riskLevel}。下一步进入应急调查处置意见书审核。`))
  chatMessages.value.push({
    comp: 'DISPOSAL_PLAN',
    components: markRaw(DisposalPlanCard),
    props: {
      eventName: event.eventName || event.title || '当前事件',
      riskLevel: result.riskLevel,
      slopeUnitId,
      onApprove: () => {
          const context = makeTaskDispatchContext(event, {
            riskAssessmentId: assessment?.id || assessment?.raw?.id || '',
            riskLevel: result.riskLevel,
            slopeUnitId,
            riskAssessedAt: new Date().toISOString(),
            planApprovedAt: new Date().toISOString(),
            planApproved: true,
            source: 'cockpit-risk-review',
          })
          storeTaskDispatchContext(context)
          router.push({ name: 'TaskDispatch', query: { eventKey: context.eventKey, event_id: context.sourceEventId } })
      },
    },
  })
}

function enterPriorityEvent() {
  if (!priorityEvent.value) return
  selectEvent(priorityEvent.value)
  openEventDetail()
}

function rotateAssistantSuggestion() {
  assistantSuggestionIndex.value = (assistantSuggestionIndex.value + 1) % assistantSuggestions.length
}

async function submitAssistantSuggestion() {
  if (priorityEvent.value && !selectedEvent.value) selectEvent(priorityEvent.value)
  await nextTick()
  chatBoxRef.value?.submit?.(assistantSuggestion.value)
}

function handleOverviewDateChange(date) {
  if (date) riskDataset.filters.assessmentDate = date
}

function handleOverviewAreaSelect(areaResult) {
  if (areaResult?.selected) riskDataset.setRegion(areaResult.selected)
}

function handleMapAreaSelect(areaResult) {
  if (!areaResult?.selected) return
  const panel = riskOverviewPanelRef.value
  if (panel?.selectArea) panel.selectArea(areaResult)
  else riskDataset.setRegion(areaResult.selected)
}

function showUnavailableAction(message) {
  ElMessage.info(message)
}

let resizeStart = null

function startResize(event, type) {
  if (event.button !== 0) return
  const grid = dashboardGridRef.value?.getBoundingClientRect()
  const workspace = mapWorkspaceRef.value?.getBoundingClientRect()
  if (!grid || (type === 'map' && !workspace)) return

  event.preventDefault()
  activeResize.value = type
  resizeStart = {
    type,
    x: event.clientX,
    y: event.clientY,
    gridWidth: grid.width,
    workspaceHeight: workspace?.height ?? 0,
    leftWidth: leftColumnRef.value?.getBoundingClientRect().width ?? 0,
    rightWidth: assistantColumnRef.value?.getBoundingClientRect().width ?? 0,
    mapHeight: mapStageRef.value?.getBoundingClientRect().height ?? 0,
  }
  document.body.style.cursor = type === 'map' ? 'row-resize' : 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', handleResizeMove)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function handleResizeMove(event) {
  if (!resizeStart) return
  const gridWidth = resizeStart.gridWidth
  if (resizeStart.type === 'left' || resizeStart.type === 'right') {
    const delta = event.clientX - resizeStart.x
    const leftSide = resizeStart.type === 'left'
    const currentWidth = leftSide ? resizeStart.leftWidth : resizeStart.rightWidth
    const targetWidth = currentWidth + (leftSide ? delta : -delta)
    const compactLayout = window.matchMedia('(max-width: 1120px)').matches
    const otherWidth = compactLayout && leftSide ? 0 : (leftSide ? resizeStart.rightWidth : resizeStart.leftWidth)
    const minWidth = leftSide ? (compactLayout ? 180 : 250) : 280
    const minMapWidth = compactLayout ? 220 : 340
    const maxWidth = Math.min(gridWidth * 0.4, gridWidth - otherWidth - minMapWidth - 20)
    const width = Math.min(Math.max(targetWidth, minWidth), maxWidth)
    const track = `clamp(${minWidth}px, ${(width / gridWidth) * 100}%, 40%)`
    if (leftSide) leftColumnTrack.value = track
    else rightColumnTrack.value = track
    return
  }

  const height = resizeStart.mapHeight + event.clientY - resizeStart.y
  const maxHeight = Math.min(resizeStart.workspaceHeight * 0.82, resizeStart.workspaceHeight - 210)
  const clampedHeight = Math.min(Math.max(height, 360), maxHeight)
  mapTrack.value = `clamp(360px, ${(clampedHeight / resizeStart.workspaceHeight) * 100}%, 82%)`
}

function stopResize() {
  if (!resizeStart) return
  resizeStart = null
  activeResize.value = ''
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', handleResizeMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
  marsMapRef.value?.resize?.()
}

function handleResizeKeydown(event, type) {
  const direction = type === 'map'
    ? (event.key === 'ArrowUp' ? 1 : event.key === 'ArrowDown' ? -1 : 0)
    : (event.key === 'ArrowRight' ? (type === 'right' ? -1 : 1) : event.key === 'ArrowLeft' ? (type === 'right' ? 1 : -1) : 0)
  if (!direction) return
  event.preventDefault()

  if (type === 'map') {
    const workspace = mapWorkspaceRef.value?.getBoundingClientRect()
    const current = mapStageRef.value?.getBoundingClientRect().height ?? 0
    if (!workspace?.height) return
    const height = Math.min(Math.max(current + direction * 20, 360), workspace.height - 210)
    mapTrack.value = `clamp(360px, ${(height / workspace.height) * 100}%, 82%)`
    marsMapRef.value?.resize?.()
    return
  }

  const grid = dashboardGridRef.value?.getBoundingClientRect()
  if (!grid?.width) return
  const isLeft = type === 'left'
  const column = isLeft ? leftColumnRef.value : assistantColumnRef.value
  const other = isLeft ? assistantColumnRef.value : leftColumnRef.value
  const compactLayout = window.matchMedia('(max-width: 1120px)').matches
  const minWidth = isLeft ? (compactLayout ? 180 : 250) : 280
  const otherWidth = compactLayout && isLeft ? 0 : (other?.getBoundingClientRect().width ?? 0)
  const minMapWidth = compactLayout ? 220 : 340
  const width = Math.min(Math.max((column?.getBoundingClientRect().width ?? minWidth) + direction * 20, minWidth), Math.min(grid.width * 0.4, grid.width - otherWidth - minMapWidth - 20))
  const track = `clamp(${minWidth}px, ${(width / grid.width) * 100}%, 40%)`
  if (isLeft) leftColumnTrack.value = track
  else rightColumnTrack.value = track
}

onBeforeUnmount(stopResize)

watch(
  [() => riskDataset.filters.riskMode, () => riskDataset.activeRiskLevels.value.join(',')],
  ([mode]) => riskLayer.setStyle({ mode, levels: riskDataset.activeRiskLevels.value }),
)

function restoreTaskDispatchEventContext() {
  const requestedIds = [route.query.event_id, route.query.eventId, route.query.eventKey].map((value) => String(value || '')).filter(Boolean)
  if (!requestedIds.length) return
  const contexts = readTaskDispatchContexts()
  const saved = contexts.find((context) => {
    const ids = [context.sourceEventId, context.event_id, context.eventKey, context.slopeUnitId].map((value) => String(value || ''))
    return requestedIds.some((id) => ids.includes(id))
  }) || {}
  const sourceId = String(route.query.event_id || route.query.eventId || saved.sourceEventId || saved.event_id || route.query.eventKey || '')
  const event = cockpitEvents.value.find((item) => requestedIds.includes(String(item.id)) || String(item.id) === sourceId)
  if (event) {
    selectedEvent.value = { ...saved, ...event }
  } else if (saved.eventName || saved.title) {
    selectedEvent.value = {
      ...saved,
      id: sourceId,
      eventName: saved.eventName || saved.title,
      title: saved.title || saved.eventName,
      displayAddress: saved.location || saved.displayAddress || '',
    }
  }
  if (selectedEvent.value) {
    updateAssistant(selectedEvent.value)
    storeTaskDispatchContext(makeTaskDispatchContext(selectedEvent.value, saved))
  }
}

onMounted(async () => {
  restoreTaskDispatchEventContext()
  if (!route.query.event_id && !route.query.eventKey && !selectedEvent.value && priorityEvent.value) {
    storeTaskDispatchContext(makeTaskDispatchContext(priorityEvent.value))
  }
  try {
    const latest = await getP6DynamicLatest('dynamic')
    p6Snapshot.value = latest.snapshot
    const countyResult = await getP6DynamicCounties({ scenario: 'dynamic', snapshotId: latest.snapshot?.snapshot_id })
    p6Counties.value = countyResult.items || []
    riskLayer.setStyle({ nextSnapshotId: latest.snapshot?.snapshot_id })
  } catch (error) {
    console.error('获取宜昌斜坡单元评价时点失败', error)
  } finally {
    p6Loading.value = false
  }
})
</script>

<style lang="less" scoped>
.cockpit-dashboard {
  height: calc(100vh - 170px);
  min-height: 760px;
  max-height: 900px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: #222527;
  font-family: var(--gg-font-ui, inherit);
  scroll-margin-top: 18px;
}

.context-status-tag {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 6px;
  border-radius: 5px;
  background: #eef5ff;
  color: #2673c8;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.dashboard-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(280px, var(--cockpit-left-track, 0.9fr)) 10px minmax(500px, 1.8fr) 10px minmax(360px, var(--cockpit-right-track, 1.2fr));
}

.column-resize-handle {
  position: relative;
  z-index: 3;
  cursor: col-resize;
  touch-action: none;

  &::after {
    position: absolute;
    top: 42%;
    left: 4px;
    width: 2px;
    height: 44px;
    border-radius: 2px;
    background: #b9c9d9;
    content: '';
    opacity: 0.45;
    transition: opacity 150ms ease;
  }

  &:hover::after,
  &.is-active::after { opacity: 1; }
}

.row-resize-handle {
  position: relative;
  z-index: 3;
  cursor: row-resize;
  touch-action: none;

  &::after {
    position: absolute;
    top: 4px;
    left: calc(50% - 22px);
    width: 44px;
    height: 2px;
    border-radius: 2px;
    background: #b9c9d9;
    content: '';
    opacity: 0.45;
    transition: opacity 150ms ease;
  }

  &:hover::after,
  &.is-active::after { opacity: 1; }
}

.cockpit-dashboard.is-resizing { cursor: col-resize; }
.cockpit-dashboard.is-resizing:has(.row-resize-handle.is-active) { cursor: row-resize; }

.left-column,
.map-workspace,
.assistant-column {
  min-width: 0;
  min-height: 0;
}

.left-column {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-color: rgba(148, 163, 184, 0.45) transparent;
  scrollbar-width: thin;

  &::-webkit-scrollbar { width: 4px; }
  &::-webkit-scrollbar-thumb { border-radius: 4px; background: rgba(148, 163, 184, 0.45); }
}

.panel-card {
  border: 1px solid #e4eaf0;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 2px 8px rgba(29, 60, 94, 0.04);
}

.business-card {
  flex: 0 0 clamp(188px, 25vh, 240px);
  padding: 14px;
  box-sizing: border-box;
}

.panel-heading {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;

  h2 {
    margin: 0;
    color: #222527;
    font-size: 16px;
    line-height: 21px;
    font-weight: 800;
  }
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.metric-item {
  min-width: 0;
  min-height: 54px;
  padding: 7px 9px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  border-radius: 7px;
  background: #f5f8fc;

  .metric-label,
  .metric-note {
    overflow: hidden;
    color: #617185;
    font-size: 13px;
    line-height: 16px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: #222527;
    font-size: 22px;
    line-height: 24px;
    font-weight: 800;

    small {
      margin-left: 3px;
      font-size: 12px;
      font-weight: 600;
    }
  }

  .danger { color: #dd4739; }
  .primary { color: #007bff; }
  .success { color: #34a46f; }
  .warning { color: #ff922c; }
}

.risk-card {
  flex: 1 1 600px;
  min-height: 0;
  overflow: hidden;

  :deep(.overview-panel) {
    height: 100%;
    padding: 14px 14px 12px;
  }

  :deep(.overview-header) {
    margin-bottom: 9px;
  }

  :deep(.panel-title) {
    font-size: 16px;
  }

  :deep(.section-title) {
    margin-bottom: 6px;
    font-size: 13px;
  }

  :deep(.summary-grid) {
    gap: 6px;
  }

  :deep(.summary-card) {
    height: 50px;
    min-height: 48px;
    gap: 6px;
    padding: 6px 7px;
  }

  :deep(.card-icon) {
    width: 22px;
    height: 22px;
  }

  :deep(.card-label) {
    font-size: 11px;
    line-height: 13px;
  }

  :deep(.card-value) {
    margin-top: 2px;
    font-size: 17px;
    line-height: 18px;
  }

  :deep(.risk-level-item) {
    height: 28px;
    min-height: 28px;
    padding: 0 7px;
  }

  :deep(.risk-levels) {
    gap: 4px;
  }

  :deep(.level-icon) {
    width: 15px;
    height: 15px;
    margin-right: 4px;
  }

  :deep(.level-name) {
    width: 23px;
    margin-right: 4px;
    font-size: 11px;
  }

  :deep(.level-bar) {
    min-width: 8px;
    margin-right: 5px;
  }

  :deep(.level-count) {
    width: 28px;
    font-size: 12px;
  }

  :deep(.level-divider) {
    margin: 0 3px;
  }

  :deep(.level-percent) {
    width: 30px;
    font-size: 12px;
  }

  :deep(.level-trend) {
    width: 48px;
    margin-left: 3px;
  }

  :deep(.trend-tag),
  :deep(.trend-val) {
    font-size: 10px;
  }

  :deep(.summary-grid),
  :deep(.risk-levels) {
    margin-bottom: 6px;
  }

  :deep(.town-empty) {
    margin: 0;
    padding: 0;
  }

  :deep(.town-empty .el-empty__image) {
    width: 38px;
    height: 30px;
  }

  :deep(.town-empty .el-empty__description) {
    margin-top: 0;
    font-size: 10px;
  }

  :deep(.ranking-title .chart-legend) {
    display: none;
  }

  :deep(.ranking-title) {
    margin-top: 12px;
  }

  :deep(.overview-footer) {
    margin-top: 8px;
    padding-top: 0;
  }

  :deep(.report-button) {
    height: 38px;
    font-size: 14px;
  }

  :deep(.overview-header) {
    margin-bottom: 6px;
    padding: 0;
  }

  :deep(.section-title) {
    margin-bottom: 4px;
    font-size: 13px;
  }

  :deep(.town-risk-chart-container) {
    height: 106px;
  }

  :deep(.town-list.cockpit-town-ranking) {
    gap: 4px;
    padding: 1px 0 3px;
  }

  :deep(.town-list.cockpit-town-ranking .town-item__head) {
    gap: 7px;
  }

  :deep(.town-list.cockpit-town-ranking .town-item__rank) {
    width: 17px;
    height: 18px;
    line-height: 18px;
  }

  :deep(.town-list.cockpit-town-ranking .town-item__name) {
    min-width: 0;
    flex: 1 1 auto;
    overflow: hidden;
    font-size: 13px;
    line-height: 16px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  :deep(.town-list.cockpit-town-ranking .town-item__value) {
    font-size: 14px;
    line-height: 16px;
  }

  :deep(.town-list.cockpit-town-ranking .town-item__bar) {
    height: 2px;
    margin-top: 3px;
    margin-left: 22px;
  }

  :deep(.overview-footer) {
    margin-top: 5px;
  }
}

.risk-supplemental-device {
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px solid #edf1f6;

  .risk-supplemental-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }

  h2 {
    margin: 0;
    color: #222527;
    font-size: 13px;
    line-height: 18px;
    font-weight: 700;
  }

  :deep(.device-type) { height: 96px; align-items: center; }
  :deep(.type-chart) { width: 96px; height: 96px; }
  :deep(.chart-inner) { width: 58px; height: 58px; }
  :deep(.chart-core) { width: 48px; height: 48px; }
  :deep(.chart-label) { font-size: 11px; }
  :deep(.type-legend) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 4px;
    margin: 0;
    padding: 0 0 0 5px;
  }
  :deep(.legend-dot) { width: 7px; height: 7px; margin-right: 4px; }
  :deep(.legend-label) {
    overflow: hidden;
    font-size: 11px;
    line-height: 14px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  :deep(.legend-value) { margin-left: 4px; font-size: 13px; line-height: 14px; }
}

.risk-supplemental-ai {
  margin-top: 3px;

  :deep(.risk-only-panel) { display: block; height: auto; padding: 0; }
  :deep(.business-section) { margin: 0; }
  :deep(.section-title) { min-height: 20px; margin: 0; padding-left: 14px; }
  :deep(.section-title::before) { width: 6px; height: 6px; }
  :deep(.section-title h2) { font-size: 13px; }
  :deep(.note) { display: none; }
  :deep(.risk-grid) { gap: 5px; margin-top: 6px; }
  :deep(.risk-grid article) { height: 54px; padding: 4px 2px; border-radius: 6px; }
  :deep(.risk-grid span) { font-size: 11px; }
  :deep(.risk-grid strong) { margin-top: 3px; font-size: 16px; }
}

.map-workspace {
  position: relative;
  display: grid;
  grid-template-rows: minmax(360px, var(--cockpit-map-track, 2.05fr)) 10px minmax(190px, 1fr);
}

.map-stage {
  position: relative;
  min-height: 0;
  overflow: hidden;
  border: 1px solid #dbe5ee;
  border-radius: 10px;
  background: #e8f0f4;
  isolation: isolate;

  &.popup-needs-down-placement :deep(.review-map-popup) {
    top: 12px !important;
    transform: translateX(-50%) !important;
  }

  :deep(.mars-map-component),
  :deep(.mars3d-container) {
    width: 100%;
    height: 100%;
  }
}

.map-stage :deep(.map-data-source-badge) { display: none; }

.map-stage :deep(.compass) {
  top: auto !important;
  right: auto !important;
  bottom: 12px !important;
  left: 12px !important;
  z-index: 14 !important;
}

.map-loading {
  position: absolute;
  top: 14px;
  left: 50%;
  z-index: 10;
  padding: 7px 12px;
  transform: translateX(-50%);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.92);
  color: #617185;
  font-size: 11px;
  box-shadow: 0 2px 8px rgba(29, 60, 94, 0.08);
}

.workbench {
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 11px 13px 9px;
  box-sizing: border-box;
  overflow: hidden;
}

.workbench-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 3px;
}

.event-name-filter {
  flex: 1 1 520px;
  min-width: 0;
  max-width: 520px;
  display: flex;
  align-items: center;
  gap: 6px;

  label {
    flex: 0 0 auto;
    color: #565e73;
    font-size: 12px;
    white-space: nowrap;
  }

  :deep(.el-input) { flex: 1 1 auto; min-width: 80px; }
  :deep(.el-input__wrapper) {
    height: 32px;
    min-height: 32px;
    border-radius: 8px;
    box-shadow: 0 0 0 1px #e4e5eb inset;
  }
  :deep(.el-button) {
    flex: 0 0 48px;
    width: 48px;
    height: 32px;
    margin-left: 0;
    padding: 0;
    border-radius: 8px;
    font-size: 12px;
  }
  :deep(.el-button--primary) {
    border-color: #007bff;
    background: #007bff;
  }
}

.cockpit-event-list {
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;

  :deep(.event-list-panel) { padding: 0; }
  :deep(.panel-header) { display: none; }
  :deep(.filter-divider) { margin: 0 0 4px; }
  :deep(.event-list-wrap) { min-height: 0; }
  :deep(.event-card-item) { padding-bottom: 4px; }
  :deep(.event-card) {
    grid-template-columns: 28px minmax(0, 1fr);
    column-gap: 8px;
    padding: 7px 9px;
  }
  :deep(.event-card .level-icon) { width: 26px; height: 22px; margin-top: 0; }
  :deep(.event-card .card-content) {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 40%);
    grid-template-areas: 'title location' 'tags date';
    align-items: center;
    column-gap: 8px;
  }
  :deep(.event-card .card-content h2) { grid-area: title; font-size: 12px; line-height: 17px; }
  :deep(.event-card .tag-row) { grid-area: tags; min-width: 0; gap: 4px; margin: 0; }
  :deep(.event-card .tag-row span) { padding: 1px 5px; font-size: 10px; line-height: 15px; white-space: nowrap; }
  :deep(.event-card .event-meta) {
    min-width: 0;
    align-items: center;
    gap: 4px;
    margin: 0;
    overflow: hidden;
    font-size: 10px;
    line-height: 16px;
    white-space: nowrap;
  }
  :deep(.event-card .event-meta:nth-of-type(1)) { grid-area: location; }
  :deep(.event-card .event-meta:nth-of-type(2)) { grid-area: date; }
  :deep(.event-card .event-meta .meta-icon) { flex-basis: 12px; width: 12px; height: 12px; margin-top: 0; }
  :deep(.event-card .event-meta .meta-text) { overflow: hidden; word-break: normal; text-overflow: ellipsis; white-space: nowrap; }
  :deep(.event-card footer) { margin-top: 5px; padding-top: 4px; }
}

.assistant-column {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assistant-intro {
  flex: 0 0 230px;
  min-height: 0;
  min-width: 0;
  position: relative;
  overflow: hidden;
  padding: 14px;
  box-sizing: border-box;
  border: 1px solid #dcecff;
  border-radius: 12px;
  background-color: #eef7ff;
  background-image: linear-gradient(110deg, rgba(248, 252, 255, 0.94), rgba(229, 243, 255, 0.78)), var(--assistant-lines);
  background-position: center, center;
  background-size: cover;
  color: #164b8b;

  .assistant-intro-content {
    position: relative;
    z-index: 1;
    width: 100%;
    padding-right: 142px;
    box-sizing: border-box;
  }

  .assistant-mascot {
    position: absolute;
    z-index: 0;
    right: 2px;
    bottom: 0;
    width: 142px;
    height: 184px;
    object-fit: contain;
    object-position: center bottom;
    pointer-events: none;
  }
}

.assistant-brandline {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 8px;
  color: #0879e8;

  strong {
    flex: none;
    font-size: 24px;
    line-height: 30px;
    font-weight: 900;
  }

  > span {
    color: #7aa7d8;
    font-size: 16px;
  }

  h2 {
    overflow: hidden;
    margin: 0;
    color: #1767c4;
    font-size: 16px;
    line-height: 22px;
    font-weight: 800;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.assistant-priority-compact {
  min-width: 0;
  margin-top: 10px;

  .assistant-priority-compact-heading {
    display: flex;
    align-items: center;
    gap: 6px;
    color: #42678f;
    font-size: 13px;
    line-height: 18px;
    font-weight: 700;
  }

  .assistant-priority-heading-dot {
    color: #1681ef;
    font-size: 16px;
    line-height: 14px;
    font-weight: 900;
  }

  .assistant-priority-alert {
    flex: none;
    display: inline-grid;
    width: 18px;
    height: 18px;
    place-items: center;
    border-radius: 50%;
    background: #ff625c;
    color: #fff;
    font-size: 11px;
    line-height: 18px;
    font-weight: 900;
  }

  .assistant-priority-link {
    display: block;
    min-width: 0;
    flex: 1 1 auto;
    overflow: hidden;
    margin-top: 0;
    padding: 0;
    border: 0;
    background: transparent;
    color: #0879e8;
    font: inherit;
    font-size: 13px;
    line-height: 18px;
    font-weight: 800;
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 1px;
  }

  .assistant-priority-event-row {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    margin-top: 6px;
  }

  .assistant-priority-enter {
    flex: none;
    height: 32px;
    padding: 0 11px;
    border: 0;
    border-radius: 4px;
    background: #0879e8;
    color: #fff;
    font: inherit;
    font-size: 12px;
    line-height: 32px;
    cursor: pointer;
  }

  .assistant-priority-meta {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 10px;
    min-width: 0;
    margin: 8px 0 0 25px;
    color: #617185;
    font-size: 11px;
    line-height: 15px;

    span {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .assistant-priority-next-row {
    display: flex;
    min-width: 0;
    align-items: flex-end;
    gap: 8px;
    margin: 8px 0 0 25px;

    .assistant-priority-next-copy {
      min-width: 0;
      flex: 1 1 auto;
    }

    p {
      overflow: hidden;
      margin: 0;
      color: #617185;
      font-size: 11px;
      line-height: 15px;
      text-overflow: ellipsis;
      white-space: nowrap;

      + p { margin-top: 2px; }
    }
  }
}

.assistant-risk-tag {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  background: #fff1df;
  color: #d97716;
  font-size: 11px;
  line-height: 18px;
  font-weight: 700;
  white-space: nowrap;
}

.assistant-welcome {
  flex: none;
  min-width: 0;
  min-height: 76px;
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 14px 0;
  padding: 0;
  box-sizing: border-box;

  img {
    flex: none;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    object-fit: cover;
    background: #edf6ff;
  }

  p {
    min-width: 0;
    margin: 0;
    padding: 10px 12px;
    border-radius: 10px;
    background: #e9f3ff;
    color: #405d7d;
    font-size: 13px;
    line-height: 1.6;
  }
}

.assistant-chat {
  flex: 1 1 0;
  min-height: 180px;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.assistant-chat-content {
  flex: 1 1 0;
  min-height: 0;
  position: relative;
}

.assistant-chat-content :deep(.chat-box) {
  padding: 12px;
  box-sizing: border-box;
}

.assistant-chat-content :deep(.model-send) {
  height: calc(100% - 196px);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding-right: 2px;
}

.assistant-chat-content :deep(.model-send > div:not(.bubble-loading)) {
  flex: 0 0 auto;
}

.assistant-chat-content :deep(.bubble-box .bubble-answer) {
  border-radius: 12px;
}

.assistant-chat-content :deep(.model-input) {
  left: 12px;
  bottom: 12px;
  width: calc(100% - 24px);
  height: 136px;
}

.assistant-chat-content :deep(.model-input .operate-box) {
  display: none;
}

.assistant-chat-content :deep(.input-box .el-textarea__inner) {
  min-height: 56px !important;
  padding: 8px 9px;
  font-size: 13px;
}

.assistant-chat-content :deep(.input-tip) {
  display: none;
}

.assistant-suggestion-row {
  position: absolute;
  right: 12px;
  bottom: 158px;
  left: 12px;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 6px;
}

.assistant-suggestion,
.assistant-suggestion-refresh {
  height: 36px;
  border: 1px solid #d5e7fb;
  background: #fff;
  color: #52677e;
  cursor: pointer;
}

.assistant-suggestion {
  min-width: 0;
  overflow: hidden;
  padding: 0 12px;
  border-radius: 999px;
  text-overflow: ellipsis;
  white-space: nowrap;
  font: inherit;
  font-size: 12px;
}

.assistant-suggestion-refresh {
  flex: none;
  width: 36px;
  display: grid;
  place-items: center;
  padding: 0;
  border-radius: 50%;

  img { width: 15px; height: 15px; }
}

.assistant-suggestion:hover,
.assistant-suggestion-refresh:hover {
  border-color: #8fc5ff;
  color: #0879e8;
}

.event-detail-mask {
  position: absolute;
  inset: 0;
  z-index: 15;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  box-sizing: border-box;
  background: rgba(26, 42, 60, 0.28);
  backdrop-filter: blur(2px);
}

.event-detail-dialog {
  width: min(500px, 100%);
  height: min(720px, 100%);
  overflow: hidden;
  border: 1px solid #e4eaf0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 16px 48px rgba(26, 42, 60, 0.2);
}

.detail-fade-enter-active,
.detail-fade-leave-active { transition: opacity 180ms ease; }
.detail-fade-enter-from,
.detail-fade-leave-to { opacity: 0; }

@media (max-width: 1450px) {
  .dashboard-grid {
    grid-template-columns: minmax(250px, var(--cockpit-left-track, 0.9fr)) 8px minmax(450px, 1.8fr) 8px minmax(320px, var(--cockpit-right-track, 1.2fr));
  }

  .column-resize-handle::after { left: 3px; }

  .business-card { padding: 12px; }
  .metric-item { padding: 7px 8px; }
  .risk-card :deep(.overview-panel) { padding: 12px 10px 10px; }
  .assistant-intro { flex-basis: 218px; padding: 12px; }
  .assistant-intro .assistant-intro-content { padding-right: 146px; }
  .assistant-intro .assistant-mascot { right: 2px; width: 162px; height: 200px; }
}

@media (max-height: 850px) {
  .business-card { flex-basis: clamp(184px, 28vh, 210px); }
  .metric-grid { gap: 6px; margin-top: 8px; }
  .metric-item { min-height: 50px; padding: 6px 8px; }
  .risk-card :deep(.summary-card) { height: 46px; min-height: 46px; }
  .risk-supplemental-device :deep(.device-type) { height: 82px; }
  .risk-supplemental-device :deep(.type-chart) { height: 82px; }
  .risk-supplemental-ai :deep(.risk-grid article) { height: 48px; }
  .assistant-intro { flex-basis: 200px; }
  .assistant-intro .assistant-intro-content { padding-right: 140px; }
  .assistant-intro .assistant-mascot { width: 150px; height: 184px; }
  .assistant-chat { min-height: 160px; }
  .assistant-welcome { min-height: 64px; }
  .assistant-welcome p { font-size: 12px; }
}

@media (max-width: 1120px) {
  .cockpit-dashboard { height: auto; max-height: none; }
  .dashboard-grid { grid-template-columns: minmax(180px, var(--cockpit-left-track, 0.8fr)) 8px minmax(0, 1.6fr); }
  .right-column-resize-handle { display: none; }
  .map-workspace { grid-column: 3; grid-template-rows: minmax(420px, var(--cockpit-map-track, 55vh)) 10px minmax(220px, 36vh); }
  .assistant-column { grid-column: 1 / -1; min-height: 560px; }
  .left-column { min-height: 720px; }
}
</style>
