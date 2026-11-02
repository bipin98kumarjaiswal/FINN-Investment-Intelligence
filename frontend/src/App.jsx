import React, { useCallback, useState } from 'react'
import { Activity, Bell, Compass, Layers3, ShieldCheck, BookOpen } from 'lucide-react'
import FilingDrawer from './components/FilingDrawer.jsx'
import Today from './pages/Today.jsx'
import Alerts from './pages/Alerts.jsx'
import Portfolio from './pages/Portfolio.jsx'
import Research from './pages/Research.jsx'

const NAV = [
  { key:'today', label:'Today', Icon:Compass, caption:'Daily briefing' },
  { key:'alerts', label:'Alerts', Icon:Bell, caption:'Your signals' },
  { key:'portfolio', label:'Portfolio', Icon:Layers3, caption:'16 companies' },
  { key:'research', label:'Research', Icon:BookOpen, caption:'Primary-source Q&A' },
]

export default function App() {
  const [page,setPage] = useState('today')
  const [filingId,setFilingId] = useState(null)
  const [researchSymbol,setResearchSymbol] = useState('')
  const closeFiling = useCallback(()=>setFilingId(null),[])
  return <div className="app-shell">
    <aside className="desktop-rail">
      <button className="brand" type="button" onClick={()=>setPage('today')} aria-label="FINN home"><div className="brand-mark"><Activity size={22} strokeWidth={2.5}/></div><span>FINN<span className="brand-dot">.</span></span></button>
      <p className="nav-overline">WORKSPACE</p>
      <nav className="desktop-nav" aria-label="Main navigation">{NAV.map(({key,label,Icon,caption})=><button type="button" key={key} onClick={()=>setPage(key)} className={`desktop-nav-item ${page===key?'active':''}`} aria-current={page===key?'page':undefined}><Icon size={20} strokeWidth={1.8}/><span><strong>{label}</strong><small>{caption}</small></span>{page===key&&<span className="active-rail-dot"/>}</button>)}</nav>
      <div className="rail-bottom"><div className="rail-foot-icon"><ShieldCheck size={18}/></div><div><strong>Source-first</strong><span>Grounded in real filings</span></div></div>
    </aside>
    <div className="workspace">
      <header className="top-bar"><div className="mobile-brand"><div className="brand-mark"><Activity size={19}/></div><span>FINN<span className="brand-dot">.</span></span></div><div className="top-bar-left"><span className="live-indicator"/><strong>Investment intelligence</strong><span className="top-bar-separator"/><span>Personal workspace</span></div><div className="top-bar-right"><span className="top-bar-badge"><ShieldCheck size={15}/> Exchange-sourced insights</span><span className="profile-avatar" aria-label="Personal profile">F</span></div></header>
      <div className="workspace-body">{page==='today'?<Today onSelectFiling={setFilingId} onOpenAlerts={()=>setPage('alerts')}/>:page==='alerts'?<Alerts onSelectFiling={setFilingId}/>:page==='portfolio'?<Portfolio/>:<Research initialSymbol={researchSymbol} onClearInitial={()=>setResearchSymbol('')}/>}</div>
      <footer className="workspace-footer"><span>FINN / INVESTMENT ATTENTION ENGINE</span><span>For research only. Verify primary sources.</span></footer>
    </div>
    <nav className="mobile-nav" aria-label="Mobile navigation">{NAV.map(({key,label,Icon})=><button className={page===key?'active':''} key={key} onClick={()=>setPage(key)} aria-current={page===key?'page':undefined} type="button"><Icon size={21} strokeWidth={page===key?2.3:1.8}/><span>{label}</span></button>)}</nav>
    {filingId&&<FilingDrawer filingId={filingId} onClose={closeFiling} onResearch={symbol=>{setResearchSymbol(symbol);setPage('research');closeFiling()}}/>}
  </div>
}
