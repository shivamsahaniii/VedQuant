<template>
  <div class="stat">
    <div class="stat-top">
      <span class="stat-label">{{ label }}</span>
      <span v-if="icon" class="stat-icon"><AppIcon :name="icon" :size="15" /></span>
    </div>
    <div class="stat-value" :class="tone">{{ value }}</div>
    <div v-if="hint" class="stat-hint">{{ hint }}</div>
  </div>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
defineProps({ label: String, value: [String, Number], hint: String, icon: String, tone: { type: String, default: '' } })
</script>

<style scoped>
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 18px; min-width: 0; box-shadow: var(--shadow); }
.stat-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.stat-label { font-size: 0.82rem; color: var(--muted); font-weight: 500; }
.stat-icon { width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; background: var(--surface-3); color: var(--muted); }
.stat-value { font-size: 1.55rem; font-weight: 700; margin-top: 8px; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.stat-value.good { color: var(--good); }
.stat-value.bad { color: var(--bad); }
.stat-value.muted { color: var(--text-2); }
.stat-hint { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }
</style>
