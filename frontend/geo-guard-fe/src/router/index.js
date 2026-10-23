import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/demo',
      name: 'YichangGoldDemo',
      component: () => import('@/views/goldDemo/index.vue'),
      meta: { title: '地脉智控宜昌演示' },
    },
    { path: '/', redirect: '/demo' },
    { path: '/:pathMatch(.*)*', redirect: '/demo' },
  ],
})

export default router
