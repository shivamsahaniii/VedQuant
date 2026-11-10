<template>
  <div class="app">
    <header class="topbar">
      <div class="topbar-inner">
        <RouterLink to="/overview" class="brand-link" aria-label="VedQuant home"><BrandMark /></RouterLink>

        <nav class="tabs" aria-label="Sections">
          <RouterLink v-for="t in tabs" :key="t.to" :to="t.to" class="tab" :class="t.tone" active-class="active">
            <AppIcon :name="t.icon" :size="16" />
            <span>{{ t.label }}</span>
            <AppIcon v-if="t.locked" name="lock" :size="12" class="tab-lock" />
          </RouterLink>
        </nav>

        <div class="top-right">
          <span class="market" :class="{ open: market.open }" :title="market.detail">
            <span class="dot"></span>{{ market.label }}<span class="clock">{{ clock }}</span>
          </span>
          <button class="btn primary new-btn" @click="ui.openNewStrategy()">
            <AppIcon name="plus" :size="16" /><span>New strategy</span>
          </button>

          <div class="user" ref="menuRoot">
            <button class="avatar-btn" @click="menuOpen = !menuOpen" :aria-expanded="menuOpen" aria-haspopup="menu">
              <span class="avatar">{{ initial }}</span>
              <span class="mode" :class="isLive ? 'live' : ''">{{ isLive ? 'LIVE' : 'PAPER' }}</span>
              <AppIcon name="chevron" :size="14" />
            </button>
            <div v-if="menuOpen" class="menu" role="menu">
              <div class="menu-head">
                <span class="avatar lg">{{ initial }}</span>
                <div>
                  <div class="menu-email">{{ auth.user?.email }}</div>
                  <div class="menu-role">{{ auth.user?.role }} · {{ auth.user?.trading_mode }} mode</div>
                </div>
              </div>
              <RouterLink to="/settings" class="menu-item" role="menuitem" @click="menuOpen = false">
                <AppIcon name="settings" :size="16" /> Settings
              </RouterLink>
              <RouterLink to="/settings" class="menu-item" role="menuitem" @click="menuOpen = false">
                <AppIcon name="broker" :size="16" /> Brokers
              </RouterLink>
              <div class="menu-sep"></div>
              <button class="menu-item" role="menuitem" @click="logout">
                <AppIcon name="logout" :size="16" /> Log out
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <div v-if="marketStore.feed?.state === 'error'" class="feed-alert" role="alert">
      <div class="feed-alert-inner">
        <AppIcon name="bell" :size="16" />
        <span><b>Live prices stopped.</b> {{ marketStore.feed.message }}</span>
        <RouterLink to="/settings" class="btn ghost sm">Fix in Settings</RouterLink>
      </div>
    </div>

    <main class="page">
      <RouterView />
    </main>

    <NewStrategyDialog />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import BrandMark from '../components/BrandMark.vue'
import NewStrategyDialog from '../components/NewStrategyDialog.vue'
import { useAuthStore } from '../stores/auth'
import { useBrokersStore } from '../stores/brokers'
import { useMarketStore } from '../stores/market'
import { useTradingStore } from '../stores/trading'
import { useMarketsStore } from '../stores/markets'
import { useStrategiesStore } from '../stores/strategies'
import { useSystemStore } from '../stores/system'
import { useUiStore } from '../stores/ui'
import { istClock, marketStatus, nseHolidays } from '../utils/format'
import { marketsApi } from '../api/client'

const auth = useAuthStore()
const system = useSystemStore()
const ui = useUiStore()
const strategiesStore = useStrategiesStore()
const brokersStore = useBrokersStore()
const marketStore = useMarketStore()
const tradingStore = useTradingStore()
const marketsStore = useMarketsStore()
const router = useRouter()

const isLive = computed(() => auth.user?.trading_mode === 'live' && system.health?.trading_mode === 'live')
const tabs = computed(() => [
  { to: '/overview', label: 'Overview', icon: 'overview' },
  { to: '/markets', label: 'Markets', icon: 'signal' },
  { to: '/algo', label: 'Algo Trading', icon: 'algo' },
  { to: '/intraday', label: 'Intraday', icon: 'intraday' },
  { to: '/swing', label: 'Swing', icon: 'swing' },
  { to: '/paper', label: 'Paper Trading', icon: 'paper' },
  { to: '/live', label: 'Live Trading', icon: 'live', tone: 'live', locked: !isLive.value },
])
const initial = computed(() => (auth.user?.email?.[0] ?? '?').toUpperCase())

const now = ref(new Date())
const market = computed(() => marketStatus(now.value))
const clock = computed(() => `${istClock(now.value)} IST`)
let timer

const menuOpen = ref(false)
const menuRoot = ref(null)
const onDocClick = (e) => { if (menuRoot.value && !menuRoot.value.contains(e.target)) menuOpen.value = false }

