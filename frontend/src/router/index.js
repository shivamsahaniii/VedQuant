import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { setUnauthorizedHandler } from '../api/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { guest: true } },
    { path: '/signup', name: 'signup', component: () => import('../views/SignupView.vue'), meta: { guest: true } },
    {
      path: '/',
      component: () => import('../layouts/AppLayout.vue'),
      children: [
        { path: '', redirect: '/overview' },
        { path: 'overview', name: 'overview', component: () => import('../views/OverviewView.vue'), meta: { title: 'Overview' } },
        { path: 'markets', name: 'markets', component: () => import('../views/MarketsView.vue'), meta: { title: 'Markets' } },
        { path: 'algo', name: 'algo', component: () => import('../views/AlgoTradingView.vue'), meta: { title: 'Algo Trading' } },
        { path: 'intraday', name: 'intraday', component: () => import('../views/IntradayView.vue'), meta: { title: 'Intraday' } },
        { path: 'swing', name: 'swing', component: () => import('../views/SwingView.vue'), meta: { title: 'Swing' } },
        { path: 'paper', name: 'paper', component: () => import('../views/PaperTradingView.vue'), meta: { title: 'Paper Trading' } },
        { path: 'live', name: 'live', component: () => import('../views/LiveTradingView.vue'), meta: { title: 'Live Trading' } },
        { path: 'dhan/callback', name: 'dhan-callback', component: () => import('../views/DhanCallbackView.vue'), meta: { title: 'Dhan login' } },
        { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: 'Settings' } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.guest && !auth.isLoggedIn) return { name: 'login', query: { next: to.fullPath } }
  if (to.meta.guest && auth.isLoggedIn) return { name: 'overview' }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · VedQuant` : 'VedQuant'
})

// A page that was open while the site was updated still points at the old code files. Moving to
// another screen then fails to load its file: reload once so the browser gets the new version.
const STALE = /dynamically imported module|Importing a module script failed|error loading dynamically|Loading chunk/i
function reloadOnce(path) {
  try {
    if (sessionStorage.getItem('vq_reloaded')) return
    sessionStorage.setItem('vq_reloaded', '1')
  } catch { /* no session storage: still reload */ }
  window.location.assign(path)
}
router.onError((err, to) => { if (STALE.test(err?.message || '')) reloadOnce(to?.fullPath || '/') })
window.addEventListener('vite:preloadError', (e) => { e.preventDefault(); reloadOnce(window.location.pathname) })
router.afterEach(() => { try { sessionStorage.removeItem('vq_reloaded') } catch { /* ignore */ } })

setUnauthorizedHandler(() => {
  useAuthStore().logout()
  router.push({ name: 'login', query: { expired: '1' } })
})

export default router
