<template>
  <Transition name="agent-panel">
    <aside
      v-if="visible"
      class="risk-report-agent"
      :class="{ 'is-embedded': embedded }"
    >
      <header class="agent-header">
        <div class="agent-title">
          <img :src="analysisIcon" alt="" />
          {{ mode === 'result' ? '宜昌市风险评价' : '今日风险评价报文' }}
        </div>
        <button type="button" title="关闭" aria-label="关闭" @click="emit('close')">
          <i class="iconfont icon-close"></i>
        </button>
      </header>

      <div v-if="mode === 'result'" class="agent-body result-body">
        <section v-if="displaySnapshot" class="result-overview">
          <div>
            <span>评价时点</span>
            <strong>{{ resultAsOf }}</strong>
          </div>
          <div>
            <span>斜坡单元</span>
            <strong>{{ Number(displayUnitCount || 0).toLocaleString() }} 个</strong>
          </div>
        </section>
        <p v-else class="result-empty">暂无可用的风险评价数据</p>

        <section v-if="displaySnapshot" class="result-grade-list" aria-label="动态风险等级统计">
          <div v-for="item in resultGrades" :key="item.level">
            <span><i :style="{ backgroundColor: item.color }"></i>{{ item.name }}风险</span>
            <strong>{{ Number(item.count || 0).toLocaleString() }} 个</strong>
          </div>
        </section>

        <p class="result-intro">评价按斜坡单元形成，地图可切换查看静态易发性与动态风险。</p>
        <details v-for="step in resultSteps" :key="step.title" class="result-step" open>
          <summary>{{ step.title }}</summary>
          <p>{{ step.content }}</p>
        </details>
      </div>

      <div v-else ref="bodyRef" class="agent-body">
        <p v-if="visibleCount >= 1" class="intro message-enter">
          宜昌市最新风险评价时点为 <span>{{ reportAsOf }}</span>，本报文按斜坡单元说明静态易发性、动态危险性、承灾体暴露与易损性、动态风险结果：
        </p>

        <article
          v-for="(item, index) in visibleSteps"
          :key="item.title"
          class="analysis-item message-enter"
        >
          <button type="button" class="analysis-title" @click="toggleStep(index)">
            <span><i class="iconfont icon-circle-right"></i>{{ item.title }}</span>
            <i class="iconfont icon-arrow-down" :class="{ 'is-folded': !item.open }"></i>
          </button>
          <Transition name="detail-expand">
            <div v-if="item.open" class="analysis-detail">
              <p v-for="text in item.content" :key="text">{{ text }}</p>
              <RiskReportMapImage
                v-if="item.imageKey"
                :src="mapImages[item.imageKey]"
                :title="item.riskTypeName"
                :units="riskUnits"
                :vector-tile-url="vectorTileUrl"
                vector-source-layer="p6_dynamic_latest"
                :level-field="item.levelField"
                :level-colors="item.levelColors"
                :risk-type-name="item.riskTypeName"
                :loading="riskMapLoading || generatingImages"
              />
            </div>
          </Transition>
        </article>

        <p v-if="visibleCount >= totalMessages - 1" class="summary message-enter">{{ reportSummary }}</p>

        <p v-if="visibleCount >= totalMessages" class="finish-message message-enter">宜昌市风险评价报文已生成，可查看全市斜坡单元静态易发性与动态风险分布。</p>

        <div v-if="loading" class="thinking"><i></i><i></i><i></i></div>
      </div>

      <Teleport v-if="mode !== 'result'" to="body">
        <div v-if="needsMapGenerator" :key="p6Snapshot?.snapshot_id" class="map-image-generator" aria-hidden="true">
          <DynamicRiskMap
            ref="generatorMapRef"
            :units="riskUnits"
            :vector-tile-url="vectorTileUrl"
            vector-source-layer="p6_dynamic_latest"
            level-field="s_grade"
            :level-colors="RISK_GRADE_COLORS"
            risk-type-name="静态易发性"
            show-yichang-boundary
            :interactive="false"
            :attribution-control="false"
            preserve-drawing-buffer
            @ready="handleGeneratorReady"
          />
        </div>
      </Teleport>
    </aside>
  </Transition>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import analysisIcon from '@/assets/imgs/fengxian/analysis.png'
