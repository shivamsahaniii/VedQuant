<template>
  <div class="card lpt">
    <div class="card-head">
      <div class="head-left">
        <h2>Live prices</h2>
        <FeedBadge />
      </div>
      <span class="feed" :class="market.status">
        <span class="dot"></span>{{ statusText }}
      </span>
    </div>

    <div v-if="market.index" class="index-strip">
      <div>
        <div class="ix-name">NIFTY 50</div>
        <div class="ix-sub">Index{{ market.feed && market.feed.source !== 'simulator' ? '' : ' · simulated' }}</div>
      </div>
      <div class="ix-ltp tabular">{{ fmt(market.index.ltp) }}</div>
      <div class="ix-chg tabular" :class="tone(market.index.change)">
        {{ signed(market.index.change) }} ({{ signed(market.index.change_pct) }}%)
      </div>
      <div class="ix-spark"><Sparkline :values="spark('NSE:NIFTY50', market.index.ltp)" :w="140" :h="32" /></div>
    </div>

    <div class="table-wrap" v-if="market.stocks.length">
      <table class="data">
        <thead>
          <tr>
            <th>Symbol</th><th class="num">LTP</th><th class="num">Change</th><th class="num hide-sm">Day high</th>
            <th class="num hide-sm">Day low</th><th class="num hide-md">Volume</th><th class="hide-sm">Last hour</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="q in market.stocks" :key="q.symbol">
            <td><span class="sym">{{ q.symbol }}</span></td>
            <td class="num ltp" :class="flash(q)" :key="q.ltp">{{ fmt(q.ltp) }}</td>
            <td class="num" :class="tone(q.change)">{{ signed(q.change) }} <span class="pct">({{ signed(q.change_pct) }}%)</span></td>
            <td class="num hide-sm">{{ fmt(q.high) }}</td>
            <td class="num hide-sm">{{ fmt(q.low) }}</td>
            <td class="num hide-md">{{ vol(q.volume) }}</td>
            <td class="hide-sm"><Sparkline :values="spark(`${q.exchange}:${q.symbol}`, q.ltp)" /></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="card-body muted">
      {{ market.status === 'offline' ? 'Cannot reach the live feed. Retrying…' : 'Waiting for the first prices…' }}
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import Sparkline from './Sparkline.vue'
import FeedBadge from './FeedBadge.vue'
import { useMarketStore } from '../stores/market'

const market = useMarketStore()
onMounted(() => market.connect())
onBeforeUnmount(() => market.disconnect())

const nf = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmt = (v) => (v === undefined || v === null ? '—' : nf.format(Number(v)))
const signed = (v) => { const n = Number(v); return `${n > 0 ? '+' : ''}${nf.format(n)}` }
const tone = (v) => (Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : '')
const vol = (v) => new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(v ?? 0)

function flash(q) {
  const p = market.prev[`${q.exchange}:${q.symbol}`]
  if (p === undefined || p === q.ltp) return ''
  return Number(q.ltp) > Number(p) ? 'flash-up' : 'flash-down'
}
function spark(key, ltp) {
  return [...(market.history[key] ?? []), Number(ltp)]
}

const statusText = computed(() => ({ live: 'Live', connecting: 'Connecting…', offline: 'Reconnecting…', idle: 'Paused' })[market.status])
</script>

<style scoped>
.head-left { display: flex; align-items: center; gap: 8px; }
.feed { display: inline-flex; align-items: center; gap: 6px; font-size: 0.8rem; font-weight: 600; color: var(--muted); }
.feed .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.feed.live { color: var(--good); }
.feed.live .dot { background: var(--good); animation: pulse 1.6s infinite; }
.feed.offline { color: var(--warn); }
.feed.offline .dot { background: var(--warn); }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 50%, transparent); } 50% { box-shadow: 0 0 0 4px transparent; } }

/* The card adapts to its own width (main column or narrow sidebar), not the screen's. */
.lpt { container-type: inline-size; min-width: 0; }
.index-strip { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; align-items: center; gap: 20px; padding: 14px 18px; border-bottom: 1px solid var(--border); background: var(--surface-2); }
.ix-spark { min-width: 0; overflow: hidden; }
.ix-name { font-weight: 700; }
.ix-sub { font-size: 0.78rem; color: var(--muted); }
.ix-ltp { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.01em; }
.ix-chg { font-weight: 600; }

.sym { font-weight: 600; }
.ltp { font-weight: 600; border-radius: 4px; }
.pct { font-size: 0.85em; }
.up { color: var(--good); }
.down { color: var(--bad); }
.flash-up { animation: fu 0.9s ease-out; }
.flash-down { animation: fd 0.9s ease-out; }
@keyframes fu { from { background: color-mix(in srgb, var(--good) 28%, transparent); } to { background: transparent; } }
@keyframes fd { from { background: color-mix(in srgb, var(--bad) 28%, transparent); } to { background: transparent; } }
table.data td { padding-top: 9px; padding-bottom: 9px; }
@container (max-width: 760px) { .hide-md { display: none; } }
@container (max-width: 560px) {
  .hide-sm { display: none; }
  .index-strip { grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; }
  .ix-chg { grid-column: 2; text-align: right; }
  .ix-spark { display: none; }
}
</style>
