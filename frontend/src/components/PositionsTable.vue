<template>
  <div class="card">
    <div class="card-head">
      <div class="head-left"><h2>Open positions</h2><span class="tag">{{ rows.length }}</span></div>
      <span class="muted small">Live P&amp;L · stop and target watched every tick</span>
    </div>
    <div v-if="rows.length" class="card-body flush">
      <div class="table-wrap">
        <table class="data">
          <thead><tr>
            <th>Symbol</th><th>Side</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">LTP</th>
            <th class="num">Stop</th><th class="num">Target</th><th class="num">P&amp;L</th><th></th>
          </tr></thead>
          <tbody>
            <tr v-for="t in rows" :key="t.id">
              <td><b>{{ t.symbol }}</b><div class="muted tiny">{{ t.strategy || 'Manual' }}</div></td>
              <td><span class="tag" :class="t.side === 'buy' ? 'good' : 'bad'">{{ t.side.toUpperCase() }}</span></td>
              <td class="num">{{ t.qty }}</td>
              <td class="num">{{ n(t.entry_price) }}</td>
              <td class="num">{{ n(t.ltp) }}</td>
              <td class="num bad-text">{{ n(t.stop) }}</td>
              <td class="num good-text">{{ n(t.target) }}</td>
              <td class="num" :class="tone(t.unrealised)"><b>{{ formatINR(t.unrealised) }}</b></td>
              <td class="num">
                <button class="btn ghost sm" :disabled="busy === t.id" @click="close(t)">
                  {{ confirmId === t.id ? 'Confirm close' : 'Close' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <EmptyState v-else icon="table" title="No open positions"
      text="When a strategy in Auto paper mode takes a trade, it appears here with live P&L, its stop loss and target." />
    <p v-if="error" class="error inline">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import EmptyState from './EmptyState.vue'
import { errorMessage } from '../api/client'
import { useTradingStore } from '../stores/trading'
import { formatINR } from '../utils/format'

const props = defineProps({ section: { type: String, default: '' } })
const trading = useTradingStore()
const rows = computed(() => trading.openBySection(props.section))
const busy = ref(null)
const confirmId = ref(null)
const error = ref('')
let confirmTimer = null

const nf = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const n = (v) => (v == null ? '—' : nf.format(Number(v)))
const tone = (v) => (v == null ? '' : Number(v) >= 0 ? 'good-text' : 'bad-text')

async function close(t) {
  if (confirmId.value !== t.id) {
    confirmId.value = t.id
    clearTimeout(confirmTimer)
    confirmTimer = setTimeout(() => { confirmId.value = null }, 6000)
    return
  }
  busy.value = t.id; error.value = ''
  try { await trading.close(t.id) } catch (e) { error.value = errorMessage(e) } finally { busy.value = null; confirmId.value = null }
}
</script>

<style scoped>
.head-left { display: flex; align-items: center; gap: 8px; }
.small { font-size: 0.8rem; }
.tiny { font-size: 0.75rem; }
.good-text { color: var(--good); }
.bad-text { color: var(--bad); }
.error.inline { margin: 0 18px 14px; }
</style>