import DynamicRiskMap from '@/components/DynamicRiskMap/index.vue'
import RiskReportMapImage from '@/components/RiskReportMapImage/index.vue'
import { getP6DynamicCounties, getP6DynamicLatest, getP6DynamicTileUrl } from '@/api/p6Dynamic.js'
import { RISK_GRADE_COLORS, RISK_GRADE_NAMES } from '@/utils/riskEvaluation.js'

defineOptions({ name: 'RiskReportAgent' })

const props = defineProps({
  visible: Boolean,
  embedded: Boolean,
  mode: {
    type: String,
    default: 'process',
    validator: (value) => ['process', 'result'].includes(value),
  },
  snapshot: { type: Object, default: null },
  counts: { type: Object, default: () => ({}) },
  unitCount: { type: Number, default: 0 },
})

const emit = defineEmits(['close', 'complete'])
const p6Snapshot = ref(props.snapshot)
const p6UnitCount = ref(Number(props.unitCount || 0))
const p6Counts = ref({ 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 })
const displaySnapshot = computed(() => props.snapshot || p6Snapshot.value)
const displayUnitCount = computed(() => props.unitCount || p6UnitCount.value)
const resultAsOf = computed(() => String(displaySnapshot.value?.as_of_local || '').replace('T', ' ') || '—')
const reportAsOf = computed(() => resultAsOf.value === '—' ? '—' : resultAsOf.value.replace(/([+-]\d{2}:\d{2})$/, ''))
const resultGrades = computed(() => [5, 4, 3, 2, 1].map((level) => ({
  level,
  name: RISK_GRADE_NAMES[level],
  color: RISK_GRADE_COLORS[level],
  count: props.counts[level] || p6Counts.value[level] || 0,
})))
const ungradedUnitCount = computed(() => Math.max(
  0,
  Number(displayUnitCount.value || 0) - [1, 2, 3, 4, 5].reduce((sum, level) => sum + Number(p6Counts.value[level] || 0), 0),
))
const reportSummary = computed(() => {
  const grades = [5, 4, 3, 2, 1].map((level) => `${RISK_GRADE_NAMES[level]}${Number(p6Counts.value[level] || 0).toLocaleString('zh-CN')}个`).join('、')
  const ungraded = ungradedUnitCount.value ? `另有${ungradedUnitCount.value.toLocaleString('zh-CN')}个单元未获得风险等级，未纳入分级统计。` : ''
  return `截至 ${reportAsOf.value}，宜昌市已计算 ${Number(displayUnitCount.value || 0).toLocaleString('zh-CN')} 个斜坡单元。动态风险分布为：${grades}。${ungraded}`
})
const resultSteps = [
  { title: '静态易发性', content: '以斜坡单元静态易发性等级作为评价基础。' },
  { title: '动态危险性', content: '根据 ECMWF IFS 模式降雨，按过去24小时、72小时和168小时窗口更新斜坡单元危险性等级。' },
  { title: '承灾体暴露', content: '结合 LandScan 人口与 OSM 道路数据，统计斜坡单元人口和道路暴露情况。' },
  { title: '资产易损性', content: '分别记录人口、高速及快速路、国省干道、县乡道路和村道及其他道路的易损性评分。' },
  { title: '动态风险', content: '综合危险性、暴露度和分项易损性，形成斜坡单元动态风险五级结果。' },
]
const bodyRef = ref(null)
const visibleCount = ref(0)
const loading = ref(false)
const riskMapLoading = ref(false)
const riskUnits = ref([])
const generatorMapRef = ref(null)
const generatorReady = ref(false)
const generatingImages = ref(false)
const mapImages = reactive({})
const vectorTileUrl = computed(() => (p6Snapshot.value?.snapshot_id
  ? getP6DynamicTileUrl({ scenario: 'dynamic', snapshotId: p6Snapshot.value.snapshot_id })
  : ''))
