<template>
  <section class="knowledge-workspace">
    <header class="workspace-toolbar">
      <div>
        <h2>宜昌知识问答</h2>
        <p>回答引用宜昌知识库资料；资料管理与导入可在 geo_rag 中打开。</p>
      </div>
      <a class="knowledge-link" :href="knowledgeUrl" target="_blank" rel="noopener noreferrer">
        打开 geo_rag 知识库
        <span aria-hidden="true">↗</span>
      </a>
    </header>
    <div class="chat-workspace">
      <ChatBox
        v-model="messages"
        yichang-qa-enabled
        input-placeholder="输入宜昌地质灾害相关问题"
        :assistant-avatar="assistantAvatar"
      />
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import ChatBox from '@/components/ChatBox/index.vue'
import assistantAvatar from '@/assets/imgs/home/maizhi-avatar.png'

defineOptions({ name: 'KnowledgeWorkspace' })

const messages = ref([])
const knowledgeUrl = `${window.location.protocol}//${window.location.hostname}:5175/?embed=rag#/extensions?tab=knowledge`
</script>

<style lang="less" scoped>
.knowledge-workspace {
  display: flex;
  min-height: 0;
  height: calc(100vh - 190px);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
}

.workspace-toolbar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 16px 20px;
  border-bottom: 1px solid #e8edf2;

  h2 {
    margin: 0;
    color: #222527;
    font-size: 17px;
    font-weight: 650;
  }

  p {
    margin: 6px 0 0;
    color: #738194;
    font-size: 12px;
  }
}

.knowledge-link {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
  padding: 9px 12px;
  border: 1px solid #d8e5f3;
  border-radius: 8px;
  color: #176fc1;
  font-size: 13px;
  text-decoration: none;
  background: #f7fbff;
}

.chat-workspace {
  flex: 1;
  min-height: 0;
  overflow: hidden;

  :deep(.chat-box) {
    height: 100%;
  }
}

@media (max-width: 760px) {
  .knowledge-workspace {
    height: calc(100vh - 225px);
  }

  .workspace-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
