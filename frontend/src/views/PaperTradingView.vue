<template>
  <div>
    <PageHeader icon="paper" title="Paper Trading"
      subtitle="The agents trade your strategies with virtual money, with the same rules, risk checks and charges as the real market.">
      <span class="tag accent">Virtual money only</span>
      <button class="btn danger sm" :disabled="killing" @click="kill">
        <AppIcon name="power" :size="14" /> {{ confirmKill ? 'Confirm: close all & pause' : 'Kill switch' }}
      </button>
    </PageHeader>

    <section class="stats">
      <StatTile label="Today's P&L (net)" :value="formatINR(todayNet)" :tone="tone(todayNet)"
        :hint="`Realised ${formatINR(sum?.realised_today)} · open ${formatINR(sum?.unrealised)}`" icon="rupee" />
      <StatTile label="Open positions" :value="String(sum?.open_positions ?? 0)" hint="Stop + target on every one" icon="layers" />
      <StatTile label="Trades today" :value="String(sum?.trades_today ?? 0)" :hint="`Charges today ${formatINR(sum?.charges_today)}`" icon="signal" />
      <StatTile label="Win rate" :value="sum?.win_rate != null ? `${sum.win_rate}%` : '—'" tone=""
        :hint="`${sum?.closed_trades ?? 0} closed · total ${formatINR(sum?.realised_total)}`" icon="check" />
    </section>
    <p v-if="note" class="note" :class="noteTone">{{ note }}</p>

    <div class="grid-2">
      <div class="stack">
        <PositionsTable />
        <LivePriceTable />
        <SignalsFeed />
        <TradeJournal />
      </div>

      <aside class="stack">
        <MarketMoodCard compact />
        <div class="card">
          <div class="card-head"><h2>By strategy</h2></div>
          <ul v-if="sum?.per_strategy?.length" class="list">
            <li v-for="r in sum.per_strategy" :key="r.strategy">
              <div class="li-main"><div class="li-title">{{ r.strategy }}</div>
                <div class="li-sub">{{ r.trades }} trades · {{ r.win_rate }}% wins</div></div>
              <b :class="tone(r.net) + '-text'">{{ formatINR(r.net) }}</b>
            </li>
          </ul>
          <div v-else class="card-body muted small">Results per strategy appear after the first closed trade.</div>
        </div>
        <div class="card">
          <div class="card-head"><h2>How the agents trade</h2></div>
          <ol class="steps small">
            <li><b>Scanner</b> finds a setup on a <i>closed</i> candle.</li>
            <li><b>Entry timer</b> checks it is fresh, in the 09:30–14:30 window, has not run away, and suits the market mood.</li>
            <li><b>Exit planner</b> sets stop and target on the NSE tick and refuses targets that can't pay charges.</li>
            <li><b>Odds</b> replays the rest of the day thousands of times from the stock's own history.</li>
            <li><b>Risk</b> sizes it (1% risk per trade) and checks daily loss, trade count and open positions.</li>
            <li><b>Paper broker</b> fills with slippage; stop and target cancel each other; 15:15 square-off.</li>
          </ol>
        </div>
        <div class="card">
          <div class="card-head"><h2>About the prices</h2><FeedBadge /></div>
          <div class="card-body muted small">
            <template v-if="realFeed">
              Real market prices from your own {{ feedName }} account. Trades are paper only: virtual money, no
              orders are sent to the broker. New trades happen between 09:30 and 14:30 IST on trading days.
              <p v-if="market.feed?.message" class="feed-msg">{{ market.feed.message }}</p>
            </template>
            <template v-else>
              Prices are simulated. To paper-trade on real prices, connect your broker's data key in
              <RouterLink to="/settings">Settings → Connections</RouterLink> and choose it for Stocks and Indices.
            </template>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import FeedBadge from '../components/FeedBadge.vue'
import LivePriceTable from '../components/LivePriceTable.vue'
import MarketMoodCard from '../components/MarketMoodCard.vue'
import PageHeader from '../components/PageHeader.vue'
import PositionsTable from '../components/PositionsTable.vue'
import SignalsFeed from '../components/SignalsFeed.vue'
import StatTile from '../components/StatTile.vue'
import TradeJournal from '../components/TradeJournal.vue'
import { errorMessage } from '../api/client'
import { useMarketStore } from '../stores/market'
import { useTradingStore } from '../stores/trading'
import { formatINR } from '../utils/format'

const trading = useTradingStore()
const market = useMarketStore()
const realFeed = computed(() => market.feed && !['simulator', 'other'].includes(market.feed.source))
const feedName = computed(() => ({ dhan: 'Dhan' })[market.feed?.source] || market.feed?.source)
const sum = computed(() => trading.summary)
const todayNet = computed(() => (sum.value ? Number(sum.value.realised_today) + Number(sum.value.unrealised) : 0))
const tone = (v) => (v == null || Number(v) === 0 ? 'muted' : Number(v) > 0 ? 'good' : 'bad')
const note = ref('')
const noteTone = ref('')
const killing = ref(false)
const confirmKill = ref(false)
let t = null

onMounted(() => { trading.load().catch((e) => { note.value = errorMessage(e); noteTone.value = 'error' }); trading.startPolling() })
onBeforeUnmount(() => trading.stopPolling())

async function kill() {
  if (!confirmKill.value) { confirmKill.value = true; clearTimeout(t); t = setTimeout(() => { confirmKill.value = false }, 6000); return }
  killing.value = true
  try {
    const r = await trading.killSwitch()
    note.value = `Kill switch: closed ${r.closed} position(s), paused ${r.paused} strateg${r.paused === 1 ? 'y' : 'ies'}.`
    noteTone.value = 'warn'
  } catch (e) { note.value = errorMessage(e); noteTone.value = 'error' } finally { killing.value = false; confirmKill.value = false }
}
</script>

<style scoped>
.small { font-size: 0.88rem; }
.note { margin: 0 0 16px; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--surface-3); font-size: 0.9rem; }
.note.warn { background: var(--warn-soft); color: var(--warn); }
.note.error { background: var(--bad-soft); color: var(--bad); }
.feed-msg { margin: 8px 0 0; color: var(--text-2); }
.steps { margin: 0; padding: 14px 18px 14px 34px; display: flex; flex-direction: column; gap: 8px; color: var(--text-2); }
.good-text { color: var(--good); }
.bad-text { color: var(--bad); }
.muted-text { color: var(--text-2); }
</style>
