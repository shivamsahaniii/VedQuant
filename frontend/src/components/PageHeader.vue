<template>
  <header class="page-header">
    <div class="ph-text">
      <div class="ph-eyebrow" :class="tone"><AppIcon :name="icon" :size="14" /> {{ eyebrow || title }}</div>
      <h1>{{ title }}</h1>
      <p>{{ subtitle }}</p>
    </div>
    <div class="ph-actions"><slot /></div>
  </header>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
defineProps({ title: String, subtitle: String, icon: String, eyebrow: String, tone: { type: String, default: 'accent' } })
</script>

<style scoped>
.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
.ph-text { min-width: 220px; flex: 1; }
.ph-eyebrow { display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-text); }
.ph-eyebrow.live { color: var(--live); }
h1 { margin: 4px 0 0; font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }
p { margin: 4px 0 0; color: var(--muted); }
.ph-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
</style>
