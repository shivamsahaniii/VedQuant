<template>
  <Teleport to="body">
    <div v-if="open" class="overlay" @mousedown.self="!locked && $emit('close')">
      <div class="dialog" :style="{ maxWidth: width }" role="dialog" aria-modal="true" :aria-label="title"
        @keydown.esc="!locked && $emit('close')">
        <header class="d-head">
          <div>
            <div v-if="eyebrow" class="eyebrow">{{ eyebrow }}</div>
            <h2>{{ title }}</h2>
          </div>
          <button class="icon-btn" aria-label="Close" :disabled="locked" @click="$emit('close')"><AppIcon name="x" :size="18" /></button>
        </header>
        <div class="d-body"><slot /></div>
        <footer v-if="$slots.footer" class="d-foot"><slot name="footer" /></footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import AppIcon from './AppIcon.vue'
defineProps({ open: Boolean, title: String, eyebrow: String, width: { type: String, default: '640px' }, locked: Boolean })
defineEmits(['close'])
</script>

<style scoped>
.overlay { position: fixed; inset: 0; z-index: 100; background: rgba(9, 12, 20, 0.55); backdrop-filter: blur(2px); display: grid; place-items: center; padding: 16px; }
.dialog { width: 100%; max-height: calc(100vh - 32px); display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow-lg); }
.d-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 18px 22px 14px; border-bottom: 1px solid var(--border); }
.eyebrow { font-size: 0.75rem; font-weight: 600; color: var(--accent-text); text-transform: uppercase; letter-spacing: 0.05em; }
.d-head h2 { margin: 2px 0 0; font-size: 1.15rem; }
.icon-btn { border: 0; background: none; color: var(--muted); padding: 6px; border-radius: 8px; cursor: pointer; }
.icon-btn:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.d-body { padding: 18px 22px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
.d-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 22px; border-top: 1px solid var(--border); background: var(--surface-2); border-radius: 0 0 14px 14px; flex-wrap: wrap; }
</style>
