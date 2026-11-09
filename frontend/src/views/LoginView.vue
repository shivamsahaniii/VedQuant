<template>
  <AuthCard title="Welcome back" subtitle="Log in to your VedQuant account">
    <p v-if="route.query.expired" class="notice">Your session ended. Please log in again.</p>
    <form @submit.prevent="submit" novalidate>
      <label>Email
        <input v-model.trim="email" type="email" autocomplete="email" required autofocus />
      </label>
      <label>Password
        <input v-model="password" type="password" autocomplete="current-password" required />
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