onMounted(async () => {
  timer = setInterval(() => { now.value = new Date() }, 30_000)
  document.addEventListener('click', onDocClick)
  try { if (!auth.user) await auth.loadMe() } catch { /* 401 handled globally */ }
  system.load()
  marketsApi.holidays().then((days) => days.forEach((d) => nseHolidays.add(d))).catch(() => {})
  marketStore.connect() // keeps the feed status (and its alert banner) live on every page
})
onBeforeUnmount(() => { clearInterval(timer); document.removeEventListener('click', onDocClick); marketStore.disconnect() })

function logout() {
  menuOpen.value = false
  auth.logout()
  strategiesStore.reset()
  brokersStore.reset()
  marketStore.reset()
  tradingStore.reset()
  marketsStore.reset()
  router.replace('/login')
}
</script>

<style scoped>
.app { min-height: 100vh; }
.topbar { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--surface) 92%, transparent); backdrop-filter: saturate(1.4) blur(8px); border-bottom: 1px solid var(--border); }
.topbar-inner { display: flex; align-items: center; gap: 20px; height: 60px; padding: 0 24px; max-width: 1320px; margin: 0 auto; }
.brand-link { color: inherit; text-decoration: none; flex: none; }
.brand-link:hover { text-decoration: none; }

.tabs { display: flex; align-self: stretch; gap: 2px; flex: 1; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.tabs::-webkit-scrollbar { display: none; }
.tab { position: relative; display: inline-flex; align-items: center; gap: 7px; padding: 0 12px; color: var(--muted); font-weight: 500; font-size: 0.89rem; text-decoration: none; white-space: nowrap; }
.tab:hover { color: var(--text); text-decoration: none; }
.tab::after { content: ''; position: absolute; left: 10px; right: 10px; bottom: -1px; height: 2px; border-radius: 2px 2px 0 0; background: transparent; }
.tab.active { color: var(--text); font-weight: 600; }
.tab.active::after { background: var(--accent); }
.tab.active :deep(svg) { color: var(--accent-text); }
.tab.live.active::after { background: var(--live); }
.tab.live.active :deep(svg) { color: var(--live); }
.tab-lock { opacity: 0.55; }

.top-right { display: flex; align-items: center; gap: 10px; flex: none; }
.market { display: inline-flex; align-items: center; gap: 7px; font-size: 0.8rem; font-weight: 500; color: var(--muted); white-space: nowrap; }
.market .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.market.open { color: var(--text-2); }
.market.open .dot { background: var(--good); box-shadow: 0 0 0 3px color-mix(in srgb, var(--good) 22%, transparent); }
.clock { padding-left: 7px; border-left: 1px solid var(--border); color: var(--muted); }
.new-btn { padding: 8px 13px; }

.user { position: relative; }
.avatar-btn { display: flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 3px 10px 3px 3px; color: var(--muted); cursor: pointer; }
.avatar-btn:hover { background: var(--surface-2); }
.avatar { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; background: linear-gradient(135deg, #6366f1, #4338ca); color: #fff; font-weight: 600; font-size: 0.82rem; flex: none; }
.avatar.lg { width: 36px; height: 36px; font-size: 0.95rem; }
.mode { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; color: var(--muted); }
.mode.live { color: var(--live); }
.menu { position: absolute; right: 0; top: calc(100% + 8px); min-width: 250px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-lg); padding: 6px; }
.menu-head { display: flex; align-items: center; gap: 10px; padding: 10px; }
.menu-email { font-weight: 600; font-size: 0.9rem; overflow-wrap: anywhere; }
.menu-role { font-size: 0.78rem; color: var(--muted); text-transform: capitalize; }
.menu-sep { height: 1px; background: var(--border); margin: 4px 0; }
.menu-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border-radius: 8px; background: none; border: 0; color: var(--text-2); font: inherit; font-size: 0.9rem; font-weight: 500; cursor: pointer; text-decoration: none; }
.menu-item:hover { background: var(--surface-2); color: var(--text); text-decoration: none; }

.feed-alert { background: var(--bad-soft); color: var(--bad); border-bottom: 1px solid var(--border); }
.feed-alert-inner { max-width: 1320px; margin: 0 auto; padding: 10px 24px; display: flex; align-items: center; gap: 10px; font-size: 0.88rem; flex-wrap: wrap; }
.feed-alert-inner .btn { margin-left: auto; }
.page { max-width: 1320px; margin: 0 auto; padding: 28px 24px 56px; }

/* The header is capped at 1320px, so on wide screens the 7 tabs need the whole row: the market pill
   moves out (each page shows market status). When tabs wrap to their own row, it comes back. */
.tab { padding: 0 9px; }
.top-right .market { display: none; }
@media (max-width: 1500px) {
  .top-right .market { display: inline-flex; }
  .topbar-inner { flex-wrap: wrap; height: auto; padding: 10px 20px 0; row-gap: 6px; }
  .tabs { order: 3; flex-basis: 100%; height: 44px; margin: 0 -8px; }
  .top-right { margin-left: auto; }
}
@media (max-width: 640px) {
  .topbar-inner { padding: 10px 16px 0; }
  .clock, .market, .new-btn span, .mode { display: none; }
  .new-btn { padding: 8px 10px; }
  .page { padding: 20px 16px 40px; }
}
</style>
