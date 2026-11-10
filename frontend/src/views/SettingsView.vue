<template>
  <div>
    <PageHeader icon="settings" title="Settings" subtitle="Connections, your accounts and keys, and security.">
      <button class="btn primary" @click="connect('')"><AppIcon name="plus" :size="16" /> Add broker</button>
    </PageHeader>

    <div class="section-title">
      <h2>Connections</h2>
      <span class="muted small">Choose where VedQuant gets prices for each market, which broker it trades through, and how charts are drawn.</span>
    </div>
    <ConnectionsPanel class="conn-panel" @connect="connect" />

    <div class="grid-2">
      <div class="stack">
        <div class="section-title">
          <h2>Your connected accounts</h2>
          <span class="muted small">Trading and data keys are kept separate, encrypted, and only the last 4 characters are shown.</span>
        </div>

        <div v-if="brokers.loading && !brokers.loaded" class="card"><div class="card-body muted">Loading brokers…</div></div>
        <p v-else-if="loadError" class="error">{{ loadError }}</p>

        <template v-else-if="brokers.accounts.length">
          <BrokerCard v-for="a in brokers.accounts" :key="a.id" :account="a" />
        </template>

        <div v-else class="card">
          <EmptyState icon="broker" title="No broker connected"
            text="Connect Dhan with your own API keys, or start with the Paper broker to practise with virtual money.">
            <button class="btn primary" @click="connect('')"><AppIcon name="plus" :size="16" /> Add broker</button>
          </EmptyState>
        </div>
      </div>

      <aside class="stack">
        <div class="card">
          <div class="card-head"><h2>Where to find Dhan keys</h2></div>
          <ol class="howto">
            <li>Log in at <b>web.dhan.co</b></li>
            <li>Open <b>My Profile → Access DhanHQ APIs</b></li>
            <li>Generate an <b>Access Token</b> and copy it with your <b>Client ID</b></li>
            <li>Paste both here. The token is valid for <b>24 hours</b></li>
          </ol>
          <div class="card-body tight muted small">Live prices also need Dhan’s Data API plan to be active on your account.</div>
        </div>
        <ProfilePanel />
        <div class="card">
          <div class="card-head"><h2>Security</h2></div>
          <ul class="list">
            <li><AppIcon name="shield" class="muted" /><div class="li-main"><div class="li-title">Two-factor login</div><div class="li-sub">Authenticator app codes</div></div><span class="tag">Phase 3</span></li>
            <li><AppIcon name="lock" class="muted" /><div class="li-main"><div class="li-title">Password to change brokers</div><div class="li-sub">Re-enter password for key changes</div></div><span class="tag">Phase 3</span></li>
            <li><AppIcon name="bell" class="muted" /><div class="li-main"><div class="li-title">Telegram alerts</div><div class="li-sub">Signals, orders and errors</div></div><span class="tag">Phase 3</span></li>
          </ul>
        </div>
      </aside>
    </div>

    <AddBrokerDialog :open="adding" :preselect="preselect" @close="closeDialog" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import AddBrokerDialog from '../components/AddBrokerDialog.vue'
import AppIcon from '../components/AppIcon.vue'
import BrokerCard from '../components/BrokerCard.vue'
import ProfilePanel from '../components/ProfilePanel.vue'
import ConnectionsPanel from '../components/ConnectionsPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import { errorMessage } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useBrokersStore } from '../stores/brokers'
import { useMarketsStore } from '../stores/markets'

const auth = useAuthStore()
const brokers = useBrokersStore()
const adding = ref(false)
const loadError = ref('')
const preselect = ref('')
const markets = useMarketsStore()

function connect(key) { preselect.value = key; adding.value = true }
function closeDialog() { adding.value = false; markets.loadConnectors().catch(() => {}) }

onMounted(() => brokers.load(true).catch((e) => { loadError.value = errorMessage(e) }))
</script>

<style scoped>
.cap { text-transform: capitalize; }
.small { font-size: 0.85rem; }
.section-title { display: flex; flex-direction: column; gap: 2px; }
.section-title h2 { margin: 0; font-size: 1.05rem; }
.conn-panel { margin: 10px 0 24px; }
.howto { margin: 0; padding: 14px 18px 4px 38px; font-size: 0.9rem; display: flex; flex-direction: column; gap: 6px; }
.card-body.tight { padding-top: 8px; }
</style>
