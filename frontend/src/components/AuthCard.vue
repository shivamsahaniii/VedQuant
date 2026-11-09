<template>
  <main class="auth-page">
    <section class="auth-card">
      <BrandMark />
      <h1>{{ title }}</h1>
      <p class="sub">{{ subtitle }}</p>
      <slot />
    </section>
    <p class="foot">Rule-based algo trading · Paper mode by default</p>
  </main>
</template>

<script setup>
import BrandMark from './BrandMark.vue'
defineProps({ title: String, subtitle: String })
</script>

<style scoped>
.auth-page {
  min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 24px 16px;
}
.auth-card {
  width: 100%; max-width: 400px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; padding: 32px 28px; box-shadow: var(--shadow);
}
h1 { margin: 24px 0 4px; font-size: 1.5rem; }
.sub { margin: 0 0 24px; color: var(--muted); }
.foot { margin-top: 20px; color: var(--muted); font-size: 0.85rem; }
</style>
