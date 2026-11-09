// Built-in strategy templates (mirror of backend app/strategies/catalog.py).
export const TEMPLATES = [
  { key: 'orb', name: 'Opening Range Breakout', idea: 'Trade the break of the first minutes’ high or low.', section: 'intraday', timeframe: '5m', phase: 2 },
  { key: 'vwap_cross', name: 'VWAP Cross', idea: 'Price crosses VWAP with strong volume.', section: 'intraday', timeframe: '5m', phase: 2 },
  { key: 'supertrend', name: 'Supertrend', idea: 'Enter when the Supertrend line flips.', section: 'intraday', timeframe: '15m', phase: 2 },
  { key: 'ema_cross', name: 'EMA Crossover', idea: 'Fast EMA crosses the slow EMA.', section: 'swing', timeframe: '1d', phase: 5 },
  { key: 'rsi_reversal', name: 'RSI Reversal', idea: 'Buy oversold, sell overbought.', section: 'swing', timeframe: '1d', phase: 5 },
  { key: 'breakout_volume', name: 'Volume Breakout', idea: 'New N-day high with high volume.', section: 'swing', timeframe: '1d', phase: 5 },
]

export const TEMPLATE_BY_KEY = Object.fromEntries(TEMPLATES.map((t) => [t.key, t]))

export const SECTION_LABEL = { intraday: 'Intraday', swing: 'Swing', options: 'Options', crypto: 'Crypto' }

// Sections a user can add strategies to today (options/crypto arrive in Phase 6).
export const ACTIVE_SECTIONS = ['intraday', 'swing']

export const STATUS_TONE = { draft: '', paper: 'accent', live: 'live', paused: 'warn' }

export function strategySummary(s) {
  const t = TEMPLATE_BY_KEY[s.template_key]
  const parts = [t?.name ?? s.template_key, s.params?.timeframe]
  const n = s.params?.symbols?.length ?? 0
  parts.push(n ? `${n} symbol${n === 1 ? '' : 's'}` : 'Scanner universe')
  return parts.filter(Boolean).join(' · ')
}
