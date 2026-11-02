import React, { useEffect, useState } from 'react'
import { Search, BookOpen, ArrowUpRight, FileSearch, LoaderCircle, Sparkles, ShieldCheck, Plus, ChevronRight, AlertCircle, RefreshCw } from 'lucide-react'
import { apiRequest } from '../lib/api.js'
import { isLikelyResearchQuestion, companySearchHint } from '../lib/researchInput.js'
import { Busy, ErrorPanel, EmptyPanel } from '../components/Elements.jsx'
import { safeHttpUrl } from '../lib/format.js'

const TIP_QUESTIONS = [
  'What did management say about revenue growth and margins?',
  'What are the main business risks discussed in the annual report?',
  'How is free cash flow related to net profit?',
]

function SourceCard({ source }) {
  const href = safeHttpUrl(source.source_url)
  return <article className="research-source" id={`source-${source.id}`}>
    <div className="research-source-top"><span className="research-ref">{source.id} · p. {source.page}</span><span className="research-kind">{source.kind?.replaceAll('_',' ')}</span></div>
    <strong>{source.title}</strong>
    <p>{source.excerpt}</p>
    {href && <a className="research-source-link" href={`${href.split('#')[0]}#page=${source.page}`} target="_blank" rel="noopener noreferrer">Open original PDF, page {source.page} <ArrowUpRight size={15}/></a>}
  </article>
}

function DocumentCard({ document }) {
  const href = safeHttpUrl(document.source_url)
  return <div className="research-document"><FileSearch size={19} /><div><strong>{document.title}</strong><span>{document.kind.replaceAll('_',' ')} · {document.page_count} pages · {document.period || 'Period unspecified'}</span></div>{href && <a aria-label={`Open ${document.title}`} href={href} target="_blank" rel="noopener noreferrer"><ArrowUpRight size={17}/></a>}</div>
}

