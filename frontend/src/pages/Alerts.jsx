import React, { useEffect, useMemo, useState } from 'react'
import { Activity, ArrowRight, Bell, Check, ChevronRight, FileText, Gauge, RotateCcw, Settings2, SlidersHorizontal, Volume2, X } from 'lucide-react'
import { apiRequest } from '../lib/api.js'
import { CATEGORY_LABELS, dateTime } from '../lib/format.js'
import { Busy, EmptyPanel, ErrorPanel } from '../components/Elements.jsx'

const allCategories = Object.entries(CATEGORY_LABELS)

function SettingsPanel({ onClose, onSaved }) {
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true
    apiRequest('/preferences/alerts').then(payload => { if (active) setSettings(payload) })
      .catch(e => { if (active) setError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  useEffect(() => {
    const listener = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', listener)
    return () => document.removeEventListener('keydown', listener)
  }, [onClose])

  function toggleCategory(category) {
    setSaved(false)
    setSettings(prev => ({...prev, categories: prev.categories.includes(category)
      ? prev.categories.filter(v => v !== category) : [...prev.categories, category]}))
  }

  async function submit(e) {
    e.preventDefault(); setError(''); setSaved(false)
    const price = Number(settings.price_change_pct), volume = Number(settings.volume_multiple), lookback = Number(settings.volume_lookback)
    if (!Number.isFinite(price) || price <= 0 || price > 50 || !Number.isFinite(volume) || volume < 1.1 || volume > 20 || !Number.isInteger(lookback) || lookback < 5 || lookback > 60) {
      setError('Check thresholds: price 0–50%, volume 1.1–20×, and lookback 5–60 sessions.'); return
    }
    setSaving(true)
    try {
      const result = await apiRequest('/preferences/alerts', { method: 'PUT', body: {
        price_change_pct: price, volume_multiple: volume, volume_lookback: lookback, categories: settings.categories,
      } })
      setSettings(result.settings); setSaved(true); onSaved()
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }

  return <div className="drawer-layer" role="presentation" onMouseDown={e => {if (e.target===e.currentTarget) onClose()}}><section className="settings-drawer" role="dialog" aria-modal="true" aria-label="Alert preferences"><header className="drawer-header"><strong><Settings2 size={18}/> Alert preferences</strong><button className="icon-button" type="button" aria-label="Close settings" onClick={onClose}><X size={19}/></button></header><div className="settings-body">
    {loading ? <Busy label="Loading saved preferences…"/> : !settings ? <ErrorPanel message={error || 'Unable to read preferences.'} /> : <form onSubmit={submit}>
      <p className="settings-lead">Make FINN useful for the way you follow your portfolio. Changes are saved to your local backend.</p>
      <div className="setting-row"><div><label htmlFor="price-alert">Daily price movement</label><p>Alert when the close-to-close change exceeds ±X%.</p></div><div className="number-unit"><input id="price-alert" type="number" min="0.1" max="50" step="0.5" required value={settings.price_change_pct} onChange={e=>{setSaved(false);setSettings(v=>({...v,price_change_pct:e.target.value}))}}/><span>%</span></div></div>
      <div className="setting-row"><div><label htmlFor="volume-alert">Unusual trading volume</label><p>Alert when the volume exceeds X times its previous-session average.</p></div><div className="number-unit"><input id="volume-alert" type="number" min="1.1" max="20" step="0.1" required value={settings.volume_multiple} onChange={e=>{setSaved(false);setSettings(v=>({...v,volume_multiple:e.target.value}))}}/><span>×</span></div></div>
      <div className="setting-row"><div><label htmlFor="lookback">Volume lookback</label><p>Average of the previous trading sessions, excluding the current session.</p></div><div className="number-unit"><input id="lookback" type="number" min="5" max="60" step="1" required value={settings.volume_lookback} onChange={e=>{setSaved(false);setSettings(v=>({...v,volume_lookback:e.target.value}))}}/><span>days</span></div></div>
      <div className="settings-categories"><div className="categories-heading"><h3>Important filing categories</h3><span>{settings.categories.length} selected</span></div><p>Select which non-routine filings should trigger in-app alerts.</p><div className="category-grid">{allCategories.map(([value,label]) => <label className={`category-check ${settings.categories.includes(value)?'selected':''}`} key={value}><input type="checkbox" checked={settings.categories.includes(value)} onChange={()=>toggleCategory(value)}/><span>{label}</span>{settings.categories.includes(value) && <Check size={15}/>}</label>)}</div></div>
      <div className="settings-footer">{error && <p role="alert" className="form-error">{error}</p>}{saved && <p role="status" className="save-success"><Check size={16}/> Saved. Alerts recalculated from stored observations.</p>}<button type="submit" className="button-dark large" disabled={saving}>{saving?'Saving and recalculating…':'Save preferences'} <ArrowRight size={17}/></button><p className="micro-copy">Alerts are generated from stored exchange filings and end-of-day bars, not real-time intraday notifications.</p></div>
    </form>}
  </div></section></div>
}

export default function Alerts({ onSelectFiling }) {
  const [filter, setFilter] = useState('all')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [data, setData] = useState(null)
  const [preferences, setPreferences] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setError(''); setLoading(true)
    Promise.all([
      apiRequest('/alerts?hours=720', {signal:controller.signal}),
      apiRequest('/preferences/alerts', {signal:controller.signal}),
    ]).then(([alerts, prefs]) => { setData(alerts); setPreferences(prefs) })
      .catch(e => { if (e.name !== 'AbortError') setError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [version])

  const alerts = useMemo(() => (data?.alerts || []).filter(x => filter === 'all' || x.alert_type === filter), [data, filter])
  const icons = { price: Activity, volume: Volume2, filing: FileText }
  return <div className="page-layout alerts-layout"><main className="primary-column"><div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> PERSONALISED MONITORING</div><h1>Alerts<span className="heading-period">.</span></h1><p className="heading-description">Your definitions of unusual. Your investment universe.</p></div><button className="icon-button heading-refresh" onClick={()=>setVersion(v=>v+1)} aria-label="Refresh alerts" type="button"><RotateCcw size={19}/></button></div>
    <div className="alert-settings-banner"><div className="alert-banner-icon"><SlidersHorizontal size={23}/></div><div><strong>You're in control</strong><p>{preferences ? `Price ±${preferences.price_change_pct}% · Volume ${preferences.volume_multiple}× · ${preferences.volume_lookback}-session average` : 'Set your own price, volume and filing triggers.'}</p></div><button className="button-dark" type="button" onClick={()=>setSettingsOpen(true)}>Configure <ChevronRight size={17}/></button></div>
    <div className="feed-heading alert-feed-heading"><div><h2>Triggered signals</h2><p>Last 30 days of generated, stored alerts</p></div><span className="results-count">{data?.count ?? '—'} total</span></div>
    <div className="alert-filters" role="group" aria-label="Filter alerts">{[['all','All'],['filing','Filings'],['price','Price'],['volume','Volume']].map(([value,label])=><button key={value} type="button" className={filter===value?'active':''} onClick={()=>setFilter(value)}>{label}</button>)}</div>
    {error && <ErrorPanel message={error} onRetry={()=>setVersion(v=>v+1)}/>}{loading ? <Busy label="Reading your alert history…"/> : !error && <>{alerts.length===0 ? <EmptyPanel icon={Bell} title="No triggered alerts" message="No stored alerts match this filter and 30-day window. This is not a live-market monitoring guarantee."/> : <div className="alert-list">{alerts.map(alert=>{const Icon=icons[alert.alert_type] || Bell; return <article className="alert-record" key={alert.alert_id}><div className={`alert-type-icon alert-type-${alert.alert_type}`}><Icon size={20}/></div><div className="alert-record-main"><div className="alert-record-top"><span>{alert.symbol} · {alert.alert_type==='filing'?'FILING':alert.alert_type==='price'?'PRICE MOVEMENT':'VOLUME SPIKE'}</span><time>{dateTime(alert.event_time_utc)}</time></div><h3>{alert.headline}</h3><p>{alert.explanation}</p><div className="alert-record-foot">{alert.alert_type==='filing' && alert.details?.filing_id ? <button type="button" className="inline-action" onClick={()=>onSelectFiling(alert.details.filing_id)}>Investigate filing <ArrowRight size={15}/></button> : alert.alert_type === 'price' ? <span>Observed change: {Number(alert.details?.price_change_pct).toFixed(2)}%</span> : <span>Observed multiple: {Number(alert.details?.volume_ratio).toFixed(2)}×</span>}</div></div></article>})}</div>}</>}
    <div className="source-footnote"><Gauge size={16}/><p>Market alerts use end-of-day data. Recomputed alerts are based on stored observations, so editing settings does not create a continuous push-notification service.</p></div>
  </main><aside className="insight-column"><div className="insight-card market-letter compact-letter"><p className="card-overline">SIGNAL, NOT SPECULATION</p><h2>Numbers first.<br/><em>Context next.</em></h2><p>A price or volume alert flags an observation. It does not explain why the market moved.</p></div><div className="insight-card"><h3>Thresholds & scope</h3><p>Alerts depend on the completeness of your saved market observations and NSE filing refreshes.</p><button className="aside-link" type="button" onClick={()=>setSettingsOpen(true)}>Review your rules <ArrowRight size={17}/></button></div></aside>
    {settingsOpen && <SettingsPanel onClose={()=>setSettingsOpen(false)} onSaved={()=>setVersion(v=>v+1)}/>}</div>
}
