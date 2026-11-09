<template>
  <div class="cc">
    <div ref="el" class="cc-canvas"></div>
    <div v-if="message" class="cc-msg muted">{{ message }}</div>
  </div>
</template>

<script setup>
// VedQuant charts: TradingView Lightweight Charts (Apache-2.0) fed by our own /market/candles,
// with the user's strategy signals drawn as markers. Times are shown in IST.
import { createChart } from 'lightweight-charts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { marketsApi } from '../api/client'
import { useTradingStore } from '../stores/trading'

const props = defineProps({
  symbol: { type: String, required: true },
  exchange: { type: String, default: 'NSE' },
  timeframe: { type: String, default: '5m' },
})
const el = ref(null)
const message = ref('')
const trading = useTradingStore()
const IST_OFFSET = 19800 // seconds: the chart library shows UTC, we want IST
let chart = null
let candles = null
let volume = null
let timer = null

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
const toTime = (iso) => Math.floor(new Date(iso).getTime() / 1000) + IST_OFFSET

function build() {
  chart = createChart(el.value, {
    autoSize: true,
    layout: { background: { color: 'transparent' }, textColor: css('--muted'), fontFamily: 'Inter, sans-serif' },
    grid: { vertLines: { color: css('--border') }, horzLines: { color: css('--border') } },
    rightPriceScale: { borderColor: css('--border') },
    timeScale: { borderColor: css('--border'), timeVisible: true, secondsVisible: false },
    crosshair: { mode: 0 },
  })
  candles = chart.addCandlestickSeries({
    upColor: css('--good'), downColor: css('--bad'), borderVisible: false,
    wickUpColor: css('--good'), wickDownColor: css('--bad'),
  })
  volume = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '', color: css('--border-strong') })
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
}

async function load(fit = false) {
  try {
    const rows = await marketsApi.candles(props.symbol, props.exchange, props.timeframe, 400)
    if (!rows.length) {
      message.value = 'No candles yet for this symbol. It needs a data source that covers it.'
      candles.setData([]); volume.setData([])
      return
    }
    message.value = ''
    candles.setData(rows.map((r) => ({ time: toTime(r.ts), open: +r.open, high: +r.high, low: +r.low, close: +r.close })))
    const hasVol = rows.some((r) => +r.volume > 0)
    volume.setData(hasVol ? rows.map((r) => ({ time: toTime(r.ts), value: +r.volume, color: +r.close >= +r.open ? css('--good-soft') : css('--bad-soft') })) : [])
    const first = toTime(rows[0].ts)
    candles.setMarkers(
      trading.signals
        .filter((s) => s.symbol === props.symbol && toTime(s.bar_ts) >= first)
        .map((s) => ({
          time: toTime(s.bar_ts),
          position: s.side === 'buy' ? 'belowBar' : 'aboveBar',
          color: s.status === 'taken' ? css('--good') : s.status === 'suggested' ? css('--accent') : css('--muted'),
          shape: s.side === 'buy' ? 'arrowUp' : 'arrowDown',
          text: s.rule.toUpperCase(),
        }))
        .sort((a, b) => a.time - b.time),
    )
    if (fit) chart.timeScale().fitContent()
  } catch {
    message.value = 'Could not load candles.'
  }
}

onMounted(() => { build(); load(true); timer = setInterval(() => load(false), 15000) })
onBeforeUnmount(() => { clearInterval(timer); chart?.remove() })
watch(() => [props.symbol, props.exchange, props.timeframe], () => load(true))
</script>

<style scoped>
.cc { position: relative; height: 100%; min-height: 320px; }
.cc-canvas { position: absolute; inset: 0; }
.cc-msg { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; padding: 24px; font-size: 0.9rem; }
</style>
