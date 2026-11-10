<template>
  <AuthCard title="Welcome back" subtitle="Log in to your VedQuant account">
    <p v-if="route.query.expired" class="notice">Your session ended. Please log in again.</p>
    <form @submit.prevent="submit" novalidate>
      <label>Email
        <input v-model.trim="email" type="email" autocomplete="email" required autofocus />
      </label>
      <label>Password
        <span class="pw-wrap">
          <input v-model="password" :type="show ? 'text' : 'password'" autocomplete="current-password"
            autocapitalize="off" autocorrect="off" spellcheck="false" required />
          <button type="button" class="pw-show" :aria-pressed="show" @click="show = !show">{{ show ? 'Hide' : 'Show' }}</button>
        </span>
        <span v-if="/^\s|\s$/.test(password)" class="hint warn">There is a space at the start or end. Remove it if it is not part of your password.</span>
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn primary" :disabled="busy">{{ busy ? 'Logging in…' : 'Log in' }}</button>
    </form>
    <p class="switch">New to VedQuant? <RouterLink to="/signup">Create an account</RouterLink></p>
  </AuthCard>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthCard from '../components/AuthCard.vue'
import { useAuthStore } from '../stores/auth'
import { errorMessage } from '../api/client'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const show = ref(false)
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (!email.value || !password.value) { error.value = 'Enter your email and password'; return }
  busy.value = true
  try {
    await auth.login(email.value, password.value)
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : '/'
    router.replace(next === '/' ? '/overview' : next)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.pw-wrap { position: relative; display: flex; }
.pw-wrap input { flex: 1; padding-right: 64px; }
.pw-show { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); border: 0; background: var(--surface-3); color: var(--text-2); font: inherit; font-size: 0.78rem; font-weight: 600; padding: 4px 9px; border-radius: 6px; cursor: pointer; }
.hint.warn { color: var(--warn); }
</style>