let sequenceTimer = null
let completeTimer = null
let completionTriggered = false
let preparationVersion = 0
let generateQueued = false

const mapConfigs = {
  susceptibility: { levelField: 's_grade', levelColors: RISK_GRADE_COLORS, riskTypeName: '静态易发性' },
  hazard: { levelField: 'h_dynamic_grade', levelColors: RISK_GRADE_COLORS, riskTypeName: '动态危险性' },
  exposure: { levelField: 'e_grade', levelColors: RISK_GRADE_COLORS, riskTypeName: '承灾体暴露度' },
  risk: { levelField: 'r_dynamic_grade', levelColors: RISK_GRADE_COLORS, riskTypeName: '动态风险' },
}
const needsMapGenerator = computed(() => props.mode !== 'result' && Object.keys(mapConfigs).some((key) => !mapImages[key]))

watch(() => p6Snapshot.value?.snapshot_id, (snapshotId, previousSnapshotId) => {
  if (!snapshotId || !previousSnapshotId || snapshotId === previousSnapshotId) return
  Object.keys(mapImages).forEach((key) => delete mapImages[key])
  generatorReady.value = false
})

const steps = reactive([
  {
    title: '宜昌市斜坡单元数据加载',
    open: true,
    content: ['正在读取宜昌市斜坡单元和最新风险评价时片。'],
  },
  {
    title: '区域「地质灾害易发性」评价',
    open: true,
    imageKey: 'susceptibility',
    ...mapConfigs.susceptibility,
    content: ['采用宜昌市斜坡单元静态易发性成果，按低、较低、中、较高、高五级展示；该等级作为动态危险性和风险计算的基础。'],
  },
  {
    title: '区域「地质灾害危险性」评价',
    open: true,
    imageKey: 'hazard',
    ...mapConfigs.hazard,
    content: ['结合静态易发性与 ECMWF IFS 模式降雨，按过去24小时、72小时和168小时窗口计算当前危险性等级。降雨值为数值模式数据。'],
  },
  {
    title: '区域「承灾体暴露度」评价',
    open: true,
    imageKey: 'exposure',
    ...mapConfigs.exposure,
    content: ['结合人口与道路数据统计斜坡单元承灾体暴露度；人口和不同等级道路的易损性系数参与风险计算。'],
  },
  {
    title: '区域「地质灾害风险性」评价',
    open: true,
    imageKey: 'risk',
    ...mapConfigs.risk,
    content: ['按危险性、承灾体暴露度和分项易损性计算斜坡单元动态风险等级，并以五级颜色显示在地图上。'],
  },
])

const totalMessages = steps.length + 3
const visibleSteps = computed(() => steps.slice(0, Math.max(0, visibleCount.value - 1)))

const scrollToBottom = async () => {
  await nextTick()
  if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
}

const clearSequence = () => {
  window.clearInterval(sequenceTimer)
  window.clearTimeout(completeTimer)
  sequenceTimer = null
  completeTimer = null
}

const updateBaseDataContent = () => {
  const countDisplay = Number(p6UnitCount.value || 0).toLocaleString('zh-CN')
  steps[0].content = [`截至 ${reportAsOf.value}，宜昌市风险评价包含 ${countDisplay} 个斜坡单元，并使用对应的单元面图层和最新评价结果。`]
}

const loadP6Data = async () => {
  if (riskMapLoading.value) return
  riskMapLoading.value = true
  try {
    const latest = props.snapshot ? { snapshot: props.snapshot } : await getP6DynamicLatest('dynamic')
    p6Snapshot.value = latest.snapshot
    const result = await getP6DynamicCounties({ scenario: 'dynamic', snapshotId: latest.snapshot?.snapshot_id })
    p6Counts.value = result.items.reduce((counts, item) => {
      for (let level = 1; level <= 5; level += 1) counts[level] += Number(item[`r${level}`] || 0)
      return counts
    }, { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 })
    p6UnitCount.value = Number(latest.snapshot?.unit_count || result.items.reduce((sum, item) => sum + Number(item.total_units || 0), 0))
    updateBaseDataContent()
  } catch (error) {
    console.error('读取宜昌风险评价数据失败', error)
    p6Snapshot.value = null
    p6UnitCount.value = 0
  } finally {
    riskMapLoading.value = false
  }
}

