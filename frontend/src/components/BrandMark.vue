<template>
  <div class="brand">
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="vq-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#6366f1" />
          <stop offset="1" stop-color="#4338ca" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#vq-grad)" />
      <path d="M7 10l5.5 13L18 13l3 5 4-8" fill="none" stroke="#fff" stroke-width="2.6"
        stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <span>VedQuant</span>
  </div>
</template>

<style scoped>
.brand { display: flex; align-items: center; gap: 9px; font-weight: 700; font-size: 1.12rem; letter-spacing: -0.02em; }
svg { width: 28px; height: 28px; }
</style>
