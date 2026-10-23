<template>
  <div class="report-content" :class="{ 'is-download': isDownload }">
    <h2>{{ reportDate }}地质灾害风险程度预测</h2>
    <p>基于宜昌市斜坡单元静态易发性、ECMWF IFS 模式降雨、承灾体暴露与易损性数据，形成动态危险性及风险评价结果。</p>
    <p>
      截至 {{ asOfText || reportDate }}，全市共 <strong>{{ Number(total || 0).toLocaleString() }}</strong> 个斜坡单元；
      高风险 <strong :style="{ color: RISK_GRADE_COLORS[5] }">{{ gradeCounts[5] }}</strong> 个，
      较高风险 <strong :style="{ color: RISK_GRADE_COLORS[4] }">{{ gradeCounts[4] }}</strong> 个，
      中风险 <strong :style="{ color: RISK_GRADE_COLORS[3] }">{{ gradeCounts[3] }}</strong> 个，
      较低风险 <strong :style="{ color: RISK_GRADE_COLORS[2] }">{{ gradeCounts[2] }}</strong> 个，
      低风险 <strong :style="{ color: RISK_GRADE_COLORS[1] }">{{ gradeCounts[1] }}</strong> 个。
    </p>
    <p v-if="ungradedCount">另有 {{ ungradedCount.toLocaleString() }} 个单元未获得风险等级，未纳入分级统计。</p>

    <section v-for="group in riskGroups" :key="group.level" class="risk-group">
      <h3 :style="{ color: group.color }">{{ group.order }}、{{ group.label }}风险斜坡单元 {{ group.count.toLocaleString() }} 个</h3>
      <p v-for="area in group.counties" :key="area.name"><strong>{{ area.name }}</strong> {{ area.count.toLocaleString() }} 个</p>
      <p v-if="!group.counties.length">当前该等级斜坡单元为 0 个。</p>
    </section>

    <p v-if="!Number(total || 0)">当前暂无斜坡单元评价数据。</p>
    <p>请结合辖区实际和现场核查情况开展巡查排查、风险研判与防范处置。动态降雨数据为数值模式产品。</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import dayjs from 'dayjs'
import { RISK_GRADE_COLORS, RISK_GRADE_NAMES } from '@/utils/riskEvaluation.js'

defineOptions({ name: 'DynamicRiskReportContent' })

const props = defineProps({
  counts: { type: Object, default: () => ({}) },
  total: { type: Number, default: 0 },
  counties: { type: Array, default: () => [] },
  isDownload: Boolean,
  date: { type: String, default: '' },
  asOf: { type: String, default: '' },
})

const reportDate = computed(() => {
  const date = dayjs(props.date)
  return (date.isValid() ? date : dayjs()).format('YYYY年MM月DD日')
})
const asOfText = computed(() => String(props.asOf || '').replace('T', ' '))
const gradeCounts = computed(() => Object.fromEntries([1, 2, 3, 4, 5].map((level) => (
  [level, Number(props.counts[level] || 0).toLocaleString('zh-CN')]
))))
const ungradedCount = computed(() => Math.max(
  0,
  Number(props.total || 0) - [1, 2, 3, 4, 5].reduce((sum, level) => sum + Number(props.counts[level] || 0), 0),
))
const riskGroups = computed(() => [5, 4, 3, 2, 1].map((level, index) => ({
  level,
  order: ['一', '二', '三', '四', '五'][index],
  label: RISK_GRADE_NAMES[level],
  color: RISK_GRADE_COLORS[level],
  count: Number(props.counts[level] || 0),
  counties: props.counties
    .map((county) => ({ name: county.county, count: Number(county[`r${level}`] || 0) }))
    .filter((county) => county.name && county.count > 0)
    .sort((a, b) => b.count - a.count),
})))
</script>

<style lang="less" scoped>
.report-content {
  color: #383c41;
  font-size: 15px;
  line-height: 24px;
  word-break: break-word;

  &:not(.is-download) {
    padding: 4px 0 20px;
  }
}

.report-content h2 { margin: 0 0 8px; color: #222527; font-size: 22px; line-height: 32px; }
.report-content p { margin: 0 0 8px; }
.risk-group { margin: 12px 0; }
.risk-group h3 { margin: 0 0 5px; font-size: 16px; line-height: 24px; }
.risk-group p { margin: 0 0 4px 14px; }

.is-download {
  width: 760px;
  padding: 20px;
  background: #ffffff;
  box-sizing: border-box;
}

@media (max-width: 760px) {
  .report-content h2 { font-size: 18px; line-height: 26px; }
}
</style>
