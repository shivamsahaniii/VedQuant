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

setUnauthorizedHandler(() => {
  useAuthStore().logout()
  router.push({ name: 'login', query: { expired: '1' } })
})

export default router
