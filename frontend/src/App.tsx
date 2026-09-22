// App shell: hash routing, workspace bar, import dialog; pages imported per route.
import { useCallback, useEffect, useLayoutEffect, useState } from 'react'

import { api, type Dataset } from './api'

import { Lightbox, Page, PageBar, I, distBar, useJobs } from './shared'
import type { Page as PageType, Theme } from './shared'
import { Dashboard } from './Dashboard'
import { QuickCleanPage } from './QuickClean'
import { Gallery } from './Gallery'
import { IssuesPage } from './Issues'
import { AnnotationPage } from './Annotate'
import { ModelCenter } from './Models'
import { VersionsPage } from './Versions'
import { ExportPage } from './Export'
import { SemanticPage } from './Semantic'

function ImportDialog({ datasets, initialDs, onClose, onDone }: { datasets: Dataset[]; initialDs: string; onClose: () => void; onDone: () => void }) {
  const [target, setTarget] = useState(initialDs || datasets[0]?.id || '')
  const [path, setPath] = useState('')
  const [zip, setZip] = useState('')
  const [err, setErr] = useState('')
  const { jobs, start } = useJobs()
  const submit = () => {
    if (!target || (!path.trim() && !zip.trim())) return
    setErr('')
    start(() => api.startImport(target, path.trim() ? [path.trim()] : [], zip.trim() ? [zip.trim()] : []), onDone)
  }
  return <div className="import-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
    <div className="import-sheet" role="dialog" aria-modal="true" aria-labelledby="import-title">
      <div className="dialog-head"><div><span className="eyebrow">IMPORT</span><h2 id="import-title">Import images</h2><p className="sub">Add a folder or ZIP to the dataset without leaving curation.</p></div><button aria-label="Close import" onClick={onClose}>×</button></div>
      <label className="field-label">Target dataset<select value={target} onChange={e => setTarget(e.target.value)}><option value="">select…</option>{datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
      <label className="field-label">Local folder<input placeholder="ex: data/fixture" value={path} onChange={e => setPath(e.target.value)} /></label>
      <div className="import-or">or</div>
      <label className="field-label">ZIP file<input placeholder="ex: data/images.zip" value={zip} onChange={e => setZip(e.target.value)} /></label>
      {err && <div className="error">{err}</div>}
      {jobs.map(job => <div className="jobbar" key={job.id}><span className="jlabel">{job.type}</span><span>{job.processed}/{job.total}</span><div className="track"><div className="fill" style={{ width: `${job.progress}%` }} /></div></div>)}
      <div className="import-actions"><span className="muted">The import runs on the backend and continues while you navigate.</span><button onClick={onClose}>cancel</button><button className="primary" disabled={!target || (!path.trim() && !zip.trim()) || jobs.length > 0} onClick={submit}>{jobs.length ? 'importing…' : 'start import'}</button></div>
    </div>
  </div>
}

function WorkspaceBar({ datasets, ds, dsName, search, onDataset, onSearch, onSubmit, onImport }: { datasets: Dataset[]; ds: string; dsName: string; search: string; onDataset: (id: string) => void; onSearch: (value: string) => void; onSubmit: () => void; onImport: () => void }) {
  return <div className="workspacebar">
    <select className="workspace-dataset" aria-label="Active dataset" value={ds} onChange={e => onDataset(e.target.value)}><option value="">Dataset…</option>{datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select>
    <span className="spacer" />
    <label className="workspace-search"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><input value={search} onChange={e => onSearch(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') onSubmit() }} placeholder={ds ? `Search in ${dsName || 'dataset'}…` : 'Search images…'} aria-label="Search images" /><kbd>⌘K</kbd></label>
    <span className="spacer" />
    <button className="primary workspace-import" onClick={onImport} aria-label="import images" title="import images">{I.import}<span>import images</span></button>
  </div>
}

// ---------- App ----------

export default function App() {
  const [page, setPage] = useState<PageType>(() => (location.hash.slice(1).split('/')[0] as PageType) || 'dashboard')
  const [ds, setDs] = useState(() => location.hash.split('/')[1] ?? '')
  const [dsName, setDsName] = useState('')
  const [dsInfo, setDsInfo] = useState<Dataset | null>(null)
  const [workspaceDatasets, setWorkspaceDatasets] = useState<Dataset[]>([])
  const [importOpen, setImportOpen] = useState(false)
  const [topSearch, setTopSearch] = useState('')
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem('ids-theme') === 'dark' ? 'dark' : 'light')
  const [reducedMotion, setReducedMotion] = useState(() => localStorage.getItem('ids-reduced-motion') === 'true')
  const [sel, setSel] = useState(new Set<string>())
  const [filter, setFilter] = useState<Record<string, string>>({ q: '', status: '', issue: '', license: '' })
  const [reloadKey, bumpReload] = useState(0)
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.dataset.reducedMotion = String(reducedMotion)
    localStorage.setItem('ids-theme', theme)
    localStorage.setItem('ids-reduced-motion', String(reducedMotion))
  }, [theme, reducedMotion])
  const onMutation = useCallback(() => { bumpReload(k => k + 1) }, [])
  const go = (p: PageType, d?: string) => {
    setImportOpen(false)
    setPage(p); if (d) setDs(d); setSel(new Set())
    location.hash = d ? `#${p}/${d}` : `#${p}`
  }
  useEffect(() => {
    const apply = () => {
      const [p, d] = location.hash.slice(1).split('/')
      setImportOpen(false)
      if (p) { setPage(p as PageType); if (d) setDs(d) }
    }
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])
  useEffect(() => {
    api.datasets().then(setWorkspaceDatasets).catch(() => {})
  }, [reloadKey])
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
    if (!ds) { setDsName(''); setDsInfo(null); return } // limpar ao sair do dataset é síncrono e intencional
    api.dataset(ds).then((dataset: Dataset) => {
      setDsName(dataset.name)
      setDsInfo(dataset)
      // contagens vêm prontas do get_dataset (GROUP BY no servidor) — sem fetch de 1000 itens
    }).catch(() => setDsName(ds.slice(0, 13) + '…'))
  }, [ds, reloadKey])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return
      if (ds && (e.key === 'l' || e.key === 'L')) go('clean', ds)
      else if (ds && (e.key === 'g' || e.key === 'G')) go('dataset', ds)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ds])
  const icons: Record<PageType, React.ReactNode> = {
    dashboard: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>,
    clean: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 20 4-4"/><path d="m8 15 7-7"/><path d="m14 9 2-2 3 3-2 2"/><path d="m4 18 2 2h11"/><path d="M17 16h4"/></svg>,
    dataset: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>,
    issues: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>,
    annotation: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>,
    semantic: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>,
    versions: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
    export: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
    models: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h16M4 12h16M4 17h16"/><circle cx="8" cy="7" r="2" fill="var(--bg)"/><circle cx="15" cy="12" r="2" fill="var(--bg)"/><circle cx="11" cy="17" r="2" fill="var(--bg)"/></svg>,
  }
  const nav: [PageType, string][] = [['dashboard', 'Home'], ['clean', 'Clean'], ['dataset', 'Explore'], ['issues', 'Review'], ['annotation', 'Annotate'], ['semantic', 'Find'], ['versions', 'History'], ['export', 'Publish'], ['models', 'Settings']]
  const primaryNav = nav
  const NAV_LABEL: Record<PageType, string> = { dashboard: 'Home', clean: 'Clean', dataset: 'Explore', issues: 'Review', annotation: 'Annotate', semantic: 'Find', versions: 'History', export: 'Publish', models: 'Settings' }
  const navHelp: Record<PageType, string> = {
    dashboard: 'Pick a dataset and see the next decision', clean: 'Decide quickly: keep, review, or remove', dataset: 'Browse all images', issues: 'Review quality alerts and duplicates', annotation: 'Mark objects and create labels', semantic: 'Find images by meaning', versions: 'Compare and restore snapshots', export: 'Generate the final dataset version', models: 'Configure models and app preferences',
  }
  // thin real-context footbar
  const foot = dsInfo ? <>
    <span><b>{dsName}</b> · <span className="mono">{dsInfo.item_counts?.total ?? 0} items</span></span>
    <span className="footer-dist">{distBar(dsInfo.item_counts, dsInfo.item_counts?.total ?? 0)}</span>
    <span>{dsInfo.open_issues ? <><b style={{ color: 'var(--warn)' }}>{dsInfo.open_issues}</b> open issues</> : 'no open issues'}</span>
    <span className="spacer" />
  </> : null
  const selectWorkspaceDataset = (id: string) => {
    setFilter(current => ({ ...current, q: '' }))
    if (id) go('dataset', id); else go('dashboard')
  }
  const updateWorkspaceSearch = (value: string) => {
    setTopSearch(value)
    setFilter(current => ({ ...current, q: value }))
  }
  const refreshWorkspace = () => {
    setImportOpen(false)
    bumpReload(k => k + 1)
  }
  const noDs = <Page bar={<PageBar title="No dataset selected" sub="choose a dataset from the top menu" />} foot={foot}>
    <div className="empty"><b>Select a dataset first</b><p>Use the active dataset selector to open a workspace.</p></div>
  </Page>
  const body = (() => {
    switch (page) {
      case 'dashboard': return <Dashboard go={go} foot={foot} />
      case 'clean': return ds ? <QuickCleanPage ds={ds} go={go} foot={foot} /> : noDs
      case 'dataset': return ds
        ? <Gallery ds={ds} sel={sel} setSel={setSel} filter={filter} setFilter={setFilter} reloadKey={reloadKey} foot={foot} onMutation={onMutation} />
        : noDs
      case 'issues': return ds ? <IssuesPage ds={ds} foot={foot} /> : noDs
      case 'annotation': return ds ? <AnnotationPage ds={ds} foot={foot} /> : noDs
      case 'semantic': return ds ? <SemanticPage ds={ds} go={go} foot={foot} /> : noDs
      case 'versions': return ds ? <VersionsPage ds={ds} foot={foot} /> : noDs
      case 'export': return ds ? <ExportPage ds={ds} foot={foot} /> : noDs
      case 'models': return <ModelCenter foot={foot} theme={theme} onThemeChange={setTheme} reducedMotion={reducedMotion} onReducedMotionChange={setReducedMotion} />
    }
  })()

  return <div className="app">
    <div className="sidebar">
      <a className="brand" href="#dashboard" aria-label="FrameSet home">
        <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" stroke="currentColor" strokeWidth="1.8"/><path d="M10 10h4v4h-4z" fill="currentColor"/></svg></span>
        <span><b>FrameSet</b><small>dataset studio</small></span>
      </a>
      <nav className="primary-nav">
        {primaryNav.map(([p]) =>
          <button key={p} className={page === p ? 'active' : ''} title={navHelp[p]} aria-label={`${NAV_LABEL[p]}: ${navHelp[p]}`}
            onClick={() => go(p, ds)}>{icons[p]}{NAV_LABEL[p]}</button>)}
      </nav>

    </div>
    <div className="main">
      <WorkspaceBar datasets={workspaceDatasets} ds={ds} dsName={dsName} search={topSearch} onDataset={selectWorkspaceDataset} onSearch={updateWorkspaceSearch} onSubmit={() => { if (ds) go('dataset', ds) }} onImport={() => setImportOpen(true)} />
      {body}
    </div>
    {importOpen && <ImportDialog datasets={workspaceDatasets} initialDs={ds} onClose={() => setImportOpen(false)} onDone={refreshWorkspace} />}
    <Lightbox />
  </div>
}
