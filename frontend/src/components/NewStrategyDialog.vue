<template>
  <Teleport to="body">
    <div v-if="ui.newStrategyOpen" class="overlay" @mousedown.self="close">
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="ns-title" @keydown.esc="close">
        <header class="d-head">
          <div>
            <div class="step">Step {{ step }} of 2</div>
            <h2 id="ns-title">{{ step === 1 ? 'Choose a template or build your own' : 'Set up your strategy' }}</h2>
          </div>
          <button class="icon-btn" aria-label="Close" @click="close"><AppIcon name="x" :size="18" /></button>
        </header>

        <div class="d-body" v-if="step === 1">
          <div class="tpl-grid">
            <button v-for="t in TEMPLATES" :key="t.key" class="tpl" :class="{ sel: selected?.key === t.key }"
              @click="selected = t" @dblclick="next">
              <div class="tpl-top">
                <span class="tpl-icon"><AppIcon :name="t.section === 'swing' ? 'swing' : 'intraday'" :size="16" /></span>
                <span class="tag">{{ SECTION_LABEL[t.section] }}</span>
              </div>
              <div class="tpl-name">{{ t.name }}</div>
              <div class="tpl-idea">{{ t.idea }}</div>
              <div class="tpl-meta"><span>{{ t.timeframe }} candles</span><span>·</span><span>{{ t.section === 'intraday' ? 'Runs now' : 'Daily candles: later phase' }}</span></div>
            </button>
            <button class="tpl builder" :class="{ sel: selected?.key === 'builder' }" @click="selected = BUILDER" @dblclick="next">
              <div class="tpl-top"><span class="tpl-icon"><AppIcon name="algo" :size="16" /></span><span class="tag accent">Your rules</span></div>
              <div class="tpl-name">Build from scratch</div>
              <div class="tpl-idea">Pick prices, indicators and conditions from dropdowns. No coding.</div>
            </button>
          </div>
        </div>

        <div class="d-body" v-else>
          <form class="ns-form" @submit.prevent="create" id="ns-form">
            <div class="chosen">
              <span class="tpl-icon"><AppIcon :name="selected.section === 'swing' ? 'swing' : 'intraday'" :size="16" /></span>
              <div><div class="tpl-name">{{ selected.name }}</div><div class="tpl-idea">{{ selected.idea }}</div></div>
              <button type="button" class="btn ghost sm" @click="step = 1">Change</button>
            </div>
            <label>Strategy name
              <input v-model="form.name" maxlength="60" required />
            </label>
            <div class="row">
              <label>Add to section
                <select v-model="form.section">
                  <option v-for="s in ACTIVE_SECTIONS" :key="s" :value="s">{{ SECTION_LABEL[s] }}</option>
                  <option :value="null">Not now (keep in My strategies)</option>
                </select>
              </label>
              <label>Timeframe
                <select v-model="form.timeframe">
                  <!-- The live feed builds 1m and 5m candles; 1d is for swing (later phase). -->
                  <option v-for="tf in ['1m', '5m', '1d']" :key="tf" :value="tf">{{ tf === '1d' ? '1d (swing, later phase)' : tf }}</option>
                </select>
              </label>
            </div>
            <label>Symbols
              <input v-model="form.symbols" placeholder="e.g. RELIANCE, SBIN, INFY" />
              <span class="hint">Comma separated NSE symbols. Leave empty to use the scanner universe.</span>
            </label>
            <template v-if="isBuilder">
              <div v-if="!builderOptions" class="hint">Loading the rule builder…</div>
              <template v-else>
                <RuleGroup v-model="rules.buy" side="buy" :options="builderOptions" />
                <RuleGroup v-model="rules.sell" side="sell" :options="builderOptions" />
                <p class="hint">Checked on every <strong>closed</strong> {{ form.timeframe }} candle. A match then goes through the same agents as every strategy: entry timing (09:30–14:30, no chasing), stop and target, odds, risk and sizing.</p>
                <div class="row">
                  <label>Market mood filter
                    <select v-model="rules.mood">
                      <option value="trend">Trend: only trade with the market</option>
                      <option value="breakout">Breakout: with the market, skip weak days</option>
                      <option value="reversion">Reversal: avoid fighting strong trends</option>
                      <option value="off">Off: ignore the market mood</option>
                    </select>
                  </label>
                  <label>Stop loss
                    <select v-model="form.stopRule">
                      <option value="auto">ATR × 1.5 (auto)</option>
                      <option value="level">At the level that was crossed</option>
                      <option value="or_mid">Middle of the opening range</option>
                      <option value="pct">Fixed %</option>
                    </select>
                  </label>
                </div>
              </template>
            </template>
            <div class="row" v-if="isBuilder">
              <label v-if="form.stopRule === 'pct'">Stop loss %
                <input v-model="form.sl" type="number" min="0.1" max="50" step="0.1" required />
              </label>
              <label>Target (× the risk)
                <input v-model="form.targetR" type="number" min="0.5" max="10" step="0.5" required />
                <span class="hint">2 = aim to win twice what you risk</span>
              </label>
            </div>
            <div class="row" v-else>
              <label>Stop loss %
                <input v-model="form.sl" type="number" min="0.1" max="50" step="0.1" required />
              </label>
              <label>Target %
                <input v-model="form.target" type="number" min="0.1" max="100" step="0.1" />
              </label>
            </div>
            <p v-if="error" class="error" role="alert">{{ error }}</p>
            <div class="info-box">
              <AppIcon name="flask" :size="16" />
              <span>New strategies start as a <strong>draft</strong>. They need a backtest, then 10 days of paper trading, before they can go live.</span>
            </div>
          </form>
        </div>

        <footer class="d-foot">
          <span class="foot-note" v-if="step === 2">Saved as a draft. Backtesting arrives in Phase 2.</span>
          <span v-else></span>
          <div class="foot-btns">
            <button class="btn ghost" @click="step === 1 ? close() : (step = 1)">{{ step === 1 ? 'Cancel' : 'Back' }}</button>
            <button v-if="step === 1" class="btn primary" :disabled="!selected" @click="next">Continue</button>
            <button v-else class="btn primary" type="submit" form="ns-form" :disabled="busy">
              {{ busy ? 'Creating…' : 'Create strategy' }}
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import RuleGroup from './RuleGroup.vue'
import { errorMessage, strategiesApi } from '../api/client'
import { useStrategiesStore } from '../stores/strategies'
import { useUiStore } from '../stores/ui'
import { ACTIVE_SECTIONS, SECTION_LABEL, TEMPLATES } from '../utils/strategies'

