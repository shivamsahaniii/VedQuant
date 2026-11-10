<template>
  <div class="card">
    <div class="card-head">
      <h2>Profile</h2>
      <span class="tag cap">{{ auth.user?.role }} · {{ auth.user?.trading_mode }}</span>
    </div>

    <form class="pf" @submit.prevent="saveProfile">
      <label>Full name
        <input v-model="form.full_name" maxlength="80" autocomplete="name" placeholder="Your name" />
      </label>
      <label>Phone
        <input v-model="form.phone" maxlength="20" autocomplete="tel" inputmode="tel" placeholder="+91 98765 43210" />
        <span class="hint">Optional. For alerts later; never shown to other users.</span>
      </label>
      <label>Email (your login)
        <input v-model="form.email" type="email" maxlength="320" autocomplete="email" required />
      </label>
      <label v-if="emailChanged">Current password
        <input v-model="form.current_password" type="password" autocomplete="current-password" required />
        <span class="hint">Needed to change your login email.</span>
      </label>
      <p v-if="profileMsg" :class="profileOk ? 'ok' : 'error'" role="status">{{ profileMsg }}</p>
      <div class="actions">
        <button class="btn primary sm" type="submit" :disabled="busy || !profileDirty">{{ busy === 'profile' ? 'Saving…' : 'Save profile' }}</button>
        <span class="muted small" v-if="auth.user">Member since {{ since }}</span>
      </div>
    </form>

    <form class="pf sep" @submit.prevent="savePassword">
      <h3>Change password</h3>
      <!-- hidden username helps password managers attach the new password to the right login -->
      <input type="text" :value="auth.user?.email" autocomplete="username" hidden readonly />
      <label>Current password
        <input v-model="pw.current" type="password" autocomplete="current-password" required />
      </label>
      <label>New password
        <input v-model="pw.next" type="password" autocomplete="new-password" minlength="10" maxlength="128" required />
        <span class="hint">At least 10 characters.</span>
      </label>
      <label>Repeat new password
        <input v-model="pw.repeat" type="password" autocomplete="new-password" minlength="10" maxlength="128" required />
      </label>
      <p v-if="pwMsg" :class="pwOk ? 'ok' : 'error'" role="status">{{ pwMsg }}</p>
      <div class="actions">
        <button class="btn ghost sm" type="submit" :disabled="!!busy">{{ busy === 'password' ? 'Changing…' : 'Change password' }}</button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { authApi, errorMessage } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const form = reactive({ full_name: '', phone: '', email: '', current_password: '' })
const pw = reactive({ current: '', next: '', repeat: '' })
const busy = ref('')
const profileMsg = ref('')
const profileOk = ref(false)
const pwMsg = ref('')
const pwOk = ref(false)

function fill(u) {
  if (!u) return
  form.full_name = u.full_name || ''
  form.phone = u.phone || ''
  form.email = u.email
  form.current_password = ''
}
watch(() => auth.user, fill, { immediate: true })

const emailChanged = computed(() => !!auth.user && form.email.trim().toLowerCase() !== auth.user.email)
const profileDirty = computed(() => !!auth.user && (emailChanged.value || form.full_name.trim() !== (auth.user.full_name || '') || form.phone.trim() !== (auth.user.phone || '')))
const since = computed(() => new Date(auth.user.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }))

async function saveProfile() {
  busy.value = 'profile'; profileMsg.value = ''
  try {
    const body = { full_name: form.full_name, phone: form.phone }
    if (emailChanged.value) Object.assign(body, { email: form.email, current_password: form.current_password })
    auth.user = await authApi.updateProfile(body)
    profileOk.value = true; profileMsg.value = 'Profile saved.'
  } catch (e) {
    profileOk.value = false; profileMsg.value = errorMessage(e)
  } finally { busy.value = '' }
}

async function savePassword() {
  pwMsg.value = ''
  if (pw.next !== pw.repeat) { pwOk.value = false; pwMsg.value = 'The two new passwords do not match.'; return }
  busy.value = 'password'
  try {
    await authApi.changePassword(pw.current, pw.next)
    pw.current = pw.next = pw.repeat = ''
    pwOk.value = true; pwMsg.value = 'Password changed. Use the new one next time you log in.'
  } catch (e) {
    pwOk.value = false; pwMsg.value = errorMessage(e)
  } finally { busy.value = '' }
}
</script>

<style scoped>
.pf { padding: 16px 18px; gap: 12px; }
.pf.sep { border-top: 1px solid var(--border); }
.pf h3 { margin: 0; font-size: 0.95rem; }
.actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.small { font-size: 0.8rem; }
.cap { text-transform: capitalize; }
.ok { margin: 0; padding: 8px 12px; border-radius: var(--radius-sm); background: var(--good-soft); color: var(--good); font-size: 0.85rem; }
.error { margin: 0; }
input { width: 100%; }
</style>
