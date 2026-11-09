<template>
  <div>
    <PageHeader icon="swing" title="Swing"
      subtitle="Hold trades for days or weeks using daily candles and a trailing stop loss." />

    <section class="stats">
      <StatTile label="Section capital" value="Not set" tone="muted" hint="Separate from intraday" icon="wallet" />
      <StatTile label="Holdings" value="0" hint="Positions held overnight" icon="layers" />
      <StatTile label="Unrealised P&L" :value="formatINR(0)" tone="muted" hint="On open holdings" icon="rupee" />
      <StatTile label="Trailing stop" value="Off" tone="muted" hint="Moves only in your favour" icon="shield" />
    </section>

    <div class="grid-2">
      <div class="stack">
      <SectionStrategies section="swing" />
      <div class="card">
        <div class="card-head"><h2>Holdings</h2><span class="tag">0</span></div>
        <div class="card-body flush">
          <div class="table-wrap">
            <table class="data">
              <thead><tr><th>Symbol</th><th>Strategy</th><th class="num">Qty</th><th class="num">Avg</th><th class="num">Days held</th><th class="num">P&amp;L</th></tr></thead>
            </table>
          </div>
          <EmptyState icon="swing" title="No swing holdings"
            text="Swing trades stay open across days. They show up here with their trailing stop level." tag="Phase 5" />
        </div>
      </div>
      </div>

      <aside class="stack">
        <div class="card">
          <div class="card-head"><h2>How swing works</h2></div>
          <ul class="list">
            <li><AppIcon name="intraday" class="muted" /><div class="li-main"><div class="li-title">Daily candles</div><div class="li-sub">Signals are checked once per day</div></div></li>
            <li><AppIcon name="swing" class="muted" /><div class="li-main"><div class="li-title">Held overnight</div><div class="li-sub">No auto square-off at 3:15 PM</div></div></li>
            <li><AppIcon name="shield" class="muted" /><div class="li-main"><div class="li-title">Trailing stop loss</div><div class="li-sub">Locks in profit as price moves up</div></div></li>
          </ul>
        </div>
        <div class="card">
          <div class="card-head"><h2>Swing templates</h2><span class="tag">Phase 5</span></div>
          <div class="card-body chips">
            <span class="tag">EMA Crossover</span><span class="tag">RSI Reversal</span><span class="tag">Volume Breakout</span>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import AppIcon from '../components/AppIcon.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionStrategies from '../components/SectionStrategies.vue'
import StatTile from '../components/StatTile.vue'
import { formatINR } from '../utils/format'
</script>

<style scoped>
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
