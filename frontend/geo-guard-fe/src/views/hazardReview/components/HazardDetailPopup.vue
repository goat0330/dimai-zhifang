<template>
  <div class="hazard-popup" :class="{ 'is-map-card': variant === 'map' }">
    <header class="popup-header">
      <span class="popup-title" :title="data.name">{{ data.name }}</span>
      <!-- 风险等级接口未返回时整块隐藏，避免出现空胶囊 -->
      <span v-if="data.level" class="level-tag">{{ data.level }}</span>
      <button class="close-button" type="button" title="关闭" @click="emit('close')">
        <img :src="closeIcon" alt="关闭" />
      </button>
    </header>

    <template v-if="variant === 'map'">
      <div class="map-address"><i class="iconfont icon-address"></i>{{ data.address || data.location || '--' }}</div>
      <h3>威胁情况：</h3>
      <div class="stat-grid map-stat-grid">
        <div v-for="stat in mapStats" :key="stat.label" class="stat-cell">
          <span class="stat-label">{{ stat.label }}</span>
          <strong class="stat-value">{{ stat.value || '--' }}</strong>
        </div>
      </div>
      <h3>责任与记录：</h3>
      <div class="map-record-grid">
        <div v-for="row in mapRecordRows" :key="row.label" class="map-record-row" :class="{ 'is-full': row.full }">
          <span>{{ row.label }}：</span><strong>{{ row.value || '--' }}</strong>
        </div>
      </div>
    </template>

    <template v-else>
      <!-- 威胁与稳定性：一行四列 -->
      <div class="stat-grid">
        <div v-for="stat in stats" :key="stat.label" class="stat-cell">
          <span class="stat-label">{{ stat.label }}</span>
          <strong class="stat-value">{{ stat.value }}</strong>
        </div>
      </div>

      <!-- 隐患点编号 / 曾发生灾害时间 -->
      <div class="info-list">
        <div v-for="row in infoRows" :key="row.label" class="info-row">
          <span class="info-label">{{ row.label }}</span>
          <span class="info-value">{{ row.value }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import closeIcon from '@/assets/imgs/hazardReview/icon-close.webp'

const props = defineProps({
  data: {
    type: Object,
    required: true,
  },
  variant: {
    type: String,
    default: 'review',
  },
})

const emit = defineEmits(['close'])

const stats = computed(() => [
  { label: '威胁总人数', value: props.data.threatPeople },
  { label: '威胁总资产', value: props.data.threatProperty },
  { label: '稳定性现状', value: props.data.stabilityNow },
  { label: '稳定性趋势', value: props.data.stabilityForecast },
])

const infoRows = computed(() => [
  { label: '隐患点编号：', value: props.data.code },
  { label: '曾发生灾害时间：', value: props.data.disasterTime },
])

const mapStats = computed(() => [
  { label: '主要威胁对象', value: props.data.threatObject || props.data.mainThreatObject },
  { label: '威胁户数', value: props.data.threatenedHouseholds ?? props.data.threatHouseholds },
  { label: '威胁人数', value: props.data.threatenedPeople ?? props.data.threatPeople },
  { label: '可能造成经济损失', value: props.data.potentialEconomicLoss ?? props.data.economicLoss },
])

const mapRecordRows = computed(() => [
  { label: '紧急联系人', value: props.data.emergencyContact || props.data.contactName },
  { label: '紧急联系电话', value: props.data.emergencyPhone || props.data.contactPhone },
  { label: '上报日期', value: props.data.reportDate || props.data.createDate },
  { label: '确认时间', value: props.data.confirmTime || props.data.checkTime },
  { label: '补充描述', value: props.data.supplementDescription || props.data.description, full: true },
])
</script>

<style lang="less" scoped>
.hazard-popup {
  position: relative;
  width: 402px;
  box-sizing: border-box;
  padding: 14px;
  border: 2px solid #ffffff;
  border-radius: 10px;
  background: rgba(241, 243, 252, 0.85);
  -webkit-backdrop-filter: blur(2px);
  backdrop-filter: blur(2px);
  font-family: 'AlibabaPuHuiTi', sans-serif;
}

.hazard-popup.is-map-card {
  width: min(840px, calc(100vw - 32px));
  padding: 18px 24px;
  color: #455468;
}

.is-map-card .map-address {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  color: #617185;
  font-size: 13px;
}

.is-map-card h3 {
  margin: 16px 0 8px;
  color: #343b43;
  font-size: 14px;
}

.is-map-card .map-stat-grid {
  margin-top: 0;
  padding: 18px 0;
  border-color: rgba(220, 145, 22, 0.24);
  background: linear-gradient(180deg, #fff8eb 0%, rgba(243, 218, 176, 0.2) 100%);
}

.is-map-card .map-stat-grid .stat-cell + .stat-cell {
  border-color: rgba(220, 145, 22, 0.2);
}

.is-map-card .map-stat-grid .stat-value {
  color: #d58a00;
}

.map-record-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 24px;
  color: #617185;
  font-size: 13px;
}

.map-record-row {
  display: flex;
  min-width: 0;
  gap: 8px;
}

.map-record-row strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-weight: 400;
}

.map-record-row.is-full {
  grid-column: 1 / -1;
}

/* 标题行：标题 + 等级标签在左，关闭按钮靠右 */
.popup-header {
  display: flex;
  align-items: center;
  gap: 5px;
}

.popup-title {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  color: #222529;
  font-size: 14px;
  font-weight: 700;
  line-height: 16px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 等级标签：红色小胶囊 */
.level-tag {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  height: 16px;
  padding: 0 4px;
  border-radius: 4px;
  background: #e23030;
  color: #ffffff;
  font-size: 10px;
  font-weight: 700;
  line-height: 10px;
  white-space: nowrap;
}

.close-button {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: auto;
  width: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;

  img {
    width: 11px;
    height: 11px;
    display: block;
    object-fit: contain;
  }
}

/* 四项指标卡片：渐变浅红底 + 竖向分隔线 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-top: 12px;
  padding: 16px 0;
  box-sizing: border-box;
  border: 1px solid rgba(226, 48, 48, 0.2);
  border-radius: 6px;
  background: linear-gradient(180deg, #f9e6e6 0%, rgba(241, 193, 193, 0.2) 100%);
}

.stat-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;

  & + .stat-cell {
    border-left: 1px solid rgba(226, 48, 48, 0.2);
  }
}

.stat-label {
  color: #506073;
  font-size: 10px;
  line-height: 14px;
  white-space: nowrap;
}

.stat-value {
  color: #c54040;
  font-size: 14px;
  line-height: 14px;
  font-weight: 700;
  white-space: nowrap;
  font-family: 'Alimama FangYuanTi VF';
}

/* 编号 / 时间：两行文本，值列左对齐 */
.info-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.info-row {
  display: flex;
  align-items: flex-start;
  color: #506073;
  font-size: 12px;
  line-height: 14px;
}

.info-label {
  flex: 0 0 96px;
}

.info-value {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
