// Annotate — canvas-based annotation workspace.
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, type Caption, type Label } from './api'

import { I, ModelPicker, apiErrorMessage, openShot, useItemWindow } from './shared'
import type React from 'react'
const annotationColors = ['#ff5b57', '#ffb547', '#31d0aa', '#4da3ff', '#b18cff', '#ff70b8']
const polygonPoints = (geometry: Record<string, number>) => {
  const raw: unknown = geometry['points']
  if (!Array.isArray(raw)) return []
  return raw.filter((point): point is { x: number; y: number } =>
    typeof point === 'object' && point !== null &&
    'x' in point && 'y' in point &&
    typeof point.x === 'number' && typeof point.y === 'number')
}
const annotationModeNames = { bbox: 'Rectangle', polygon: 'Polygon', keypoint: 'Point', note: 'Comment' } as const
const layerValueText = (label: Label) => {
  const value = label.value_json?.text
  return typeof value === 'string' ? value : ''
}

export function AnnotationPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  // items via useAllItems
  const [idx, setIdx] = useState(0)
  const [category, setCategory] = useState('')
  const [labels, setLabels] = useState<Label[]>([])
  const [caption, setCaption] = useState<Caption | null>(null)
  const [captionDraft, setCaptionDraft] = useState('')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)
  const [live, setLive] = useState<Record<string, number> | null>(null)
  const [draft, setDraft] = useState<Record<string, number> | null>(null)
  const [savedAt, setSavedAt] = useState('')
  const [mode, setMode] = useState<'bbox' | 'polygon' | 'keypoint' | 'note'>('bbox')
  const [noteText, setNoteText] = useState('')
  const [polyPts, setPolyPts] = useState<{ x: number; y: number }[]>([])
  const [zoom, setZoom] = useState(1)
  const [piiModel, setPiiModel] = useState('')
  const choosePiiModel = (value: string) => {
    setPiiModel(value)
    if (value) api.activateModel(value, 'pii').catch(e => setSavedAt(apiErrorMessage(e)))
  }
  const [selectedLayer, setSelectedLayer] = useState<string | null>(null)
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set())
  const [editingLayer, setEditingLayer] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [layerOrder, setLayerOrder] = useState<string[]>([])
  const wrapRef = useRef<HTMLDivElement>(null)
  const { items, reload: load, ensure } = useItemWindow(ds)
  useEffect(() => { load() }, [load])
  const item = items[idx]
  const categories = [...new Set(labels.map(label => label.category).filter(Boolean))]
  const orderedLabels = [...labels].sort((a, b) => {
    const ai = layerOrder.indexOf(a.id); const bi = layerOrder.indexOf(b.id)
    return (ai < 0 ? labels.length : ai) - (bi < 0 ? labels.length : bi)
  })
  const layerColor = useCallback((label: Label) => annotationColors[Math.max(0, orderedLabels.indexOf(label)) % annotationColors.length], [orderedLabels])
  const labelName = category.trim()

  useEffect(() => {
    if (!item) return
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
    setDraft(null); setSavedAt(''); setSelectedLayer(null); setHiddenLayers(new Set()); setZoom(1)
    setEditingLayer(null); setEditingName('')
    const raw = localStorage.getItem(`draft-${item.id}`)
    if (raw) setDraft(JSON.parse(raw))
    const savedOrder = localStorage.getItem(`layer-order-${item.id}`)
    if (!savedOrder) { setLayerOrder([]); return }
    try {
      const parsed: unknown = JSON.parse(savedOrder)
      setLayerOrder(Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [])
    } catch { setLayerOrder([]) }
  }, [item])
  useEffect(() => {
    if (!draft || !item) return
    const tv = setTimeout(() => {
      localStorage.setItem(`draft-${item.id}`, JSON.stringify(draft))
      setSavedAt(new Date().toLocaleTimeString())
    }, 800)
    return () => clearTimeout(tv)
  }, [draft, item])
  const loadLabels = useCallback(() => {
    if (!item) return
    api.item(item.id).then((d: { labels: Label[]; caption?: Caption | null }) => {
      const ids = d.labels.map(label => label.id)
      setLabels(d.labels)
      setCaption(d.caption ?? null)
      setCaptionDraft(d.caption?.text ?? '')
      setLayerOrder(current => [...current.filter(id => ids.includes(id)), ...ids.filter(id => !current.includes(id))])
    })
  }, [item])
  useEffect(() => { loadLabels() }, [loadLabels])
  useEffect(() => {
    if (item) localStorage.setItem(`layer-order-${item.id}`, JSON.stringify(layerOrder))
  }, [item, layerOrder])
  const moveLayer = (id: string, direction: -1 | 1) => setLayerOrder(current => {
    const order = orderedLabels.map(label => label.id)
    const index = order.indexOf(id); const nextIndex = index + direction
    if (index < 0 || nextIndex < 0 || nextIndex >= order.length) return current
    ;[order[index], order[nextIndex]] = [order[nextIndex], order[index]]
    return order
  })
  const saveLayerName = async () => {
    if (!editingLayer || !editingName.trim()) return
    try {
      await api.updateLabel(editingLayer, editingName.trim())
      setEditingLayer(null); setEditingName(''); setSavedAt('layer renamed'); loadLabels()
    } catch (error) { setSavedAt(apiErrorMessage(error)) }
  }
  const saveCaption = async () => {
    if (!item || !captionDraft.trim()) return
    try {
      const saved = await api.updateCaption(item.id, captionDraft.trim())
      setCaption(saved)
      setCaptionDraft(saved.text)
      setSavedAt('caption saved')
    } catch (error) {
      setSavedAt(apiErrorMessage(error))
    }
  }
  useEffect(() => {
    const im = new Image()
    im.onload = () => setImg(im)
    if (item) im.src = api.fileUrl(item.id, 1280)
  }, [item])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      const modes = ['bbox', 'polygon', 'keypoint', 'note'] as const
      if (['1', '2', '3', '4'].includes(e.key)) { setMode(modes[Number(e.key) - 1]); setPolyPts([]) }
      else if (e.key === 'ArrowLeft') { setIdx(value => Math.max(0, value - 1)); ensure(idx - 1); setZoom(1) }
      else if (e.key === 'ArrowRight') { setIdx(value => Math.min(items.length - 1, value + 1)); ensure(idx + 1); setZoom(1) }
      else if (e.key === '+' || e.key === '=') setZoom(value => Math.min(2, +(value + .25).toFixed(2)))
      else if (e.key === '-') setZoom(value => Math.max(.5, +(value - .25).toFixed(2)))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items.length, ensure, idx])
  useEffect(() => {
    const c = canvasRef.current, im = img
    if (!c || !im || !item) return
    const box = wrapRef.current?.getBoundingClientRect()
    const maxW = Math.max(200, (box?.width ?? 900) - 8)
    const maxH = Math.max(160, window.innerHeight - 230)
    const scale = Math.min(maxW / im.width, maxH / im.height, 1.2)
    c.width = im.width * scale; c.height = im.height * scale
    const ctx = c.getContext('2d')!
    ctx.drawImage(im, 0, 0, c.width, c.height)
    // geometria é guardada no espaço da IMAGEM ORIGINAL; o canvas (preview) só escala
    const r = (v: number) => v * (c.width / (item?.width || im.width))
    for (const lb of orderedLabels) {
      if (hiddenLayers.has(lb.id) || lb.label_type !== 'bbox') continue
      const color = layerColor(lb); const g = lb.geometry_json
      ctx.strokeStyle = color; ctx.lineWidth = selectedLayer === lb.id ? 3 : 2
      ctx.strokeRect(r(g.x), r(g.y), r(g.w), r(g.h))
      ctx.font = '11px "IBM Plex Mono", monospace'; ctx.fillStyle = color
      ctx.fillRect(r(g.x), Math.max(0, r(g.y) - 16), ctx.measureText(lb.category).width + 12, 16)
      ctx.fillStyle = '#fff'; ctx.fillText(lb.category, r(g.x) + 5, Math.max(11, r(g.y) - 5))
    }
    for (const lb of orderedLabels) {
      if (hiddenLayers.has(lb.id)) continue
      const color = layerColor(lb)
      if (lb.label_type === 'polygon') {
        const pts = polygonPoints(lb.geometry_json)
        if (!pts.length) continue
        ctx.strokeStyle = color; ctx.lineWidth = selectedLayer === lb.id ? 3 : 2; ctx.fillStyle = `${color}25`
        ctx.beginPath(); ctx.moveTo(r(pts[0].x), r(pts[0].y))
        for (const pt of pts.slice(1)) ctx.lineTo(r(pt.x), r(pt.y))
        ctx.closePath(); ctx.fill(); ctx.stroke()
      } else if (lb.label_type === 'keypoint') {
        const g = lb.geometry_json
        ctx.fillStyle = color; ctx.beginPath(); ctx.arc(r(g.x), r(g.y), selectedLayer === lb.id ? 6 : 4, 0, Math.PI * 2); ctx.fill()
      }
    }
    if (live) { ctx.strokeStyle = '#e5a04b'; ctx.setLineDash([6, 4]); ctx.strokeRect(r(live.x), r(live.y), r(live.w), r(live.h)); ctx.setLineDash([]) }
    if (polyPts.length) {
      ctx.strokeStyle = '#e5a04b'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(r(polyPts[0].x), r(polyPts[0].y))
      for (const pt of polyPts.slice(1)) ctx.lineTo(r(pt.x), r(pt.y))
      ctx.stroke()
      for (const pt of polyPts) { ctx.fillStyle = '#e5a04b'; ctx.fillRect(r(pt.x) - 2, r(pt.y) - 2, 4, 4) }
    }
  }, [img, labels, item, live, polyPts, hiddenLayers, selectedLayer, orderedLabels, layerColor])
  const pos = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const c = canvasRef.current!; const r = c.getBoundingClientRect()
    // coords no espaço da IMAGEM ORIGINAL: o canvas mostra o preview (item.width -> c.width)
    const k = (item?.width || c.width) / c.width
    return { x: (e.clientX - r.left) * (c.width / r.width) * k, y: (e.clientY - r.top) * (c.height / r.height) * ((item?.height || c.height) / c.height) }
  }
  return <div className="page" style={{ overflow: 'hidden' }}>
    <div className="pagebar annotate-bar">
      <span className="mono annotate-counter">{item ? `${idx + 1} / ${items.length}` : 'no items'}</span>
      <h2 style={{ fontSize: 17 }}>Annotate</h2><span className="sub">{item ? item.original_filename : 'empty queue'}</span>
      <span className="spacer" />{savedAt && <span className="mono annotate-save-state">{savedAt}</span>}
      <ModelPicker capability="pii" value={piiModel} onChange={choosePiiModel} />
      <button className="sm" onClick={() => api.startJob(ds, 'pii_scan', piiModel ? { model_id: piiModel } : {}).then(() => setSavedAt('PII scan started')).catch(e => setSavedAt(apiErrorMessage(e)))}>scan PII</button>
      <button className="sm" onClick={() => { if (window.confirm('Apply PII redaction? This creates a new version; originals stay preserved.')) api.redactPii(ds).then(() => setSavedAt('PII redact started — see jobs on Home')).catch(e => alert(e.message)) }} title="apply blur to possible-PII regions (job)">redact PII</button>
    </div>
    <div className="annotate">
      <div className="annotate-stage" ref={wrapRef}>
        <button className="annotate-nav annotate-prev" aria-label="Previous image" onClick={() => { setIdx(i => Math.max(0, i - 1)); ensure(idx - 1); setZoom(1) }} disabled={idx === 0}><span className="nav-icon">{I.chevL}</span><span>previous</span></button>
        <div className="annotate-canvas-wrap">
          <canvas ref={canvasRef} className="annotate" tabIndex={0} style={{ touchAction: 'none', cursor: mode === 'bbox' ? 'crosshair' : mode === 'polygon' ? 'cell' : mode === 'keypoint' ? 'crosshair' : 'default', transform: `scale(${zoom})` }} aria-label="Annotation canvas; use mouse or touch to draw"
            onDoubleClick={() => {
              if (mode !== 'polygon' || polyPts.length < 3) { if (item) openShot!({ id: item.id, name: item.original_filename, caption: `${idx + 1}/${items.length}` }); return }
              if (!labelName) { setSavedAt('type a layer label first'); return }
              api.addLabel(item.id, { label_type: 'polygon', category: labelName, geometry: { points: polyPts }, source_type: 'human' }).then(() => { setPolyPts([]); loadLabels() }).catch(error => setSavedAt(apiErrorMessage(error)))
            }}
            onPointerDown={e => {
              if (!item) return
              e.currentTarget.setPointerCapture(e.pointerId)
              const point = pos(e)
              if (mode === 'keypoint') {
                if (!labelName) { setSavedAt('type a layer label first'); return }
                api.addLabel(item.id, { label_type: 'keypoint', category: labelName, geometry: { x: point.x, y: point.y }, source_type: 'human' }).then(loadLabels).catch(error => setSavedAt(apiErrorMessage(error))); return
              }
              if (mode === 'polygon') { setPolyPts(points => [...points, point]); return }
              drag.current = point
            }}
            onPointerMove={e => {
              if (!drag.current || mode !== 'bbox') return
              const b = pos(e); setLive({ x: Math.min(drag.current.x, b.x), y: Math.min(drag.current.y, b.y), w: Math.abs(b.x - drag.current.x), h: Math.abs(b.y - drag.current.y) })
            }}
            onPointerUp={e => {
              const a = drag.current; drag.current = null; setLive(null)
              if (mode !== 'bbox' || !a) return
              const b = pos(e); const g = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) }
              if (g.w < 3 || g.h < 3) return
              if (!labelName) { setSavedAt('type a layer label first'); return }
              setDraft(g)
              api.addLabel(item.id, { label_type: 'bbox', category: labelName, geometry: g, source_type: 'human' }).then(() => { localStorage.removeItem(`draft-${item.id}`); setDraft(null); setSavedAt(''); loadLabels() }).catch(error => { setDraft(null); setSavedAt(apiErrorMessage(error)) })
            }}
            onPointerCancel={() => { drag.current = null; setLive(null) }}
            onLostPointerCapture={() => { drag.current = null; setLive(null) }} />
          <div className="annotate-zoom" aria-label="Image zoom">
            <button className="sm" aria-label="Zoom out" onClick={() => setZoom(value => Math.max(.5, +(value - .25).toFixed(2)))}>−</button>
            <button className="sm zoom-value" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
            <button className="sm" aria-label="Zoom in" onClick={() => setZoom(value => Math.min(2, +(value + .25).toFixed(2)))}>+</button>
        </div>
        </div>
        <button className="annotate-nav annotate-next" aria-label="Next image" onClick={() => { setIdx(i => Math.min(items.length - 1, i + 1)); ensure(idx + 1); setZoom(1) }} disabled={idx >= items.length - 1}><span className="nav-icon">{I.chevR}</span><span>next</span></button>
      </div>
      <aside className="annotate-inspector" aria-label="Annotation tools and properties">
        <div className="annotate-panel-head"><div><span className="eyebrow">LABEL WORKSPACE</span><h3>Label this image</h3></div><span className="annotate-panel-count mono">{labels.length} layers</span></div>
        <p className="muted">{item ? `${idx + 1} of ${items.length} · choose a layer, then draw on the image` : 'no image selected'}</p>
        <section className="annotation-accordion">
          <div className="annotation-section-head"><b>Draw labels</b><span>1–4</span></div>
          <div className="toolrow mode-selector" role="group" aria-label="Drawing mode">
            {(['bbox', 'polygon', 'keypoint', 'note'] as const).map(m => <button type="button" key={m} className={mode === m ? 'on' : ''} aria-pressed={mode === m} aria-label={annotationModeNames[m]} title={annotationModeNames[m]} onClick={() => { setMode(m); setPolyPts([]); setLive(null); drag.current = null }}>
              <span className="mode-icon" aria-hidden="true">{m === 'bbox' ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="4" y="5" width="16" height="14" rx="1.5" /></svg> : m === 'polygon' ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m5 6 9-2 5 6-3 9-10 1-3-7Z" /></svg> : m === 'keypoint' ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="4" /><path d="M12 3v5M12 16v5M3 12h5M16 12h5" /></svg> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M5 5h14v10H9l-4 4V5Z" /><path d="M8 9h8M8 12h5" /></svg>}</span>
              <span className="mode-label">{annotationModeNames[m]}</span>
            </button>)}
          </div>
          <label className="field-label compact-label">Layer label
            <input list={`label-categories-${ds}`} value={category} onChange={e => setCategory(e.target.value)} placeholder="Type any label…" />
            <datalist id={`label-categories-${ds}`}>{categories.map(value => <option key={value} value={value} />)}</datalist>
          </label>
        </section>
        <details className="annotation-accordion">
          <summary>Training caption <span>{caption?.status ?? 'not generated'}</span></summary>
          <section className="caption-editor" aria-label="Image caption">
            <div className="layer-heading"><h4>Training caption</h4><span className="muted">{caption?.status ?? 'not generated'}</span></div>
            <textarea rows={4} value={captionDraft} onChange={e => setCaptionDraft(e.target.value)} placeholder="Generate in Gallery, then refine this caption…" />
            <div className="row">
              <button type="button" className="primary sm" disabled={!captionDraft.trim() || captionDraft === caption?.text} onClick={saveCaption}>save caption</button>
              {caption?.status === 'pending' && <><button type="button" className="sm" onClick={() => api.reviewCaption(caption.id, 'approved').then(loadLabels)}>approve</button><button type="button" className="sm del" onClick={() => api.reviewCaption(caption.id, 'rejected').then(loadLabels)}>reject</button></>}
            </div>
          </section>
        </details>
        {mode === 'note' && item && <section className="annotation-accordion">
          <div className="annotation-section-head"><b>Comment</b><span>text layer</span></div>
          <textarea className="note-input" rows={3} value={noteText} onChange={e => setNoteText(e.target.value)} placeholder="write a comment for this image…" />
          <div className="row" style={{ marginTop: 6 }}><button type="button" className="primary sm" disabled={!noteText.trim() || !labelName} onClick={() => api.addLabel(item.id, { label_type: 'note', category: labelName, geometry: {}, value: { text: noteText }, source_type: 'human' }).then(() => { setNoteText(''); loadLabels() })}>save comment</button></div>
        </section>}
        <p className="muted" style={{ marginTop: 8 }}>{mode === 'bbox' ? 'drag on the canvas to draw a rectangle' : mode === 'polygon' ? 'click points · double-click closes' : mode === 'keypoint' ? 'click to mark a point' : 'write a comment and save'}</p>
        {savedAt && <p className="mono annotate-save-state">{savedAt}</p>}
        <section className="annotation-accordion">
          <div className="annotation-section-head"><b>Layers</b><span>{labels.length}</span></div>
          <div className="layer-heading">{hiddenLayers.size > 0 && <button type="button" className="sm" onClick={() => setHiddenLayers(new Set())}>show all</button>}<span className="muted mono">{labels.length}</span></div>
          {labels.length === 0 && <p className="muted">draw on the canvas to create the first layer</p>}
          <div className="layer-list" aria-label="Annotation layers">
            {orderedLabels.map(l => {
              const color = layerColor(l); const hidden = hiddenLayers.has(l.id); const layerIndex = orderedLabels.indexOf(l)
              return <div key={l.id} className={`annItem layer-row${selectedLayer === l.id ? ' selected' : ''}${hidden ? ' hidden' : ''}`}>
                {editingLayer === l.id
                  ? <input className="layer-name-input" value={editingName} autoFocus onChange={e => setEditingName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') saveLayerName(); if (e.key === 'Escape') { setEditingLayer(null); setEditingName('') } }} onBlur={saveLayerName} aria-label={`Rename ${l.category} layer`} />
                  : <button type="button" className="layer-select" onClick={() => setSelectedLayer(l.id)} onDoubleClick={() => { setEditingLayer(l.id); setEditingName(l.category) }} aria-label={`Select ${l.category} layer`}><span className="layer-swatch" style={{ background: color }} /><span className="layer-copy"><b>{l.category}</b><span className="muted mono">{l.label_type} · {l.status}{l.confidence == null ? '' : ` · ${(l.confidence * 100).toFixed(0)}%`}</span>{(l.label_type === 'note' || l.label_type === 'text') && layerValueText(l) && <span className="note-text">{layerValueText(l)}</span>}</span></button>}
                <div className="layer-actions">
                  <button type="button" className="layer-edit" onClick={() => { setEditingLayer(l.id); setEditingName(l.category); setSelectedLayer(l.id) }} aria-label={`Rename ${l.category} layer`} title="Rename layer"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m4 16-.8 4.8L8 20l11-11-4-4L4 16Z" /><path d="m13 6 4 4" /></svg></button>
                  <button type="button" className="layer-move" onClick={() => moveLayer(l.id, -1)} disabled={layerIndex === 0} aria-label={`Move ${l.category} layer up`} title="Move layer up"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m6 14 6-6 6 6" /></svg></button>
                  <button type="button" className="layer-move" onClick={() => moveLayer(l.id, 1)} disabled={layerIndex === orderedLabels.length - 1} aria-label={`Move ${l.category} layer down`} title="Move layer down"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m6 10 6 6 6-6" /></svg></button>
                  <button type="button" className="layer-eye" onClick={() => setHiddenLayers(current => { const next = new Set(current); if (hidden) next.delete(l.id); else next.add(l.id); return next })} aria-label={`${hidden ? 'Show' : 'Hide'} ${l.category} layer`} title={`${hidden ? 'Show' : 'Hide'} layer`}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z" /><circle cx="12" cy="12" r="2.5" /></svg></button>
                  {l.status === 'pending' && <button type="button" className="primary sm" onClick={() => api.reviewLabel(l.id, 'approved').then(loadLabels)}>approve</button>}
                  {l.status !== 'rejected' && <button type="button" className="del layer-reject" onClick={() => api.reviewLabel(l.id, 'rejected').then(loadLabels)} aria-label={`Reject ${l.category} layer`} title="Reject layer">{I.reject}</button>}
                </div>
              </div>
            })}
          </div>
        </section>
        <h4 style={{ marginTop: 14 }}>Shortcuts</h4><p className="muted">1–4 modes · ← → image · − + zoom · double-click opens</p>
      </aside>
    </div>
    {foot && <div className="footbar" style={{ marginTop: 'auto' }}>{foot}</div>}
  </div>
}
