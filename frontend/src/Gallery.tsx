// Gallery — virtualized grid + inspector + caption modal.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, type Caption, type Issue, type Item, type Label, type ProviderInfo } from './api'

import { ADV_KEYS, GALLERY_PAGE, I, ISSUE_LABELS, ISSUE_TYPES, ModelPicker, openShot, t, useJobs } from './shared'
import type { Page as PageType } from './shared'
import type React from 'react'
export function Gallery({ ds, sel, setSel, filter, setFilter, reloadKey, foot, onMutation }: {
  ds: string; sel: Set<string>; setSel: (s: Set<string>) => void;
  filter: Record<string, string>; setFilter: (f: Record<string, string>) => void; reloadKey: number; foot: React.ReactNode;
  onMutation: () => void
}) {
  const [items, setItems] = useState<Item[]>([])
  const sentinel = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)
  const totalRef = useRef(0)
  const [compare, setCompare] = useState<string[]>([])
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [impPath, setImpPath] = useState('')
  const [apOpen, setApOpen] = useState('')
  const [toolsOpen, setToolsOpen] = useState(false)
  const [captionOpen, setCaptionOpen] = useState(false)
  const [prov, setProv] = useState<ProviderInfo[] | null>(null)
  const [modelByCapability, setModelByCapability] = useState<Record<string, string>>({})
  const [captionPrompt, setCaptionPrompt] = useState('Describe the main subject, setting, and visual style for image training.')
  const [captionPrefix, setCaptionPrefix] = useState('')
  const [captionSuffix, setCaptionSuffix] = useState('')
  const [captionTemplate, setCaptionTemplate] = useState('{caption}')
  const { start } = useJobs()
  const loadProviders = () => api.providers().then(setProv).catch(console.error)
  const [views, setViews] = useState<Record<string, string>>({})
  const [viewName, setViewName] = useState('')
  const [labelCats, setLabelCats] = useState<Record<string, string[]>>({})
  // modular filter builder rows: key -> display title; add new backend-supported filters here
  const activeCount = ADV_KEYS.filter(([k,]) => filter[k]).length
  useEffect(() => { api.itemsByLabel(ds).then(d => setLabelCats(d.categories)).catch(() => {}) }, [ds])
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
  useEffect(() => { setViews(JSON.parse(localStorage.getItem(`views-${ds}`) ?? '{}')) }, [ds])
  const buildParams = useCallback((offset = 0): Record<string, string> => {
    const params: Record<string, string> = { limit: String(GALLERY_PAGE), offset: String(offset) }
    for (const [k] of ADV_KEYS) {
      const v = (filter as Record<string, unknown>)[k]
      if (v !== undefined && v !== null && v !== '') params[k] = String(v)
    }
    return params
  }, [filter])
  const load = useCallback(() => {
    api.itemsPage(ds, buildParams()).then(({ items: page, total }) => {
      setItems(page)
      totalRef.current = total
    }).catch(console.error)
  }, [ds, buildParams])
  useEffect(load, [load, reloadKey])
  const loadMore = useCallback(() => {
    if (loadingRef.current || items.length >= totalRef.current) return
    loadingRef.current = true
    api.itemsPage(ds, buildParams(items.length)).then(({ items: page }) => {
      setItems(prev => [...prev, ...page])
      loadingRef.current = false
    }).catch(() => { loadingRef.current = false })
  }, [ds, buildParams, items.length])
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const io = new IntersectionObserver(es => { if (es[0].isIntersecting) loadMore() })
    io.observe(el)
    return () => io.disconnect()
  }, [loadMore])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const ordered = items.filter(i => sel.has(i.id))
        if (ordered.length) {
          const cur = ordered.findIndex(i => i.id === [...sel][sel.size - 1])
          const delta = e.key === 'ArrowRight' ? 1 : -1
          const next = ordered[Math.max(0, Math.min(ordered.length - 1, cur + delta))]
          if (next) setSel(new Set([next.id]))
        }
      } else if (e.key === 'Enter' && sel.size === 1) {
        const selected = items.find(i => i.id === [...sel][0])
        if (selected) openShot!({ id: selected.id, name: selected.original_filename, caption: `${selected.width}×${selected.height}` })
      } else if (e.key.toLowerCase() === 'c' && sel.size >= 1) {
        setCompare([...sel])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items, sel, setSel])
  const saveView = () => {
    const name = viewName.trim() || `view ${Object.keys(views).length + 1}`
    const next = { ...views, [name]: JSON.stringify(filter) }
    setViews(next); setViewName('')
    localStorage.setItem(`views-${ds}`, JSON.stringify(next))
  }
  return <div className="page with-inspector">
    <div className="pagebar">
      <span className="seg" role="group" aria-label="decision filter">
        <button className={!filter.status ? 'on' : ''} onClick={() => setFilter({ ...filter, status: '' })}>all<span className="n">{items.length}</span></button>
        {['keep', 'review', 'quarantine', 'reject', 'error'].map(s => <button key={s} className={filter.status === s ? 'on' : ''}
          onClick={() => setFilter({ ...filter, status: filter.status === s ? '' : s })}>{t(s)}</button>)}
      </span>
      <span className="spacer" />
      {Object.entries(views).map(([name, f]) =>
        <span key={name} className="chip" role="button" tabIndex={0} onClick={() => setFilter(JSON.parse(f))} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFilter(JSON.parse(f)) } }}>{name}</span>)}
      <button className={`sm icon-btn${filtersOpen ? ' active' : ''}`} onClick={() => setFiltersOpen(open => !open)} aria-expanded={filtersOpen} aria-label="More filters" title="more filters">{I.funnel}</button>
      <button className="sm icon-btn" onClick={saveView} title="save current filters as a view" aria-label="Save current filters as a view">{I.bookmark}</button>
      <button className={`sm tools-toggle${toolsOpen ? ' active' : ''}`} onClick={() => setToolsOpen(open => !open)} aria-expanded={toolsOpen} disabled={sel.size > 0}>dataset tools</button>
      <button className={`sm caption-primary${captionOpen ? ' active' : ''}`} onClick={() => setCaptionOpen(open => !open)} aria-expanded={captionOpen} aria-haspopup="dialog">Caption</button>
      <button className="sm pagebar-review" onClick={() => go2('issues', ds)} aria-label="Review issues" title="Review issues">{I.warn}<span>review issues</span></button>
    </div>
    <div className="page-body" style={{ display: 'flex', flex: 1, minHeight: 0, gap: 14 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* modular filter builder: expandable via the funnel icon in the pagebar */}
        {filtersOpen && <div className="fbuilder" role="group" aria-label="Advanced filters">
          {ADV_KEYS.map(([k, t]) => k === 'status' ? null : <div key={k} className="frow">
            <span className="fname">{t}</span>
            {k === 'issue'
              ? <div className="chips">
                  {ISSUE_TYPES.map(it => <span key={it} className={`chip${filter.issue === it ? ' on' : ''}`}
                    role="button" tabIndex={0} aria-pressed={filter.issue === it}
                    onClick={() => setFilter({ ...filter, issue: filter.issue === it ? '' : it })}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFilter({ ...filter, issue: filter.issue === it ? '' : it }) } }}>
                    <span className="cdot" style={{ background: filter.issue === it ? 'var(--acc)' : 'var(--hair-2)' }}></span>
                    {ISSUE_LABELS[it]}
                  </span>)}
                </div>
              : k === 'license'
              ? <select value={filter.license} onChange={e => setFilter({ ...filter, license: e.target.value })} title="license">
                  <option value="">all</option>
                  <option value="unknown">unknown</option>
                </select>
              : k === 'label'
              ? <select value={filter.label} onChange={e => setFilter({ ...filter, label: e.target.value })} title="label">
                  <option value="">all</option>
                  {Object.keys(labelCats).map(c => <option key={c} value={c}>{c} ({labelCats[c].length})</option>)}
                </select>
              : k === 'min_width'
              ? <input type="number" min={0} placeholder="px" style={{ width: 90 }} value={filter.min_width ?? ''} onChange={e => setFilter({ ...filter, min_width: e.target.value })} />
              : k === 'tag'
              ? <input placeholder="tag contains…" style={{ width: 160 }} value={filter.tag ?? ''} onChange={e => setFilter({ ...filter, tag: e.target.value })} />
              : null}
            {filter[k] && <button className="sm fclear" onClick={() => setFilter({ ...filter, [k]: '' })} aria-label={`clear ${t} filter`}>×</button>}
          </div>)}
          <div className="fsummary muted">{activeCount} active filter{activeCount === 1 ? '' : 's'} · <button className="sm" onClick={() => setFilter({ q: filter.q, status: '', issue: '', license: '', label: '', min_width: '', tag: '' })}>clear all</button></div>
        </div>}

        {/* single selection is handled by the inspector; bulk actions stay for multi-select */}
        {sel.size > 0 && <div className="toolbar actions" role="group" aria-label="Selection actions">
          <span className="chip on"><span className="cdot" style={{ background: 'var(--text)' }}></span>{sel.size} selected</span>
          {sel.size > 1 && <>
            <button className="sm" onClick={() => { for (const id of sel) api.setDecision(id, 'quarantine', 'bulk').then(load); setSel(new Set()) }}>Quarantine</button>
            <button className="sm" onClick={() => { for (const id of sel) api.setDecision(id, 'keep').then(load); setSel(new Set()) }}>Keep</button>
            <button className="sm" onClick={() => setCompare([...sel])}>Compare</button>
          </>}
          <button className="sm" onClick={() => setSel(new Set())}>clear</button>
        </div>}

        {compare.length > 0 && <div className="card" style={{ marginBottom: 12 }}>
          <h3>Compare ({compare.length}) <button className="sm" onClick={() => setCompare([])}>close</button></h3>
          <div className="row">
            {compare.map((cid, i) => <div key={cid} className="thumb" style={{ width: 220 }}>
              <img src={api.thumbnailUrl(cid)} alt={`Comparison image ${i + 1}`} style={{ width: '100%', height: 160, objectFit: 'contain', background: 'var(--canvas)' }} />
              <div className="name">#{i + 1}</div>
            </div>)}
          </div>
        </div>}

      {/* dataset actions accordion: import / analyses / derive */}
      {toolsOpen && <div className="card action-panel">
        <div className="ap-head"><h3>Dataset tools</h3><button className="sm" onClick={() => setToolsOpen(false)}>close</button></div>
        <div className="ap-acc">
          {([['import', 'Import images', <>
              <div className="toolbar">
                <input style={{ flex: 1 }} placeholder="folder path (e.g. data/fixture)" value={impPath} onChange={e => setImpPath(e.target.value)} />
                <button className="primary" disabled={!impPath} onClick={() => start(() => api.startImport(ds, [impPath.trim()], []), load)}>import</button>
              </div>
            </>],
            ['analyses', 'Analyses', <>
              <div className="analysis-models">
                {(['embedding', 'preannotation', 'pii', 'ocr', 'detection', 'segmentation', 'captioning'] as const).map(capability =>
                  <ModelPicker key={capability} capability={capability} value={modelByCapability[capability] ?? ''}
                    onChange={value => setModelByCapability(current => ({ ...current, [capability]: value }))} />)}
                <button className="sm" onClick={() => go2('models', ds)}>manage models</button>
              </div>
              <div className="toolbar">
                {[['quality', 'quality', ''], ['dedup_exact', 'exact dedup', ''], ['dedup_phash', 'phash dedup', ''],
                  ['embeddings', 'Embeddings', modelByCapability.embedding], ['retry_errors', 'retry failed', ''],
                  ['preannotate', 'AI pre-annotation', modelByCapability.preannotation], ['pii_scan', 'PII scan', modelByCapability.pii],
                  ['ocr', 'OCR', modelByCapability.ocr], ['detection', 'object detection', modelByCapability.detection],
                  ['segmentation', 'create masks', modelByCapability.segmentation], ['label_issues', 'label issues', '']].map(([jt, label, modelId]) =>
                <button key={jt} className="sm" onClick={() => start(() => api.startJob(ds, jt, modelId ? { model_id: modelId } : {}), load)}>{label}</button>)}
                <button className="sm" onClick={loadProviders}>providers</button>
              </div>
            </>],
            ['derive', 'Derive / merge / split', <>
              <div className="toolbar">
                <button className="sm" onClick={() => go2('annotation', ds)}>annotate · add labels</button>
                <button className="sm" onClick={() => go2('issues', ds)}>review issues</button>
                <button className="sm" onClick={async () => { await api.split(ds, [0.8, 0.1, 0.1]); load() }}>split 80/10/10</button>
                <button className="sm" onClick={async () => { await api.derive(ds, `derived-${Date.now()}`, { status: 'keep' }); load() }}>derive kept</button>
              </div>
            </>],
          ] as [string, string, React.ReactNode][]).map(([key, title, body]) => <div key={key} className={`ap-sec${apOpen === key ? ' open' : ''}`}>
            <button className="ap-sec-head" aria-expanded={apOpen === key} onClick={() => setApOpen(apOpen === key ? '' : key)}>
              <span>{title}</span>{I.chevD}
            </button>
            {apOpen === key && <div className="ap-sec-body">{body}</div>}
          </div>)}
          {prov && <div className={`ap-sec${apOpen === 'providers' ? ' open' : ''}`}>
            <button className="ap-sec-head" aria-expanded={apOpen === 'providers'} onClick={() => setApOpen(apOpen === 'providers' ? '' : 'providers')}>
              <span>Providers</span>{I.chevD}
            </button>
            {apOpen === 'providers' && <div className="ap-sec-body">
              <table><thead><tr><th>scope</th><th>provider</th><th>active</th><th>available</th><th>setup</th></tr></thead><tbody>
                {prov.map(p => <tr key={p.scope + p.name}>
                  <td>{p.scope}</td><td>{p.name}</td>
                  <td>{p.active ? '✓' : '—'}</td>
                  <td>{p.available ? <span style={{ color: 'var(--ok)' }}>yes</span> : <span style={{ color: 'var(--bad)' }}>no</span>}</td>
                  <td className="muted">{p.setup}</td>
                </tr>)}
              </tbody></table>
            </div>}
          </div>}
        </div>
      </div>}
        <div className="gallery">
          {items.map(it => {
            const bad = it.ingest_status === 'error'
            const status = bad ? 'error' : it.decision_status
            return <div key={it.id} className={`thumb status-${status}${sel.has(it.id) ? ' selected' : ''}`} role="button" tabIndex={0}
              aria-pressed={sel.has(it.id)}
              aria-label={`${it.original_filename}, status ${t(status)}. Click selects; Enter or double-click zooms`}
              onKeyDown={e => {
                if (e.key === ' ') {
                  e.preventDefault()
                  const next = new Set(sel)
                  if (next.has(it.id)) next.delete(it.id); else next.add(it.id)
                  setSel(next)
                  setToolsOpen(false)
                } else if (e.key === 'Enter') {
                  e.preventDefault()
                  openShot!({ id: it.id, name: it.original_filename, caption: `${it.width}×${it.height} · ${(it.byte_size / 1024).toFixed(0)}kB` })
                }
              }}
              onDoubleClick={() => openShot!({ id: it.id, name: it.original_filename, caption: `${it.width}×${it.height} · ${(it.byte_size / 1024).toFixed(0)}kB` })}
              onClick={e => { setToolsOpen(false); if (e.ctrlKey || e.metaKey) { const n = new Set(sel); if (n.has(it.id)) n.delete(it.id); else n.add(it.id); setSel(n) } else setSel(new Set([it.id])) }}>
              {bad
                ? <div style={{ height: 122, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--bad)' }}>corrupt</div>
                : <img loading="lazy" src={api.thumbnailUrl(it.id)} alt={it.original_filename} />}
              <span className="ck" aria-hidden="true">{I.check}</span>
              {status !== 'keep' && status !== 'pending' && <span className={`badge ${status}`}>{t(status)}</span>}
              <div className="name">{it.original_filename}</div>
              <div className="name dim">{it.width}×{it.height} · {(it.byte_size / 1024).toFixed(0)}kB</div>
            </div>
          })}
        </div>
        <div ref={sentinel} style={{ height: 10 }} />
        {items.length === 0 && <div className="empty"><b>No items here</b>import images on the Home page, or adjust the filters above</div>}
      </div>


      {/* contextual inspector: single selection only */}
      {sel.size === 1 && <InspectorPanel item={items.find(i => i.id === [...sel][0])} onJob={start} onRefresh={() => { load(); onMutation() }} onClose={() => setSel(new Set())} />}
    </div>
    {captionOpen && <div className="caption-modal-backdrop" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) setCaptionOpen(false) }}>
      <section className="caption-modal" role="dialog" aria-modal="true" aria-labelledby="caption-dialog-title">
        <div className="caption-modal-head">
          <div><span className="eyebrow">DATASET TOOL</span><h3 id="caption-dialog-title">Generate captions</h3></div>
          <button className="sm" onClick={() => setCaptionOpen(false)} aria-label="Close caption dialog">close</button>
        </div>
        <p className="muted">Generate editable training captions for {items.length} images. Nothing is published automatically.</p>
        <ModelPicker capability="captioning" value={modelByCapability.captioning ?? ''} onChange={value => setModelByCapability(current => ({ ...current, captioning: value }))} />
        <div className="caption-controls">
          <label>prompt<textarea value={captionPrompt} onChange={e => setCaptionPrompt(e.target.value)} rows={3} /></label>
          <label>prefix<input value={captionPrefix} onChange={e => setCaptionPrefix(e.target.value)} placeholder="optional trigger word" /></label>
          <label>suffix<input value={captionSuffix} onChange={e => setCaptionSuffix(e.target.value)} placeholder="optional final keyword" /></label>
          <label>template<input value={captionTemplate} onChange={e => setCaptionTemplate(e.target.value)} placeholder="{caption}" /></label>
        </div>
        <div className="caption-modal-actions">
          <span className="muted">Review and edit each result in Annotate.</span>
          <button className="primary" onClick={() => { setCaptionOpen(false); start(() => api.startJob(ds, 'caption', { ...(modelByCapability.captioning ? { model_id: modelByCapability.captioning } : {}), prompt: captionPrompt, prefix: captionPrefix, suffix: captionSuffix, template: captionTemplate }), load) }}>generate captions</button>
        </div>
      </section>
    </div>}
    {foot && <div className="footbar" style={{ marginTop: 'auto' }}>{foot}</div>}
  </div>
}
const EXIF_LABELS: Record<string, string> = {
  Make: 'Camera maker', Model: 'Camera', LensModel: 'Lens', Software: 'Software',
  DateTimeOriginal: 'Taken at', DateTime: 'Modified at', Artist: 'Taken by',
  Copyright: 'Copyright', Description: 'Description', ImageDescription: 'Description',
  FocalLength: 'Focal length', ExposureTime: 'Exposure time', FNumber: 'Aperture',
  ISOSpeedRatings: 'ISO', ISO: 'ISO', PixelXDimension: 'Pixel width', PixelYDimension: 'Pixel height',
  271: 'Camera maker', 272: 'Camera', 305: 'Software', 306: 'Modified at',
  315: 'Taken by', 33432: 'Copyright', 34665: 'EXIF data', 36867: 'Taken at',
  37377: 'Shutter speed', 37378: 'Aperture', 37386: 'Focal length', 34855: 'ISO',
}

