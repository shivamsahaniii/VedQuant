<template>
  <div>
    <PageHeader icon="intraday" title="Intraday"
      subtitle="Same-day trades. Everything is squared off automatically before the market closes.">
      <span class="tag" :class="market.open ? 'good' : ''">{{ market.label }} · {{ market.detail }}</span>
    </PageHeader>

    <section class="stats">
      <StatTile label="Paper capital" :value="formatINR(100000)" hint="Default per section" icon="wallet" />
      <StatTile label="Today's P&L (net)" :value="formatINR(todayNet)" :tone="todayNet > 0 ? 'good' : todayNet < 0 ? 'bad' : 'muted'"
        hint="Realised + open, after charges" icon="rupee" />
      <StatTile label="Trades today" :value="`${trading.summary?.trades_today ?? 0} / 5`" hint="Max 5 per day" icon="signal" />
      <StatTile label="Auto square-off" value="3:15 PM" hint="IST, every trading day" icon="clock" />
    </section>

    <div class="grid-2">
      <div class="stack">
        <SectionStrategies section="intraday" />
        <PositionsTable section="intraday" />
        <SignalsFeed section="intraday" />
      </div>

      <aside class="stack">
        <MarketMoodCard compact />
        <div class="card">
          <div class="card-head"><h2>Risk limits</h2><AppIcon name="shield" :size="18" class="muted" /></div>
          <div class="card-body">
            <dl class="kv">
              <dt>Risk per trade</dt><dd>1% of capital</dd>
              <dt>Max daily loss</dt><dd>{{ formatINR(3000) }}</dd>
              <dt>Max open positions</dt><dd>3</dd>
              <dt>Max trades / day</dt><dd>5</dd>
              <dt>Max position size</dt><dd>33% of capital (3 positions fit)</dd>
              <dt>Stop loss</dt><dd>Required on every trade</dd>
              <dt>Charges</dt><dd>Target must pay them 2× over</dd>
            </dl>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Today's schedule</h2><span class="tag">IST</span></div>
          <ul class="list timeline">
            <li v-for="s in schedule" :key="s.time">
              <span class="time">{{ s.time }}</span>
              <div class="li-main"><div class="li-title">{{ s.title }}</div><div class="li-sub">{{ s.sub }}</div></div>
            </li>
          </ul>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import MarketMoodCard from '../components/MarketMoodCard.vue'
import PageHeader from '../components/PageHeader.vue'
import PositionsTable from '../components/PositionsTable.vue'
import SectionStrategies from '../components/SectionStrategies.vue'
import SignalsFeed from '../components/SignalsFeed.vue'
import StatTile from '../components/StatTile.vue'
import { useTradingStore } from '../stores/trading'
import { formatINR, marketStatus } from '../utils/format'

const trading = useTradingStore()
const todayNet = computed(() => {
  const intra = trading.openBySection('intraday').reduce((a, t) => a + Number(t.unrealised || 0), 0)
  return Number(trading.summary?.realised_today || 0) + intra
})
onMounted(() => { trading.load().catch(() => {}); trading.startPolling() })
onBeforeUnmount(() => trading.stopPolling())

const market = computed(() => marketStatus())
const schedule = [
  { time: '09:15', title: 'Market opens', sub: 'Opening range forms (09:15–09:30)' },
  { time: '09:30', title: 'Entries allowed', sub: 'Agents may open new trades' },
  { time: '14:30', title: 'No new entries', sub: 'Default entry window ends' },
  { time: '15:15', title: 'Auto square-off', sub: 'All intraday positions closed' },
  { time: '15:30', title: 'Market closes', sub: 'Daily P&L is final' },
]
</script>

<style scoped>
.timeline .time { font-family: ui-monospace, monospace; font-weight: 700; color: var(--accent); width: 48px; flex: none; }
</style>
