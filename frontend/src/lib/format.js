export const CATEGORY_LABELS = {
  results: 'Financial results', 'M&A': 'Mergers & acquisitions', fund_raise: 'Fund raising',
  management_change: 'Leadership', litigation: 'Legal & regulatory', insider_trading: 'Insider trading',
  earnings_call: 'Earnings call', investor_meetings: 'Investor meetings', credit_rating: 'Credit rating',
  dividend: 'Dividend', bonus_split: 'Bonus / split', capex: 'Capital expenditure',
  press_release: 'Company update', postal_ballot: 'Postal ballot', agm_egm: 'General meeting',
  pledging: 'Share pledging', unclassified: 'Other disclosure',
}

export function priorityLabel(priority) {
  return ({ high: 'High priority', review: 'Worth reviewing', routine: 'Routine' })[priority] ?? 'Unclassified'
}

export function indianMoney(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  return `₹${Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function numeric(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  return Number(value).toLocaleString('en-IN')
}

export function dateTime(value) {
  if (!value) return 'Date unavailable'
  const dt = new Date(value)
  return Number.isNaN(dt.getTime()) ? 'Date unavailable' : dt.toLocaleString('en-IN', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata',
  }) + ' IST'
}

export function dateOnly(value) {
  if (!value) return 'No trading date'
  const dt = new Date(`${value}T00:00:00+05:30`)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })
}

export function safeHttpUrl(value) {
  if (typeof value !== 'string' || !value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch { return null }
}

export function scoreSort(items) {
  return [...(items ?? [])].sort((a, b) =>
    (Number(b.score) || 0) - (Number(a.score) || 0) ||
    (Date.parse(b.published_at_utc) || 0) - (Date.parse(a.published_at_utc) || 0))
}

export function toDateTimeLocal(date) {
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return ''
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function customWindowParams(start, end) {
  if (!start || !end) throw new Error('Choose both a start and end time.')
  const first = new Date(start), last = new Date(end)
  if (!Number.isFinite(first.getTime()) || !Number.isFinite(last.getTime())) throw new Error('Enter valid dates.')
  if (last <= first) throw new Error('End time must be after start time.')
  if (last > new Date(Date.now() + 5 * 60 * 1000)) throw new Error('End time cannot be in the future.')
  if (last.getTime() - first.getTime() > 90 * 24 * 3600000) throw new Error('Maximum window is 90 days.')
  return { start: first.toISOString(), end: last.toISOString() }
}

export function pdfStatusInfo(status) {
  switch (status) {
    case 'ok': return { text: 'PDF examined', tone: 'success' }
    case 'skipped_too_large': return { text: 'PDF too large to analyse', tone: 'warning' }
    case 'error': return { text: 'PDF analysis unavailable', tone: 'warning' }
    case 'pending': return { text: 'PDF analysis pending', tone: 'neutral' }
    case 'no_attachment': return { text: 'No PDF attachment', tone: 'neutral' }
    case 'not_selected': return { text: 'Metadata review only', tone: 'neutral' }
    default: return { text: 'Metadata review only', tone: 'neutral' }
  }
}
