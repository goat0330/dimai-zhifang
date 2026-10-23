<template>
  <div class="risk-level-overview">
    <div class="section-header">
      <div class="header-left">
        <span class="section-bullet"></span>
        <h3 class="section-title">风险等级概况</h3>
      </div>

      <div class="header-right">
        <!-- 图例 -->
        <div class="chart-legend">
          <span v-for="item in legendList" :key="item.name" class="legend-item">
            <i class="line-marker" :style="{ background: item.color }"></i>
            <span class="legend-text">{{ item.name }}</span>
          </span>
        </div>

        <!-- 周期下拉选择 -->
        <div class="period-select">
          <span>{{ selectedPeriod }}</span>
          <i class="arrow-down"></i>
        </div>
      </div>
    </div>

    <!-- ECharts 趋势折线图或空态 -->
    <div class="chart-card">
      <div v-if="hasChartData" ref="chartRef" class="line-chart"></div>
      <el-empty v-else class="chart-empty" :image-size="60" description="暂无风险等级趋势数据" />
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useEcharts } from '@/hooks/useEcharts.js'

defineOptions({
  name: 'RiskLevelOverview',
})

const props = defineProps({
  data: {
    type: Object,
    default: null,
  },
})

const selectedPeriod = ref('近一周')

const gradeSeries = [
  { level: 5, name: '高风险', color: '#E45B5B' },
  { level: 4, name: '较高风险', color: '#FF922C' },
  { level: 3, name: '中风险', color: '#F8D35E' },
  { level: 2, name: '较低风险', color: '#7EA8FF' },
  { level: 1, name: '低风险', color: '#A6C5EE' },
]
const legendList = gradeSeries.map(({ name, color }) => ({ name, color }))

const hasChartData = computed(() => {
  return Boolean(props.data && Array.isArray(props.data?.dates) && props.data.dates.length > 0)
})

const buildOption = (px) => ({
    animationDuration: 1400,
    animationEasing: 'cubicOut',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: '#E0EEFA',
      textStyle: {
        color: '#383C41',
        fontSize: px(12),
      },
    },
    grid: {
      top: px(16),
      right: px(14),
      bottom: px(20),
      left: px(14),
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.data?.dates || [],
      axisLine: {
        lineStyle: {
          color: '#EDF1F6',
        },
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        color: '#9096A2',
        fontSize: px(12),
        margin: px(10),
      },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 'dataMax',
      splitLine: {
        lineStyle: {
          color: '#EDF1F6',
          type: 'solid',
        },
      },
      axisLabel: {
        color: '#9096A2',
        fontSize: px(12),
      },
    },
    series: gradeSeries.map((grade) => ({
      name: grade.name,
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: px(4),
      showSymbol: false,
      lineStyle: {
        color: grade.color,
        width: px(1.5),
      },
      itemStyle: {
        color: grade.color,
      },
      data: props.data?.counts?.[grade.level] || [],
    })),
})

const { chartRef, renderChart } = useEcharts({
  initOnVisible: true,
  getOption: buildOption,
})

watch(() => props.data, () => {
  if (hasChartData.value) renderChart(buildOption)
}, { deep: true })
</script>

<style lang="less" scoped>
.risk-level-overview {
  width: 100%;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-bullet {
  width: 8px;
  height: 8px;
  background: url('@/assets/imgs/point.png') center / contain no-repeat;
  flex-shrink: 0;
}

.section-title {
  margin: 0;
  color: #383c41;
  font-size: 16px;
  font-weight: 600;
  line-height: 20px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.chart-legend {
  display: flex;
  align-items: center;
  gap: 14px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.line-marker {
  width: 10px;
  height: 2px;
  border-radius: 1px;
}

.legend-text {
  color: #617185;
  font-size: 12px;
}

.period-select {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #ffffff;
  border: 1px solid #e0eefa;
  border-radius: 4px;
  color: #617185;
  font-size: 12px;
  line-height: 16px;
  cursor: pointer;
}

.arrow-down {
  display: inline-block;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid #9096a2;
}

.chart-card {
  box-sizing: border-box;
  background: #ffffff;
  border-radius: 10px;
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;

  .chart-empty {
    padding: 0;
  }
}

.line-chart {
  width: 100%;
  height: 100%;
}
</style>
