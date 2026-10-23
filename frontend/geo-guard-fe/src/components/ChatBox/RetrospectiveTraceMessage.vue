<template>
  <div class="retrospective-trace">
    <p class="trace-intro">
      好的，我将基于 <strong>{{ eventName }}</strong> 当前事件上下文，参考秭归场景 Gold 资料，逐步整理处置经过、核验证据并形成复盘报告演示稿：
    </p>
    <div class="trace-source">主事件沿用当前驾驶舱选择 · 内容参考 GOLD-02 / GOLD-03</div>

    <section v-for="(step, index) in steps" :key="step.title" class="trace-step">
      <button class="trace-step-heading" type="button" @click="toggle(index)" :aria-expanded="openSteps.has(index)">
        <span class="trace-check" aria-hidden="true">✓</span>
        <span>{{ step.title }}</span>
        <span class="trace-state">演示</span>
        <span class="trace-chevron" :class="{ open: openSteps.has(index) }" aria-hidden="true">⌄</span>
      </button>
      <ul v-if="openSteps.has(index)" class="trace-details">
        <li v-for="detail in step.details" :key="detail.label">
          <strong>{{ detail.label }}：</strong>{{ detail.value }}
        </li>
      </ul>
    </section>

    <p class="trace-summary">
      已以当前主事件生成复盘报告演示稿，复用了 Gold 的调查、任务反馈及恢复复核内容结构。报告状态为<strong>待正式审核</strong>；尚未执行后台持久化、真实审核或事件状态变更。
    </p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  eventName: { type: String, default: '秭归县水田坝乡滑坡险情' },
  eventId: { type: String, default: '--' },
  eventTime: { type: String, default: '--' },
  location: { type: String, default: '--' },
})

const openSteps = ref(new Set([0, 1, 2]))
const steps = computed(() => [
  {
    title: '已完成识别事件与复盘范围',
    details: [
      { label: '主事件', value: props.eventName },
      { label: '事件编号', value: props.eventId },
      { label: '时间与位置', value: `${props.eventTime} · ${props.location}` },
      { label: 'Gold参考', value: 'GOLD-02 监测异常发现 + GOLD-03 恢复观察；仅复用演示链路与样例资料' },
    ],
  },
  {
    title: '已完成汇集并核验复盘资料',
    details: [
      { label: 'Gold演示材料', value: '1份调查样例、1份处置意见书样例、4项任务、6条反馈、4条任务复核' },
      { label: '证据分级', value: '区分当前主事件上下文与 Gold Mock 资料；模拟监测值不作为当前事件实测值' },
      { label: '待接入资料', value: '当前事件的正式调查报告、监测时序、任务回执和审核记录' },
    ],
  },
  {
    title: '已汇聚变化依据并生成报告草稿',
    details: [
      { label: '异常与恢复', value: '沿 GOLD-02 异常阶段和 GOLD-03 恢复观察组织变化依据，数值均标注为模拟' },
      { label: '报告内容', value: '事件概况、处置过程、专业分析、综合评价、问题原因、改进建议、复盘结论' },
      { label: '报告状态', value: '本地演示稿已生成，待正式审核；未写入后台业务状态' },
    ],
  },
])

function toggle(index) {
  const next = new Set(openSteps.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  openSteps.value = next
}
</script>

<style scoped>
.retrospective-trace{width:100%;padding:0 2px 8px;color:#354a62;font-size:13px;line-height:1.65}
.trace-intro{margin:0 0 8px;color:#354a62;line-height:1.75}
.trace-intro strong{color:#087cff}
.trace-source{display:inline-flex;margin:0 0 12px;padding:3px 9px;border:1px solid #dbe9fb;border-radius:14px;background:#f4f8ff;color:#56708f;font-size:11px}
.trace-step{margin:0 0 10px}
.trace-step-heading{display:flex;width:100%;align-items:center;gap:9px;padding:10px 12px;border:1px solid #dce7f6;border-radius:10px;background:#f4f8ff;color:#087cff;text-align:left;font:inherit;cursor:pointer}
.trace-check{display:grid;width:19px;height:19px;flex:none;place-items:center;border:1px solid #1685ff;border-radius:50%;font-size:12px;font-weight:700}
.trace-state{margin-left:auto;color:#788ba5;font-size:11px}
.trace-chevron{color:#8795a8;font-size:17px;transform:rotate(0);transition:transform .16s ease}
.trace-chevron.open{transform:rotate(180deg)}
.trace-details{display:grid;gap:8px;margin:10px 0 15px;padding:0 10px 0 29px;color:#75808f;list-style:disc}
.trace-details li{padding-left:1px;overflow-wrap:anywhere}
.trace-details strong{color:#303b49}
.trace-summary{margin:16px 0 0;color:#394454;line-height:1.8}
.trace-summary strong{color:#e78a20}
</style>