function metadataLabel(key: string) {
  return EXIF_LABELS[key] ?? key.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ')
    .replace(/^./, char => char.toUpperCase())
}

function inspectorDate(value?: string) {
  if (!value) return '—'
  const exifDate = value.replace(/^(\d{4}):(\d{2}):(\d{2})/, '$1-$2-$3')
  const parsed = Date.parse(exifDate)
  return Number.isNaN(parsed) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(parsed))
}

function inspectorBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} kB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

function InspectorHistogram({ item }: { item: Item }) {
  return <section className="isec inspector-preview-section">
    <div className="isec-title"><h4>Preview</h4><span>RGB histogram</span></div>
    <img className="inspector-histogram" src={api.histogramUrl(item.id)} alt={`RGB histogram for ${item.original_filename}`} />
    <div className="histogram-legend" aria-label="Histogram channels">
      <span className="histogram-red">red</span><span className="histogram-green">green</span><span className="histogram-blue">blue</span>
    </div>
  </section>
}

function InspectorPanel({ item, onRefresh, onClose, onJob }: { item: Item | undefined; onRefresh: () => void; onClose: () => void; onJob: (fn: () => Promise<{ job_id: string }>, onDone: () => void) => void }) {
  const [data, setData] = useState<{ issues: Issue[]; labels: Label[]; caption: Caption | null } | null>(null)
  const [tab, setTab] = useState<'decision' | 'quality' | 'file' | 'labels'>('decision')
  const [commandStatus, setCommandStatus] = useState('')
  const loadData = useCallback(() => {
    if (!item) return
    api.item(item.id).then(d => setData({ issues: d.issues, labels: d.labels, caption: d.caption ?? null })).catch(console.error)
  }, [item])
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
    setData(null)
    setTab('decision')
    setCommandStatus('')
    loadData()
  }, [loadData])
  if (!item) return null
  const openIssueCount = data?.issues.filter(i => i.status === 'open').length ?? 0
  const suggested = item.ingest_status === 'error' ? 'quarantine' : openIssueCount > 0 ? 'postpone' : item.decision_status === 'keep' ? 'keep' : undefined
  const suggestion = data ? (suggested === 'quarantine' ? 'quarantine · file cannot be opened' : suggested === 'postpone' ? `postpone · ${openIssueCount} quality alert${openIssueCount === 1 ? '' : 's'}` : suggested === 'keep' ? 'keep · no open quality alerts' : 'choose a decision') : 'checking quality alerts…'
  const runItemJob = (type: string, label: string) => {
    setCommandStatus(`${label} started…`)
    onJob(() => api.startJob(item.dataset_id, type, { item_ids: [item.id] }), () => {
      setCommandStatus(`${label} finished — refresh results`)
      onRefresh()
    })
  }
  return <aside className="inspector" aria-label="Inspector of the selected item">
    <div className="inspector-head">
      <img className="inspector-preview" src={api.thumbnailUrl(item.id)} alt={`Preview of ${item.original_filename}`} onClick={() => openShot!({ id: item.id, name: item.original_filename, caption: `${item.width}×${item.height}` })} />
      <div className="inspector-id">
        <span className="eyebrow">SELECTED IMAGE</span>
        <h3>{item.original_filename}</h3>
        <p>{item.relative_path}</p>
        <span className={`stat-pill ${item.decision_status}`}>{t(item.decision_status)}</span>
      </div>
      <button className="inspector-close" aria-label="Close inspector" title="close inspector" onClick={onClose}>×</button>
    </div>
    <div className={`inspector-decision${suggested ? ` is-${suggested}` : ''}`}>
      <div className="inspector-decision-copy">
        <span className="eyebrow">RECOMMENDED</span>
        <strong>{suggestion}</strong>
      </div>
      <div className="inspector-actions" aria-label="Image decision">
        {['keep', 'postpone', 'quarantine', 'reject'].map(d =>
          <button key={d} className={`dk ${d}${suggested === d ? ' recommended' : ''}`} onClick={() => api.setDecision(item.id, d === 'postpone' ? 'review' : d).then(onRefresh)}>
            {d}
            {suggested === d && <span className="rec-mark">recommended</span>}
          </button>)}
      </div>
      {item.decision_status !== 'keep' && <button className="sm inspector-restore" onClick={() => api.setDecision(item.id, 'restore').then(onRefresh)}>restore previous decision</button>}
    </div>
    <div className="inspector-meta" aria-label="Image summary">
      <span>{item.width}×{item.height}</span>
      <span>{(item.byte_size / 1024).toFixed(0)} kB</span>
      <span>{data ? openIssueCount : '…'} open {openIssueCount === 1 ? 'alert' : 'alerts'}</span>
    </div>
    <div className="inspector-tabs" role="tablist" aria-label="Inspector tabs">
      <button role="tab" aria-selected={tab === 'decision'} className={tab === 'decision' ? 'on' : ''} onClick={() => setTab('decision')}>decision</button>
      <button role="tab" aria-selected={tab === 'quality'} className={tab === 'quality' ? 'on' : ''} onClick={() => setTab('quality')}>quality{openIssueCount > 0 ? ` ${openIssueCount}` : ''}</button>
      <button role="tab" aria-selected={tab === 'file'} className={tab === 'file' ? 'on' : ''} onClick={() => setTab('file')}>file</button>
      <button role="tab" aria-selected={tab === 'labels'} className={tab === 'labels' ? 'on' : ''} onClick={() => setTab('labels')}>labels{data && data.labels.length > 0 ? ` ${data.labels.length}` : ''}</button>
    </div>
    {tab === 'decision' && <>
      <InspectorHistogram item={item} />
      <section className="isec">
        <div className="isec-title"><h4>General</h4><span>image record</span></div>
        <dl className="kv inspector-general">
          <dt>folder</dt><dd>{item.relative_path.includes('/') || item.relative_path.includes('\\') ? item.relative_path.replace(/[\\/][^\\/]+$/, '') : 'root'}</dd>
          <dt>album</dt><dd>{item.exif_json.Album ?? item.exif_json.album ?? '—'}</dd>
          <dt>size</dt><dd>{inspectorBytes(item.byte_size)}</dd>
          <dt>dimensions</dt><dd>{item.width}×{item.height}{item.channels ? ` · ${item.channels} ch` : ''}</dd>
          <dt>created at</dt><dd>{inspectorDate(item.exif_json.DateTimeOriginal ?? item.created_at)}</dd>
          <dt>modified at</dt><dd>{inspectorDate(item.exif_json.DateTime ?? item.created_at)}</dd>
          <dt>last scanned</dt><dd>{inspectorDate(item.created_at)}</dd>
        </dl>
      </section>
    </>}
    {tab === 'quality' && <section className="isec">
      <div className="isec-title"><h4>Quality review</h4>{data && <span>{openIssueCount} open</span>}</div>
      <p className="inspector-context">{item.ingest_status === 'error' ? 'This file could not be read. Quarantine it before publishing.' : openIssueCount > 0 ? `${openIssueCount} quality alert${openIssueCount === 1 ? '' : 's'} need attention before you keep this image.` : 'No open quality alerts. This image has passed the current quality checks.'}</p>
      {data ? (openIssueCount === 0
        ? <p className="muted">Quality is clear for this image.</p>
        : data.issues.filter(i => i.status === 'open').map(i => <div key={i.id} className="annItem inspector-issue">
            {I.warn}<span className="inspector-issue-copy"><b>{ISSUE_LABELS[i.issue_type] ?? i.issue_type}</b><span className="mono muted">score {i.score.toFixed(2)} · threshold {i.threshold.toFixed(2)}</span><span>{i.detector_name} · {i.detector_version}</span></span>
            <button className="del" type="button" onClick={() => api.ackIssue(i.id, 'acknowledged').then(loadData)}>acknowledge</button>
          </div>)) : <p className="muted">Checking quality alerts…</p>}
    </section>}
    {tab === 'labels' && <section className="isec">
      <div className="isec-title"><h4>Labels & analysis</h4><button className="sm" type="button" onClick={() => { location.hash = `#annotation/${item.dataset_id}` }}>open annotation</button></div>
      <details className="inspector-command">
        <summary>Caption <span>{data?.caption?.status ?? 'not generated'}</span></summary>
        <p className="muted">{data?.caption?.text ?? 'Generate a training caption for this image.'}</p>
        <div className="row">
          <button className="primary sm" type="button" onClick={() => runItemJob('caption', 'Caption')}>generate caption</button>
          <button className="sm" type="button" onClick={() => { location.hash = `#annotation/${item.dataset_id}` }}>edit in Annotate</button>
        </div>
      </details>
      <details className="inspector-command">
        <summary>Run analysis <span>on demand</span></summary>
        <p className="muted">Run only what this image needs. Results appear below or in Annotate.</p>
        <div className="command-grid">
          <button className="sm" type="button" onClick={() => runItemJob('preannotate', 'Label suggestions')}>suggest labels</button>
          <button className="sm" type="button" onClick={() => runItemJob('ocr', 'OCR')}>read text</button>
          <button className="sm" type="button" onClick={() => runItemJob('detection', 'Object detection')}>detect objects</button>
          <button className="sm" type="button" onClick={() => runItemJob('segmentation', 'Mask creation')}>create mask</button>
        </div>
      </details>
      {commandStatus && <p className="mono inspector-command-status" aria-live="polite">{commandStatus}</p>}
      <div className="isec-title inspector-labels-title"><h4>Labels</h4><span>{data ? data.labels.length : '…'}</span></div>
      {data ? (data.labels.length === 0
        ? <p className="muted">No labels for this image. Draw one in Annotation.</p>
        : data.labels.map(l => <div key={l.id} className={`annItem${l.status === 'pending' ? ' pending' : ''}`}>
            <span className="cdot" style={{ background: l.status === 'approved' ? 'var(--ok)' : l.status === 'rejected' ? 'var(--bad)' : 'var(--warn)' }}></span>
            <span className="inspector-issue-copy"><b>{l.label_type} · {l.category}</b><span>{l.confidence == null ? 'confidence unavailable' : `${(l.confidence * 100).toFixed(0)}% confidence`} · {l.source_type}</span></span>
            <span className="mono muted">{t(l.status)}</span>
            {l.status === 'pending' && <button className="primary sm" type="button" onClick={() => api.reviewLabel(l.id, 'approved').then(loadData)}>approve</button>}
            {l.status !== 'rejected' && <button className="del" type="button" onClick={() => api.reviewLabel(l.id, 'rejected').then(loadData)}>reject</button>}
          </div>)) : <p className="muted">Loading labels…</p>}
    </section>}
    {tab === 'file' && <>
      <section className="isec">
        <div className="isec-title"><h4>File details</h4></div>
        <dl className="kv">
          <dt>path</dt><dd>{item.relative_path || 'root'}</dd>
          <dt>dimensions</dt><dd>{item.width}×{item.height}</dd>
          <dt>size</dt><dd>{inspectorBytes(item.byte_size)}</dd>
          <dt>format</dt><dd>{item.mime_type || '—'}</dd>
          <dt>color mode</dt><dd>{item.mode || '—'}</dd>
          <dt>status</dt><dd>{t(item.decision_status)}</dd>
        </dl>
      </section>
      <section className="isec">
        <div className="isec-title"><h4>Metadata</h4><span>adaptive</span></div>
        <input aria-label="Tags" placeholder="tags, comma-separated" defaultValue={item.tags_json.join(',')} onBlur={e =>
          api.setTags(item.id, e.target.value.split(',').map(s => s.trim()).filter(Boolean)).then(onRefresh)} />
        <input aria-label="License" placeholder="license, e.g. CC-BY-4.0" defaultValue={item.license} onBlur={e =>
          api.setLicense(item.id, e.target.value.trim() || 'unknown').then(onRefresh)} />
        {Object.entries(item.exif_json).filter(([key]) => !['brightness_histogram', 'rgb_histogram'].includes(key)).length > 0
          ? <div className="metadata-grid">
              {Object.entries(item.exif_json).filter(([key]) => !['brightness_histogram', 'rgb_histogram'].includes(key)).map(([key, value]) =>
                <div className="metadata-cell" key={key}><span>{metadataLabel(key)}</span><b>{value}</b></div>)}
            </div>
          : <p className="muted">No embedded metadata found.</p>}
      </section>
    </>}
  </aside>
}

function go2(p: PageType, ds: string) { location.hash = `#${p}/${ds}` }
