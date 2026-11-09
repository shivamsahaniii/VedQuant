<template>
  <div class="stack">
    <div class="card">
      <div class="card-head">
        <h2>What VedQuant uses</h2>
        <span class="muted small">Your choice, per market</span>
      </div>
      <div class="prefs">
        <label v-for="a in ASSETS" :key="a.key" class="pref">
          <span class="pref-label"><AppIcon :name="a.icon" :size="15" /> {{ a.label }} data</span>
          <select :value="prefs.data_sources?.[a.key] ?? ''" :disabled="busy" @change="setSource(a.key, $event.target.value)">
            <option value="">None</option>
            <option v-for="c in sourcesFor(a.key)" :key="c.key" :value="c.key" :disabled="!usable(c)">
              {{ c.name }}{{ c.status !== 'available' ? ' (coming soon)' : !usable(c) ? ' (connect first)' : '' }}
            </option>
          </select>
        </label>
        <label class="pref">
          <span class="pref-label"><AppIcon name="table" :size="15" /> Charts</span>
          <select :value="prefs.chart_provider" :disabled="busy" @change="setChart($event.target.value)">
            <option v-for="c in byCategory('charts')" :key="c.key" :value="c.key" :disabled="c.status !== 'available'">
              {{ c.name }}{{ c.status !== 'available' ? ' (coming soon)' : '' }}
            </option>
          </select>
        </label>
      </div>
      <p v-if="note" class="note">{{ note }}</p>
      <p v-if="error" class="error inline">{{ error }}</p>
    </div>

    <div v-for="g in GROUPS" :key="g.key" class="card">
      <div class="card-head">
        <h2>{{ g.title }}</h2>
        <span class="muted small">{{ g.hint }}</span>
      </div>
      <div class="conn-grid">
        <div v-for="c in byCategory(g.key)" :key="c.key" class="conn" :class="{ soon: c.status !== 'available' }">
          <div class="conn-top">
            <div class="conn-logo">{{ initials(c.name) }}</div>
            <div class="conn-main">
              <div class="conn-name">{{ c.name }}</div>
              <div class="conn-tags">
                <span v-if="c.status !== 'available'" class="tag">Coming soon</span>
                <span v-else-if="c.connected_accounts" class="tag good">Connected</span>
                <span v-else-if="c.category === 'charts'" class="tag info">Ready</span>
                <span v-for="u in c.in_use_for" :key="u" class="tag accent">In use: {{ u }}</span>
              </div>
            </div>
          </div>
          <p class="conn-sum">{{ c.summary }}</p>
          <dl class="conn-kv">
            <dt>Provides</dt><dd>{{ c.provides.join(', ') }}</dd>
            <dt>Covers</dt><dd>{{ c.markets.join(' · ') }}</dd>
            <dt>Pricing</dt><dd>{{ c.pricing }}</dd>
          </dl>
          <p v-for="n in c.notes" :key="n" class="conn-note">{{ n }}</p>
          <div class="conn-actions">
            <template v-if="c.status === 'available'">
              <button v-if="c.broker_key && c.key !== 'paper'" class="btn primary sm" @click="$emit('connect', c.broker_key)">
                <AppIcon name="plus" :size="14" /> {{ c.connected_accounts ? 'Add another' : 'Connect' }}
              </button>
              <span v-else class="muted small">{{ c.key === 'paper' ? 'Built in, always on' : 'Built in, pick it above' }}</span>
            </template>
            <button v-else class="btn ghost sm" :disabled="c.requested || busy" @click="request(c)">
              {{ c.requested ? 'Requested ✓' : 'Request this' }}
            </button>
            <a v-if="c.docs_url" :href="c.docs_url" target="_blank" rel="noopener noreferrer" class="docs">Docs ↗</a>
          </div>
        </div>
      </div>
    </div>
    <p class="muted tiny">Pricing and coverage are summaries; check each provider’s own site before you subscribe.</p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { errorMessage } from '../api/client'
import { ASSETS, useMarketsStore } from '../stores/markets'

defineEmits(['connect'])
const markets = useMarketsStore()
const busy = ref(false)
const error = ref('')
const note = ref('')
const prefs = computed(() => markets.preferences)

const GROUPS = [
  { key: 'broker', title: 'Indian brokers & market data', hint: 'Stocks, indices, F&O, with your own account and keys' },
  { key: 'crypto', title: 'Crypto exchanges', hint: 'Crypto prices and trading' },
  { key: 'charts', title: 'Charts', hint: 'How charts are drawn in VedQuant' },
]

const byCategory = (cat) => markets.connectors.filter((c) => c.category === cat)
const sourcesFor = (asset) => markets.connectors.filter((c) => c.assets.includes(asset) && c.provides.includes('market data'))
const usable = (c) => c.status === 'available' && (c.key === 'paper' || c.connected_accounts > 0)
const initials = (name) => name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()

onMounted(() => markets.loadConnectors().catch((e) => { error.value = errorMessage(e) }))

async function save(body, msg) {
  busy.value = true; error.value = ''; note.value = ''
  try { await markets.savePreferences(body); note.value = msg } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
const setSource = (asset, key) => save({ data_sources: { [asset]: key || null } },
  key && key !== 'paper' ? 'Saved. The live feed from your own account is being added next; until then prices stay simulated.' : 'Saved.')
const setChart = (key) => save({ chart_provider: key }, 'Saved. Open Markets to see the chart.')

async function request(c) {
  busy.value = true; error.value = ''
  try { await markets.request(c.key); note.value = `Thanks. We count requests to decide which connector to build next (${c.name}).` }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
</script>

<style scoped>
.small { font-size: 0.82rem; }
.tiny { font-size: 0.78rem; margin: 0; }
.prefs { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; padding: 16px 18px; }
.pref { display: flex; flex-direction: column; gap: 6px; }
.pref-label { display: flex; align-items: center; gap: 6px; font-size: 0.82rem; font-weight: 600; color: var(--text-2); }
.pref select { font: inherit; font-size: 0.88rem; padding: 8px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); }
.note { margin: 0 18px 14px; padding: 8px 12px; border-radius: var(--radius-sm); background: var(--info-soft); color: var(--info); font-size: 0.85rem; }
.error.inline { margin: 0 18px 14px; }
.conn-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; padding: 16px 18px; }
.conn { border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; display: flex; flex-direction: column; gap: 8px; background: var(--surface-2); min-width: 0; }
.conn.soon { opacity: 0.85; }
.conn-top { display: flex; gap: 10px; align-items: center; }
.conn-logo { width: 36px; height: 36px; border-radius: 9px; display: grid; place-items: center; font-weight: 700; font-size: 0.8rem; background: var(--accent-soft); color: var(--accent-text); flex: none; }
.conn.soon .conn-logo { background: var(--surface-3); color: var(--muted); }
.conn-main { min-width: 0; }
.conn-name { font-weight: 700; }
.conn-tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 3px; }
.conn-sum { margin: 0; font-size: 0.86rem; color: var(--text-2); }
.conn-kv { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; margin: 0; font-size: 0.8rem; }
.conn-kv dt { color: var(--muted); }
.conn-kv dd { margin: 0; overflow-wrap: anywhere; }
.conn-note { margin: 0; font-size: 0.78rem; color: var(--warn); }
.conn-actions { display: flex; align-items: center; gap: 10px; margin-top: auto; padding-top: 4px; }
.docs { margin-left: auto; font-size: 0.8rem; }
</style>
