<template>
  <div>
    <PageHeader icon="signal" title="Markets"
      subtitle="The indices, stocks and crypto you follow. Prices come from the data source you choose for each market.">
      <RouterLink to="/settings" class="btn ghost sm"><AppIcon name="broker" :size="14" /> Connections</RouterLink>
    </PageHeader>

    <div class="asset-tabs" role="tablist">
      <button v-for="a in ASSETS" :key="a.key" role="tab" class="asset-tab" :class="{ active: asset === a.key }"
        :aria-selected="asset === a.key" @click="setAsset(a.key)">
        <AppIcon :name="a.icon" :size="15" /> {{ a.label }} <span class="tag">{{ markets.byAsset(a.key).length }}</span>
      </button>
    </div>

    <div class="source-bar" :class="sourceTone">
      <AppIcon name="broker" :size="15" />
      <span v-if="source">Data for {{ assetLabel }}: <b>{{ source.name }}</b><template v-if="source.key === 'paper'"> (simulated prices)</template></span>
      <span v-else>No data source chosen for {{ assetLabel }}.</span>
      <RouterLink to="/settings" class="link">Change in Settings → Connections</RouterLink>
    </div>

    <div class="grid-2 wide-left">
      <div class="stack">
        <div class="card">
          <div class="card-head">
            <div class="head-left"><h2>{{ assetLabel }}</h2><span class="tag">{{ list.length }}</span></div>
            <button class="btn primary sm" @click="adding = !adding"><AppIcon name="plus" :size="14" /> Add</button>
          </div>

          <form v-if="adding" class="add-row" @submit.prevent="addItem">
            <select v-model="pick" class="inp">
              <option value="">Pick from the list…</option>
              <option v-for="c in suggestions" :key="c.exchange + c.symbol" :value="`${c.exchange}:${c.symbol}`">
                {{ c.symbol }} · {{ c.name }} ({{ c.exchange }})
              </option>
              <option value="__custom">Other symbol…</option>
            </select>
            <template v-if="pick === '__custom'">
              <select v-model="customExchange" class="inp sm"><option v-for="x in exchanges" :key="x">{{ x }}</option></select>
              <input v-model="customSymbol" class="inp" placeholder="Symbol, e.g. TATASTEEL" maxlength="30" />
            </template>
            <button class="btn primary sm" :disabled="busy || !pick">Add</button>
            <button type="button" class="btn ghost sm" @click="adding = false">Cancel</button>
          </form>
          <p v-if="error" class="error inline">{{ error }}</p>

          <div v-if="list.length" class="table-wrap">
            <table class="data">
              <thead><tr><th>Symbol</th><th class="num">LTP</th><th class="num">Change</th><th>Data</th><th></th></tr></thead>
              <tbody>
                <tr v-for="i in list" :key="i.id" class="row" :class="{ sel: selected?.id === i.id }" @click="selected = i">
                  <td><b>{{ i.symbol }}</b><div class="muted tiny">{{ i.name }} · {{ i.exchange }}</div></td>
                  <td class="num">{{ ltp(i) }}</td>
                  <td class="num" :class="tone(i)">{{ chg(i) }}</td>
                  <td><span class="tag" :class="DATA_TONE[i.data.state]" :title="i.data.hint || ''">{{ i.data.label }}</span></td>
                  <td class="num"><button class="btn ghost sm" title="Remove from your list" @click.stop="remove(i)"><AppIcon name="x" :size="13" /></button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <EmptyState v-else :icon="ASSETS.find((a) => a.key === asset).icon" :title="`No ${assetLabel.toLowerCase()} yet`"
            text="Add the instruments you want to follow." />
        </div>
      </div>

      <aside class="stack">
        <div class="card chart-card">
          <div class="card-head">
            <div class="head-left">
              <h2>{{ selected ? selected.symbol : 'Chart' }}</h2>
              <span v-if="selected" class="muted small">{{ selected.name }}</span>
            </div>
            <div class="chart-tools">
              <select v-model="timeframe" class="inp sm" title="Candle size">
                <option v-for="t in TIMEFRAMES" :key="t" :value="t">{{ t }}</option>
              </select>
              <select :value="chartProvider" class="inp sm" title="Chart provider" @change="setChart($event.target.value)">
                <option v-for="c in chartProviders" :key="c.key" :value="c.key" :disabled="c.status !== 'available'">
                  {{ c.name }}{{ c.status !== 'available' ? ' (soon)' : '' }}
                </option>
              </select>
            </div>
          </div>
          <div class="chart-body">
            <div v-if="!selected" class="muted chart-empty">Pick an instrument to see its chart.</div>
            <CandleChart v-else-if="chartProvider === 'vedquant_charts'" :key="selected.id" :symbol="selected.symbol"
              :exchange="selected.exchange" :timeframe="timeframe" />
            <TradingViewWidget v-else :key="selected.id + timeframe" :tv-symbol="selected.tv || ''" :interval="TV_INTERVAL[timeframe]" />
          </div>
          <div class="chart-foot muted tiny">
            <template v-if="chartProvider === 'vedquant_charts'">VedQuant charts · candles from your data source · arrows = your strategies' signals · IST</template>
            <template v-else>TradingView widget · TradingView's own data (may be delayed for Indian exchanges)</template>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import CandleChart from '../components/CandleChart.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import TradingViewWidget from '../components/TradingViewWidget.vue'
import { errorMessage, marketsApi } from '../api/client'
import { useMarketStore } from '../stores/market'
import { ASSETS, useMarketsStore } from '../stores/markets'
import { useTradingStore } from '../stores/trading'