const ui = useUiStore()
const strategies = useStrategiesStore()
const router = useRouter()
const step = ref(1)
const selected = ref(null)
const busy = ref(false)
const error = ref('')
const form = reactive({ name: '', section: 'intraday', timeframe: '5m', symbols: '', sl: 1, target: 2, stopRule: 'auto', targetR: 2 })
const BUILDER = { key: 'builder', name: 'Custom rules', idea: 'Your own conditions, checked on every closed candle.', section: 'intraday', timeframe: '5m' }
const isBuilder = computed(() => selected.value?.key === 'builder')
const builderOptions = ref(null)
const newRules = () => ({
  mood: 'trend',
  buy: { match: 'all', conditions: [{ left: { kind: 'close', period: null, value: null, mult: 1 }, op: 'crosses_above', right: { kind: 'vwap', period: null, value: null, mult: 1 } }] },
  sell: null,
})
const rules = ref(newRules())

watch(() => ui.newStrategyOpen, (open) => {
  if (!open) return
  error.value = ''
  selected.value = ui.newStrategyTemplate === 'builder' ? BUILDER : TEMPLATES.find((t) => t.key === ui.newStrategyTemplate) ?? null
  rules.value = newRules()
  form.stopRule = 'auto'; form.targetR = 2
  if (!builderOptions.value) strategiesApi.builder().then((o) => { builderOptions.value = o }).catch((e) => { error.value = errorMessage(e) })
  step.value = selected.value ? 2 : 1
  if (selected.value) fill()
})

