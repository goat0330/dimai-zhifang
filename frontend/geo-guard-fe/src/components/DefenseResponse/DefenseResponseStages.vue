<template>
  <header class="defense-stages">
    <button class="defense-back" type="button" @click="$emit('back')">‹ &nbsp;返回驾驶舱</button>
    <div class="defense-stage-flow" aria-label="防御响应阶段">
      <div v-for="(step, index) in visibleStages" :key="step.value" class="defense-stage"
        :class="{ done: activeStage > step.value, current: activeStage === step.value }">
        <span class="defense-stage-dot">{{ activeStage > step.value ? '✓' : activeStage === step.value ? '✓' : '' }}</span>
        <span>{{ step.label }}</span>
        <span v-if="index < visibleStages.length - 1" class="defense-stage-line" />
      </div>
    </div>
  </header>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ activeStage: { type: Number, default: 3 }, skipPlan: { type: Boolean, default: false } })
defineEmits(['back'])
const stages = [
  { value: 2, label: '方案接入' },
  { value: 3, label: '响应执行' },
  { value: 4, label: '闭环归档' },
]
const visibleStages = computed(() => props.skipPlan ? stages.slice(1) : stages)
</script>
<style scoped>
.defense-stages{flex-shrink:0;min-height:72px;border-radius:16px;background:#fff;display:flex;align-items:center;gap:26px;padding:12px 22px;margin-bottom:16px}
.defense-back{border:0;border-radius:6px;padding:12px 18px;background:#3561fa;color:#fff;font-weight:650;cursor:pointer;white-space:nowrap}
.defense-stage-flow{display:flex;align-items:center;flex:1;min-width:0}
.defense-stage{position:relative;display:flex;gap:8px;align-items:center;flex:1;min-width:0;font-size:14px;color:#98a4b5;white-space:nowrap;font-weight:600}
.defense-stage-dot{width:22px;height:22px;border:1.5px solid #c7d3e7;border-radius:50%;display:flex;align-items:center;justify-content:center;z-index:1;color:#fff;background:#fff;font-size:12px}
.defense-stage.done,.defense-stage.current{color:#3162f3}
.defense-stage.done .defense-stage-dot,.defense-stage.current .defense-stage-dot{border-color:#3561fa;background:#3561fa}
.defense-stage.current{font-weight:700}
.defense-stage-line{height:4px;background:#d7dce6;flex:1;margin:0 15px;min-width:15px}
.defense-stage.done .defense-stage-line{background:#3561fa}
@media(max-width:850px){.defense-stages{flex-wrap:wrap}.defense-stage-flow{flex-basis:100%}.defense-stage{font-size:12px}.defense-stage-line{margin:0 6px}}
</style>
