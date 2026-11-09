<template>
  <Teleport to="body">
    <div v-if="open" class="overlay" @mousedown.self="$emit('close')">
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="as-title" @keydown.esc="$emit('close')">
        <header class="d-head">
          <div>
            <div class="eyebrow">{{ label }}</div>
            <h2 id="as-title">Add strategies to {{ label }}</h2>
          </div>
          <button class="icon-btn" aria-label="Close" @click="$emit('close')"><AppIcon name="x" :size="18" /></button>
        </header>

        <div class="d-body">
          <div v-if="!candidates.length" class="none">
            <AppIcon name="layers" :size="22" />
            <div class="none-title">No other strategies to add</div>
            <p>All your strategies are already in {{ label }}, or you have not created any yet.</p>
          </div>

          <ul v-else class="pick-list">
            <li v-for="s in candidates" :key="s.id">
              <label class="pick" :class="{ disabled: !movable(s), checked: picked.has(s.id) }">
                <input type="checkbox" :disabled="!movable(s)" :checked="picked.has(s.id)" @change="toggle(s.id)" />
                <div class="pick-main">
                  <div class="pick-name">{{ s.name }}</div>
                  <div class="pick-sub">{{ strategySummary(s) }}</div>
                  <div v-if="!movable(s)" class="pick-warn">Running in {{ SECTION_LABEL[s.section] }} ({{ s.status }}). Pause it to move.</div>
                </div>
                <span class="tag" :class="s.section ? '' : 'accent'">{{ s.section ? `In ${SECTION_LABEL[s.section]}` : 'Not in a section' }}</span>
              </label>
            </li>
          </ul>
          <p v-if="error" class="error" role="alert">{{ error }}</p>
        </div>

        <footer class="d-foot">
          <button class="btn ghost" @click="createNew"><AppIcon name="plus" :size="16" /> Create new instead</button>
          <div class="foot-btns">
            <button class="btn ghost" @click="$emit('close')">Cancel</button>
            <button class="btn primary" :disabled="!picked.size || busy" @click="add">
              {{ busy ? 'Adding…' : picked.size ? `Add ${picked.size} to ${label}` : 'Add to ' + label }}
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { errorMessage } from '../api/client'
import { MOVABLE, useStrategiesStore } from '../stores/strategies'
import { useUiStore } from '../stores/ui'
import { SECTION_LABEL, strategySummary } from '../utils/strategies'

const props = defineProps({ open: Boolean, section: { type: String, required: true } })
const emit = defineEmits(['close'])

const strategies = useStrategiesStore()
const ui = useUiStore()
const label = computed(() => SECTION_LABEL[props.section])
const picked = ref(new Set())
const busy = ref(false)
const error = ref('')

// Unassigned first, then those in other sections.
const candidates = computed(() =>
  strategies.items
    .filter((s) => s.section !== props.section)
    .sort((a, b) => (a.section === null ? -1 : 0) - (b.section === null ? -1 : 0)),
)
const movable = (s) => s.section === null || MOVABLE.includes(s.status)

watch(() => props.open, (o) => { if (o) { picked.value = new Set(); error.value = '' } })

function toggle(id) {
  const next = new Set(picked.value)
  next.has(id) ? next.delete(id) : next.add(id)
  picked.value = next
}

async function add() {
  busy.value = true
  error.value = ''
  try {
    for (const id of picked.value) await strategies.setSection(id, props.section)
    emit('close')
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

function createNew() {
  emit('close')
  ui.openNewStrategy({ section: props.section })
}
</script>

<style scoped>
.overlay { position: fixed; inset: 0; z-index: 100; background: rgba(9, 12, 20, 0.55); backdrop-filter: blur(2px); display: grid; place-items: center; padding: 16px; }
.dialog { width: 100%; max-width: 620px; max-height: calc(100vh - 32px); display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow-lg); }
.d-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 18px 22px 14px; border-bottom: 1px solid var(--border); }
.eyebrow { font-size: 0.75rem; font-weight: 600; color: var(--accent-text); text-transform: uppercase; letter-spacing: 0.05em; }
.d-head h2 { margin: 2px 0 0; font-size: 1.15rem; }
.icon-btn { border: 0; background: none; color: var(--muted); padding: 6px; border-radius: 8px; cursor: pointer; }
.icon-btn:hover { background: var(--surface-2); color: var(--text); }
.d-body { padding: 16px 22px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.d-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 22px; border-top: 1px solid var(--border); background: var(--surface-2); border-radius: 0 0 14px 14px; flex-wrap: wrap; }
.foot-btns { display: flex; gap: 8px; margin-left: auto; }

.pick-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.pick { flex-direction: row; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius); cursor: pointer; font-weight: 400; color: var(--text); transition: border-color 0.15s; }
.pick:hover { border-color: var(--border-strong); }
.pick.checked { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 5%, var(--surface)); }
.pick.disabled { cursor: not-allowed; opacity: 0.65; }
.pick input { width: 17px; height: 17px; accent-color: var(--accent); box-shadow: none; flex: none; }
.pick-main { flex: 1; min-width: 0; }
.pick-name { font-weight: 600; }
.pick-sub { font-size: 0.83rem; color: var(--muted); }
.pick-warn { font-size: 0.8rem; color: var(--warn); margin-top: 2px; }
.none { text-align: center; padding: 24px 8px; color: var(--muted); display: flex; flex-direction: column; align-items: center; gap: 6px; }
.none-title { font-weight: 600; color: var(--text); }
.none p { margin: 0; font-size: 0.9rem; }
</style>
