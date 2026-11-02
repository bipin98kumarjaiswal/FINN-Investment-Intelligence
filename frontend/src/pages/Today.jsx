import React, { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Bell, CalendarDays, ChevronDown, ChevronRight, ChevronUp, Clock3, FileText, RefreshCw, ShieldAlert, Sparkles } from 'lucide-react'
import { apiRequest, briefingPath } from '../lib/api.js'
import { CATEGORY_LABELS, customWindowParams, dateTime, pdfStatusInfo, priorityLabel, scoreSort, toDateTimeLocal } from '../lib/format.js'
import { Busy, EmptyPanel, ErrorPanel, FilingLink, Priority } from '../components/Elements.jsx'

function FilingCard({ filing, onSelect }) {
  const info = pdfStatusInfo(filing.pdf_analysis_status)
  return <article className={`filing-card ${filing.priority === 'high' ? 'filing-card-high' : ''}`}>
    <div className="filing-card-top"><div className="company-mark">{String(filing.symbol || '?').slice(0, 2)}</div><div className="company-main"><strong>{filing.company_name || filing.symbol}</strong><span>{filing.symbol} <span className="middle-dot">·</span> {dateTime(filing.published_at_utc)}</span></div><Priority compact priority={filing.priority}/></div>
    <p className="card-category">{CATEGORY_LABELS[filing.category] || filing.category}</p>
    <h3>{filing.subject}</h3>
    <p className="filing-excerpt">{filing.what_happened || 'NSE has not provided a description for this filing.'}</p>
    <div className="why-panel"><span>WHY IT MATTERS</span><p>{filing.why_it_matters || 'Review the source filing for context.'}</p></div>
    <div className="filing-card-bottom"><div className="card-state"><span className="card-score">{filing.score}/100</span><span className="score-divider"/><span title={info.text}>{info.text}</span></div><div className="filing-actions"><FilingLink url={filing.source_url} label="Original" compact/><button className="read-action" type="button" onClick={() => onSelect(filing.filing_id)}>Investigate <ArrowRight size={16}/></button></div></div>
  </article>
}

function SyncMessage({ statuses }) {
  if (!statuses) return null
  const failures = statuses.filter(item => item.status === 'error')
  const missing = statuses.length === 0
  if (!missing && failures.length === 0) return null
  return <div className="sync-alert"><ShieldAlert size={19}/><p>{missing ? 'No NSE synchronization history found. Run the filing sync in your backend before relying on this briefing.' : `${failures.length} of ${statuses.length} NSE symbol refreshes failed. Stored filings may be incomplete or stale. Please inspect /api/filings/status.`}</p></div>
}