function fill() {
  form.name = isBuilder.value ? 'My strategy' : `My ${selected.value.name}`
  form.section = ui.newStrategySection !== undefined ? ui.newStrategySection : selected.value.section
  form.timeframe = selected.value.timeframe
}

function next() {
  if (!selected.value) return
  fill()
  step.value = 2
}

function close() {
  if (!busy.value) ui.closeNewStrategy()
}

async function create() {
  error.value = ''
  if (isBuilder.value && !rules.value.buy && !rules.value.sell) {
    error.value = 'Turn on Buy or Sell and add at least one condition.'
    return
  }
  busy.value = true
  try {
    const params = {
      timeframe: form.timeframe,
      symbols: form.symbols,
      stop_loss_pct: String(form.sl),
      target_pct: form.target === '' || form.target === null ? null : String(form.target),
    }
    if (isBuilder.value) {
      Object.assign(params, { builder: rules.value, stop_rule: form.stopRule, target_r: String(form.targetR) })
    }
    const s = await strategies.create({
      name: form.name,
      template_key: isBuilder.value ? null : selected.value.key,
      section: form.section,
      params,
    })
    ui.closeNewStrategy()
    if (s.section && router.currentRoute.value.path !== `/${s.section}`) router.push(`/${s.section}`)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.overlay { position: fixed; inset: 0; z-index: 100; background: rgba(9, 12, 20, 0.55); backdrop-filter: blur(2px); display: grid; place-items: center; padding: 16px; }
.dialog { width: 100%; max-width: 820px; max-height: calc(100vh - 32px); display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow-lg); }
.d-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 18px 22px 14px; border-bottom: 1px solid var(--border); }
.step { font-size: 0.75rem; font-weight: 600; color: var(--accent-text); text-transform: uppercase; letter-spacing: 0.05em; }
.d-head h2 { margin: 2px 0 0; font-size: 1.15rem; }
.icon-btn { border: 0; background: none; color: var(--muted); padding: 6px; border-radius: 8px; cursor: pointer; }
.icon-btn:hover { background: var(--surface-2); color: var(--text); }
.d-body { padding: 18px 22px; overflow-y: auto; }
.d-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 22px; border-top: 1px solid var(--border); background: var(--surface-2); border-radius: 0 0 14px 14px; flex-wrap: wrap; }
.foot-note { font-size: 0.83rem; color: var(--muted); }
.foot-btns { display: flex; gap: 8px; margin-left: auto; }

.tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; }
.tpl { text-align: left; font: inherit; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; cursor: pointer; display: flex; flex-direction: column; gap: 4px; transition: border-color 0.15s, box-shadow 0.15s; }
.tpl:hover:not(:disabled) { border-color: var(--border-strong); }
.tpl.sel { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.tpl:disabled { cursor: not-allowed; opacity: 0.6; border-style: dashed; }
.tpl-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.tpl-icon { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; background: var(--accent-soft); color: var(--accent-text); flex: none; }
.tpl-name { font-weight: 600; font-size: 0.93rem; }
.tpl-idea { font-size: 0.83rem; color: var(--muted); }
.tpl-meta { display: flex; gap: 6px; font-size: 0.76rem; color: var(--muted); margin-top: 6px; }

.ns-form { gap: 14px; }
.chosen { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-2); }
.chosen > div { flex: 1; min-width: 0; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.info-box { display: flex; gap: 10px; align-items: flex-start; padding: 11px 13px; border-radius: var(--radius-sm); background: var(--accent-soft); color: var(--text-2); font-size: 0.86rem; }
.info-box :deep(svg) { color: var(--accent-text); margin-top: 2px; }
@media (max-width: 560px) { .row { grid-template-columns: 1fr; } }
</style>
