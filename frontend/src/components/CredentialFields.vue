<template>
  <div class="cred-fields">
    <label v-for="f in specs" :key="f.name">
      <span class="lbl">{{ f.label }}<span v-if="f.secret" class="lock"><AppIcon name="lock" :size="11" /> encrypted</span></span>
      <div class="input-wrap">
        <!-- Browsers must never autofill the user's login email/password into broker key
             fields: unique names, "new-password"/"off", password-manager opt-outs, and
             read-only until focused (autofill skips read-only inputs). -->
        <input :type="f.secret && !shown[f.name] ? 'password' : 'text'" :value="modelValue[f.name] ?? ''"
          :name="`vq-broker-${f.name}`" :placeholder="placeholder(f)"
          :autocomplete="f.secret ? 'new-password' : 'off'" spellcheck="false" autocapitalize="off"
          data-lpignore="true" data-1p-ignore="true" data-bwignore="true"
          :readonly="!focused[f.name]" @focus="focused[f.name] = true"
          @input="update(f.name, $event.target.value)" />
        <button v-if="f.secret" type="button" class="reveal" :aria-label="shown[f.name] ? 'Hide' : 'Show'"
          @click="shown[f.name] = !shown[f.name]">{{ shown[f.name] ? 'Hide' : 'Show' }}</button>
      </div>
      <span v-if="f.help" class="hint">{{ f.help }}</span>
    </label>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import AppIcon from './AppIcon.vue'

// specs: [{ name, label, secret, help }]; saved: { fieldName: { last4, value } } for existing keys.
const props = defineProps({ specs: Array, modelValue: Object, saved: { type: Object, default: () => ({}) } })
const emit = defineEmits(['update:modelValue'])
const shown = reactive({})
const focused = reactive({})

function update(name, value) {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}

function placeholder(f) {
  const s = props.saved[f.name]
  if (!s) return f.secret ? 'Paste here' : ''
  return f.secret ? `Saved ••••${s.last4 ?? ''}. Leave empty to keep it` : `Saved: ${s.value ?? ''}. Leave empty to keep it`
}
</script>

<style scoped>
.cred-fields { display: flex; flex-direction: column; gap: 14px; }
.lbl { display: flex; align-items: center; gap: 8px; }
.lock { display: inline-flex; align-items: center; gap: 3px; font-size: 0.72rem; font-weight: 500; color: var(--muted); }
.input-wrap { position: relative; display: flex; }
.input-wrap input { flex: 1; padding-right: 60px; font-family: ui-monospace, 'SFMono-Regular', monospace; font-size: 0.88rem; }
.reveal { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); border: 0; background: var(--surface-3); color: var(--text-2); font: inherit; font-size: 0.75rem; font-weight: 600; padding: 3px 8px; border-radius: 6px; cursor: pointer; }
</style>
