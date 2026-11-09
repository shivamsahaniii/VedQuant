import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const newStrategyOpen = ref(false)
  const newStrategyTemplate = ref(null)
  const newStrategySection = ref(undefined) // undefined = use the template's suggestion

  // openNewStrategy({ template: 'orb', section: 'swing' }) — both optional.
  function openNewStrategy(opts = {}) {
    newStrategyTemplate.value = opts.template ?? null
    newStrategySection.value = opts.section
    newStrategyOpen.value = true
  }
  function closeNewStrategy() {
    newStrategyOpen.value = false
  }

  return { newStrategyOpen, newStrategyTemplate, newStrategySection, openNewStrategy, closeNewStrategy }
})
