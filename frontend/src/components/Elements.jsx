import React from 'react'
import { AlertCircle, ArrowUpRight, FileText, LoaderCircle, RotateCcw, ShieldCheck } from 'lucide-react'
import { safeHttpUrl, priorityLabel } from '../lib/format.js'

export function IconButton({ icon: Icon, label, onClick, className = '' }) {
  return <button className={`icon-button ${className}`} onClick={onClick} type="button" aria-label={label} title={label}><Icon size={19} strokeWidth={1.8} /></button>
}

export function Priority({ priority, compact = false }) {
  return <span className={`priority-tag priority-${priority || 'routine'} ${compact ? 'priority-compact' : ''}`}><span className="priority-dot" />{priorityLabel(priority)}</span>
}

export function Status({ children, tone = 'neutral' }) {
  return <span className={`state-tag state-${tone}`}>{children}</span>
}

export function FilingLink({ url, label = 'View original filing', compact = false }) {
  const href = safeHttpUrl(url)
  if (!href) return <span className="muted text-sm">Original filing link unavailable</span>
  return <a href={href} className={compact ? 'source-link compact' : 'source-link'} target="_blank" rel="noopener noreferrer"><FileText size={15} />{label}<ArrowUpRight size={14} /></a>
}

export function Busy({ label = 'Loading saved data…' }) {
  return <div className="system-panel"><LoaderCircle className="spin" size={24} /><span>{label}</span></div>
}

export function ErrorPanel({ message, onRetry }) {
  return <div className="system-panel error-panel"><AlertCircle size={23} /><strong>Unable to load data</strong><p>{message}</p>{onRetry && <button className="button-outline" onClick={onRetry} type="button"><RotateCcw size={15} /> Try again</button>}</div>
}

export function EmptyPanel({ icon: Icon = ShieldCheck, title, message, children }) {
  return <div className="empty-panel"><div className="empty-icon"><Icon size={26} strokeWidth={1.6} /></div><h3>{title}</h3><p>{message}</p>{children}</div>
}
