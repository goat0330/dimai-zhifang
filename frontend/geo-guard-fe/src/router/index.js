import { createRouter, createWebHistory } from 'vue-router'
import setupPermissionGuard from '@/router/permission.js'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layout/index.vue'),
    redirect: '/warning/risk-eval',
    children: [
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
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/warning/risk-eval' },
]

const router = createRouter({ history: createWebHistory(), routes })
setupPermissionGuard(router)

export default router