export default function Today({ onSelectFiling, onOpenAlerts }) {
  const [mode, setMode] = useState('day')
  const [custom, setCustom] = useState(() => ({ from: toDateTimeLocal(new Date(Date.now() - 7 * 86400000)), until: toDateTimeLocal(new Date()) }))
  const [appliedRange, setAppliedRange] = useState(null)
  const [rangeError, setRangeError] = useState('')
  const [routineOpen, setRoutineOpen] = useState(false)
  const [refreshIndex, setRefreshIndex] = useState(0)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (mode === 'custom' && !appliedRange) return
    const controller = new AbortController()
    setLoading(true); setError('')
    const path = briefingPath({ mode, from: appliedRange?.start, until: appliedRange?.end, includeRoutine: routineOpen })
    apiRequest(path, { signal: controller.signal }).then(payload => {
      if (!payload || !payload.counts || !Array.isArray(payload.important)) throw new Error('Unexpected briefing response from backend.')
      setData(payload)
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [mode, appliedRange, routineOpen, refreshIndex])

  function chooseWindow(next) {
    setMode(next)
    setRoutineOpen(false)
    setRangeError('')
    if (next === 'custom') setAppliedRange(null)
  }

  function applyCustom(event) {
    event.preventDefault()
    try { const range = customWindowParams(custom.from, custom.until); setAppliedRange(range); setRangeError(''); setRoutineOpen(false) }
    catch (e) { setRangeError(e.message) }
  }

  const important = useMemo(() => scoreSort(data?.important || []), [data])
  const counts = data?.counts || { all: 0, high: 0, review: 0, routine: 0 }
  const currentDate = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  return <div className="page-layout today-layout">
    <main className="primary-column">
      <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> YOUR INVESTMENT INTELLIGENCE</div><h1>Today's brief<span className="heading-period">.</span></h1><p className="heading-description">The signals that deserve your attention, without the noise.</p></div><button className="icon-button heading-refresh" type="button" aria-label="Refresh briefing from stored data" title="Refresh stored briefing" onClick={() => setRefreshIndex(x => x + 1)}><RefreshCw size={20}/></button></div>
      <div className="briefing-toolbar"><div className="window-options" role="group" aria-label="Briefing period">{[['day','24 hours'],['week','7 days'],['month','30 days'],['custom','Custom']].map(([value,label]) => <button type="button" className={mode === value ? 'active' : ''} key={value} onClick={() => chooseWindow(value)}>{label}</button>)}</div><span className="toolbar-meta"><Clock3 size={14}/> {currentDate}</span></div>
      {mode === 'custom' && <form className="custom-range" onSubmit={applyCustom}><div><label htmlFor="from-date">From (your local time)</label><input type="datetime-local" id="from-date" required value={custom.from} onChange={e => setCustom(v => ({ ...v, from:e.target.value }))}/></div><div><label htmlFor="until-date">To (your local time)</label><input type="datetime-local" id="until-date" required value={custom.until} onChange={e => setCustom(v => ({ ...v, until:e.target.value }))}/></div><button type="submit" className="button-dark">Apply range</button>{rangeError && <p className="form-error" role="alert">{rangeError}</p>}</form>}
      {mode === 'custom' && !appliedRange ? <EmptyPanel icon={CalendarDays} title="Choose your window" message="Pick a start and end time to load filings from that period."/> : <>
        {error && <ErrorPanel message={error} onRetry={() => setRefreshIndex(x => x+1)} />}
        {loading ? <Busy label="Reading your stored exchange filings…"/> : !error && data && <>
          <SyncMessage statuses={data.filing_source_status}/>
          <div className="briefing-summary"><div className="summary-lead"><Sparkles size={18}/><span>YOUR ATTENTION SNAPSHOT</span></div><div className="summary-counts"><div><strong>{counts.high}</strong><span>High priority</span></div><span className="summary-rule"/><div><strong>{counts.review}</strong><span>Worth reviewing</span></div><span className="summary-rule"/><div><strong>{counts.routine}</strong><span>Routine</span></div></div></div>
          <div className="feed-heading"><div><h2>Worth your attention</h2><p>Ranked by materiality score, not just recency</p></div><span className="results-count">{important.length} filings</span></div>
          {important.length ? <div className="filing-feed">{important.map(filing => <FilingCard key={filing.filing_id} filing={filing} onSelect={onSelectFiling}/>)}</div> : <EmptyPanel icon={FileText} title="Nothing important in this window" message={counts.all ? 'Only routine disclosures were found. You can expand them below.' : 'No saved NSE filings were found for this period. This does not guarantee that no announcements occurred.'}>{mode === 'day' && <button className="button-dark" type="button" onClick={() => chooseWindow('week')}>Look back 7 days <ArrowRight size={16}/></button>}</EmptyPanel>}
          <section className="routine-section"><button className="routine-toggle" type="button" onClick={() => setRoutineOpen(v=>!v)} aria-expanded={routineOpen}><span className="routine-icon"><FileText size={19}/></span><span className="routine-title"><strong>Routine disclosures</strong><small>{counts.routine} filing{counts.routine===1?'':'s'} kept out of your way</small></span><span className="routine-right">{routineOpen?'Hide':'Show'} {routineOpen ? <ChevronUp size={19}/> : <ChevronDown size={19}/>}</span></button>{routineOpen && <div className="routine-list">{data.routine?.length ? data.routine.map(item => <button className="routine-row" type="button" key={item.filing_id} onClick={() => onSelectFiling(item.filing_id)}><span><strong>{item.symbol}</strong><small>{item.subject}</small></span><span className="routine-end">{dateTime(item.published_at_utc)} <ChevronRight size={16}/></span></button>) : <p className="routine-empty">No routine filings in this window.</p>}</div>}</section>
          <div className="source-footnote"><ShieldAlert size={16}/><p>{data.note || 'Briefing reflects stored observations from NSE; refresh times and coverage may vary.'}</p></div>
        </>}
      </>}
    </main>
    <aside className="insight-column">
      <div className="insight-card market-letter"><p className="card-overline">A CLEARER PICTURE</p><h2>Less noise.<br/><em>More signal.</em></h2><p>Every filing is scored, explained and linked back to its original NSE disclosure.</p><div className="market-line"/><span>DETECT <span>→</span> PRIORITIZE <span>→</span> INVESTIGATE</span></div>
      <div className="insight-card"><div className="aside-card-heading"><div className="aside-icon"><Bell size={19}/></div><h3>Your watchlist, your rules</h3></div><p>Decide what deserves a notification—from leadership changes to unusual daily volume.</p><button className="aside-link" type="button" onClick={onOpenAlerts}>Manage alerts <ArrowRight size={17}/></button></div>
      <div className="insight-mini"><span className="insight-dot"/><p><strong>Built for investor judgment.</strong><br/> Scores are explainable and do not predict returns.</p></div>
    </aside>
  </div>
}
