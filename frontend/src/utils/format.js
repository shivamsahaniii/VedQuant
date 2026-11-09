const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const formatINR = (value) => (value === null || value === undefined ? '—' : inr.format(Number(value)))

export const IST = 'Asia/Kolkata'

// NSE regular session: Mon–Fri 09:15–15:30 IST. Exchange holidays are not considered yet.
export function marketStatus(now = new Date()) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', { timeZone: IST, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
      .formatToParts(now)
      .map((p) => [p.type, p.value]),
  )
  const minutes = Number(parts.hour) * 60 + Number(parts.minute)
  const weekday = !['Sat', 'Sun'].includes(parts.weekday)
  if (!weekday) return { open: false, label: 'Market closed', detail: 'Weekend' }
  if (minutes < 9 * 60) return { open: false, label: 'Market closed', detail: 'Opens 09:15 IST' }
  if (minutes < 9 * 60 + 15) return { open: false, label: 'Pre-open', detail: 'Opens 09:15 IST' }
  if (minutes < 15 * 60 + 30) return { open: true, label: 'Market open', detail: 'Closes 15:30 IST' }
  return { open: false, label: 'Market closed', detail: 'Opens next weekday 09:15 IST' }
}

// "3 min ago", "in 5 h", ... for timestamps near now.
export function relativeTime(iso, now = new Date()) {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - now.getTime()) / 1000
  const abs = Math.abs(diff)
  const [n, unit] =
    abs < 60 ? [Math.round(abs), 's'] : abs < 3600 ? [Math.round(abs / 60), 'min'] : abs < 86400 ? [Math.round(abs / 3600), 'h'] : [Math.round(abs / 86400), 'd']
  if (abs < 10) return 'just now'
  return diff < 0 ? `${n} ${unit} ago` : `in ${n} ${unit}`
}

export function istDateTime(iso) {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-IN', { timeZone: IST, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(iso))
}

export function istClock(now = new Date()) {
  return new Intl.DateTimeFormat('en-IN', { timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: true }).format(now)
}
