<template>
  <div class="card">
    <div class="card-head">
      <div class="head-left"><h2>Trade journal</h2><span class="tag">{{ rows.length }}</span></div>
      <span class="muted small">Net of brokerage, STT, exchange, SEBI, stamp duty and GST</span>
    </div>
    <div v-if="rows.length" class="card-body flush">
      <div class="table-wrap">
        <table class="data">
          <thead><tr>
            <th>Closed</th><th>Symbol</th><th>Side</th><th class="num">Qty</th><th class="num">Entry</th>
            <th class="num">Exit</th><th>Why</th><th class="num">Gross</th><th class="num">Charges</th><th class="num">Net</th>
          </tr></thead>
          <tbody>
            <tr v-for="t in rows" :key="t.id">
              <td class="muted">{{ when(t.exit_at) }}</td>
              <td><b>{{ t.symbol }}</b><div class="muted tiny">{{ t.strategy || 'Manual' }}</div></td>
              <td>{{ t.side.toUpperCase() }}</td>
              <td class="num">{{ t.qty }}</td>
              <td class="num">{{ n(t.entry_price) }}</td>
              <td class="num">{{ n(t.exit_price) }}</td>
              <td><span class="tag" :class="REASON_TONE[t.exit_reason]">{{ REASON[t.exit_reason] || t.exit_reason }}</span></td>
              <td class="num" :class="tone(t.gross_pnl)">{{ formatINR(t.gross_pnl) }}</td>
              <td class="num muted">{{ formatINR(t.charges) }}</td>
              <td class="num" :class="tone(t.net_pnl)"><b>{{ formatINR(t.net_pnl) }}</b></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <EmptyState v-else icon="paper" title="No closed trades yet" text="Every closed paper trade is recorded here with its exit reason and net P&L." />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import EmptyState from './EmptyState.vue'
import { useTradingStore } from '../stores/trading'
import { formatINR } from '../utils/format'

const props = defineProps({ section: { type: String, default: '' }, limit: { type: Number, default: 50 } })
const trading = useTradingStore()
const rows = computed(() => trading.closed.filter((t) => !props.section || t.section === props.section).slice(0, props.limit))
const REASON = { target: 'Target', stop: 'Stop loss', square_off: '15:15 square-off', manual: 'Closed by you', kill_switch: 'Kill switch' }
const REASON_TONE = { target: 'good', stop: 'bad', square_off: 'info', manual: '', kill_switch: 'warn' }
const nf = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const n = (v) => (v == null ? '—' : nf.format(Number(v)))
const tone = (v) => (v == null ? '' : Number(v) >= 0 ? 'good-text' : 'bad-text')
const df = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
const when = (iso) => (iso ? df.format(new Date(iso)) : '—')
</script>

<style scoped>
.head-left { display: flex; align-items: center; gap: 8px; }
.small { font-size: 0.8rem; }
.tiny { font-size: 0.75rem; }
.good-text { color: var(--good); }
.bad-text { color: var(--bad); }
</style>