const generateMapImages = async () => {
  if (!generatorReady.value || !generatorMapRef.value || !vectorTileUrl.value) return
  if (generatingImages.value) {
    generateQueued = true
    return
  }

  generatingImages.value = true
  try {
    do {
      generateQueued = false
      for (const [key, config] of Object.entries(mapConfigs)) {
        const image = await generatorMapRef.value.renderAndExport(config, [])
        if (image) mapImages[key] = image
      }
    } while (generateQueued)
  } finally {
    generatingImages.value = false
  }
}

const handleGeneratorReady = () => {
  generatorReady.value = true
  if (needsMapGenerator.value && vectorTileUrl.value) {
    void generateMapImages()
  }
}

const startSequence = () => {
  clearSequence()
  completionTriggered = false
  visibleCount.value = 1
  loading.value = true
  sequenceTimer = window.setInterval(() => {
    visibleCount.value += 1
    void scrollToBottom()
    if (visibleCount.value >= totalMessages) {
      window.clearInterval(sequenceTimer)
      sequenceTimer = null
      loading.value = false
      if (!completionTriggered) {
        completionTriggered = true
        completeTimer = window.setTimeout(async () => {
          const deadline = Date.now() + 15000
          while (!generatorReady.value && props.visible && Date.now() < deadline) {
            await new Promise((resolve) => window.setTimeout(resolve, 120))
          }
          if (props.visible && generatorReady.value && needsMapGenerator.value) await generateMapImages()
          if (props.visible) emit('complete')
        }, 600)
      }
    }
  }, 720)
}

const toggleStep = (index) => {
  if (steps[index]) steps[index].open = !steps[index].open
}

watch([() => props.visible, () => props.mode], async ([visible, mode]) => {
  const version = ++preparationVersion
  if (!visible) {
    clearSequence()
    return
  }

  if (mode === 'result') {
    clearSequence()
    visibleCount.value = totalMessages
    loading.value = false
    return
  }

  visibleCount.value = 1
  loading.value = true
  await loadP6Data()
  await nextTick()
  if (!props.visible || version !== preparationVersion) return
  if (generatorReady.value && needsMapGenerator.value) await generateMapImages()
  startSequence()
}, { immediate: true })

onBeforeUnmount(() => {
  preparationVersion += 1
  clearSequence()
})
</script>

