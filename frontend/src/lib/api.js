// Works with Phase 2.2 FastAPI as-is. In local development Vite proxies /api to :8000.
const API_ROOT = '/api'

export async function apiRequest(path, { signal, method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      signal, method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Could not connect to FINN. Start FastAPI on port 8000 and try again.')
  }
  let payload
  try { payload = await response.json() } catch { payload = null }
  if (!response.ok) {
    const detail = payload?.detail
    const message = typeof detail === 'string' ? detail
      : (Array.isArray(detail) ? detail.map(x => x.msg).join('; ') : null)
    throw new Error(message || `Request failed (${response.status}).`)
  }
  return payload
}

export function briefingPath({ mode, from, until, includeRoutine = false }) {
  const params = new URLSearchParams()
  if (mode === 'custom') {
    params.set('start', from)
    params.set('end', until)
  } else {
    params.set('hours', String(({ day: 24, week: 168, month: 720 })[mode] || 24))
  }
  if (includeRoutine) params.set('include_routine', 'true')
  return `/briefing?${params.toString()}`
}
