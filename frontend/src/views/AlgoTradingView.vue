<template>
  <div>
    <PageHeader icon="algo" title="Algo Trading"
      subtitle="Build strategies, test them on past data, and let the scanner find trades for you.">
      <button class="btn ghost" disabled title="Phase 2"><AppIcon name="flask" :size="16" /> Run backtest</button>
      <button class="btn primary" @click="ui.openNewStrategy()"><AppIcon name="plus" :size="16" /> New strategy</button>
    </PageHeader>

    <section class="stats">
      <StatTile label="Strategies" :value="strategies.count" :hint="`${inSections} in a section`" icon="layers" />
      <StatTile label="Running now" :value="running" hint="Paper or live" icon="algo" />
      <StatTile label="Signals today" :value="String(signalsToday.length)" :hint="`${signalsToday.filter((s) => ['taken', 'suggested'].includes(s.status)).length} taken or suggested`" icon="signal" />
      <StatTile label="Backtests" value="0" hint="Runs on past data" icon="flask" />
    </section>

    <div class="grid-2">
      <div class="stack">
        <div class="card">
          <div class="card-head"><h2>My strategies</h2><span class="tag">{{ strategies.count }}</span></div>
          <div v-if="strategies.items.length" class="card-body flush">
            <div class="table-wrap">
              <table class="data">
                <thead><tr><th>Strategy</th><th>Section</th><th>Status</th><th class="num">Version</th><th></th></tr></thead>
                <tbody>
                  <tr v-for="s in strategies.items" :key="s.id">
                    <td>
                      <div class="s-name">{{ s.name }}</div>
                      <div class="s-sub">{{ strategySummary(s) }}</div>
                    </td>
                    <td>
                      <select class="section-select" :value="s.section ?? ''" :disabled="!MOVABLE.includes(s.status) || busyId === s.id"
                        :aria-label="`Section for ${s.name}`" @change="move(s, $event.target.value || null)">
                        <option v-for="sec in ACTIVE_SECTIONS" :key="sec" :value="sec">{{ SECTION_LABEL[sec] }}</option>
                        <option value="">Not in a section</option>
                      </select>
                    </td>
                    <td><span class="tag cap" :class="STATUS_TONE[s.status]">{{ s.status }}</span></td>
                    <td class="num">v{{ s.version }}</td>
                    <td class="num">
                      <button class="btn sm" :class="confirmId === s.id ? 'danger' : 'ghost'"
                        :disabled="!MOVABLE.includes(s.status) || busyId === s.id"
                        @click="remove(s)">{{ confirmId === s.id ? 'Confirm delete' : 'Delete' }}</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="error" class="error inline">{{ error }}</p>
          </div>
          <div v-else class="card-body flush">
            <EmptyState icon="layers" title="No strategies yet"
              text="Start from a proven template, adjust the settings, and backtest it before paper trading.">
              <button class="btn primary" @click="ui.openNewStrategy()"><AppIcon name="plus" :size="16" /> Create your first strategy</button>
            </EmptyState>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h2>Templates</h2><span class="sub">Ready-made strategies you can copy and edit</span></div>
          <ul class="list">
            <li v-for="t in TEMPLATES" :key="t.key">
              <div class="tpl-icon"><AppIcon :name="t.section === 'swing' ? 'swing' : 'intraday'" :size="16" /></div>
              <div class="li-main">
                <div class="li-title">{{ t.name }}</div>
                <div class="li-sub">{{ t.idea }}</div>
              </div>
              <span class="tag hide-sm">{{ SECTION_LABEL[t.section] }}</span>
              <span class="tag hide-sm">{{ t.timeframe }}</span>
              <button class="btn ghost sm" @click="ui.openNewStrategy({ template: t.key })">Use</button>
            </li>
          </ul>
        </div>
      </div>

      <aside class="stack">
        <MarketMoodCard compact />
        <div class="card">
          <div class="card-head"><h2>Scanner</h2><span class="tag good">Running</span></div>
          <div class="card-body">
            <dl class="kv spaced">
              <dt>Runs on</dt><dd>Every closed candle</dd>
              <dt>Symbols</dt><dd>Each strategy's own list (or all followed)</dd>
              <dt>Mode</dt><dd>Per strategy: Suggest only / Auto paper</dd>
              <dt>Strategies running</dt><dd>{{ running }}</dd>
            </dl>
            <p class="muted small-note">Set the mode and start or pause each strategy in its section (Intraday, Swing).</p>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Strategy lifecycle</h2></div>
          <ol class="steps">
            <li><span class="n">1</span><div><b>Draft</b><span>Create from a template</span></div></li>
            <li><span class="n">2</span><div><b>Backtest</b><span>6+ months of past data, with charges</span></div></li>
            <li><span class="n">3</span><div><b>Paper</b><span>10 trading days with virtual money</span></div></li>
            <li><span class="n">4</span><div><b>Live</b><span>Small size, strict limits</span></div></li>
          </ol>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import MarketMoodCard from '../components/MarketMoodCard.vue'
