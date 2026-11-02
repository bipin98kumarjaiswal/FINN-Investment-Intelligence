// Run against your EXISTING FastAPI server with its original SQLite database.
// Read-only: does not write or seed any sample financial records.
const BASE = process.env.FINN_API_URL ?? 'http://127.0.0.1:8000'

async function check(label, path, validate) {
  const response = await fetch(BASE + path, { signal: AbortSignal.timeout(8000) })
  if (!response.ok) throw Error(`${label}: HTTP ${response.status}`)
  const payload = await response.json()
  if (!validate(payload)) throw Error(`${label}: Unexpected JSON response shape`)
  console.log(`[OK] ${label}`)
  return payload
}

async function run() {
  await check('FastAPI health', '/health', x => x?.status === 'ok')
  const brief = await check('7-day briefing and counts', '/api/briefing?hours=168', x => !!x?.counts && Array.isArray(x.important))
  await check('Routine-expanded briefing', '/api/briefing?hours=168&include_routine=true', x => Array.isArray(x?.routine))
  const companies = await check('Portfolio prices', '/api/portfolio', x => Array.isArray(x?.companies) && Number.isInteger(x.count))
  await check('Alert preferences', '/api/preferences/alerts', x => typeof x?.volume_multiple === 'number' && Array.isArray(x.categories))
  const alerts = await check('Alert history', '/api/alerts?hours=720', x => Array.isArray(x?.alerts) && typeof x.count === 'number')
  const lookup = await check('Research ticker lookup', '/api/research/search?q=INFY', x => Array.isArray(x?.companies))
  await check('Research primary-source library', '/api/research/INFY/documents', x => Array.isArray(x?.documents))
  await check('Research evidence-only / empty response', '/api/research/INFY/documents', x => typeof x?.count === 'number')
  if (brief.important.length) {
    const docId = encodeURIComponent(brief.important[0].filing_id)
    await check('Individual filing evidence', `/api/announcements/${docId}`, x => typeof x?.priority === 'string' && !!x?.score_breakdown)
  } else {
    console.log('[INFO] No important saved filings in the last 7 days; expand the range or run a filing sync.')
  }
  const failed = (brief.filing_source_status ?? []).filter(x => x.status === 'error').length
  console.log(`\nReal stored records: ${companies.count} portfolio companies; ${companies.companies.filter(x => x.trade_date).length} with prices; ${brief.counts.all} seven-day filings; ${alerts.count} 30-day alerts; ${failed} failed NSE symbol syncs.`)
  if (companies.companies.every(x => !x.trade_date)) console.log('[WARN] No stored price data was found in this database; confirm FINN_DB_PATH and the backend working folder.')
  if (!brief.filing_source_status?.length) console.log('[WARN] No NSE sync history was found. The feed may be empty because the backend is using a fresh database.')
  console.log('No test rows were inserted or modified.')
}

run().catch(err => { console.error(`[FAILED] ${err.message}`); process.exitCode = 1 })
