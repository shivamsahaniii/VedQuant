import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { strategiesApi } from '../api/client'

// Strategies that can be moved between sections or deleted (not running).
export const MOVABLE = ['draft', 'paused']

export const useStrategiesStore = defineStore('strategies', () => {
  const items = ref([])
  const loaded = ref(false)
  const loading = ref(false)

  const bySection = (section) => items.value.filter((s) => s.section === section)
  const count = computed(() => items.value.length)

  async function load(force = false) {
    if (loaded.value && !force) return
    loading.value = true
    try {
      items.value = await strategiesApi.list()
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  function upsert(s) {
    const i = items.value.findIndex((x) => x.id === s.id)
    if (i === -1) items.value.unshift(s)
    else items.value[i] = s
  }

  async function create(payload) {
    const s = await strategiesApi.create(payload)
    upsert(s)
    return s
  }

  async function setSection(id, section) {
    upsert(await strategiesApi.update(id, { section }))
  }

  async function setStatus(id, status) {
    upsert(await strategiesApi.setStatus(id, status))
  }

  async function setParams(id, changes) {
    const s = items.value.find((x) => x.id === id)
    upsert(await strategiesApi.update(id, { params: { ...(s?.params || {}), ...changes } }))
  }

  async function remove(id) {
    await strategiesApi.remove(id)
    items.value = items.value.filter((s) => s.id !== id)
  }

  function reset() {
    items.value = []
    loaded.value = false
  }

  return { items, loaded, loading, count, bySection, load, create, setSection, setStatus, setParams, remove, reset }
})
