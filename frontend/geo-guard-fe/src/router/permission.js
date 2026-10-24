export default function setupPermissionGuard(router) {
  router.beforeEach((to) => (to.path === '/login' ? '/cockpit' : true))
}
