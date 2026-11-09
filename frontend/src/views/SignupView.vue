<template>
  <AuthCard title="Create your account" subtitle="Start in paper mode. Connect your own broker later.">
    <form @submit.prevent="submit" novalidate>
      <label>Email
        <input v-model.trim="email" type="email" autocomplete="email" required autofocus />
      </label>
      <label>Password
        <input v-model="password" type="password" autocomplete="new-password" required />
        <span class="hint" :class="{ ok: password.length >= 10 }">At least 10 characters</span>
      </label>
      <label>Confirm password
        <input v-model="confirm" type="password" autocomplete="new-password" required />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn primary" :disabled="busy">{{ busy ? 'Creating account…' : 'Create account' }}</button>
    </form>
    <p class="switch">Already have an account? <RouterLink to="/login">Log in</RouterLink></p>
  </AuthCard>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AuthCard from '../components/AuthCard.vue'
import { useAuthStore } from '../stores/auth'
import { errorMessage } from '../api/client'

const auth = useAuthStore()
const router = useRouter()
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (password.value.length < 10) { error.value = 'Password must be at least 10 characters'; return }
  if (password.value !== confirm.value) { error.value = 'Passwords do not match'; return }
  busy.value = true
  try {
    await auth.signup(email.value, password.value)
    router.replace('/overview')
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>
