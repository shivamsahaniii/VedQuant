<template>
  <BaseDialog :open="open" :locked="busy" width="680px" :eyebrow="stepLabel"
    :title="titles[step]" @close="$emit('close')">

    <!-- Step 1: pick broker -->
    <template v-if="step === 1">
      <div class="broker-grid">
        <button v-for="b in brokers.available" :key="b.key" class="broker-opt" :class="{ sel: choice?.key === b.key }"
          @click="pick(b)">
          <span class="b-logo" :class="b.is_paper ? 'paper' : ''">{{ b.display_name[0] }}</span>
          <div class="b-main">
            <div class="b-name">{{ b.display_name }}</div>
            <div class="b-sub">{{ b.is_paper ? 'Virtual money. No keys needed.' : 'Use your own Dhan account and API keys.' }}</div>
          </div>
          <div class="b-tags"><span v-for="s in b.supports" :key="s" class="tag">{{ s }}</span></div>
        </button>
      </div>
      <label v-if="choice">Name for this connection
        <input v-model="label" maxlength="64" />
        <span class="hint">Shown on your dashboard, e.g. “Dhan main”.</span>
      </label>
    </template>

    <!-- Step 2: keys -->
    <template v-else-if="step === 2">
      <div class="purpose-toggle">
        <label class="check"><input type="checkbox" v-model="useTrading" /> <span><b>Trading keys</b><small>Used to place orders (Phase 4). Add now or later.</small></span></label>
        <label class="check"><input type="checkbox" v-model="useData" /> <span><b>Data keys</b><small>Used for live prices and history. Add now or later.</small></span></label>
      </div>

      <section v-if="useTrading" class="purpose-box">
        <h3>Trading keys</h3>
        <CredentialFields :specs="choice.credential_fields.trading" v-model="trading" />
      </section>

      <section v-if="useData" class="purpose-box">
        <div class="pb-head">
          <h3>Data keys</h3>
          <label v-if="useTrading" class="check inline"><input type="checkbox" v-model="sameKeys" /> Same as trading keys</label>
        </div>
        <CredentialFields v-if="!(useTrading && sameKeys)" :specs="choice.credential_fields.data" v-model="data" />
        <p v-else class="muted small">The trading Client ID and access token will also be used for data.</p>
      </section>

      <p v-if="!useTrading && !useData" class="muted small">You can save the connection now and add keys later from its card.</p>
      <p v-if="error" class="error">{{ error }}</p>
    </template>

    <!-- Step 3: result -->
    <template v-else>
      <div class="result" :class="result?.ok ? 'ok' : 'bad'">
        <span class="r-icon"><AppIcon :name="result?.ok ? 'check' : 'x'" :size="20" /></span>
        <div>
          <div class="r-title">{{ result ? (result.ok ? 'Connected' : 'Saved, but the test failed') : 'Saved' }}</div>
          <div class="r-text">{{ result ? result.message : 'Add keys and test the connection from the broker card.' }}</div>
          <div v-if="result?.funds_available" class="r-text">Available funds: <b>{{ formatINR(result.funds_available) }}</b></div>
        </div>
      </div>
      <p class="muted small">Keys are encrypted before they are saved. Only the last 4 characters are ever shown again.</p>
    </template>

    <template #footer>
      <span class="muted small" v-if="step === 2"><AppIcon name="lock" :size="12" /> Encrypted at rest. Never shown in full.</span>
      <span v-else></span>
      <div class="foot-btns">
        <template v-if="step === 1">
          <button class="btn ghost" @click="$emit('close')">Cancel</button>
          <button class="btn primary" :disabled="!choice || !label.trim() || busy" @click="fromStep1">
            {{ busy ? 'Connecting…' : choice?.is_paper ? 'Add and test' : 'Continue' }}
          </button>
        </template>
        <template v-else-if="step === 2">
          <button class="btn ghost" :disabled="busy" @click="step = 1">Back</button>
          <button class="btn primary" :disabled="busy" @click="saveAndTest">
            {{ busy ? 'Saving…' : useTrading || useData ? 'Save and test' : 'Save without keys' }}
          </button>
        </template>
        <button v-else class="btn primary" @click="$emit('close')">Done</button>
      </div>
    </template>
  </BaseDialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import BaseDialog from './BaseDialog.vue'
import CredentialFields from './CredentialFields.vue'
import { errorMessage } from '../api/client'
import { useBrokersStore } from '../stores/brokers'
import { formatINR } from '../utils/format'

const props = defineProps({ open: Boolean, preselect: { type: String, default: '' } })
defineEmits(['close'])
const brokers = useBrokersStore()

