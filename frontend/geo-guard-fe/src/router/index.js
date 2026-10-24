import { createRouter, createWebHistory } from 'vue-router'
import setupPermissionGuard from '@/router/permission.js'

const routes = [
  {
    path: '/login',
    name: 'Login',
    redirect: '/cockpit',
    meta: { title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layout/index.vue'),
    redirect: '/cockpit',
    children: [
      {
        path: 'home',
        name: 'YichangQaHome',
        component: () => import('@/views/home/index.vue'),
        meta: { title: '智能问答主页' },
      },
      {
        path: 'cockpit',
        name: 'CockpitHome',
        component: () => import('@/views/cockpit/index.vue'),
        meta: { title: '智能驾驶舱' },
      },
      {
        path: 'chat-engine/chatting',
        name: 'ChatEngineChatting',
        component: () => import('@/views/chatEngine/chatting/index.vue'),
        meta: { title: '智能问答' },
      },
      {
        path: 'warning/risk-eval',
        name: 'RiskEval',
        component: () => import('@/views/riskEvaluation/index.vue'),
        meta: { title: '风险评价地图' },
      },
      {
        path: 'warning/risk-report',
        name: 'DynamicRiskReport',
        component: () => import('@/views/dynamicRiskReport/index.vue'),
        meta: { title: '动态风险一张图' },
      },
      {
        path: 'ai-studio',
        name: 'GeoAiStudio',
        component: () => import('@/views/geoAiStudio/index.vue'),
        meta: { title: 'AI 工作台' },
      },
      {
        path: 'business/cases',
        name: 'BusinessCaseCenter',
        component: () => import('@/views/caseCenter/index.vue'),
        meta: { title: '协同处置中心' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/cockpit' },
]

const router = createRouter({ history: createWebHistory(), routes })
setupPermissionGuard(router)

export default router
