<template>
  <div class="tvw">
    <div v-if="!tvSymbol" class="tvw-msg muted">This symbol is not mapped to TradingView. Use VedQuant charts instead.</div>
    <div v-else-if="indian" class="tvw-msg muted">
      TradingView does not allow NSE/BSE data in its free embedded widget (exchange licensing).<br />
      Switch to <b>VedQuant charts</b> for Indian stocks and indices. The widget works for crypto.
    </div>
    <div v-else :id="id" class="tvw-box"></div>
    <div v-if="error" class="tvw-msg muted">{{ error }}</div>
  </div>
</template>

<script setup>
// TradingView's free chart widget (tv.js). It shows TradingView's own data feed, not the user's broker.
// TODO(verify): widget options against https://www.tradingview.com/widget-docs/ if TradingView changes them.
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps({ tvSymbol: { type: String, default: '' }, interval: { type: String, default: '5' } })
const indian = computed(() => /^(NSE|BSE):/.test(props.tvSymbol))
const id = `tv_${Math.random().toString(36).slice(2, 9)}`
const error = ref('')
let loading = null

function loadScript() {
  if (window.TradingView) return Promise.resolve()
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = 'https://s3.tradingview.com/tv.js'
      s.async = true
      s.onload = resolve
      s.onerror = () => { loading = null; reject(new Error('blocked')) }
      document.head.appendChild(s)
    })
  }
  return loading
}

async function render() {
  if (!props.tvSymbol || indian.value) return
  error.value = ''
  try {
    await loadScript()
    await nextTick()
    const box = document.getElementById(id)
    if (!box) return
    box.innerHTML = ''
    const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
    // eslint-disable-next-line no-new
    new window.TradingView.widget({
      container_id: id, symbol: props.tvSymbol, interval: props.interval, timezone: 'Asia/Kolkata',
      theme: dark ? 'dark' : 'light', style: '1', locale: 'en', autosize: true,
      allow_symbol_change: false, hide_side_toolbar: false, withdateranges: true,
    })
  } catch {
    error.value = 'Could not load TradingView (blocked or offline).'
  }
}

onMounted(render)
watch(() => [props.tvSymbol, props.interval], render)
</script>

<style scoped>
.tvw { position: relative; height: 100%; min-height: 320px; }
.tvw-box { position: absolute; inset: 0; }
.tvw-msg { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; padding: 24px; font-size: 0.9rem; }
</style>
