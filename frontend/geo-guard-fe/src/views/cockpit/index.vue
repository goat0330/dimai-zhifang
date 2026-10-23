<template>
  <div class="cockpit-page">
    <CockpitDashboard />
  </div>
</template>

<script setup>
import CockpitDashboard from '@/views/home/components/CockpitDashboard.vue'
</script>

<style lang="less" scoped>
.cockpit-page {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: 18px;
  box-sizing: border-box;

  :deep(.cockpit-dashboard) {
    height: 100%;
    min-height: 0;
    max-height: none;
  }
}
</style>
