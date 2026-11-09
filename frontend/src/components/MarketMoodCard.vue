<template>
  <div class="card mood" :class="{ compact }">
    <div class="card-head">
      <div class="head-left">
        <h2>Market mood</h2>
        <FeedBadge />
      </div>
      <span v-if="ctx" class="muted small">
        <template v-if="!compact">{{ ctx.timeframe }} candles · </template>{{ relativeTime(ctx.as_of) }}
      </span>
    </div>

    <div v-if="!ctx" class="card-body muted">Reading the market… (needs the first NIFTY candle)</div>

    <template v-else>
      <div class="mood-top">
        <div class="bias" :class="ctx.bias">
          <AppIcon :name="ctx.bias === 'bearish' ? 'down' : ctx.bias === 'bullish' ? 'swing' : 'minus'" :size="20" />
          <div>
            <div class="bias-label">{{ BIAS[ctx.bias] }}</div>
            <div class="bias-sub">{{ BIAS_HINT[ctx.bias] }}</div>
          </div>
        </div>
        <div class="chips">
          <div class="chip"><span>Trend</span><b :class="ctx.trend">{{ TREND[ctx.trend] }}</b></div>
          <div class="chip"><span>Strength</span><b class="cap">{{ ctx.strength }}</b></div>
          <div class="chip"><span>Volatility</span><b class="cap">{{ ctx.volatility }}</b></div>
          <div class="chip"><span>Breadth</span><b>{{ ctx.breadth.up }}↑ {{ ctx.breadth.down }}↓</b></div>
          <div class="chip"><span>Session</span><b class="cap">{{ ctx.phase }}</b></div>
        </div>
      </div>

      <p v-if="ctx.warming_up || ctx.timeframe === '1m'" class="warm">
        <AppIcon name="clock" :size="14" />
        <template v-if="compact">Warming up: reading the last ~30 min.</template>
        <template v-else>Warming up: reading 1-minute candles (last ~30 min). Switches to 5-minute candles after 20 of them.</template>
      </p>

      <div v-if="!compact" class="mood-body">
        <div class="why">
          <div class="why-title">Why</div>
          <ul>
            <li v-for="r in ctx.reasons" :key="r">{{ r }}</li>
          </ul>
        </div>
        <dl class="kv nums">
          <dt>NIFTY</dt><dd>{{ n(ctx.index.ltp) }} <span :class="Number(ctx.index.change_pct) >= 0 ? 'up' : 'down'">({{ signed(ctx.index.change_pct) }}%)</span></dd>
          <dt>EMA 20</dt><dd>{{ n(ctx.index.ema20) }}</dd>
          <dt>VWAP</dt><dd>{{ n(ctx.index.vwap) }}</dd>
          <dt>ADX</dt><dd>{{ ctx.index.adx ?? '—' }}</dd>
          <dt>ATR</dt><dd>{{ ctx.index.atr_pct != null ? `${ctx.index.atr_pct}%` : '—' }}</dd>
        </dl>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import AppIcon from './AppIcon.vue'
import FeedBadge from './FeedBadge.vue'
import { useMarketStore } from '../stores/market'
import { relativeTime } from '../utils/format'

defineProps({ compact: Boolean })
const market = useMarketStore()
const ctx = computed(() => market.context)
onMounted(() => market.connect())
onBeforeUnmount(() => market.disconnect())

const BIAS = { bullish: 'Bullish', bearish: 'Bearish', neutral: 'Neutral' }
const BIAS_HINT = {
  bullish: 'Buy-side rules allowed',
  bearish: 'Avoid fresh buys',
  neutral: 'Wait for a clearer move',
}
const TREND = { up: 'Up', down: 'Down', sideways: 'Sideways' }
const nf = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const n = (v) => (v == null ? '—' : nf.format(v))
const signed = (v) => `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(2)}`
</script>

<style scoped>
.head-left { display: flex; align-items: center; gap: 8px; }
.small { font-size: 0.8rem; }
.mood-top { display: flex; gap: 16px; padding: 16px 18px; align-items: stretch; flex-wrap: wrap; }
.bias { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: var(--radius); min-width: 210px; background: var(--surface-3); color: var(--text-2); }
.bias.bullish { background: var(--good-soft); color: var(--good); }
.bias.bearish { background: var(--bad-soft); color: var(--bad); }
.bias-label { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.01em; }
.bias-sub { font-size: 0.8rem; color: var(--text-2); }
.chips { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; flex: 1; min-width: 280px; }
.chip { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; background: var(--surface-2); }
.chip span { font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; }
.chip b { font-size: 0.92rem; }
.chip b.up { color: var(--good); }
.chip b.down { color: var(--bad); }
.cap { text-transform: capitalize; }
.warm { display: flex; align-items: center; gap: 8px; margin: 0 18px 14px; padding: 8px 12px; border-radius: var(--radius-sm); background: var(--warn-soft); color: var(--warn); font-size: 0.84rem; }
.mood-body { display: grid; grid-template-columns: 1.6fr 1fr; gap: 18px; padding: 0 18px 16px; }
.why-title { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 6px; }
.why ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; font-size: 0.88rem; color: var(--text-2); }
.nums { font-size: 0.86rem; align-content: start; }
.up { color: var(--good); }
.down { color: var(--bad); }
.compact .mood-top { flex-direction: column; gap: 10px; }
.compact .bias { min-width: 0; }
.compact .chips { grid-template-columns: repeat(3, minmax(0, 1fr)); min-width: 0; }
.compact .chip { padding: 7px 9px; }
@media (max-width: 760px) {
  .chips { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .mood-body { grid-template-columns: 1fr; }
}
</style>
