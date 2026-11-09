<template>
  <span class="tag" :class="info.tone" :title="info.title">{{ info.label }}</span>
</template>

<script setup>
// Where prices come from right now: simulated, or the user's real broker feed (and its state).
import { computed } from 'vue'
import { useMarketStore } from '../stores/market'

const market = useMarketStore()
const NAMES = { dhan: 'Dhan' }
const info = computed(() => {
  const f = market.feed
  if (!f || f.source === 'simulator') return { label: 'Simulated data', tone: 'warn', title: f?.message || 'Prices come from the market simulator' }
  if (f.source === 'other') return { label: 'No data source', tone: 'warn', title: f.message }
  const name = NAMES[f.source] || f.source
  const by = {
    live: { label: `Live · ${name}`, tone: 'good' },
    connecting: { label: `${name} · connecting`, tone: 'info' },
    closed: { label: `${name} · market closed`, tone: '' },
    error: { label: `${name} · not connected`, tone: 'bad' },
  }
  return { ...(by[f.state] || { label: name, tone: '' }), title: f.message }
})
</script>
