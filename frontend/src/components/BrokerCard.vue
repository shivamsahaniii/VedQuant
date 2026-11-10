<template>
  <article class="broker-card">
    <header class="bc-head">
      <span class="b-logo" :class="account.is_paper ? 'paper' : ''">{{ account.broker_name[0] }}</span>
      <div class="bc-title">
        <div class="bc-name">{{ account.label }}</div>
        <div class="bc-sub">{{ account.broker_name }} · added {{ istDateTime(account.created_at) }}</div>
      </div>
      <span class="status" :class="statusTone"><span class="dot"></span>{{ statusLabel }}</span>
    </header>

    <div class="bc-meta">
      <div><span>Last checked</span><b>{{ account.last_checked_at ? relativeTime(account.last_checked_at) : 'Never' }}</b></div>
      <div v-if="!account.is_paper"><span>Token expires</span><b :class="{ warnText: expiringSoon }">{{ account.token_expires_at ? istDateTime(account.token_expires_at) : '—' }}</b></div>
      <div v-if="lastFunds !== null"><span>Available funds</span><b>{{ formatINR(lastFunds) }}</b></div>
    </div>

    <p v-if="account.last_error && account.status !== 'connected'" class="bc-error">
      <AppIcon name="x" :size="14" /> {{ account.last_error }}
    </p>

    <div v-if="!account.is_paper" class="purposes">
      <section v-for="p in ['trading', 'data']" :key="p" class="purpose">
        <div class="p-head">
          <div>
            <div class="p-title">{{ p === 'trading' ? 'Trading keys' : 'Data keys' }}</div>
            <div class="p-sub">{{ p === 'trading' ? 'Place orders (Phase 4)' : 'Live prices & history' }}</div>
          </div>
          <span class="tag" :class="account.credentials[p].complete || usesTradingKeys(p) ? 'good' : ''">{{ account.credentials[p].complete ? 'Added' : usesTradingKeys(p) ? 'Uses trading keys' : 'Not added' }}</span>
        </div>
        <dl class="p-fields">
          <template v-for="f in account.credentials[p].fields" :key="f.name">
            <dt>{{ f.label }}</dt>
            <dd class="mono">{{ !f.saved ? '—' : f.secret ? `••••${f.last4}` : f.value }}</dd>
          </template>
        </dl>
        <div class="p-actions">
          <button class="btn ghost sm" @click="editing = p">{{ account.credentials[p].complete ? 'Replace' : 'Add keys' }}</button>
          <button v-if="anySaved(p)" class="btn ghost sm" :disabled="busy" @click="removeKeys(p)">
            {{ confirm === `rm-${p}` ? 'Confirm remove' : 'Remove' }}
          </button>
        </div>
      </section>
    </div>
    <p v-else class="paper-note">Simulated broker with ₹1,00,000 virtual money. No API keys needed.</p>

    <div v-if="account.broker === 'dhan'" class="dhan-login">
      <div class="dl-text">
        <b>Daily login</b>
        <span v-if="hasApiKey">Click to log in on Dhan's page; a fresh 24-hour token is saved here by itself.</span>
        <span v-else>Optional: add your Dhan <b>API key + secret</b> under Trading keys to log in with one click each day instead of pasting a token.</span>
        <span class="redirect">Redirect URL for Dhan: <code>{{ redirectUrl }}</code>
          <button class="btn ghost xs" type="button" @click="copyRedirect">{{ copied ? 'Copied' : 'Copy' }}</button></span>
      </div>
      <button v-if="hasApiKey" class="btn primary sm" :disabled="busy" @click="dhanLogin">
        <AppIcon name="power" :size="14" /> Login with Dhan
      </button>
    </div>

    <footer class="bc-foot">
      <button class="btn ghost sm" :disabled="busy" @click="test">
        <AppIcon name="power" :size="14" /> {{ testing ? 'Testing…' : 'Test connection' }}
      </button>
      <span v-if="message" class="test-msg" :class="messageOk ? 'okText' : 'badText'">{{ message }}</span>
      <button class="btn sm disconnect" :class="confirm === 'dc' ? 'danger' : 'ghost'" :disabled="busy" @click="disconnect">
        {{ confirm === 'dc' ? 'Confirm disconnect' : 'Disconnect' }}
      </button>
    </footer>

    <KeysDialog :open="!!editing" :account="account" :purpose="editing" @close="editing = null" @tested="showResult" />
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import KeysDialog from './KeysDialog.vue'
import { brokersApi, errorMessage } from '../api/client'
import { useBrokersStore } from '../stores/brokers'
import { formatINR, istDateTime, relativeTime } from '../utils/format'

const props = defineProps({ account: { type: Object, required: true } })
const brokers = useBrokersStore()

const editing = ref(null)
const busy = ref(false)
const testing = ref(false)
const message = ref('')
const messageOk = ref(false)
const lastFunds = ref(null)
const confirm = ref(null)
let confirmTimer