export default function Research({ initialSymbol='', onClearInitial }) {
  const [search,setSearch]=useState(initialSymbol)
  const [found,setFound]=useState([])
  const [lookupError,setLookupError]=useState('')
  const [company,setCompany]=useState(null)
  const [docs,setDocs]=useState([])
  const [candidates,setCandidates]=useState([])
  const [status,setStatus]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [candidateBusy,setCandidateBusy]=useState(false)
  const [addOpen,setAddOpen]=useState(false)
  const [form,setForm]=useState({title:'',url:'',kind:'annual_report',published_on:'',period:''})
  const [question,setQuestion]=useState('')
  const [answer,setAnswer]=useState(null)
  const [asking,setAsking]=useState(false)
  const [metric,setMetric]=useState('revenue_growth')
  const [period,setPeriod]=useState('FY2026')
  const [guidance,setGuidance]=useState(null)

  // STEP 1: resolve a company ticker. Full questions belong only to Step 2.
  useEffect(()=>{
    const query = search.trim()
    if (!query) { setFound([]); setLookupError(''); return }
    if (isLikelyResearchQuestion(query)) {
      setFound([])
      setLookupError(companySearchHint(query))
      return  // never send an invalid >60-char query to FastAPI
    }
    const controller = new AbortController()
    const handle = setTimeout(() => apiRequest(`/research/search?q=${encodeURIComponent(query)}`, {signal:controller.signal})
      .then(r => { setFound(r.companies || []); setLookupError('') })
      .catch(e => { if (e.name!=='AbortError') setLookupError('Unable to search NSE companies right now. Check the backend connection.') }), 270)
    return ()=>{ clearTimeout(handle); controller.abort() }
  }, [search])

  useEffect(()=>{
    if (initialSymbol) {setSearch(initialSymbol);selectCompany(initialSymbol);onClearInitial?.()}
  },[initialSymbol])

  async function selectCompany(symbol) {
    setCompany(null);setAnswer(null);setGuidance(null);setCandidates([]);setError('');setStatus('');setBusy(true)
    try {
      const data=await apiRequest(`/research/${encodeURIComponent(symbol)}/documents`)
      setCompany(data.company);setDocs(data.documents);setSearch(data.company.symbol);setFound([])
    } catch(e){setError(e.message)} finally{setBusy(false)}
  }

  async function loadDocuments() {
    if (!company) return
    const data=await apiRequest(`/research/${encodeURIComponent(company.symbol)}/documents`)
    setDocs(data.documents)
  }

  async function loadCandidates() {
    setCandidateBusy(true);setError('');setStatus('')
    try {
      const r=await apiRequest(`/research/${encodeURIComponent(company.symbol)}/candidates?days=90`)
      setCandidates(r.candidates||[])
      setStatus(r.count?`${r.count} potential primary-source PDF(s) found on NSE.`:'No qualifying NSE attachments found in the last 90 days. You can add an official PDF URL.')
    }catch(e){setError(e.message)}finally{setCandidateBusy(false)}
  }

  async function addDocument(e) {
    e.preventDefault();setError('');setStatus('');setBusy(true)
    try {
      const result=await apiRequest('/research/documents',{method:'POST',body:{...form,symbol:company.symbol,published_on:form.published_on||null,period:form.period||null}})
      setStatus(`${result.document.chunk_count} page-level passages available. ${result.document.cached?'Loaded from cache.':'Source PDF indexed.'}`)
      setAddOpen(false);setForm({title:'',url:'',kind:'annual_report',published_on:'',period:''})
      await loadDocuments()
    }catch(e){setError(e.message)}finally{setBusy(false)}
  }

  async function ask(e) {
    e.preventDefault();setAnswer(null);setError('');setAsking(true)
    try{setAnswer(await apiRequest('/research/ask',{method:'POST',body:{symbol:company.symbol,question}}))}
    catch(e){setError(e.message)}finally{setAsking(false)}
  }

  async function compare(e) {
    e.preventDefault();setGuidance(null);setError('');setAsking(true)
    try{setGuidance(await apiRequest('/research/guidance',{method:'POST',body:{symbol:company.symbol,metric,period}}))}
    catch(e){setError(e.message)}finally{setAsking(false)}
  }

  function candidateImport(c) {
    setForm({title:c.title||'',kind:c.kind,url:c.url,published_on:'',period:''})
    setAddOpen(true)
  }

  return <div className="page-layout research-layout"><main className="primary-column">
    <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> SOURCE-GROUNDED RESEARCH</div><h1>Investigate<span className="heading-period">.</span></h1><p className="heading-description">Ask better questions. Get evidence from the actual documents.</p></div></div>
    <div className="research-step-heading"><span className="research-step-number">01</span><div><strong>Choose a company</strong><p>Search for a ticker or company name, not a research question.</p></div></div>
    <div className="research-search"><Search size={19}/><input aria-label="Company ticker or company name — Step 1" value={search} onChange={e=>{setSearch(e.target.value);if(company && e.target.value!==company.symbol) setCompany(null)}} placeholder="Company or NSE symbol, e.g. INFY" /></div>
    {!company && search.trim() && <div className="research-suggestions">{found.map(item=><button type="button" key={item.symbol} onClick={()=>selectCompany(item.symbol)}><span><strong>{item.symbol}</strong><small>{item.name}</small></span><ChevronRight size={17}/></button>)}{!found.length && !lookupError && !isLikelyResearchQuestion(search) && <p>No matching ticker in the saved NSE catalog. Try another name or refresh the NSE list.</p>}</div>}
    {lookupError && <p className="research-notice warning" role="status">{lookupError}</p>}
    {busy&&!company&&<Busy label="Opening company research…"/>}
    {error&&<ErrorPanel message={error}/>}
    {!company&&!busy&&<section className="research-step-two-disabled" aria-label="Research question — Step 2">
      <div className="research-step-heading"><span className="research-step-number">02</span><div><strong>Ask FINN about this company</strong><p>Once you choose a ticker above, ask about risks, guidance, strategy or financial performance.</p></div></div>
      <textarea aria-label="Question input (select a company first)" placeholder="First choose a company to unlock research questions..." disabled rows={2}/>
    </section>}
    {company && <>
      <div className="research-company"><div className="company-mark">{company.symbol.slice(0,2)}</div><div><strong>{company.name}</strong><span>NSE: {company.symbol} · {docs.length} original document{docs.length!==1?'s':''} indexed</span></div><ShieldCheck size={20}/></div>
      <div className="research-section-heading"><div><h2>Primary-source library</h2><p>Annual reports, call transcripts and financial results</p></div><button className="button-outline" type="button" onClick={()=>setAddOpen(v=>!v)}><Plus size={16}/> Add PDF</button></div>
      {docs.length>0?<div className="research-doc-list">{docs.map(d=><DocumentCard key={d.id} document={d}/>)}</div>:<p className="research-notice">No research documents indexed for this company. Find NSE attachments or add a verified primary-source PDF URL. No research answer will be invented.</p>}
      {status && <p role="status" className="research-notice success">{status}</p>}
      <button type="button" className="research-discover" disabled={candidateBusy} onClick={loadCandidates}>{candidateBusy?<LoaderCircle className="spin" size={17}/>:<RefreshCw size={17}/>} Find recent NSE filings with documents</button>
      {candidates.length>0&&<div className="research-candidates">{candidates.map((c,i)=><div key={`${c.url}-${i}`}><span><strong>{c.title}</strong><small>{c.kind.replaceAll('_',' ')} · {c.published_at}</small></span><button type="button" className="button-outline" onClick={()=>candidateImport(c)}>Index PDF</button></div>)}</div>}
      {addOpen&&<form className="research-add" onSubmit={addDocument}>
        <h3>Add an official primary-source PDF</h3>
        <p>Use a genuine NSE/BSE attachment or verified company investor-relations PDF. Source access and size limits are checked before indexing.</p>
        <label>Document title<input required maxLength={180} value={form.title} onChange={e=>setForm(f=>({...f,title:e.target.value}))}/></label>
        <label>PDF URL<input required type="url" value={form.url} placeholder="https://.../annual-report.pdf" onChange={e=>setForm(f=>({...f,url:e.target.value}))}/></label>
        <div className="research-form-grid"><label>Document type<select value={form.kind} onChange={e=>setForm(f=>({...f,kind:e.target.value}))}><option value="annual_report">Annual report</option><option value="transcript">Earnings-call transcript</option><option value="results">Financial results</option><option value="presentation">Investor presentation</option></select></label><label>Published on (if known)<input type="date" value={form.published_on} onChange={e=>setForm(f=>({...f,published_on:e.target.value}))}/></label></div>
        <label>Reporting period (if known)<input value={form.period} maxLength={30} placeholder="FY2026 or Q2 FY2027" onChange={e=>setForm(f=>({...f,period:e.target.value}))}/></label>
        <div className="research-form-actions"><button type="submit" disabled={busy} className="button-dark">{busy?'Indexing PDF…':'Download and index'}</button><button type="button" className="button-outline" onClick={()=>setAddOpen(false)}>Cancel</button></div>
      </form>}
      <section className="research-chat"><div className="research-section-heading"><div><p className="research-step-label">STEP 02 · ASK A QUESTION</p><h2>Ask FINN about {company.symbol}</h2><p>Write your full question here. Answers come from indexed source pages.</p></div><Sparkles size={20}/></div>
        <div className="research-prompts">{TIP_QUESTIONS.map(q=><button key={q} type="button" onClick={()=>setQuestion(q)}>{q}</button>)}</div>
        <form onSubmit={ask} className="research-ask"><textarea aria-label="Question about primary documents" value={question} onChange={e=>setQuestion(e.target.value)} minLength={8} maxLength={800} placeholder={`Ask a question about ${company.name}...`} rows={3} required/><button type="submit" className="button-dark" disabled={asking||!docs.length}>{asking?'Checking sources…':'Ask with sources'} <ChevronRight size={16}/></button></form>
        {answer&&<div className="research-answer" role="status"><div className="research-answer-header"><ShieldCheck size={18}/><strong>{answer.status==='answered'?'Source-grounded answer':answer.status==='evidence_only'?'Source excerpts available':answer.status==='model_error'?'AI response unavailable':'Not enough evidence'}</strong></div><p className="research-answer-text">{answer.answer}</p>{answer.sources?.length>0&&<><h3>Referenced passages</h3><div className="research-sources">{answer.sources.map(s=><SourceCard key={s.id} source={s}/>)}</div></>}</div>}
      </section>
      <section className="research-chat research-guidance"><div className="research-section-heading"><div><h2>Guidance vs performance</h2><p>Compare only when periods, units and source dates align</p></div><BookOpen size={20}/></div>
        <form className="research-guidance-form" onSubmit={compare}><select aria-label="Metric" value={metric} onChange={e=>setMetric(e.target.value)}><option value="revenue_growth">Revenue growth</option><option value="operating_margin">Operating margin</option><option value="capex">Capital expenditure</option></select><input aria-label="Fiscal year" pattern="FY20[0-9]{2}" placeholder="FY2026" value={period} onChange={e=>setPeriod(e.target.value.toUpperCase())}/><button type="submit" disabled={asking||!docs.length} className="button-dark">Check evidence</button></form>
        {guidance&&<div className="research-answer"><h3>{guidance.status==='comparison_available'?'Matched guidance and actual':'Comparison not verified'}</h3><p>{guidance.reason}</p>{guidance.comparison&&<div className="research-compare"><div><span>Guidance</span><strong>{guidance.comparison.guidance.value} {guidance.comparison.unit}</strong><small>{guidance.comparison.guidance_source}</small></div><div><span>Actual</span><strong>{guidance.comparison.actual.value} {guidance.comparison.unit}</strong><small>{guidance.comparison.actual_source}</small></div><div><span>Difference</span><strong>{guidance.comparison.difference>0?'+':''}{guidance.comparison.difference}</strong><small>{guidance.comparison.difference_unit}</small></div></div>}{guidance.sources?.length>0&&<div className="research-sources">{guidance.sources.map(s=><SourceCard key={s.id} source={s}/>)}</div>}</div>}
      </section>
    </>}
  </main><aside className="insight-column"><div className="insight-card market-letter"><p className="card-overline">EVIDENCE, NOT OPINION</p><h2>Read less.<br/><em>Know more.</em></h2><p>Trace every research finding to its annual-report or earnings-call page.</p><div className="market-line"/><span>DISCOVER <span>→</span> RETRIEVE <span>→</span> VERIFY</span></div><div className="insight-card"><div className="aside-card-heading"><div className="aside-icon"><AlertCircle size={19}/></div><h3>Evidence first</h3></div><p>Research needs primary documents. Missing data is shown explicitly. AI synthesis is optional and never replaces source citations.</p></div></aside></div>
}
