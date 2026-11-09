<template>
  <BaseDialog :open="open" :locked="busy" width="560px" :eyebrow="account?.label"
    :title="`${hasSaved ? 'Replace' : 'Add'} ${purpose} keys`" @close="$emit('close')">
    <p class="muted small">
      {{ purpose === 'trading' ? 'Trading keys are used to place orders.' : 'Data keys are used for live prices and history.' }}
      Saving these does not change your {{ purpose === 'trading' ? 'data' : 'trading' }} keys.
    </p>
    <CredentialFields v-if="specs.length" :specs="specs" :saved="saved" v-model="values" />
    <p v-if="error" class="error">{{ error }}</p>

    <template #footer>
      <label class="check inline"><input type="checkbox" v-model="testAfter" /> Test connection after saving</label>
      <div class="foot-btns">
        <button class="btn ghost" :disabled="busy" @click="$emit('close')">Cancel</button>
        <button class="btn primary" :disabled="busy" @click="save">{{ busy ? 'Saving…' : 'Save keys' }}</button>
      </div>
    </template>
  </BaseDialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import BaseDialog from './BaseDialog.vue'
import CredentialFields from './CredentialFields.vue'
import { errorMessage } from '../api/client'
import { useBrokersStore } from '../stores/brokers'

const props = defineProps({ open: Boolean, account: Object, purpose: String })
const emit = defineEmits(['close', 'tested'])
const brokers = useBrokersStore()

const values = ref({})
const busy = ref(false)
const error = ref('')
const testAfter = ref(true)

const fields = computed(() => props.account?.credentials?.[props.purpose]?.fields ?? [])
const specs = computed(() => {
  const avail = brokers.available.find((b) => b.key === props.account?.broker)
  const help = Object.fromEntries((avail?.credential_fields?.[props.purpose] ?? []).map((f) => [f.name, f.help]))
  return fields.value.map((f) => ({ ...f, help: help[f.name] }))
})
const saved = computed(() => Object.fromEntries(fields.value.filter((f) => f.saved).map((f) => [f.name, f])))
const hasSaved = computed(() => Object.keys(saved.value).length > 0)

watch(() => props.open, (o) => { if (o) { values.value = {}; error.value = ''; testAfter.value = true } })

async function save() {
  error.value = ''
  const filled = Object.fromEntries(Object.entries(values.value).filter(([, v]) => v && v.trim()))
  if (!Object.keys(filled).length) { error.value = 'Enter at least one value to save.'; return }
  const missing = specs.value.filter((f) => f.required && !saved.value[f.name] && !filled[f.name])
  if (missing.length) { error.value = `Please fill: ${missing.map((f) => f.label).join(', ')}`; return }
  busy.value = true
  try {
    await brokers.saveKeys(props.account.id, props.purpose, filled)
    values.value = {}
    if (testAfter.value) emit('tested', await brokers.test(props.account.id))
    emit('close')
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.small { font-size: 0.88rem; margin: 0; }
.foot-btns { display: flex; gap: 8px; margin-left: auto; }
.check.inline { flex-direction: row; align-items: center; gap: 8px; font-size: 0.85rem; font-weight: 500; }
.check input { width: 16px; height: 16px; accent-color: var(--accent); box-shadow: none; }
</style>
