// QuickClean — curation flow with keyboard shortcuts.
import { useCallback, useEffect, useState } from 'react'

import { api, type Issue, type Item, type Label } from './api'

import { I, ISSUE_LABELS, apiErrorMessage, openShot, t, type Page as PageType } from './shared'
import type React from 'react'
export function QuickCleanPage({ ds, go, foot }: { ds: string; go: (p: PageType, ds?: string) => void; foot: React.ReactNode }) {
  const [items, setItems] = useState<Item[]>([])
  const [idx, setIdx] = useState(0)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [infoOpen, setInfoOpen] = useState(false)
  const [tally, setTally] = useState<Record<string, number>>({})
  const [history, setHistory] = useState<{ id: string; prev: string; next: string }[]>([])
  const [queueTotal, setQueueTotal] = useState(0)
  const [itemInfo, setItemInfo] = useState<{ issues: Issue[]; labels: Label[] } | null>(null)
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
    setQueueTotal(0)
    setTally({})
    setHistory([])
  }, [ds])
  // fila drenada paginada: o servidor ordena (order=pending_first:
  // pending/review primeiro, depois quarantine/reject/keep; corruptos
  // no topo de cada grupo) — sem teto de 1000 no cliente.
  const load = useCallback(() => {
    const drain = (offset: number): Promise<void> =>
      api.itemsPage(ds, { limit: '200', order: 'pending_first', queue: '1', offset: String(offset) })
        .then(({ items: page, total }) => {
          setItems(prev => (offset === 0 ? page : prev.concat(page)))
          setQueueTotal(total || page.length)
          if (offset + page.length < total) return drain(offset + page.length)
        }).catch(e => setErr(e.message))
    setIdx(0)
    return drain(0)
  }, [ds])
  // oxlint-disable-next-line react/set-state-in-effect — fetch-then-set (drain), reset acima é intencional
  useEffect(() => { load() }, [load])
  const item = items[idx]
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
    setItemInfo(null)
    if (item) api.item(item.id).then(d => setItemInfo({ issues: d.issues, labels: d.labels })).catch(() => {})
  }, [item])
  const decide = useCallback((decision: string) => {
    if (!item || busy) return
    setBusy(true); setErr('')
    api.setDecision(item.id, decision, 'quick-clean').then(() => {
      setMsg(`${item.original_filename}: ${t(decision)}`)
      setTally(tl => ({ ...tl, [decision]: (tl[decision] ?? 0) + 1 }))
      setHistory(h => [...h, { id: item.id, prev: item.decision_status, next: decision }])
      setItems(prev => prev.filter(x => x.id !== item.id))
      setIdx(i => Math.min(i, Math.max(0, items.length - 2)))
    }).catch(e => setErr(e.message)).finally(() => setBusy(false))
  }, [item, busy, items.length])
  // real undo: restores the previous decision of the last decided item
  const undo = useCallback(() => {
    const last = history[history.length - 1]
    if (!last || busy) return
    setBusy(true); setErr('')
    api.setDecision(last.id, last.prev, 'undo').then(() => {
      setHistory(h => h.slice(0, -1))
      setTally(tl => ({ ...tl, [last.next]: Math.max(0, (tl[last.next] ?? 1) - 1) }))
      setMsg(`undone: ${t(last.next)} → ${t(last.prev)}`)
      load()
    }).catch(e => setErr(e.message)).finally(() => setBusy(false))
  }, [history, busy, load])
  const exportKept = () => {
    if (exporting) return
    setExporting(true); setErr('')
    api.export(ds, 'imagefolder').then(result => setMsg(result?.zip_path ? `export ready: ${String(result.zip_path)}` : 'export finished')).catch(e => setErr(apiErrorMessage(e))).finally(() => setExporting(false))
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return
      if (e.key === 'k' || e.key === 'K') decide('keep')
      else if (e.key === 'x' || e.key === 'X') decide('reject')
      else if (e.key === 'q' || e.key === 'Q') decide('quarantine')
      else if (e.key === 'p' || e.key === 'P') decide('review')
      else if (e.key === 'z' || e.key === 'Z') undo()
      else if (e.key === ' ' || e.key === 'ArrowRight') { e.preventDefault(); setIdx(i => Math.min(items.length - 1, i + 1)) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); setIdx(i => Math.max(0, i - 1)) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items.length, item, busy, history, decide, undo])
  const doneCount = Math.max(0, queueTotal - items.length)
  const pct = queueTotal ? Math.round((doneCount / queueTotal) * 100) : items.length ? 0 : 100
  const position = queueTotal ? `${Math.min(doneCount + 1, queueTotal)} of ${queueTotal}` : items.length ? 'loading…' : 'queue clear'
  const openIssueCount = itemInfo?.issues.filter(i => i.status === 'open').length ?? 0
  return <div className="review">
    <div className="pagebar clean-bar">
      <button className="sm" onClick={() => go('dataset', ds)} title="back to gallery">← gallery</button>
      <h2>Clean</h2>
      <span className="sub">{items.length ? `${items.length} left to clean · originals stay safe` : 'queue clear · originals stay safe'}</span>
      <span className="clean-count mono" aria-live="polite">{items.length ? `${position} · ${pct}% complete` : 'queue clear'}</span>
      <button className={`sm clean-details-toggle${infoOpen ? ' active' : ''}`} onClick={() => setInfoOpen(o => !o)} aria-expanded={infoOpen}>{infoOpen ? 'hide details' : 'details'}</button>
      <span className="spacer" />
      <button className="sm icon-btn" disabled={exporting} onClick={exportKept} title="export kept images" aria-label="export kept">{I.export}</button>
      <button className="sm icon-btn" disabled={!history.length || busy} onClick={undo} title="undo last decision (Z)" aria-label="undo last decision">{I.undo}</button>
    </div>
    {msg && <div className="ok clean-msg">{msg}</div>}
    {err && <div className="error clean-msg">{err}</div>}
    {!item && !err && <div className="empty clean-done"><b>queue clear</b>every image that needed a decision has been handled.</div>}
    {item && <>
      <div className={`clean-workspace${infoOpen ? ' has-details' : ''}`}>
      <div className="review-stage">
        <div className="review-visual">
          <button className="review-nav" aria-label="Previous image" title="previous (←)" disabled={idx === 0 || busy} onClick={() => setIdx(i => Math.max(0, i - 1))}>{I.chevL}</button>
          <div className={`review-photo${item.ingest_status === 'error' ? ' is-error' : ''}`} role="button" tabIndex={0} aria-label={`Open ${item.original_filename} large`} onClick={() => openShot!({ id: item.id, name: item.original_filename, caption: `${item.width}×${item.height}` })} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openShot!({ id: item.id, name: item.original_filename }) } }}>
            {item.ingest_status === 'error'
              ? <div className="review-error"><b>File could not be opened</b><span>Quarantine keeps this original safe and removes it from publish candidates.</span></div>
              : <img src={api.fileUrl(item.id)} alt={item.original_filename} />}
          </div>
          <button className="review-nav" aria-label="Next image" title="next (→)" disabled={idx >= items.length - 1 || busy} onClick={() => setIdx(i => Math.min(items.length - 1, i + 1))}>{I.chevR}</button>
        </div>
        <div className="review-meta">
          <div className="review-file">
            <b>{item.original_filename}</b>
            <span className="m">{item.relative_path && item.relative_path !== item.original_filename ? item.relative_path : 'root'}</span>
            <span className="m mono">{item.width}×{item.height} · {(item.byte_size / 1024).toFixed(0)} kB</span>
          </div>
          <div className="review-problems">{itemInfo ? `${openIssueCount} problem${openIssueCount === 1 ? '' : 's'} found` : 'checking problems…'}</div>
          <div className="review-tally">
            <span className="m mono">kept <b style={{ color: 'var(--ok)' }}>{tally.keep ?? 0}</b></span>
            <span className="m mono">quarantined <b style={{ color: 'var(--warn)' }}>{tally.quarantine ?? 0}</b></span>
            <span className="m mono">rejected <b style={{ color: 'var(--bad)' }}>{tally.reject ?? 0}</b></span>
          </div>
        </div>
        <div className="review-prog" aria-label={`${pct}% of Clean queue completed`}>
          <span className="track"><span className="fill" style={{ width: `${pct}%` }} /></span>
        </div>
        <div className="review-decisions" role="group" aria-label="Image decision">
          <button className="dk keep" disabled={busy} onClick={() => decide('keep')} title="keep">Keep<kbd>K</kbd></button>
          <button className="dk quarantine" disabled={busy} onClick={() => decide('quarantine')} title="quarantine">Quarantine<kbd>Q</kbd></button>
          <button className="dk review" disabled={busy} onClick={() => decide('review')} title="postpone">Postpone<kbd>P</kbd></button>
          <button className="dk reject" disabled={busy} onClick={() => decide('reject')} title="reject">Reject<kbd>X</kbd></button>
        </div>
      </div>
      {infoOpen && <aside className="clean-details" aria-label="Image details">
        <div className="clean-details-head">
          <span className="eyebrow">IMAGE DETAILS</span>
          <button className="sm" onClick={() => setInfoOpen(false)}>close</button>
        </div>
        <h3>{item.original_filename}</h3>
        <dl className="kv">
          <dt>location</dt><dd>{item.relative_path || 'root'}</dd>
          <dt>size</dt><dd>{item.width}×{item.height} · {(item.byte_size / 1024).toFixed(0)} kB</dd>
          <dt>format</dt><dd>{item.mime_type}</dd>
          <dt>status</dt><dd>{t(item.decision_status)}</dd>
        </dl>
        {item.ingest_status !== 'error' && <img className="clean-histogram" src={api.histogramUrl(item.id)} alt="brightness histogram" />}
        <div className="clean-detail-issues">
          <span className="eyebrow">PROBLEMS</span>
          {!itemInfo && <p className="muted">checking…</p>}
          {itemInfo?.issues.filter(i => i.status === 'open').map(i => <div key={i.id} className="clean-detail-issue">{I.warn}<span>{ISSUE_LABELS[i.issue_type] ?? i.issue_type}</span></div>)}
          {itemInfo && !itemInfo.issues.some(i => i.status === 'open') && <p className="muted">No open problems.</p>}
        </div>
      </aside>}
      </div>
    </>}

    {foot && <div className="footbar" style={{ marginTop: 'auto' }}>{foot}</div>}
  </div>
}
