import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { brokersApi } from '../api/client'

export const useBrokersStore = defineStore('brokers', () => {
  const accounts = ref([])
  const available = ref([])
  const loaded = ref(false)
  const loading = ref(false)

  const connectedCount = computed(() => accounts.value.filter((a) => a.status === 'connected').length)
  // A real (non-paper) broker whose trading keys are saved and tested OK.
  const hasLiveTradingKey = computed(() =>
    accounts.value.some((a) => !a.is_paper && a.status === 'connected' && a.credentials.trading.complete),
  )

  async function load(force = false) {
    if (loaded.value && !force) return
    loading.value = true
    try {
      const [accs, avail] = await Promise.all([brokersApi.list(), brokersApi.available()])
      accounts.value = accs
      available.value = avail
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  function upsert(a) {
    const i = accounts.value.findIndex((x) => x.id === a.id)
    if (i === -1) accounts.value.push(a)
    else accounts.value[i] = a
    return a
  }

  const add = async (broker, label) => upsert(await brokersApi.add(broker, label))
  const saveKeys = async (id, purpose, fields) => upsert(await brokersApi.saveKeys(id, purpose, fields))
  const removeKeys = async (id, purpose) => upsert(await brokersApi.removeKeys(id, purpose))

  async function test(id) {
    const result = await brokersApi.test(id)
    upsert(result.account)
    return result
  }

  async function disconnect(id) {
    await brokersApi.disconnect(id)
    accounts.value = accounts.value.filter((a) => a.id !== id)
  }

  function reset() {
    accounts.value = []
    loaded.value = false
  }

  return { accounts, available, loaded, loading, connectedCount, hasLiveTradingKey, load, add, saveKeys, removeKeys, test, disconnect, reset }
})
