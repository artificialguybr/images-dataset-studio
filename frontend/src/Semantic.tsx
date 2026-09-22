// Semantic — meaning search.
import { useEffect, useState } from 'react'

import { api, type Item } from './api'

import { Page, PageBar, ModelPicker, apiErrorMessage, openShot, useLightbox } from './shared'
import type { Page as PageType } from './shared'
import type React from 'react'
export function SemanticPage({ ds, go, foot }: { ds: string; go: (p: PageType, ds?: string) => void; foot: React.ReactNode }) {
  const [mode, setMode] = useState<'text' | 'image' | 'clusters'>('text')
  const [q, setQ] = useState('')
  const [referenceId, setReferenceId] = useState('')
  const [referenceItems, setReferenceItems] = useState<Item[]>([])
  const [fStatus, setFStatus] = useState('')
  const [results, setResults] = useState<{ image_id: string; score: number }[]>([])
  const [clusters, setClusters] = useState<{ clusters: { cluster: number; count: number; representative: string | null; members: string[] }[]; outliers: { image_id: string; distance: number }[] } | null>(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [embeddingModel, setEmbeddingModel] = useState('')
  useLightbox(results.map(r => ({ id: r.image_id, name: 'search result', caption: `score ${r.score.toFixed(3)}` })), [results])
  // ponytail: dropdown de referência limitado a 100; com datasets gigantes, troque por busca incremental
  useEffect(() => { api.items(ds, { limit: '100' }).then(setReferenceItems).catch(() => {}) }, [ds])
  const chooseEmbeddingModel = (value: string) => {
    setEmbeddingModel(value)
    if (value) api.activateModel(value, 'embedding').catch(e => setErr(apiErrorMessage(e)))
  }
  const run = async () => {
    setErr(''); setMsg('')
    try {
      if (mode === 'clusters') {
        setClusters(await api.clusters(ds)); setResults([]); return
      }
      if (mode === 'text' && !q.trim()) { setErr('Describe something to search for.'); return }
      if (mode === 'image' && !referenceId) { setErr('Choose a reference image first.'); return }
      const found = await api.searchWithFilters(ds, mode === 'text' ? q.trim() : '', mode === 'image' ? referenceId : '', { status: fStatus })
      setResults(found as { image_id: string; score: number }[]); setClusters(null); setMsg(`${found.length} candidates · no decisions changed`)
      setUnavailable(false)
    } catch (e) {
      const message = apiErrorMessage(e); setErr(message)
      if (message.includes('not installed') || message.includes('501')) setUnavailable(true)
    }
  }
  const prepare = () => api.startJob(ds, 'embeddings', embeddingModel ? { model_id: embeddingModel } : {}).then(() => setMsg('Embeddings job queued. Return when it completes.')).catch(e => setErr(apiErrorMessage(e)))
  const loadClusters = () => run()
  const deriveFrom = (body: Record<string, unknown>, label: string) =>
    api.deriveFrom(ds, `derived-${label}`, body).then(d => setMsg(`derived dataset created: ${d.id.slice(0, 8)}`)).catch(e => setErr(apiErrorMessage(e)))
  return <Page
    bar={<PageBar title="Find" sub="optional semantic discovery">
      <button className={`sm${configOpen ? ' active' : ''}`} onClick={() => setConfigOpen(value => !value)} aria-expanded={configOpen}>configure</button>
    </PageBar>}
    foot={foot}>
    {err && <div className="error" role="alert">{err}</div>}
    {msg && <div className="ok" role="status">{msg}</div>}
    <div className="workflow-screen find-screen">
      <div className="find-context"><span className="eyebrow">ACTIVE DATASET</span><b>Search {referenceItems.length ? `${referenceItems.length.toLocaleString()} images` : 'the dataset'}</b><span className="find-status">{unavailable ? 'EMBEDDINGS NOT READY' : 'INDEX READY'}</span></div>
      <section className="find-composer">
        <header><h1>Describe what you need.</h1><p>Search by text or reference image. Results are candidates; decisions stay unchanged.</p></header>
        <div className="find-modes" role="tablist" aria-label="Discovery mode">
          {(['text', 'image', 'clusters'] as const).map(value => <button key={value} role="tab" aria-selected={mode === value} className={mode === value ? 'active' : ''} onClick={() => { setMode(value); setResults([]); setClusters(null); setErr('') }}>{value === 'text' ? 'Text' : value === 'image' ? 'Reference image' : 'Clusters / outliers'}</button>)}
        </div>
        {mode === 'text' && <form className="find-query" onSubmit={e => { e.preventDefault(); run() }}><input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="e.g. red chair beside a window" aria-label="Describe what to find" /><button className="primary" type="submit" disabled={unavailable}>Search</button></form>}
        {mode === 'image' && <div className="find-query"><select value={referenceId} onChange={e => setReferenceId(e.target.value)} aria-label="Reference image"><option value="">Choose a reference image…</option>{referenceItems.map(item => <option key={item.id} value={item.id}>{item.original_filename}</option>)}</select><button className="primary" onClick={run} disabled={unavailable || !referenceId}>Search similar</button></div>}
        {mode === 'clusters' && <div className="find-query find-cluster-query"><p>Group indexed images and surface the most distant outliers.</p><button className="primary" onClick={loadClusters} disabled={unavailable}>Find clusters</button></div>}
        {configOpen && <div className="find-config"><ModelPicker capability="embedding" value={embeddingModel} onChange={chooseEmbeddingModel} /><label>Status<select value={fStatus} onChange={e => setFStatus(e.target.value)}><option value="">all decisions</option><option value="keep">kept</option><option value="review">to review</option><option value="quarantine">quarantined</option></select></label><button className="sm" onClick={prepare}>prepare embeddings</button></div>}
      </section>
      {unavailable && <div className="empty find-unavailable"><b>Semantic discovery is not ready</b><p>Choose an installed embedding model in Configuration, then prepare embeddings from this screen.</p><button className="primary" onClick={() => go('models')}>Open Configuration</button></div>}
      {!unavailable && results.length === 0 && !clusters && <div className="empty find-empty"><b>Results will appear here.</b><p>Find suggests candidates; it never changes a decision.</p></div>}
      {results.length > 0 && <section className="find-results"><header><div><span className="eyebrow">CANDIDATES</span><h2>Closest matches for “{mode === 'text' ? q : referenceItems.find(item => item.id === referenceId)?.original_filename}”</h2></div><span className="mono">{results.length} results</span></header><div className="gallery">{results.map(result => <article key={result.image_id} className="find-result"><button className="find-result-image" onClick={() => openShot?.({ id: result.image_id, name: 'search result', caption: `score ${result.score.toFixed(3)}` })}><img loading="lazy" src={api.thumbnailUrl(result.image_id)} alt="" /></button><b>{referenceItems.find(item => item.id === result.image_id)?.original_filename || result.image_id.slice(0, 8)}</b><small>{Math.round(result.score * 100)}% similarity</small><div><button className="sm" onClick={() => go('issues', ds)}>Review</button><button className="sm" onClick={() => go('annotation', ds)}>Annotate</button></div></article>)}</div></section>}
      {clusters && <section className="find-clusters"><header><div><span className="eyebrow">DISCOVERY MAP</span><h2>{clusters.clusters.length} clusters · {clusters.outliers.length} outliers</h2></div><button className="sm" onClick={() => deriveFrom({ outliers: true }, 'outliers')}>derive outliers dataset</button></header><table><thead><tr><th>cluster</th><th>items</th><th>representative</th><th></th></tr></thead><tbody>{clusters.clusters.map(cluster => <tr key={cluster.cluster}><td className="mono">{cluster.cluster}</td><td>{cluster.count}</td><td>{cluster.representative && <img src={api.thumbnailUrl(cluster.representative)} alt="" />}</td><td><button className="sm" onClick={() => deriveFrom({ cluster_index: cluster.cluster }, `cluster-${cluster.cluster}`)}>derive</button></td></tr>)}</tbody></table><div className="gallery">{clusters.outliers.map(outlier => <button className="thumb" key={outlier.image_id} onClick={() => openShot?.({ id: outlier.image_id, name: 'outlier', caption: `distance ${outlier.distance.toFixed(3)}` })}><img loading="lazy" src={api.thumbnailUrl(outlier.image_id)} alt="" /><span className="name">distance {outlier.distance.toFixed(2)}</span></button>)}</div></section>}
    </div>
  </Page>
}


// ---------- Workspace header ----------
