<template>
  <section class="report-document-section" aria-label="事件复盘报告文档">
    <!-- 顶部导航与操作栏 -->
    <header class="doc-top-bar">
      <div class="header-left">
        <button
          type="button"
          class="back-btn"
          title="返回"
          @click="emit('back')"
        >
          <i class="iconfont icon-title-back"></i>
        </button>
        <h1 class="page-title" :title="event.title || '秭归市事件'">
          {{ event.title || '秭归市事件' }}
        </h1>
        <div class="tags-group">
          <template v-if="demoPresentation">
            <span class="tag-badge tag-disaster">{{ event.disasterType || '滑坡险情' }}</span>
            <span class="tag-badge tag-scale">{{ event.scale || '监测处置' }}</span>
            <span class="tag-badge tag-status"><i class="status-dot"></i><span>报告预览</span></span>
          </template>
          <template v-else>
            <span class="tag-badge tag-disaster">{{ event.disasterType || '滑坡' }}</span>
            <span class="tag-badge tag-scale">{{ event.scale || '小型' }}</span>
            <span class="tag-badge tag-mutation">{{ event.mutationType || '新生突发' }}</span>
            <span class="tag-badge tag-status"><i class="status-dot"></i><span>已生成</span></span>
          </template>
        </div>
      </div>

      <div class="header-right">
        <button v-if="demoPresentation" type="button" class="btn-action btn-download" title="下载 Word 报告" @click="handleDownload">
          <el-icon><Download /></el-icon><span>下载 Word</span>
        </button>
        <template v-else>
          <button type="button" class="btn-action btn-edit" @click="handleEdit">编辑</button>
          <button type="button" class="btn-action btn-confirm" @click="handleConfirm">确认</button>
        </template>
      </div>
    </header>

    <!-- 下部正文与大纲左右分栏 -->
    <div class="doc-body-split">
      <!-- 左侧大纲导航栏 (200px) -->
      <aside class="toc-sidebar" aria-label="文档大纲目录">
        <h2 class="toc-title">事件复盘报告</h2>
        <nav class="toc-nav-list">
          <button
            v-for="item in tocItems"
            :key="item.id"
            type="button"
            class="toc-nav-item"
            :class="{
              'is-active': activeHeadingId === item.id,
              'is-sub': item.level > 1,
            }"
            @click="scrollToHeading(item.id)"
          >
            <span class="toc-nav-text" :title="item.title">{{ item.title }}</span>
          </button>
        </nav>
      </aside>

      <!-- 右侧 Markdown 文档滚动渲染区 -->
      <main ref="articleScrollRef" class="article-scroll-container" @scroll="handleScroll">
        <div ref="articleExportRef" class="article-inner-wrap">
          <!-- 顶部引导与免责声明 -->
          <div class="disclaimer-tip-row">
            <el-icon class="tip-icon"><InfoFilled /></el-icon>
            <span v-if="demoPresentation">报告依据当前事件信息及随软件交付的秭归市事件资料整理；实际结论以现场核查和业务审核记录为准。</span>
            <span v-else>根据事件基础信息、现场调查报告、处置记录及相关图片，智能体已形成以下复盘草稿。</span>
          </div>

          <!-- 文档报头居中区域 -->
          <div class="doc-header-center">
            <h1 class="doc-big-title">{{ reportTitle }}</h1>
            <p class="doc-meta-line">{{ demoPresentation ? '秭归市事件 · 处置复盘报告' : '报告编号:PS-20260411-01 | AI草稿V1.0' }}</p>
            <div v-if="demoPresentation" class="warning-alert-pill">
              <el-icon class="alert-icon"><WarningFilled /></el-icon>
              <span>报告所列历史监测时片和处置记录来自随软件交付的业务资料，不代表实时监测数据或已完成的正式审核。</span>
            </div>
            <div v-else class="warning-alert-pill">
              <el-icon class="alert-icon"><WarningFilled /></el-icon>
              <span>带“待核实”标记的内容尚未完成确认，确认前不作为正式结论。</span>
            </div>
          </div>

          <!-- Markdown 正文解析区 -->
          <article class="markdown-body-render" v-html="parsedData.html"></article>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import {
  DEMO_REPORT_MARKDOWN,
  parseReportMarkdown,
} from './demoReportMarkdown.js'

defineOptions({ name: 'ReportDocumentSection' })

const props = defineProps({
  event: {
    type: Object,
    default: () => ({}),
  },
  markdown: {
    type: String,
    default: '',
  },
  demoPresentation: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['back', 'edit', 'confirm'])

const articleScrollRef = ref(null)
const articleExportRef = ref(null)
const activeHeadingId = ref('')
let isManualScrolling = false

const reportTitle = computed(() => `${props.event.title || '秭归市事件'} 处置复盘报告`)

// 解析 Markdown 与目录树
const parsedData = computed(() => {
  const content = props.markdown || DEMO_REPORT_MARKDOWN
  return parseReportMarkdown(content)
})

// 过滤展示大纲列表（优先展示一级章节）
const tocItems = computed(() => {
  return parsedData.value.toc.filter((item) => item.level === 1)
})

// 默认高亮首个目录项
onMounted(() => {
  if (tocItems.value.length > 0) {
    activeHeadingId.value = tocItems.value[0].id
  }
})

// 点击目录项平滑滚动定位到指定段落
const scrollToHeading = (id) => {
  activeHeadingId.value = id
  isManualScrolling = true

  nextTick(() => {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    window.setTimeout(() => {
      isManualScrolling = false
    }, 600)
  })
}

// 滚动时动态监听当前可视段落
const handleScroll = () => {
  if (isManualScrolling || !articleScrollRef.value) return

  const container = articleScrollRef.value
  const headings = container.querySelectorAll('.report-doc-heading')
  if (!headings.length) return

  const containerTop = container.getBoundingClientRect().top
  let currentId = tocItems.value[0]?.id || ''

  headings.forEach((heading) => {
    const rect = heading.getBoundingClientRect()
    // 相对容器顶部的有效视口阈值
    if (rect.top - containerTop <= 120) {
      currentId = heading.id
    }
  })

  if (currentId) {
    activeHeadingId.value = currentId
  }
}

const handleEdit = () => {
  ElMessage.info('进入报告编辑模式')
  emit('edit')
}

const handleConfirm = () => {
  ElMessage.success('复盘报告已确认归档')
  emit('confirm')
}

const handleDownload = async () => {
  try {
    const [{ exportDomToDocx }, { saveAs }] = await Promise.all([
      import('@/utils/docx.js'),
      import('file-saver'),
    ])
    const blob = await exportDomToDocx(articleExportRef.value)
    const safeTitle = (props.event.title || '秭归市事件').replace(/[\\/:*?"<>|]/g, '_')
    saveAs(blob, `${safeTitle}_处置复盘报告.docx`)
    ElMessage.success('Word 报告已下载')
  } catch (error) {
    console.error('导出复盘报告 Word 失败', error)
    ElMessage.error('Word 导出失败，请稍后重试')
  }
}
</script>

<style lang="less" scoped src="./ReportDocumentSection.less"></style>
