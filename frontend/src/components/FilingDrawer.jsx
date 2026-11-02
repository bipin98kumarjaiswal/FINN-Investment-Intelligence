import React, { useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft, FileText, X } from 'lucide-react'
import { apiRequest } from '../lib/api.js'
import { CATEGORY_LABELS, dateTime, pdfStatusInfo } from '../lib/format.js'
import { Busy, ErrorPanel, FilingLink, Priority, Status } from './Elements.jsx'

export default function FilingDrawer({ filingId, onClose, onResearch }) {
  const [filing, setFiling] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(null); setFiling(null)
    apiRequest(`/announcements/${encodeURIComponent(filingId)}`, { signal: controller.signal })
      .then(setFiling)
      .catch(error => { if (error.name !== 'AbortError') setError(error.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [filingId, retry])

  useEffect(() => {
    const listener = event => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', listener)
    document.body.classList.add('drawer-open')
    return () => { window.removeEventListener('keydown', listener); document.body.classList.remove('drawer-open') }
  }, [onClose])

  const status = pdfStatusInfo(filing?.pdf_analysis_status)
  const breakdown = filing?.score_breakdown

  return <div className="drawer-layer" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
    <section className="filing-drawer" role="dialog" aria-modal="true" aria-label="Filing details">
      <header className="drawer-header"><button className="back-action" onClick={onClose} type="button"><ArrowLeft size={19}/> Back to briefing</button><button type="button" className="icon-button" aria-label="Close filing details" onClick={onClose}><X size={19}/></button></header>
      <div className="drawer-scroll">
        {loading ? <Busy label="Loading filing evidence…" /> : error ? <ErrorPanel message={error} onRetry={() => setRetry(v => v + 1)} /> : filing && <>
          <div className="drawer-topline"><Priority priority={filing.priority}/><span className="micro-copy">{dateTime(filing.published_at_utc)}</span></div>
          <p className="eyebrow space-top">{filing.company_name} · {filing.symbol}</p>
          <h2 className="drawer-title">{filing.subject}</h2>
          <div className="meta-flow"><Status>{CATEGORY_LABELS[filing.category] || filing.category}</Status><Status tone={status.tone}>{status.text}</Status></div>
          <section className="detail-block"><p className="section-kicker">01 / THE EVENT</p><h3>What happened</h3><p>{filing.what_happened || 'No exchange-provided summary available.'}</p></section>
          <section className="detail-block"><p className="section-kicker">02 / INVESTOR CONTEXT</p><h3>Why it matters</h3><p>{filing.why_it_matters || 'Investor implications have not been assessed.'}</p></section>
          <section className="detail-block score-card"><div className="score-heading"><div><p className="section-kicker">03 / TRANSPARENT PRIORITY</p><h3>How was this ranked?</h3></div><div className="score-number">{filing.score}<span>/100</span></div></div>
            <div className="score-rail"><span style={{width:`${Math.min(100, Math.max(0, Number(filing.score) || 0))}%`}} /></div>
            <div className="score-scale"><span>Routine · 0–39</span><span>Review · 40–69</span><span>High · 70+</span></div>
            <div className="score-math"><div><span>Initial score</span><strong>{breakdown?.stage1_score ?? filing.metadata_score ?? '—'}</strong></div><div><span>PDF adjustment</span><strong>{(breakdown?.pdf_adjustment ?? 0) > 0 ? '+' : ''}{breakdown?.pdf_adjustment ?? 0}</strong></div><div><span>Final score</span><strong>{breakdown?.final_score ?? filing.score}</strong></div></div>
            <div className="score-components"><p className="component-title">Scoring factors</p>{(breakdown?.components ?? []).map((part, i) => <div className="component-row" key={`${i}-${part.reason}`}><div><span>{part.reason}</span><small>{part.source === 'PDF' ? `PDF evidence${part.page ? ` · Page ${part.page}` : ''}` : 'NSE metadata / scoring rule'}</small></div><strong className={Number(part.points) < 0 ? 'down-points' : ''}>{Number(part.points) > 0 ? '+' : ''}{part.points}</strong></div>)}</div>
            <p className="minor-disclaimer">This is a review-priority score, not a prediction of stock movement or investment advice.</p>
          </section>
          {filing.pdf_evidence?.length > 0 && <section className="detail-block"><p className="section-kicker">04 / DOCUMENT EVIDENCE</p><h3>Evidence from the filing</h3>{filing.pdf_evidence.map((entry, i) => <blockquote className="evidence-quote" key={i}><span>Page {entry.page} · {entry.signal}</span><p>“{entry.excerpt}”</p></blockquote>)}</section>}
          {filing.pdf_analysis_status === 'skipped_too_large' && <div className="inline-notice"><AlertTriangle size={18}/><div><strong>Attachment not analysed</strong><p>The PDF exceeded the safe processing limit. The priority shown is based on NSE metadata only. Open the original document to investigate further.</p></div></div>}
          {filing.pdf_analysis_status === 'error' && <div className="inline-notice"><AlertTriangle size={18}/><div><strong>PDF analysis failed</strong><p>{filing.pdf_error || 'The document was inaccessible or could not be processed.'} Metadata-only priority is retained.</p></div></div>}
          <section className="source-box"><div className="source-box-icon"><FileText size={20}/></div><div><strong>Original NSE disclosure</strong><p>{filing.evidence_scope || 'Source: NSE announcement'}</p><FilingLink url={filing.source_url}/></div></section>
          <button type="button" className="button-dark large" onClick={()=>onResearch?.(filing.symbol)}>Research {filing.symbol} from primary reports</button>
          <p className="micro-copy">FINN highlights potentially material events. Verify figures and statements in the original filing before making decisions.</p>
        </>}
      </div>
    </section>
  </div>
}
