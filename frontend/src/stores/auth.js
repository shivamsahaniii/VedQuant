import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, tokenStore } from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(tokenStore.get())
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)

  function setToken(t) {
    token.value = t
    tokenStore.set(t)
  }

  async function signup(email, password) {
    const { access_token } = await authApi.signup(email, password)
    setToken(access_token)
    await loadMe()
  }

  async function login(email, password) {
    const { access_token } = await authApi.login(email, password)
    setToken(access_token)
    await loadMe()
  }

  async function loadMe() {
    user.value = await authApi.me()
    return user.value
  }

  function logout() {
    token.value = null
    user.value = null
    tokenStore.clear()
  }

  return { token, user, isLoggedIn, signup, login, loadMe, logout }
})