const step = ref(1)
const choice = ref(null)
const label = ref('')
const useTrading = ref(true)
const useData = ref(false)
const sameKeys = ref(true)
const trading = ref({})
const data = ref({})
const busy = ref(false)
const error = ref('')
const result = ref(null)
const account = ref(null)

const stepLabel = computed(() => {
  const total = choice.value?.is_paper ? 2 : 3
  const n = choice.value?.is_paper && step.value === 3 ? 2 : step.value
  return `Step ${n} of ${total}`
})
const titles = computed(() => ({ 1: 'Add a broker', 2: 'Enter your API keys', 3: 'Connection result' }))

watch(() => props.open, (o) => {
  if (!o) return
  step.value = 1; choice.value = null; label.value = ''; useTrading.value = true; useData.value = false
  sameKeys.value = true; trading.value = {}; data.value = {}; error.value = ''; result.value = null; account.value = null
  const pre = props.preselect && brokers.available.find((b) => b.key === props.preselect)
  if (pre) pick(pre)
})

function pick(b) {
  choice.value = b
  if (!label.value || brokers.available.some((x) => x.display_name === label.value || `${x.display_name} main` === label.value)) {
    label.value = b.is_paper ? 'Paper trading' : `${b.display_name} main`
  }
}

async function ensureAccount() {
  if (!account.value) account.value = await brokers.add(choice.value.key, label.value.trim())
  return account.value
}

async function fromStep1() {
  error.value = ''
  if (!choice.value.is_paper) { step.value = 2; return }
  busy.value = true
  try {
    const acct = await ensureAccount()
    result.value = await brokers.test(acct.id)
    step.value = 3
  } catch (e) {
    error.value = errorMessage(e)
    step.value = 3
  } finally {
    busy.value = false
  }
}

const filled = (obj) => Object.fromEntries(Object.entries(obj).filter(([, v]) => v && v.trim()))

async function saveAndTest() {
  error.value = ''
  const t = filled(trading.value)
  const d = useTrading.value && sameKeys.value ? t : filled(data.value)
  if (useTrading.value && !Object.keys(t).length) { error.value = 'Enter your trading keys, or untick “Trading keys”.'; return }
  if (useData.value && !Object.keys(d).length) { error.value = 'Enter your data keys, or untick “Data keys”.'; return }
  busy.value = true
  try {
    const acct = await ensureAccount()
    if (useTrading.value) await brokers.saveKeys(acct.id, 'trading', t)
    if (useData.value) await brokers.saveKeys(acct.id, 'data', d)
    result.value = useTrading.value || useData.value ? await brokers.test(acct.id) : null
    trading.value = {}; data.value = {}
    step.value = 3
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.broker-grid { display: flex; flex-direction: column; gap: 10px; }
.broker-opt { display: flex; align-items: center; gap: 14px; text-align: left; font: inherit; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; }
.broker-opt:hover { border-color: var(--border-strong); }
.broker-opt.sel { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.b-logo { width: 40px; height: 40px; border-radius: 10px; display: grid; place-items: center; font-weight: 700; font-size: 1.1rem; background: linear-gradient(135deg, #6366f1, #4338ca); color: #fff; flex: none; }
.b-logo.paper { background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border); }
.b-main { flex: 1; min-width: 0; }
.b-name { font-weight: 600; }
.b-sub { font-size: 0.85rem; color: var(--muted); }
.b-tags { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
.purpose-toggle { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.check { flex-direction: row; align-items: flex-start; gap: 10px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius); font-weight: 400; cursor: pointer; }
.check input { width: 16px; height: 16px; margin-top: 2px; accent-color: var(--accent); box-shadow: none; flex: none; }
.check span { display: flex; flex-direction: column; }
.check small { color: var(--muted); font-size: 0.8rem; }
.check.inline { border: 0; padding: 0; align-items: center; font-size: 0.85rem; font-weight: 500; }
.purpose-box { border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; background: var(--surface-2); }
.purpose-box h3 { margin: 0 0 12px; font-size: 0.95rem; }
.pb-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.pb-head h3 { margin: 0; }
.small { font-size: 0.85rem; margin: 0; }
.foot-btns { display: flex; gap: 8px; margin-left: auto; }
.result { display: flex; gap: 14px; padding: 16px; border-radius: var(--radius); border: 1px solid var(--border); }
.result.ok { background: var(--good-soft); border-color: transparent; }
.result.bad { background: var(--warn-soft); border-color: transparent; }
.r-icon { width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; background: var(--surface); flex: none; }
.ok .r-icon { color: var(--good); }
.bad .r-icon { color: var(--warn); }
.r-title { font-weight: 700; }
.r-text { font-size: 0.9rem; color: var(--text-2); overflow-wrap: anywhere; }
@media (max-width: 560px) { .purpose-toggle { grid-template-columns: 1fr; } .b-tags { display: none; } }
</style>
