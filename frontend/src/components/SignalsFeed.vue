<template>
  <div class="card">
    <div class="card-head">
      <div class="head-left">
        <h2>Live signals</h2>
        <span class="tag">{{ list.length }}</span>
      </div>
      <label class="toggle muted small">
        <input v-model="onlyActionable" type="checkbox" /> Only taken / suggested
      </label>
    </div>

    <ul v-if="shown.length" class="list sig-list">
      <li v-for="s in shown" :key="s.id" class="sig" @click="toggle(s.id)">
        <div class="sig-row">
          <span class="side" :class="s.side">{{ s.side === 'buy' ? 'BUY' : 'SELL' }}</span>
          <div class="li-main">
            <div class="li-title">{{ s.symbol }} <span class="muted">· {{ ruleName(s.rule) }}</span>
              <span v-if="s.strategy" class="muted"> · {{ s.strategy }}</span></div>
            <div class="li-sub">{{ s.reason }}</div>
          </div>
          <div class="right">
            <span class="tag" :class="SIGNAL_TONE[s.status]">{{ SIGNAL_LABEL[s.status] }}</span>
            <span class="muted small">{{ istTime(s.created_at) }}</span>
          </div>
        </div>
        <div class="why-line" :class="s.status">{{ s.status_reason || s.mood?.reason }}</div>

        <div v-if="openId === s.id" class="detail" @click.stop>
          <div v-if="s.plan" class="box">
            <div class="box-title">Plan</div>
            <dl class="kv">
              <dt>Entry</dt><dd>{{ s.plan.entry }}</dd>
              <dt>Stop loss</dt><dd>{{ s.plan.stop }} <span class="muted">({{ s.plan.stop_rule }})</span></dd>
              <dt>Target</dt><dd>{{ s.plan.target }} <span class="muted">({{ s.plan.reward_risk }}R)</span></dd>
              <dt>Flat by</dt><dd>{{ s.plan.flat_by }} IST</dd>
            </dl>
          </div>
          <div v-if="s.odds" class="box">
            <div class="box-title">Odds (time machine)</div>
            <template v-if="s.odds.available">
              <div class="odds-bar">
                <span class="t" :style="{ width: s.odds.target_first + '%' }" />
                <span class="n" :style="{ width: s.odds.neither + '%' }" />
                <span class="s" :style="{ width: s.odds.stop_first + '%' }" />
              </div>
              <dl class="kv">
                <dt>Target first</dt><dd>{{ s.odds.target_first }}%</dd>
                <dt>Stop first</dt><dd>{{ s.odds.stop_first }}%</dd>
                <dt>Neither by 15:15</dt><dd>{{ s.odds.neither }}%</dd>
              </dl>
              <p class="verdict">{{ s.odds.verdict }} <span class="muted">(needs {{ s.odds.breakeven }}% to break even, got {{ s.odds.win_share }}%)</span></p>
              <p class="muted tiny">{{ s.odds.replays }} replays from {{ s.odds.sessions }} past sessions, seed {{ s.odds.seed }}. A simulation, not a prediction.</p>
            </template>
            <p v-else class="muted small">{{ s.odds.reason }}</p>
          </div>
          <div v-if="s.risk" class="box">
            <div class="box-title">Risk check</div>
            <dl v-if="s.risk.ok" class="kv">
              <dt>Quantity</dt><dd>{{ s.risk.qty }} <span class="muted">({{ s.risk.sized_by }})</span></dd>
              <dt>Max loss</dt><dd>{{ formatINR(s.risk.max_loss) }}</dd>
              <dt>Target profit</dt><dd>{{ formatINR(s.risk.target_profit) }}</dd>
              <dt>Charges</dt><dd>{{ formatINR(s.risk.charges?.total) }}</dd>
            </dl>
            <p v-else class="small bad-text">{{ s.risk.reason }}</p>
          </div>
          <div class="box">
            <div class="box-title">Market mood</div>
            <p class="small">{{ s.mood?.summary || '—' }}</p>
            <p class="small" :class="s.mood?.ok ? 'good-text' : 'bad-text'">{{ s.mood?.reason }}</p>
          </div>
        </div>
      </li>
    </ul>
    <EmptyState v-else icon="signal" title="No signals yet"
      :text="emptyText" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import EmptyState from './EmptyState.vue'
import { SIGNAL_LABEL, SIGNAL_TONE, useTradingStore } from '../stores/trading'
import { formatINR } from '../utils/format'
import { TEMPLATE_BY_KEY } from '../utils/strategies'

const props = defineProps({ section: { type: String, default: '' }, limit: { type: Number, default: 30 } })
const trading = useTradingStore()
const onlyActionable = ref(false)
const openId = ref(null)
const list = computed(() => trading.signalsBySection(props.section))
const shown = computed(() => list.value.filter((s) => !onlyActionable.value || ['taken', 'suggested'].includes(s.status)).slice(0, props.limit))
const emptyText = 'Start paper trading a strategy. Every setup the agents find on a closed candle appears here with the reason it was taken, suggested, skipped or blocked.'

const ruleName = (k) => TEMPLATE_BY_KEY[k]?.name ?? k
const toggle = (id) => { openId.value = openId.value === id ? null : id }
const tf = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false })
const istTime = (iso) => tf.format(new Date(iso))
</script>

<style scoped>
.head-left { display: flex; align-items: center; gap: 8px; }
.toggle { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.small { font-size: 0.82rem; }
.tiny { font-size: 0.75rem; margin: 4px 0 0; }
.sig-list li.sig { display: block; cursor: pointer; }
.sig-row { display: flex; align-items: center; gap: 12px; }
.side { font-size: 0.72rem; font-weight: 700; padding: 4px 8px; border-radius: 6px; flex: none; letter-spacing: 0.04em; }
.side.buy { background: var(--good-soft); color: var(--good); }
.side.sell { background: var(--bad-soft); color: var(--bad); }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
.why-line { margin: 6px 0 0 52px; font-size: 0.82rem; color: var(--text-2); }
.why-line.blocked, .why-line.refused { color: var(--warn); }
.why-line.taken { color: var(--good); }
.detail { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 12px 0 4px 52px; cursor: default; }
.box { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 12px; background: var(--surface-2); }
.box p { margin: 0; }
.box-title { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 6px; }
.box .kv { font-size: 0.84rem; }
.odds-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--surface-3); margin-bottom: 8px; }
.odds-bar .t { background: var(--good); }
.odds-bar .n { background: var(--border-strong); }
.odds-bar .s { background: var(--bad); }
.verdict { font-weight: 600; font-size: 0.86rem; margin-top: 6px !important; }
.good-text { color: var(--good); }
.bad-text { color: var(--bad); }
@media (max-width: 760px) { .detail, .why-line { margin-left: 0; } }
</style>
