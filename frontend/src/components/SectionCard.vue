<template>
  <RouterLink :to="to" class="section-card" :class="tone">
    <div class="sc-top">
      <div class="sc-icon"><AppIcon :name="icon" :size="18" /></div>
      <span class="tag" :class="tagTone">{{ tag }}</span>
    </div>
    <div class="sc-title">{{ title }}</div>
    <p class="sc-text">{{ text }}</p>
    <span class="sc-link">Open {{ title }} <span aria-hidden="true">→</span></span>
  </RouterLink>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
defineProps({ to: String, icon: String, title: String, text: String, tag: String, tagTone: String, tone: { type: String, default: '' } })
</script>

<style scoped>
.section-card { display: flex; flex-direction: column; gap: 6px; padding: 18px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); text-decoration: none; font-weight: 400; box-shadow: var(--shadow); transition: border-color 0.15s, box-shadow 0.15s; }
.section-card:hover { text-decoration: none; border-color: var(--border-strong); box-shadow: var(--shadow-lg); }
.sc-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.sc-icon { width: 36px; height: 36px; border-radius: 9px; display: grid; place-items: center; background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border); }
.live .sc-icon { background: var(--live-soft); color: var(--live); border-color: transparent; }
.sc-title { font-weight: 600; font-size: 1rem; }
.sc-text { margin: 0; color: var(--muted); font-size: 0.87rem; flex: 1; }
.sc-link { font-weight: 600; color: var(--accent-text); font-size: 0.85rem; margin-top: 6px; }
.live .sc-link { color: var(--live); }
</style>