const markets = useMarketsStore()
const live = useMarketStore()
const trading = useTradingStore()
const TIMEFRAMES = ['1m', '5m', '15m', '1h']
const TV_INTERVAL = { '1m': '1', '5m': '5', '15m': '15', '1h': '60' }
const DATA_TONE = { live: 'good', waiting: '', pending: 'info', unsupported: 'warn', no_source: 'warn' }

const asset = ref(localStorage.getItem('vq.markets.asset') || 'indices')
const selected = ref(null)
const timeframe = ref('5m')
const adding = ref(false)
const pick = ref('')
const customSymbol = ref('')
const customExchange = ref('')
const catalog = ref({ items: [], exchanges: {} })
const busy = ref(false)
const error = ref('')

const assetLabel = computed(() => ASSETS.find((a) => a.key === asset.value).label)
const list = computed(() => markets.byAsset(asset.value))
const source = computed(() => markets.connectorByKey[markets.preferences.data_sources?.[asset.value]] || null)
const sourceTone = computed(() => (!source.value ? 'warn' : source.value.key === 'paper' ? 'sim' : 'ok'))
const chartProvider = computed(() => markets.preferences.chart_provider || 'vedquant_charts')
const chartProviders = computed(() => markets.connectors.filter((c) => c.category === 'charts'))
const exchanges = computed(() => catalog.value.exchanges[asset.value] || [])
const suggestions = computed(() => catalog.value.items.filter((c) => c.asset_class === asset.value && !c.followed))

// Live price: from the shared quote stream when available, else the snapshot from the API.
const quote = (i) => live.quotes[`${i.exchange}:${i.symbol}`] || i.quote
const nf = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const ltp = (i) => (i.data.state === 'live' && quote(i) ? nf.format(Number(quote(i).ltp)) : '—')
const chg = (i) => {
  const q = i.data.state === 'live' ? quote(i) : null
  return q ? `${Number(q.change) > 0 ? '+' : ''}${nf.format(Number(q.change))} (${Number(q.change_pct).toFixed(2)}%)` : '—'
}
const tone = (i) => { const q = i.data.state === 'live' ? quote(i) : null; return !q ? '' : Number(q.change) >= 0 ? 'up' : 'down' }

function setAsset(a) {
  asset.value = a
  try { localStorage.setItem('vq.markets.asset', a) } catch { /* private mode */ }
}
watch(asset, () => { adding.value = false; pick.value = ''; selected.value = list.value[0] || null; customExchange.value = exchanges.value[0] || '' })
watch(list, (l) => { if (!selected.value || !l.some((i) => i.id === selected.value.id)) selected.value = l[0] || null })

async function loadCatalog() { catalog.value = await marketsApi.catalog() }

onMounted(async () => {
  live.connect()
  try {
    await Promise.all([markets.loadWatchlist(), markets.loadConnectors(), loadCatalog(), trading.loaded ? null : trading.load()])
    customExchange.value = exchanges.value[0] || ''
    selected.value = list.value[0] || null
  } catch (e) { error.value = errorMessage(e) }
})
onBeforeUnmount(() => live.disconnect())

async function addItem() {
  busy.value = true; error.value = ''
  try {
    if (pick.value === '__custom') {
      await markets.add({ asset_class: asset.value, exchange: customExchange.value, symbol: customSymbol.value })
    } else {
      const [exchange, symbol] = pick.value.split(':')
      await markets.add({ asset_class: asset.value, exchange, symbol })
    }
    await loadCatalog()
    pick.value = ''; customSymbol.value = ''; adding.value = false
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}

async function remove(i) {
  error.value = ''
  try { await markets.remove(i.id); await loadCatalog() } catch (e) { error.value = errorMessage(e) }
}

async function setChart(key) {
  error.value = ''
  try { await markets.savePreferences({ chart_provider: key }) } catch (e) { error.value = errorMessage(e) }
}
</script>

<style scoped>
.asset-tabs { display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }
.asset-tab { display: inline-flex; align-items: center; gap: 8px; font: inherit; font-weight: 600; font-size: 0.9rem; padding: 8px 14px; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--surface); color: var(--text-2); cursor: pointer; }
.asset-tab.active { border-color: var(--accent); color: var(--accent-text); background: var(--accent-soft); }
.source-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 14px; border-radius: var(--radius-sm); margin-bottom: 16px; font-size: 0.88rem; background: var(--surface-3); color: var(--text-2); }
.source-bar.warn { background: var(--warn-soft); color: var(--warn); }
.source-bar.ok { background: var(--good-soft); color: var(--good); }
.source-bar .link { margin-left: auto; font-weight: 600; }
.wide-left { grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr); }
.head-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.add-row { display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 18px; border-bottom: 1px solid var(--border); background: var(--surface-2); }
.inp { font: inherit; font-size: 0.86rem; padding: 7px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); min-width: 0; flex: 1 1 180px; }
.inp.sm { flex: 0 0 auto; padding: 5px 8px; font-size: 0.8rem; }
.row { cursor: pointer; }
.row.sel td { background: var(--accent-soft); }
.tiny { font-size: 0.75rem; }
.small { font-size: 0.82rem; }
.up { color: var(--good); }
.down { color: var(--bad); }
.chart-card { position: sticky; top: 88px; }
.chart-card .card-head { flex-wrap: wrap; row-gap: 8px; }
.chart-tools { display: flex; gap: 6px; min-width: 0; max-width: 100%; }
.chart-tools .inp.sm { max-width: 190px; min-width: 0; }
.chart-body { height: 460px; position: relative; }
.chart-empty { display: grid; place-items: center; height: 100%; }
.chart-foot { padding: 8px 18px 12px; border-top: 1px solid var(--border); }
.error.inline { margin: 10px 18px; }
@media (max-width: 1100px) { .wide-left { grid-template-columns: 1fr; } .chart-card { position: static; } .chart-body { height: 380px; } }
</style>
