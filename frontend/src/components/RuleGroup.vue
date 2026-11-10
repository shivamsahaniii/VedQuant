<template>
  <fieldset class="rg" :class="side">
    <legend>
      <label class="switch">
        <input type="checkbox" :checked="!!modelValue" @change="toggle($event.target.checked)" />
        <span>{{ side === 'buy' ? 'Buy (go long) when…' : 'Sell (go short) when…' }}</span>
      </label>
    </legend>

    <template v-if="modelValue">
      <div v-if="modelValue.conditions.length > 1" class="match">
        <select v-model="modelValue.match" aria-label="How conditions combine">
          <option value="all">ALL of these are true</option>
          <option value="any">ANY one of these is true</option>
        </select>
      </div>

      <div v-for="(c, i) in modelValue.conditions" :key="i" class="cond">
        <div class="operand">
          <select v-model="c.left.kind" aria-label="Left side" @change="fix(c.left)">
            <option v-for="o in leftOptions" :key="o.kind" :value="o.kind">{{ o.label }}</option>
          </select>
          <input v-if="hasPeriod(c.left)" v-model.number="c.left.period" type="number" min="1" :max="meta(c.left).max_period" class="period" aria-label="Period" />
        </div>

        <select v-model="c.op" class="op" aria-label="Comparison">
          <option v-for="o in options.ops" :key="o.key" :value="o.key">{{ o.label }}</option>
        </select>

        <div class="operand">
          <select v-model="c.right.kind" aria-label="Right side" @change="fix(c.right)">
            <option v-for="o in options.operands" :key="o.kind" :value="o.kind">{{ o.label }}</option>
          </select>
          <input v-if="c.right.kind === 'number'" v-model.number="c.right.value" type="number" step="any" class="value" aria-label="Number" />
          <input v-else-if="hasPeriod(c.right)" v-model.number="c.right.period" type="number" min="1" :max="meta(c.right).max_period" class="period" aria-label="Period" />
          <label v-if="c.right.kind !== 'number'" class="mult" title="Multiply the right side, e.g. 1.5 × average volume">
            ×<input v-model.number="c.right.mult" type="number" min="0.01" max="100" step="0.01" aria-label="Multiplier" />
          </label>
        </div>

        <button type="button" class="icon-btn" :disabled="modelValue.conditions.length === 1" aria-label="Remove condition" @click="modelValue.conditions.splice(i, 1)">
          <AppIcon name="x" :size="15" />
        </button>
      </div>

      <button type="button" class="btn ghost sm add" :disabled="modelValue.conditions.length >= options.max_conditions" @click="add">
        <AppIcon name="plus" :size="14" /> Add condition
      </button>
    </template>
  </fieldset>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: Object, default: null },
  side: { type: String, required: true },
  options: { type: Object, required: true },
})
const emit = defineEmits(['update:modelValue'])

const leftOptions = computed(() => props.options.operands.filter((o) => o.kind !== 'number'))
const meta = (op) => props.options.operands.find((o) => o.kind === op.kind) ?? {}
const hasPeriod = (op) => meta(op).period != null

function fix(op) {
  const m = meta(op)
  op.period = m.period ?? null
  if (op.kind === 'number') { op.value = op.value ?? 0; op.mult = 1 } else op.value = null
}

const blank = () => ({
  left: { kind: 'close', period: null, value: null, mult: 1 },
  op: props.side === 'buy' ? 'crosses_above' : 'crosses_below',
  right: { kind: 'vwap', period: null, value: null, mult: 1 },
})

function toggle(on) {
  emit('update:modelValue', on ? { match: 'all', conditions: [blank()] } : null)
}
function add() { props.modelValue.conditions.push(blank()) }
</script>

<style scoped>
.rg { border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px 14px; margin: 0; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.rg.buy { border-left: 3px solid var(--good); }
.rg.sell { border-left: 3px solid var(--bad); }
legend { padding: 0 6px; }
.switch { flex-direction: row; align-items: center; gap: 8px; cursor: pointer; }
.switch input { box-shadow: none; }
.match select { width: auto; }
.cond { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px; border-radius: var(--radius-sm); background: var(--surface-2); }
.operand { display: flex; gap: 6px; align-items: center; flex: 1 1 200px; min-width: 0; }
.operand select { flex: 1; min-width: 0; }
.op { flex: 0 1 150px; }
.period { width: 70px; }
.value { width: 110px; }
.mult { flex-direction: row; align-items: center; gap: 4px; font-weight: 400; color: var(--muted); }
.mult input { width: 70px; }
select, input { padding: 7px 9px; font-size: 0.86rem; }
.icon-btn { border: 0; background: none; color: var(--muted); padding: 6px; border-radius: 8px; cursor: pointer; }
.icon-btn:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
.icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.add { align-self: flex-start; }
</style>
