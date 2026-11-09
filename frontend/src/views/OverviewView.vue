<template>
  <div>
    <PageHeader icon="overview" :title="`Hello, ${firstName}`"
      eyebrow="Overview" subtitle="Everything at a glance. You are in paper mode, so no real money is used.">
      <RouterLink to="/settings" class="btn ghost"><AppIcon name="broker" :size="16" /> Connect broker</RouterLink>
      <button class="btn primary" @click="ui.openNewStrategy()"><AppIcon name="plus" :size="16" /> New strategy</button>
    </PageHeader>

    <section class="stats">
      <StatTile label="Today's P&L (net)" :value="formatINR(todayNet)" :tone="todayNet > 0 ? 'good' : todayNet < 0 ? 'bad' : 'muted'"
        :hint="trading.summary?.trades_today ? `${trading.summary.trades_today} paper trades today` : 'No trades yet today'" icon="rupee" />
      <StatTile label="Open positions" :value="String(trading.summary?.open_positions ?? 0)" hint="Across all sections" icon="layers" />
      <StatTile label="Strategies" :value="strategies.count" :hint="strategies.count ? `${inSections} added to a section` : 'Create one in Algo Trading'" icon="algo" />
      <StatTile label="Brokers connected" :value="brokers.connectedCount" :hint="brokers.accounts.length ? `${brokers.accounts.length} added` : 'Add Dhan in Settings'" icon="broker" />
    </section>

    <MarketMoodCard class="mood-gap" />

    <div class="grid-2">
      <section class="grid-3 sections">
        <SectionCard to="/algo" icon="algo" title="Algo Trading" tag="Scanner running" tag-tone="accent"
          text="Strategies, backtests on past data, and the market scanner that finds trades for you." />
        <SectionCard to="/intraday" icon="intraday" title="Intraday" tag="Paper trading" tag-tone="accent"
          text="Same-day trades with strict limits. Auto square-off at 3:15 PM." />
        <SectionCard to="/swing" icon="swing" title="Swing" tag="Phase 5"
          text="Hold positions for days, on daily candles, with a trailing stop loss." />
        <SectionCard to="/paper" icon="paper" title="Paper Trading" tag="Available" tag-tone="accent"
          text="Practise every strategy with virtual money before risking real money." />
        <SectionCard to="/live" icon="live" title="Live Trading" tag="Locked" tag-tone="live" tone="live"
          text="Real orders through your broker. Unlocks after backtest + paper trading." />
      </section>

      <aside class="stack">
        <RouterLink to="/paper" class="card nifty">
          <div class="card-head"><h2>NIFTY 50</h2><FeedBadge /></div>
          <div class="card-body nifty-body" v-if="market.index">
            <div class="nifty-ltp tabular">{{ Number(market.index.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 }) }}</div>
            <div class="tabular" :class="Number(market.index.change) >= 0 ? 'up' : 'down'">
              {{ Number(market.index.change) >= 0 ? '+' : '' }}{{ Number(market.index.change).toFixed(2) }}
              ({{ Number(market.index.change_pct) >= 0 ? '+' : '' }}{{ market.index.change_pct }}%)
            </div>
            <Sparkline :values="[...(market.history['NSE:NIFTY50'] ?? []), Number(market.index.ltp)]" :w="260" :h="40" />
          </div>
          <div class="card-body muted" v-else>Waiting for prices…</div>
        </RouterLink>
        <div class="card">
          <div class="card-head"><h2>Account</h2><span class="tag" :class="mode === 'live' ? 'live' : 'accent'">{{ mode }}</span></div>
          <div class="card-body">
            <dl class="kv" v-if="auth.user">
              <dt>Email</dt><dd>{{ auth.user.email }}</dd>
              <dt>Role</dt><dd class="cap">{{ auth.user.role }}</dd>
              <dt>Member since</dt><dd>{{ joined }}</dd>
            </dl>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2>System</h2></div>
          <div class="card-body">
            <dl class="kv">
              <dt>API</dt>
              <dd><span class="tag" :class="system.health ? 'good' : system.error ? 'live' : ''">{{ system.health ? 'Online' : system.error ? 'Offline' : 'Checking…' }}</span></dd>
              <dt>Platform mode</dt><dd class="cap">{{ system.health?.trading_mode ?? '—' }}</dd>
              <dt>Market</dt><dd>{{ marketState.label }}</dd>
            </dl>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import FeedBadge from '../components/FeedBadge.vue'
import { computed, onBeforeUnmount, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import MarketMoodCard from '../components/MarketMoodCard.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import Sparkline from '../components/Sparkline.vue'
import StatTile from '../components/StatTile.vue'
import { useAuthStore } from '../stores/auth'
import { useBrokersStore } from '../stores/brokers'
import { useMarketStore } from '../stores/market'
import { useStrategiesStore } from '../stores/strategies'
import { useTradingStore } from '../stores/trading'
import { useSystemStore } from '../stores/system'
import { useUiStore } from '../stores/ui'
import { formatINR, marketStatus } from '../utils/format'

const auth = useAuthStore()
const system = useSystemStore()
const ui = useUiStore()
const strategies = useStrategiesStore()
const inSections = computed(() => strategies.items.filter((s) => s.section).length)
const brokers = useBrokersStore()
const market = useMarketStore()
const trading = useTradingStore()
const todayNet = computed(() => Number(trading.summary?.realised_today || 0) + Number(trading.summary?.unrealised || 0))
onMounted(() => { strategies.load().catch(() => {}); brokers.load().catch(() => {}); trading.load().catch(() => {}); market.connect() })
onBeforeUnmount(() => market.disconnect())
const marketState = computed(() => marketStatus())
const mode = computed(() => auth.user?.trading_mode ?? 'paper')
const firstName = computed(() => {
  const name = (auth.user?.email?.split('@')[0] ?? '').split(/[._-]/)[0]
  return name ? name[0].toUpperCase() + name.slice(1) : 'there'
})
const joined = computed(() =>
  auth.user ? new Date(auth.user.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }) : '',
)
</script>

<style scoped>
.sections { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.cap { text-transform: capitalize; }
.mood-gap { margin-bottom: 20px; }
.nifty { display: block; color: inherit; text-decoration: none; font-weight: 400; }
.nifty:hover { text-decoration: none; border-color: var(--border-strong); }
.nifty-body { display: flex; flex-direction: column; gap: 4px; }
.nifty-ltp { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }
.up { color: var(--good); font-weight: 600; }
.down { color: var(--bad); font-weight: 600; }
</style>