const STATUS = { new: ['Not tested', ''], connected: ['Connected', 'good'], error: ['Error', 'bad'], expired: ['Token expired', 'warn'], disconnected: ['Disconnected', ''] }
const statusLabel = computed(() => STATUS[props.account.status]?.[0] ?? props.account.status)
const statusTone = computed(() => STATUS[props.account.status]?.[1] ?? '')
const expiringSoon = computed(() => {
  const t = props.account.token_expires_at
  return t && new Date(t).getTime() - Date.now() < 3 * 3600 * 1000
})
const hasApiKey = computed(() => ['api_key', 'api_secret'].every((n) => props.account.credentials.trading.fields.find((f) => f.name === n)?.saved))
const redirectUrl = `${window.location.origin}/dhan/callback`
const copied = ref(false)
async function copyRedirect() {
  try { await navigator.clipboard.writeText(redirectUrl); copied.value = true; setTimeout(() => { copied.value = false }, 2000) } catch { /* clipboard blocked: the URL is shown */ }
}
async function dhanLogin() {
  busy.value = true
  message.value = ''
  try {
    const { login_url: url } = await brokersApi.dhanLogin(props.account.id)
    if (!url.startsWith('https://auth.dhan.co/')) throw new Error('unexpected login page')
    window.location.assign(url) // Dhan's own login page; it sends you back to /dhan/callback
  } catch (e) {
    messageOk.value = false
    message.value = errorMessage(e)
    busy.value = false
  }
}
// Data calls fall back to the trading token when no separate data key is saved.
const usesTradingKeys = (p) => p === 'data' && !props.account.credentials.data.complete && props.account.credentials.trading.complete
const anySaved = (p) => props.account.credentials[p].fields.some((f) => f.saved)

function showResult(r) {
  messageOk.value = r.ok
  message.value = r.message || (r.ok ? 'Connection OK' : 'Test failed')
  lastFunds.value = r.funds_available ?? null
}

async function test() {
  busy.value = testing.value = true
  message.value = ''
  try { showResult(await brokers.test(props.account.id)) } catch (e) { messageOk.value = false; message.value = errorMessage(e) } finally { busy.value = testing.value = false }
}

function armed(key) {
  if (confirm.value === key) { confirm.value = null; return true }
  confirm.value = key
  clearTimeout(confirmTimer)
  confirmTimer = setTimeout(() => { confirm.value = null }, 6000)
  return false
}

async function removeKeys(p) {
  if (!armed(`rm-${p}`)) return
  busy.value = true
  try { await brokers.removeKeys(props.account.id, p) } catch (e) { message.value = errorMessage(e) } finally { busy.value = false }
}

async function disconnect() {
  if (!armed('dc')) return
  busy.value = true
  try { await brokers.disconnect(props.account.id) } catch (e) { message.value = errorMessage(e); busy.value = false }
}
</script>

<style scoped>
.broker-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); display: flex; flex-direction: column; }
.bc-head { display: flex; align-items: center; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.b-logo { width: 40px; height: 40px; border-radius: 10px; display: grid; place-items: center; font-weight: 700; font-size: 1.1rem; background: linear-gradient(135deg, #6366f1, #4338ca); color: #fff; flex: none; }
.b-logo.paper { background: var(--surface-3); color: var(--text-2); border: 1px solid var(--border); }
.bc-title { flex: 1; min-width: 0; }
.bc-name { font-weight: 600; font-size: 1rem; }
.bc-sub { font-size: 0.82rem; color: var(--muted); }
.status { display: inline-flex; align-items: center; gap: 6px; font-size: 0.8rem; font-weight: 600; padding: 4px 10px; border-radius: 999px; background: var(--surface-3); color: var(--muted); white-space: nowrap; }
.status .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.status.good { background: var(--good-soft); color: var(--good); }
.status.bad { background: var(--bad-soft); color: var(--bad); }
.status.warn { background: var(--warn-soft); color: var(--warn); }
.bc-meta { display: flex; flex-wrap: wrap; gap: 8px 28px; padding: 12px 18px; font-size: 0.85rem; }
.bc-meta div { display: flex; flex-direction: column; }
.bc-meta span { color: var(--muted); font-size: 0.78rem; }
.warnText { color: var(--warn); }
.bc-error { display: flex; gap: 8px; align-items: flex-start; margin: 0 18px 12px; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--bad-soft); color: var(--bad); font-size: 0.85rem; overflow-wrap: anywhere; }
.purposes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 0 18px 16px; }
.purpose { border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; background: var(--surface-2); display: flex; flex-direction: column; gap: 10px; }
.p-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.p-title { font-weight: 600; font-size: 0.92rem; }
.p-sub { font-size: 0.78rem; color: var(--muted); }
.p-fields { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 0; font-size: 0.84rem; }
.p-fields dt { color: var(--muted); }
.p-fields dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
.mono { font-family: ui-monospace, 'SFMono-Regular', monospace; }
.p-actions { display: flex; gap: 6px; }
.paper-note { margin: 0 18px 16px; font-size: 0.88rem; color: var(--muted); }
.bc-foot { display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-top: 1px solid var(--border); background: var(--surface-2); border-radius: 0 0 var(--radius) var(--radius); flex-wrap: wrap; }
.test-msg { font-size: 0.85rem; font-weight: 600; }
.okText { color: var(--good); }
.badText { color: var(--bad); }
.disconnect { margin-left: auto; }
@media (max-width: 640px) { .purposes { grid-template-columns: 1fr; } }
.dhan-login { display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; margin: 0 18px 14px; padding: 10px 12px; border: 1px dashed var(--border-strong); border-radius: var(--radius-sm); font-size: 0.83rem; }
.dl-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1 1 260px; color: var(--text-2); }
.redirect { color: var(--muted); overflow-wrap: anywhere; }
.redirect code { color: var(--text); }
.btn.xs { padding: 2px 8px; font-size: 0.75rem; margin-left: 4px; }
</style>
