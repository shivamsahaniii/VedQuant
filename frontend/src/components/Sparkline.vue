<template>
  <svg class="spark" :viewBox="`0 0 ${w} ${h}`" :width="w" :height="h" aria-hidden="true">
    <polyline v-if="points" :points="points" fill="none" :class="trend" stroke-width="1.5"
      stroke-linejoin="round" stroke-linecap="round" />
    <line v-else :x1="0" :x2="w" :y1="h / 2" :y2="h / 2" class="flat" stroke-dasharray="2 3" />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ values: { type: Array, default: () => [] }, w: { type: Number, default: 96 }, h: { type: Number, default: 28 } })

const points = computed(() => {
  const v = props.values.filter((x) => Number.isFinite(x))
  if (v.length < 2) return null
  const min = Math.min(...v)
  const max = Math.max(...v)
  const span = max - min || 1
  return v.map((x, i) => `${((i / (v.length - 1)) * props.w).toFixed(1)},${(props.h - 2 - ((x - min) / span) * (props.h - 4)).toFixed(1)}`).join(' ')
})
const trend = computed(() => {
  const v = props.values
  if (v.length < 2) return 'flat'
  return v[v.length - 1] >= v[0] ? 'up' : 'down'
})
</script>

<style scoped>
.spark { display: block; overflow: visible; }
.up { stroke: var(--good); }
.down { stroke: var(--bad); }
.flat { stroke: var(--border-strong); }
</style>
