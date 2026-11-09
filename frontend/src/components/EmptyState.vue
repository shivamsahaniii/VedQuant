<template>
  <div class="empty">
    <div class="empty-icon"><AppIcon :name="icon" :size="22" /></div>
    <div class="empty-title">{{ title }}</div>
    <p class="empty-text">{{ text }}</p>
    <span v-if="tag" class="tag">{{ tag }}</span>
    <slot />
  </div>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
defineProps({ icon: { type: String, default: 'table' }, title: String, text: String, tag: String })
</script>

<style scoped>
.empty { text-align: center; padding: 32px 16px; display: flex; flex-direction: column; align-items: center; gap: 6px; }
.empty-icon { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
.empty-title { font-weight: 700; margin-top: 6px; }
.empty-text { margin: 0; color: var(--muted); max-width: 420px; font-size: 0.92rem; }
</style>
