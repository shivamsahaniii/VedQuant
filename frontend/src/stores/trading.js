// Signals, paper positions, the trade journal and P&L. Live updates arrive over the market
// WebSocket ("signal" and "trade" messages, only ever this user's own).
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { tradingApi } from '../api/client'

export const SIGNAL_TONE = { taken: 'good', suggested: 'accent', skipped: '', refused: 'warn', blocked: 'bad' }
export const SIGNAL_LABEL = { taken: 'Paper trade taken', suggested: 'Suggested', skipped: 'Skipped', refused: 'Refused', blocked: 'Blocked by risk' }

export const useTradingStore = defineStore('trading', () => {
  const signals = ref([])
  const open = ref([])
  const closed = ref([])
  const summary = ref(null)
  const loaded = ref(false)
  let timer = null

  const openBySection = (section) => open.value.filter((t) => !section || t.section === section)
  const signalsBySection = (section) => signals.value.filter((s) => !section || s.section === section)
  const actionable = computed(() => signals.value.filter((s) => ['taken', 'suggested'].includes(s.status)))

  async function load() {
    const [sig, op, cl, sum] = await Promise.all([
      tradingApi.signals({ limit: 100 }),
      tradingApi.trades({ status: 'open' }),
      tradingApi.trades({ status: 'closed', limit: 100 }),
      tradingApi.summary(),
    ])
    signals.value = sig; open.value = op; closed.value = cl; summary.value = sum
    loaded.value = true
  }

  // Positions' live P&L and the summary refresh every 5 s while a page shows them.
  function startPolling() { if (!timer) timer = setInterval(() => refreshLive().catch(() => {}), 5000) }
  function stopPolling() { clearInterval(timer); timer = null }
  async function refreshLive() {
    const [op, sum] = await Promise.all([tradingApi.trades({ status: 'open' }), tradingApi.summary()])
    open.value = op; summary.value = sum
  }

  function onSignal(sig) {
    if (signals.value.some((s) => s.id === sig.id)) return
    signals.value = [sig, ...signals.value].slice(0, 200)
  }
  function onTradeEvent() { load().catch(() => {}) }

  async function close(id) { await tradingApi.close(id); await load() }
  async function killSwitch() { const r = await tradingApi.killSwitch(); await load(); return r }

  function reset() { stopPolling(); signals.value = []; open.value = []; closed.value = []; summary.value = null; loaded.value = false }

  return { signals, open, closed, summary, loaded, actionable, openBySection, signalsBySection, load, startPolling, stopPolling, refreshLive, onSignal, onTradeEvent, close, killSwitch, reset }
})