import PageHeader from '../components/PageHeader.vue'
import StatTile from '../components/StatTile.vue'
import { computed, onMounted, ref } from 'vue'
import { errorMessage } from '../api/client'
import { MOVABLE, useStrategiesStore } from '../stores/strategies'
import { useTradingStore } from '../stores/trading'
import { useUiStore } from '../stores/ui'
import { ACTIVE_SECTIONS, SECTION_LABEL, STATUS_TONE, TEMPLATES, strategySummary } from '../utils/strategies'

const ui = useUiStore()
const strategies = useStrategiesStore()
const busyId = ref(null)
const confirmId = ref(null)
const error = ref('')
let confirmTimer

const inSections = computed(() => strategies.items.filter((s) => s.section).length)
const running = computed(() => strategies.items.filter((s) => s.status === 'paper' || s.status === 'live').length)

const trading = useTradingStore()
const todayIST = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
const signalsToday = computed(() => trading.signals.filter((s) => new Date(s.created_at).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }) === todayIST()))
onMounted(() => { strategies.load().catch((e) => { error.value = errorMessage(e) }); trading.load().catch(() => {}) })

async function run(s, fn) {
  busyId.value = s.id
  error.value = ''
  try { await fn() } catch (e) { error.value = errorMessage(e) } finally { busyId.value = null }
}

const move = (s, section) => run(s, () => strategies.setSection(s.id, section))

// Two-step delete: first click asks, second click (within 6s) deletes.
function remove(s) {
  if (confirmId.value !== s.id) {
    confirmId.value = s.id
    clearTimeout(confirmTimer)
    confirmTimer = setTimeout(() => { confirmId.value = null }, 6000)
    return
  }
  confirmId.value = null
  run(s, () => strategies.remove(s.id))
}
</script>

<style scoped>
.small-note { font-size: 0.82rem; margin: 10px 0 0; }
.tpl-icon { width: 32px; height: 32px; border-radius: 8px; display: grid; place-items: center; background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border); flex: none; }
.seg { display: flex; background: var(--surface-3); border: 1px solid var(--border); border-radius: 9px; padding: 3px; }
.seg-btn { flex: 1; border: 0; background: none; padding: 7px; border-radius: 7px; font: inherit; font-weight: 600; font-size: 0.84rem; color: var(--muted); }
.seg-btn.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
.spaced { margin-top: 16px; }
.steps { list-style: none; margin: 0; padding: 8px 18px 14px; }
.steps li { display: flex; gap: 12px; padding: 9px 0; position: relative; }
.steps li:not(:last-child)::after { content: ''; position: absolute; left: 11px; top: 34px; bottom: -6px; width: 1px; background: var(--border); }
.steps .n { width: 23px; height: 23px; border-radius: 50%; display: grid; place-items: center; font-size: 0.75rem; font-weight: 700; background: var(--accent-soft); color: var(--accent-text); flex: none; }
.steps div { display: flex; flex-direction: column; font-size: 0.88rem; }
.steps span:not(.n) { color: var(--muted); font-size: 0.82rem; }
.s-name { font-weight: 600; }
.s-sub { font-size: 0.82rem; color: var(--muted); }
.section-select { padding: 5px 8px; font-size: 0.85rem; min-width: 150px; }
.cap { text-transform: capitalize; }
.error.inline { margin: 12px 18px; }
table.data td { vertical-align: middle; }
@media (max-width: 640px) { .hide-sm { display: none; } }
</style>
