import { defineStore } from 'pinia'
import { ref } from 'vue'
import { systemApi } from '../api/client'

export const useSystemStore = defineStore('system', () => {
  const health = ref(null)
  const error = ref(false)

  async function load() {
    try {
      health.value = await systemApi.health()
      error.value = false
    } catch {
      error.value = true
    }
  }

  return { health, error, load }
})
