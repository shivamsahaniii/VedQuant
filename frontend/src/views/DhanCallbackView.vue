<template>
  <div class="cb">
    <div class="card">
      <div class="card-head"><h2>Dhan login</h2></div>
      <div class="body">
        <p v-if="state === 'working'" class="muted">Saving your new Dhan access token…</p>
        <template v-else-if="state === 'ok'">
          <p class="good">✓ Logged in to Dhan. A fresh 24-hour token is saved (encrypted) and tested.</p>
          <p class="muted">{{ message }}</p>
        </template>
        <template v-else>
          <p class="bad">Dhan login did not finish.</p>
          <p class="muted">{{ message }}</p>
        </template>
        <RouterLink to="/settings" class="btn primary">Go to Settings</RouterLink>
      </div>
    </div>
  </div>
</template>

<script setup>
// Dhan sends the browser here after "Login with Dhan": /dhan/callback?tokenId=...
// The tokenId is handed to our API once, then removed from the address bar.
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { brokersApi, errorMessage } from '../api/client'
import { useBrokersStore } from '../stores/brokers'

const route = useRoute()
const router = useRouter()
const brokers = useBrokersStore()
const state = ref('working')
const message = ref('')

onMounted(async () => {
  const tokenId = route.query.tokenId || route.query.tokenid || route.query.token_id
  router.replace({ query: {} }) // don't keep it in history
  if (!tokenId) {
    state.value = 'error'
    message.value = 'Dhan did not send a login token back. Start again from Settings → Dhan → Login with Dhan.'
    return
  }
  try {
    const r = await brokersApi.dhanComplete(String(tokenId))
    state.value = r.ok ? 'ok' : 'error'
    message.value = r.message
    brokers.load?.().catch?.(() => {})
  } catch (e) {
    state.value = 'error'
    message.value = errorMessage(e)
  }
})
</script>

<style scoped>
.cb { max-width: 560px; margin: 40px auto; padding: 0 16px; }
.body { padding: 16px 18px 20px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
.good { color: var(--good); font-weight: 600; margin: 0; }
.bad { color: var(--bad); font-weight: 600; margin: 0; }
.muted { margin: 0; }
</style>
