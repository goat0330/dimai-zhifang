<template>
  <section class="studio-page">
    <header class="studio-header">
      <div class="header-copy">
        <h1>地脉智防 · 专业知识工作台</h1>
      </div>
      <div class="service-health" aria-label="AI 服务状态">
        <div class="health-item">
          <span class="health-dot" :class="ragStatus"></span>
          <span
            >RAG <b>{{ serviceLabel(ragStatus) }}</b></span
          >
        </div>
      </div>
    </header>
    <KnowledgeWorkspace />
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getRagHealth } from '@/api/geoAiStudio.js'
import KnowledgeWorkspace from './components/KnowledgeWorkspace.vue'

defineOptions({ name: 'GeoAiStudio' })

const ragStatus = ref('checking')

const serviceLabel = (status) =>
  ({
    checking: '检测中',
    online: '已连接',
    offline: '未连接',
  })[status] || '未知'

onMounted(async () => {
  try {
    await getRagHealth()
    ragStatus.value = 'online'
  } catch {
    ragStatus.value = 'offline'
  }
})
</script>

<style lang="less" scoped>
.studio-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 30px 36px 40px;
  box-sizing: border-box;
  color: var(--gg-text-primary, #222527);
  font-family: var(--gg-font-ui, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif);
  background: var(--gg-page-bg, #f5f7fc);
}

.studio-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  padding: 0 4px 24px;
}

.header-copy h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  line-height: 38px;
}

.service-health {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-left: auto;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 11px;
  border: 1px solid var(--gg-border-quiet, #e2e8f0);
  border-radius: 8px;
  background: var(--gg-surface, #ffffff);
  color: var(--gg-text-secondary, #617185);
  font-size: 12px;
  white-space: nowrap;

  b {
    margin-left: 4px;
    color: var(--gg-text-strong, #383c41);
    font-weight: 600;
  }
}

.health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--gg-text-quiet, #a6acb8);

  &.online {
    background: var(--gg-success, #34a46f);
  }
  &.offline {
    background: var(--gg-danger, #dd4739);
  }
  &.checking {
    background: var(--gg-warning, #ff922c);
  }
}

@media (max-width: 980px) {
  .studio-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .service-health {
    width: 100%;
    justify-content: flex-end;
  }
}

@media (max-width: 680px) {
  .studio-page {
    padding: 22px 16px 30px;
  }
  .header-copy h1 {
    font-size: 24px;
    line-height: 32px;
  }
}
</style>

