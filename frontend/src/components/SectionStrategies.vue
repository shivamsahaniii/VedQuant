<template>
  <div class="card">
    <div class="card-head">
      <div class="head-left">
        <h2>Strategies in {{ label }}</h2>
        <span class="tag">{{ list.length }}</span>
      </div>
      <div class="head-actions">
        <button class="btn ghost sm" @click="ui.openNewStrategy({ section })"><AppIcon name="plus" :size="14" /> New</button>
        <button class="btn primary sm" @click="adding = true"><AppIcon name="layers" :size="14" /> Add strategy</button>
      </div>
    </div>

    <div v-if="strategies.loading && !strategies.loaded" class="loading">Loading strategies…</div>

    <ul v-else-if="list.length" class="list">
      <li v-for="s in list" :key="s.id">
        <div class="s-icon"><AppIcon :name="section === 'swing' ? 'swing' : 'intraday'" :size="16" /></div>
        <div class="li-main">
          <div class="li-title">{{ s.name }}</div>
          <div class="li-sub">{{ strategySummary(s) }} · Stop {{ STOP_LABEL[s.params?.stop_rule || 'auto'] }} · Target {{ s.params?.target_r || 2 }}R · Risk {{ s.params?.risk_per_trade_pct || 1 }}%/trade</div>
        </div>
        <select class="mode" :value="s.params?.mode || 'suggest'" :disabled="busyId === s.id"
          title="Suggest only: signals are shown, you decide. Auto paper: approved signals become paper trades."
          @change="setMode(s, $event.target.value)">
          <option value="suggest">Suggest only</option>
          <option value="auto">Auto paper trade</option>
        </select>
        <span class="tag cap" :class="STATUS_TONE[s.status]">{{ s.status === 'paper' ? 'running · paper' : s.status }}</span>
        <button v-if="s.status === 'paper'" class="btn ghost sm" :disabled="busyId === s.id" @click="setStatus(s, 'paused')">
          <AppIcon name="power" :size="14" /> Pause
        </button>
        <button v-else class="btn primary sm" :disabled="busyId === s.id || !runnable(s)"
          :title="runnable(s) ? 'The agents start watching every closed candle for this strategy' : 'Swing (daily candle) strategies run in a later phase'"
          @click="setStatus(s, 'paper')">
          <AppIcon name="flask" :size="14" /> Start paper
        </button>
        <button class="btn ghost sm" :disabled="!MOVABLE.includes(s.status) || busyId === s.id"
          :title="MOVABLE.includes(s.status) ? 'Remove from this section (keeps it in My strategies)' : 'Pause it first'"
          @click="removeFromSection(s)">
          Remove
        </button>
      </li>
    </ul>

    <EmptyState v-else icon="layers" :title="`No strategies in ${label} yet`"
      :text="`Add one of your strategies, or create a new one for ${label}.`">
      <div class="empty-actions">
        <button class="btn primary" @click="adding = true"><AppIcon name="layers" :size="16" /> Add strategy</button>
        <button class="btn ghost" @click="ui.openNewStrategy({ section })"><AppIcon name="plus" :size="16" /> Create new</button>
      </div>
    </EmptyState>

    <p v-if="error" class="error inline">{{ error }}</p>
    <AddStrategyDialog :open="adding" :section="section" @close="adding = false" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import AddStrategyDialog from './AddStrategyDialog.vue'
import AppIcon from './AppIcon.vue'
import EmptyState from './EmptyState.vue'
import { errorMessage } from '../api/client'
import { MOVABLE, useStrategiesStore } from '../stores/strategies'
import { useUiStore } from '../stores/ui'
import { SECTION_LABEL, STATUS_TONE, strategySummary } from '../utils/strategies'

const props = defineProps({ section: { type: String, required: true } })
const strategies = useStrategiesStore()
const ui = useUiStore()
const label = computed(() => SECTION_LABEL[props.section])
const list = computed(() => strategies.bySection(props.section))
const adding = ref(false)
const busyId = ref(null)
const error = ref('')

onMounted(() => strategies.load().catch((e) => { error.value = errorMessage(e) }))

const STOP_LABEL = { auto: 'auto', or_mid: 'range mid', or_far: 'range far side', level: 'at level', atr: 'ATR', pct: '%' }
// The engine runs intraday timeframes now; daily (swing) candles come in a later phase.
const runnable = (s) => (s.params?.timeframe || '5m') !== '1d'

async function act(s, fn) {
  busyId.value = s.id
  error.value = ''
  try { await fn() } catch (e) { error.value = errorMessage(e) } finally { busyId.value = null }
}
const setStatus = (s, status) => act(s, () => strategies.setStatus(s.id, status))
const setMode = (s, mode) => act(s, () => strategies.setParams(s.id, { mode }))

async function removeFromSection(s) {
  busyId.value = s.id
  error.value = ''
  try {
    await strategies.setSection(s.id, null)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busyId.value = null
  }
}
</script>

<style scoped>
.head-left { display: flex; align-items: center; gap: 8px; }
.head-actions { display: flex; gap: 6px; }
.s-icon { width: 32px; height: 32px; border-radius: 8px; display: grid; place-items: center; background: var(--accent-soft); color: var(--accent-text); flex: none; }
.cap { text-transform: capitalize; }
.mode { font: inherit; font-size: 0.8rem; padding: 5px 8px; border-radius: var(--radius-sm); border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); }
.loading { padding: 24px 18px; color: var(--muted); font-size: 0.9rem; }
.empty-actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; justify-content: center; }
.error.inline { margin: 0 18px 14px; }
</style>
