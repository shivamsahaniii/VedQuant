// Markets lists (indices / stocks / crypto) and the user's connection choices.
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { connectorsApi, marketsApi } from '../api/client'

export const ASSETS = [
  { key: 'indices', label: 'Indices', icon: 'signal' },
  { key: 'stocks', label: 'Stocks', icon: 'swing' },
  { key: 'crypto', label: 'Crypto', icon: 'layers' },
]

export const useMarketsStore = defineStore('markets', () => {
  const items = ref([])
  const connectors = ref([])
  const preferences = ref({ chart_provider: 'vedquant_charts', data_sources: {} })
  const loaded = ref(false)

  const byAsset = (asset) => items.value.filter((i) => i.asset_class === asset)
  const connectorByKey = computed(() => Object.fromEntries(connectors.value.map((c) => [c.key, c])))

  async function loadWatchlist() {
    const r = await marketsApi.watchlist()
    items.value = r.items
    preferences.value = r.preferences
    loaded.value = true
  }
  async function loadConnectors() {
    const r = await connectorsApi.list()
    connectors.value = r.connectors
    preferences.value = r.preferences
  }
  async function add(item) { await marketsApi.add(item); await loadWatchlist() }
  async function remove(id) { await marketsApi.remove(id); items.value = items.value.filter((i) => i.id !== id) }
  async function savePreferences(prefs) {
    preferences.value = await connectorsApi.savePreferences(prefs)
    await loadConnectors()
    if (loaded.value) await loadWatchlist()
  }
  async function request(key) { await connectorsApi.request(key); await loadConnectors() }
  function reset() { items.value = []; connectors.value = []; loaded.value = false }

  return { items, connectors, preferences, loaded, byAsset, connectorByKey, loadWatchlist, loadConnectors, add, remove, savePreferences, request, reset }
})
