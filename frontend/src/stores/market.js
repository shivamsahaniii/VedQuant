// Live market quotes over one shared WebSocket (/api/ws/quotes).
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import api, { tokenStore } from '../api/client'
import { useTradingStore } from './trading'

export const INDEX_SYMBOLS = ['NIFTY50']

export const useMarketStore = defineStore('market', () => {
  const quotes = ref({}) // "NSE:SBIN" -> quote
  const prev = ref({}) // previous ltp, for up/down flash
  const status = ref('idle') // idle | connecting | live | offline
  const lastUpdate = ref(null)
  const context = ref(null) // market mood from the engine
  const feed = ref(null) // where prices come from: { source, state, message, ... }
  const history = ref({}) // "NSE:SBIN" -> [close, ...] last ~60 one-minute closes

  let ws = null
  let users = 0
  let retry = 0
  let retryTimer = null
  let historyTimer = null

  const list = computed(() =>
    Object.values(quotes.value).sort((a, b) =>
      (INDEX_SYMBOLS.includes(b.symbol) - INDEX_SYMBOLS.includes(a.symbol)) || a.symbol.localeCompare(b.symbol)),
  )
  const index = computed(() => quotes.value['NSE:NIFTY50'] ?? null)
  const stocks = computed(() => list.value.filter((q) => !INDEX_SYMBOLS.includes(q.symbol)))

  function apply(q) {
    const key = `${q.exchange}:${q.symbol}`
    const old = quotes.value[key]
    if (old) prev.value[key] = old.ltp
    quotes.value[key] = q
    lastUpdate.value = q.ts
  }

  function open() {
    const token = tokenStore.get()
    if (!token) return
    status.value = 'connecting'
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/ws/quotes`)
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }))
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'snapshot') { quotes.value = {}; msg.quotes.forEach(apply); context.value = msg.context || null; feed.value = msg.feed || null; status.value = 'live'; retry = 0 }
      else if (msg.type === 'quote') { apply(msg.quote); status.value = 'live' }
      else if (msg.type === 'context') { context.value = msg.context }
      else if (msg.type === 'feed') { const was = feed.value?.source; feed.value = msg.feed; if (was && was !== msg.feed.source) { quotes.value = {}; history.value = {} } }
      else if (msg.type === 'signal') { useTradingStore().onSignal(msg.signal) }
      else if (msg.type === 'trade') { useTradingStore().onTradeEvent(msg.trade) }
    }
    ws.onclose = () => {
      ws = null
      if (users <= 0) { status.value = 'idle'; return }
      status.value = 'offline'
      const delay = Math.min(15000, 1000 * 2 ** retry++)
      retryTimer = setTimeout(open, delay)
    }
  }

  async function loadHistory() {
    const syms = list.value // index + stocks
    await Promise.all(
      syms.map(async (q) => {
        try {
          const rows = (await api.get('/market/candles', { params: { symbol: q.symbol, exchange: q.exchange, timeframe: '1m', limit: 60 } })).data
          history.value[`${q.exchange}:${q.symbol}`] = rows.map((r) => Number(r.close))
        } catch { /* sparkline is optional */ }
      }),
    )
  }

  // Components call connect() on mount and disconnect() on unmount (ref-counted).
  function connect() {
    users++
    if (!ws && !retryTimer) open()
    if (!historyTimer) {
      setTimeout(loadHistory, 1500)
      historyTimer = setInterval(loadHistory, 60_000)
    }
  }
  function disconnect() {
    users = Math.max(0, users - 1)
    if (users > 0) return
    clearTimeout(retryTimer); retryTimer = null
    clearInterval(historyTimer); historyTimer = null
    if (ws) ws.close()
  }
  function reset() {
    users = 0
    disconnect()
    quotes.value = {}; prev.value = {}; history.value = {}; context.value = null; feed.value = null; status.value = 'idle'
  }

  return { quotes, prev, status, lastUpdate, context, feed, history, list, index, stocks, connect, disconnect, reset }
})
