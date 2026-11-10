// The single API client for the whole app.
import axios from 'axios'

const TOKEN_KEY = 'vq_token'

export const tokenStore = {
  get: () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set: (t) => {
    try { localStorage.setItem(TOKEN_KEY, t) } catch { /* storage blocked */ }
  },
  clear: () => {
    try { localStorage.removeItem(TOKEN_KEY) } catch { /* storage blocked */ }
  },
}

const api = axios.create({ baseURL: '/api', timeout: 15000 })

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let onUnauthorized = () => {}
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn }

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.startsWith('/auth/login')) {
      tokenStore.clear()
      onUnauthorized()
    }
    return Promise.reject(error)
  },
)

// Turn any API error into one readable sentence.
export function errorMessage(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        const field = d.loc?.[d.loc.length - 1]
        if (field === 'password' && d.type === 'string_too_short') {
          return `Password must be at least ${d.ctx?.min_length} characters`
        }
        if (field === 'email') return 'Enter a valid email address'
        return d.msg
      })
      .join('. ')
  }
  if (error?.code === 'ERR_NETWORK') return 'Cannot reach the server. Is the API running?'
  return 'Something went wrong. Please try again.'
}

export const authApi = {
  signup: (email, password) => api.post('/auth/signup', { email, password }).then((r) => r.data),
  login: (email, password) => api.post('/auth/login', { email, password }).then((r) => r.data),
  me: () => api.get('/auth/me').then((r) => r.data),
}

export const systemApi = {
  health: () => api.get('/health').then((r) => r.data),
}

export const brokersApi = {
  available: () => api.get('/brokers/available').then((r) => r.data),
  list: () => api.get('/brokers').then((r) => r.data),
  add: (broker, label) => api.post('/brokers', { broker, label }).then((r) => r.data),
  saveKeys: (id, purpose, fields) => api.put(`/brokers/${id}/credentials/${purpose}`, { fields }).then((r) => r.data),
  removeKeys: (id, purpose) => api.delete(`/brokers/${id}/credentials/${purpose}`).then((r) => r.data),
  test: (id) => api.post(`/brokers/${id}/test`, null, { timeout: 45000 }).then((r) => r.data),
  disconnect: (id) => api.delete(`/brokers/${id}`),
  dhanLogin: (id) => api.post(`/brokers/${id}/dhan/login`).then((r) => r.data),
  dhanComplete: (tokenId) => api.post('/brokers/dhan/complete', { token_id: tokenId }, { timeout: 45000 }).then((r) => r.data),
}

export const strategiesApi = {
  list: (section) => api.get('/strategies', { params: section ? { section } : {} }).then((r) => r.data),
  create: (payload) => api.post('/strategies', payload).then((r) => r.data),
  update: (id, changes) => api.patch(`/strategies/${id}`, changes).then((r) => r.data),
  remove: (id) => api.delete(`/strategies/${id}`),
  setStatus: (id, status) => api.post(`/strategies/${id}/status`, { status }).then((r) => r.data),
  builder: () => api.get('/strategies/builder').then((r) => r.data),
}

export const tradingApi = {
  signals: (params = {}) => api.get('/signals', { params }).then((r) => r.data),
  trades: (params = {}) => api.get('/trades', { params }).then((r) => r.data),
  summary: () => api.get('/trading/summary').then((r) => r.data),
  close: (id) => api.post(`/trades/${id}/close`).then((r) => r.data),
  killSwitch: () => api.post('/trading/kill-switch').then((r) => r.data),
}

export const connectorsApi = {
  list: () => api.get('/connectors').then((r) => r.data),
  savePreferences: (prefs) => api.put('/connectors/preferences', prefs).then((r) => r.data),
  request: (key) => api.post(`/connectors/${key}/request`).then((r) => r.data),
}

export const marketsApi = {
  holidays: () => api.get('/market/holidays').then((r) => r.data),
  catalog: (asset) => api.get('/markets/catalog', { params: asset ? { asset } : {} }).then((r) => r.data),
  watchlist: () => api.get('/markets/watchlist').then((r) => r.data),
  add: (item) => api.post('/markets/watchlist', item).then((r) => r.data),
  remove: (id) => api.delete(`/markets/watchlist/${id}`),
  candles: (symbol, exchange, timeframe, limit = 300) =>
    api.get('/market/candles', { params: { symbol, exchange, timeframe, limit } }).then((r) => r.data),
}

export default api
