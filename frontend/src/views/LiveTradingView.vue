<template>
  <div>
    <PageHeader icon="live" title="Live Trading" tone="live"
      subtitle="Real orders with real money through your own broker account.">
      <span class="tag" :class="unlocked ? 'live' : ''"><AppIcon :name="unlocked ? 'live' : 'lock'" :size="13" /> {{ unlocked ? 'Live' : 'Locked' }}</span>
    </PageHeader>

    <div class="locked-banner" v-if="!unlocked">
      <div class="lb-icon"><AppIcon name="lock" :size="22" /></div>
      <div>
        <div class="lb-title">Live trading is locked</div>
        <div class="lb-text">This keeps your money safe. It unlocks only when every check below is green.</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-head"><h2>Unlock checklist</h2><span class="tag">{{ doneCount }} / {{ checks.length }}</span></div>
        <ul class="list">
          <li v-for="c in checks" :key="c.title">
            <span class="check" :class="c.ok ? 'ok' : 'no'"><AppIcon :name="c.ok ? 'check' : 'x'" :size="14" /></span>
            <div class="li-main"><div class="li-title">{{ c.title }}</div><div class="li-sub">{{ c.sub }}</div></div>
            <span v-if="c.when" class="tag">{{ c.when }}</span>
          </li>
        </ul>
      </div>

      <aside class="stack">
        <div class="card">
          <div class="card-head"><h2>Kill switch</h2><AppIcon name="power" :size="18" class="muted" /></div>
          <div class="card-body">
            <p class="muted small">One click cancels all open orders, closes every position at market price and stops all trading until you resume it.</p>
            <button class="btn danger full" disabled><AppIcon name="power" :size="16" /> Stop all trading</button>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Live limits</h2></div>
          <div class="card-body">
            <dl class="kv">
              <dt>Starting capital</dt><dd>₹500 – ₹1,000</dd>
              <dt>First period</dt><dd>2 weeks, tiny size</dd>
              <dt>Mismatch with broker</dt><dd>Alert + halt</dd>
            </dl>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import PageHeader from '../components/PageHeader.vue'
import { useAuthStore } from '../stores/auth'
import { useBrokersStore } from '../stores/brokers'
import { useSystemStore } from '../stores/system'

const auth = useAuthStore()
const system = useSystemStore()
const brokers = useBrokersStore()
onMounted(() => brokers.load().catch(() => {}))

const checks = computed(() => [
  { title: 'Broker trading key connected', sub: 'Your own Dhan account, keys stored encrypted', ok: brokers.hasLiveTradingKey, when: brokers.hasLiveTradingKey ? null : 'Settings' },
  { title: 'Strategy backtested', sub: 'Tested on at least 6 months of past data', ok: false, when: 'Phase 2' },
  { title: '10 trading days in paper mode', sub: 'Same strategy, simulated money, no surprises', ok: false, when: 'Phase 3' },
  { title: 'Static IP whitelisted on Dhan', sub: 'Required by Dhan for placing orders', ok: false, when: 'Phase 4' },
  { title: 'Your account switched to live', sub: 'You turn this on yourself', ok: auth.user?.trading_mode === 'live' },
  { title: 'Platform live mode on', sub: 'Set by the admin after SEBI and broker checks', ok: system.health?.trading_mode === 'live' },
])
const doneCount = computed(() => checks.value.filter((c) => c.ok).length)
const unlocked = computed(() => doneCount.value === checks.value.length)
</script>

<style scoped>
.locked-banner { display: flex; align-items: center; gap: 14px; padding: 16px 18px; border-radius: 14px; background: var(--live-soft); border: 1px solid color-mix(in srgb, var(--live) 30%, transparent); margin-bottom: 20px; }
.lb-icon { width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center; background: var(--surface); color: var(--live); flex: none; }
.lb-title { font-weight: 700; color: var(--live); }
.lb-text { color: var(--text); font-size: 0.92rem; }
.check { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; flex: none; }
.check.ok { background: var(--good-soft); color: var(--good); }
.check.no { background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
.small { font-size: 0.9rem; margin-top: 0; }
.full { width: 100%; }
</style>
