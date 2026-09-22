// Dashboard — dataset list + creation dialog.
import { useCallback, useEffect, useState } from 'react'

import { api, type Dataset } from './api'

import { Page, I, distBar, useJobs } from './shared'
import type { Page as PageType } from './shared'
import type React from 'react'
export function Dashboard({ go, foot }: { go: (p: PageType, ds?: string) => void; foot: React.ReactNode }) {
  const [dss, setDss] = useState<Dataset[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [err, setErr] = useState('')
  const { jobs } = useJobs()
  const [page, setPage] = useState(0)
  const PER_PAGE = 24
  const pageDss = dss.slice(page * PER_PAGE, (page + 1) * PER_PAGE)
  const load = useCallback(() => api.datasets().then(d => { setPage(0); setDss(d) }).catch(e => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  return <Page
    bar={null}
    foot={foot}>
    {err && <div className="error">{err}</div>}
    <div className="dash-top">
      <span className="eyebrow">DATASETS · {dss.length}</span>
      <button className="primary dash-create-btn" onClick={() => setCreateOpen(true)}>{I.plus}<span>new dataset</span></button>
    </div>
    {createOpen && <CreateDatasetDialog onClose={() => setCreateOpen(false)} onDone={load} />}


    <div className="cards">
      {pageDss.map(ds => {
        const total = ds.item_counts?.total ?? 0
        const done = (ds.item_counts?.keep ?? 0) + (ds.item_counts?.quarantine ?? 0) + (ds.item_counts?.reject ?? 0)
        const curation = total ? Math.round(done / total * 100) : 0
        return <div key={ds.id} className="card dataset-card">
          <div className="cover"><img src={api.coverUrl(ds.id)} alt="" loading="lazy" onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} /></div>
          <h3><a href="#" onClick={e => { e.preventDefault(); go('dataset', ds.id) }}>{ds.name}</a></h3>
          <div className="dashboard-report" aria-label={`${total} images: ${ds.item_counts?.keep ?? 0} kept, ${ds.item_counts?.review ?? 0} to review, ${ds.item_counts?.quarantine ?? 0} quarantined, ${ds.item_counts?.reject ?? 0} rejected`}>
            {distBar(ds.item_counts, total)}
            <div className="report-legend">
              <span className="report-kept"><i />{ds.item_counts?.keep ?? 0} kept</span>
              <span className="report-review"><i />{(ds.item_counts?.review ?? 0) + (ds.item_counts?.pending ?? 0)} to review</span>
              <span className="report-quarantine"><i />{ds.item_counts?.quarantine ?? 0} quarantined</span>
              <span className="report-rejected"><i />{ds.item_counts?.reject ?? 0} rejected</span>
            </div>
          </div>
          <div className="card-progress">
            <span className="lbl">{curation}% decided · {total} images</span>
            <span className="issue-count">{ds.open_issues ?? 0} open issues</span>
          </div>
          <div className="dash-card-actions">
            <button className="sm primary" onClick={() => go('dataset', ds.id)}>open gallery</button>
            {(ds.open_issues ?? 0) > 0 && <button className="sm" onClick={() => go('issues', ds.id)}>review {ds.open_issues} issues</button>}
            <button className="sm" onClick={() => go('clean', ds.id)}>clean</button>
          </div>
        </div>
      })}
    </div>
    {dss.length === 0 && <div className="empty">
      <b>Start with a dataset</b>
      Create a workspace, then import a folder or ZIP. Your originals stay untouched.
      <div className="row" style={{ marginTop: 12 }}>
        <button className="primary" onClick={() => setCreateOpen(true)}>new dataset</button>
      </div>
    </div>}
    {dss.length > PER_PAGE && <div className="pager">
      <button className="sm" disabled={page === 0} onClick={() => setPage(0)}>{I.chevL}<span>first</span></button>
      <button className="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>{I.chevL}</button>
      <span className="muted" style={{ fontSize: 11, font: '11px var(--font-m)' }}>{page + 1} / {Math.ceil(dss.length / PER_PAGE)}</span>
      <button className="sm" disabled={page >= Math.ceil(dss.length / PER_PAGE) - 1} onClick={() => setPage(p => p + 1)}>{I.chevR}</button>
      <button className="sm" disabled={page >= Math.ceil(dss.length / PER_PAGE) - 1} onClick={() => setPage(Math.ceil(dss.length / PER_PAGE) - 1)}><span>last</span>{I.chevR}</button>
    </div>}



    {jobs.length > 0 && <h4>Jobs in progress</h4>}
    {jobs.map(j => <div key={j.id} className="jobbar">
      <span className="jlabel">{j.type}</span>
      <span className="muted">{j.processed}/{j.total}</span>
      {j.status === 'failed' && <span className="error" style={{ padding: 0, background: 'none', border: 'none' }}>{j.error_summary}</span>}
      {j.status === 'running' && <button className="sm" onClick={() => api.cancelJob(j.id)}>cancel</button>}
      <div className="track"><div className="fill" style={{ width: `${j.progress}%` }} /></div>
    </div>)}
  </Page>
}
export function CreateDatasetDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [folder, setFolder] = useState('')
  const [err, setErr] = useState('')
  const [creating, setCreating] = useState(false)
  const create = async () => {
    if (creating) return
    setCreating(true); setErr('')
    try {
      await api.createDataset(name.trim(), '', folder.trim() || undefined)
      onDone()
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to create dataset')
    } finally {
      setCreating(false)
    }
  }
  const steps = ['name', 'folder', 'create']
  return <div className="cd-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
    <div className="import-sheet cd-sheet" role="dialog" aria-modal="true" aria-labelledby="create-title">
      <div className="dialog-head"><div><span className="eyebrow">NEW DATASET</span><h2 id="create-title">Create dataset</h2><p className="sub">Three quick steps: name, source folder, then create.</p></div><button aria-label="Close create dialog" onClick={onClose}>×</button></div>
      <div className="create-steps" role="group" aria-label="Create dataset steps">
        {steps.map((s, i) => <button key={s} className={`create-step${step === i ? ' on' : ''}${step > i ? ' done' : ''}`} onClick={() => setStep(i)}>
          <span className="n">{i + 1}</span>{s === 'name' ? 'Name' : s === 'folder' ? 'Source folder' : 'Create'}
        </button>)}
      </div>
      {step === 0 && <label className="field-label">Dataset name<input value={name} onChange={e => setName(e.target.value)} placeholder="ex: product-shots" autoFocus /></label>}
      {step === 1 && <label className="field-label">Source folder (optional)<input value={folder} onChange={e => setFolder(e.target.value)} placeholder="ex: data/product-shots" /></label>}
      {step === 2 && <div className="create-confirm">
        <p className="muted" style={{ margin: '0 0 10px' }}>Creating <b>{name || '—'}</b>{folder ? <> with folder <b>{folder}</b></> : ''}.</p>
        {err && <div className="error">{err}</div>}
        <button className="primary" disabled={creating || !name.trim()} onClick={create}>{creating ? 'creating…' : 'create dataset'}</button>
      </div>}
      <div className="import-actions">
        <button className="sm" disabled={step === 0} onClick={() => setStep(s => Math.max(0, s - 1))}>back</button>
        <span className="spacer" style={{ flex: 1 }} />
        {step < 2
          ? <button className="primary" disabled={step === 0 && !name.trim() || step === 1 && false} onClick={() => setStep(s => s + 1)}>next</button>
          : <span className="muted">Review and create</span>}
      </div>
    </div>
  </div>
}