<style lang="less" scoped>
.risk-report-agent {
  position: absolute;
  inset: 0 0 0 auto;
  z-index: 24;
  width: 480px;
  max-width: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  background: #ffffff;
  color: #617185;
}
.risk-report-agent.is-embedded {
  position: relative;
  inset: auto;
  z-index: 1;
  width: 480px;
  height: 100%;
  flex: 0 0 480px;
}
.agent-header {
  display: flex;
  width: 100%;
  height: 58px;
  min-height: 58px;
  flex: 0 0 58px;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  box-sizing: border-box;
  background: url('@/assets/imgs/fengxian/fxpj-bg.png') center / 120% 100% no-repeat;
  color: #222527;
  font-family: 'AlibabaPuHuiTi', sans-serif;
  font-size: 18px;
  font-style: normal;
  font-weight: 700;
  line-height: 18px;
}
.agent-title { display: flex; align-items: center; gap: 8px; }
.agent-title img { width: 20px; height: 20px; object-fit: contain; }
.sample-origin-badge { padding: 3px 7px; border-radius: 10px; color: #8a5a13; background: #fff3da; font-size: 11px; font-weight: 600; }
.agent-header button { width: 28px; height: 28px; padding: 0; border: 0; background: transparent; color: #222527; cursor: pointer; }
.agent-header button i { font-size: 16px; }
.agent-body {
  min-height: 0;
  flex: 1 1 auto;
  padding: 20px;
  overflow-x: hidden;
  overflow-y: auto;
  box-sizing: border-box;
  font-size: 14px;
  line-height: 24px;
  scroll-behavior: smooth;
}
.result-body { padding: 16px; }
.result-overview { display: grid; gap: 8px; margin-bottom: 12px; padding: 12px; border: 1px solid #dcedff; border-radius: 8px; background: #f4f8ff; }
.result-overview > div { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.result-overview span { color: #617185; }
.result-overview strong { color: #222527; text-align: right; }
.result-grade-list { display: grid; gap: 6px; }
.result-grade-list > div { display: flex; min-height: 36px; align-items: center; justify-content: space-between; padding: 0 10px; border-radius: 6px; background: #f7faff; font-size: 13px; }
.result-grade-list span { display: flex; align-items: center; gap: 8px; }
.result-grade-list i { width: 10px; height: 10px; border-radius: 50%; }
.result-grade-list strong { color: #383c41; font-weight: 600; }
.result-intro { margin: 16px 0 10px; color: #617185; font-size: 13px; }
.result-step { margin: 0 0 8px; padding: 10px 12px; border: 1px solid #dcedff; border-radius: 8px; background: #fff; }
.result-step summary { color: #007bff; font-size: 13px; font-weight: 600; cursor: pointer; }
.result-step p { margin: 8px 0 0; color: #617185; font-size: 12px; line-height: 20px; }
.result-empty { margin: 12px 0; color: #9096a2; text-align: center; }
.intro { margin: 0 0 18px; color: #383C41; }
.intro span { color: #007BFF; font-weight: 500; }
.analysis-item { margin-bottom: 12px; }
.analysis-title { display: flex; width: 100%; min-height: 46px; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 12px; border: 1px solid #DCEDFF; border-radius: 8px; background: #f4f8ff; color: #007BFF; font-size: 14px; line-height: 22px; text-align: left; cursor: pointer; }
.analysis-title span { display: flex; align-items: flex-start; gap: 8px; }
.analysis-title span i { margin-top: 3px; font-size: 16px; }
.analysis-title > i { flex: 0 0 auto; transition: transform 0.24s ease; }
.analysis-title > i.is-folded { transform: rotate(180deg); }
.analysis-detail { overflow: hidden; padding: 10px 12px 0; color: #9096A2; }
.analysis-detail p { position: relative; margin: 0 0 8px; padding-left: 12px; }
.analysis-detail p::before { position: absolute; top: 10px; left: 0; width: 4px; height: 4px; border-radius: 50%; background: #A6ACB8; content: ''; }
.summary, .finish-message { margin: 18px 0 0; color: #617185; }
.finish-message { padding: 12px; border-left: 4px solid #007BFF; border-radius: 0 6px 6px 0; background: #E0EEFA; color: #383C41; }
.thinking { display: flex; gap: 5px; padding: 12px 2px; }
.thinking i { width: 6px; height: 6px; border-radius: 50%; background: #007BFF; animation: thinking 1s infinite ease-in-out; }
.thinking i:nth-child(2) { animation-delay: 0.16s; }.thinking i:nth-child(3) { animation-delay: 0.32s; }
.message-enter { animation: message-in 0.28s ease both; }
.detail-expand-enter-active, .detail-expand-leave-active { transition: max-height 0.24s ease, opacity 0.2s ease; }
.detail-expand-enter-from, .detail-expand-leave-to { max-height: 0; opacity: 0; }.detail-expand-enter-to, .detail-expand-leave-from { max-height: 120px; opacity: 1; }
.agent-panel-enter-active, .agent-panel-leave-active { transition: transform 0.28s ease, opacity 0.24s ease; }
.agent-panel-enter-from, .agent-panel-leave-to { opacity: 0; transform: translateX(30px); }
@keyframes message-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes thinking { 0%, 60%, 100% { transform: translateY(0); opacity: 0.35; } 30% { transform: translateY(-4px); opacity: 1; } }
</style>

<style lang="less">
.map-image-generator { position: fixed; top: 0; left: -10000px; width: 640px; height: 360px; overflow: hidden; pointer-events: none; }
</style>
