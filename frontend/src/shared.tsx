/* oxlint-disable only-export-components */
// shared — vocabulary, helpers, icons, lightbox, hooks, shell components.
// oxlint-disable-file react/only-export-components — barrel de utilitários compartilhados; fast-refresh não se aplica
// oxlint-disable-file react/only-export-components — barrel de utilitários compartilhados; fast-refresh não se aplica
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, type Item, type Job, type ModelCatalog } from './api'

export type Page = 'dashboard' | 'clean' | 'dataset' | 'issues' | 'annotation' | 'semantic' | 'versions' | 'export' | 'models'
export const ISSUE_TYPES = ['blur', 'underexposed', 'overexposed', 'low_contrast', 'low_information', 'small_resolution', 'odd_aspect_ratio', 'grayscale', 'corrupt_file', 'screenshot', 'possible_pii']

// English display labels for backend domain keys
export const ISSUE_LABELS: Record<string, string> = {
  blur: 'blurry', underexposed: 'underexposed', overexposed: 'overexposed',
  low_contrast: 'low contrast', low_information: 'low information',
  small_resolution: 'small resolution', odd_aspect_ratio: 'odd aspect ratio',
  grayscale: 'grayscale', corrupt_file: 'corrupt file',
  screenshot: 'screenshot/watermark', possible_pii: 'possible PII',
}
export const STATUS_LABELS: Record<string, string> = {
  keep: 'kept', review: 'review', quarantine: 'quarantine',
  reject: 'rejected', pending: 'pending', approved: 'approved',
  rejected: 'rejected', acknowledged: 'acknowledged', open: 'open',
  error: 'error', restore: 'restored',
}
export const t = (s: string) => STATUS_LABELS[s] ?? ISSUE_LABELS[s] ?? s

export function apiErrorMessage(error: unknown) {
  const raw = error instanceof Error ? error.message : String(error)
  const payload = raw.replace(/^\d+:\s*/, '')
  try {
    const detail = JSON.parse(payload).detail
    if (typeof detail === 'string') return detail
  } catch {
    // Plain-text API errors are already useful to the user.
  }
  return payload
}
export type Theme = 'light' | 'dark'


// inline SVG icons, consistent stroke (no emoji in the UI)
export const I = {
  keep: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>,
  reject: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>,
  review: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>,
  quarantine: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>,
  undo: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/><path d="M21 17a9 9 0 0 1-9 9 9 9 0 0 1-6-2.3L3 22"/></svg>,
  fullscreen: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>,
  warn: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>,
  license: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v18"/><path d="M6 7h12"/><path d="M6 17h12"/><path d="M8 3h8"/></svg>,
  export: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>,
  import: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/></svg>,
  plus: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>,
  chevL: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>,
  chevR: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 18 6-6-6-6"/></svg>,
  chevD: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>,
  funnel: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5h16l-6 7v5l-4 2v-7L4 5Z"/></svg>,
  bookmark: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4h12v17l-6-4-6 4Z"/></svg>,
  info: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>,
}

// ---------- lightbox global ----------
export type Shot = { id: string; name: string; caption?: string }
export let openShot: ((s: Shot | null) => void) | null = null
let shotNav: ((d: number) => void) | null = null

export function Lightbox() {
  const [shot, setShot] = useState<Shot | null>(null)
  const [zoom, setZoom] = useState(1)
  const [playing, setPlaying] = useState(false)
  const [help, setHelp] = useState(false)
  const [loupePos, setLoupePos] = useState<{ sx: number; sy: number; wPct: number; hPct: number; px: number; py: number } | null>(null)
  const [hoverMode, setHoverMode] = useState(false)
  const stageRef = useRef<HTMLDivElement>(null)
  useEffect(() => { openShot = (s) => { setShot(s); setZoom(1); setLoupePos(null); setHoverMode(false); if (s) setCurId(s.id) } }, [])
  const close = () => { setShot(null); setZoom(1); setPlaying(false); setHelp(false); setLoupePos(null); setHoverMode(false) }
  const next = (direction: number) => { if (shotNav) shotNav(direction) }
  useEffect(() => {
    if (!playing || !shotNav) return
    const timer = window.setInterval(() => shotNav?.(1), 2600)
    return () => window.clearInterval(timer)
  }, [playing, shot])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!shot) return
      if (e.key === 'Escape') close()
      else if (e.key === 'ArrowRight') next(1)
      else if (e.key === 'ArrowLeft') next(-1)
      else if (e.key === '+' || e.key === '=') setZoom(z => Math.min(3, +(z + .25).toFixed(2)))
      else if (e.key === '-' || e.key === '_') setZoom(z => Math.max(1, +(z - .25).toFixed(2)))
      else if (e.key === '0') setZoom(1)
      else if (e.key.toLowerCase() === 'a' || e.key === ' ') { e.preventDefault(); setPlaying(p => !p) }
      else if (e.key.toLowerCase() === 'm') setHoverMode(h => !h)
      else if (e.key === '?') setHelp(p => !p)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shot, playing])
  if (!shot) return null
  return <div className="lb-backdrop" role="dialog" aria-modal="true" aria-label={`Viewing ${shot.name}`} onClick={close}>
      <div className="lb-body" onClick={e => e.stopPropagation()}>
        <div className="lb-toolbar">
          <span className="mono">{Math.round(zoom * 100)}%</span>
          <button className="sm" onClick={() => setZoom(z => Math.max(1, +(z - .25).toFixed(2)))} title="zoom out (-)">−</button>
          <button className="sm" onClick={() => setZoom(1)} title="reset zoom (0)">100%</button>
          <button className="sm" onClick={() => setZoom(z => Math.min(3, +(z + .25).toFixed(2)))} title="zoom in (+)">+</button>
          <button className={`sm${playing ? ' active' : ''}`} onClick={() => setPlaying(p => !p)} title="auto-advance (A or space)">{playing ? 'pause' : 'auto'}</button>
          <button className={`sm${hoverMode ? ' active' : ''}`} onClick={() => setHoverMode(h => !h)} title="hover zoom (magnifier)">loupe</button>
          <button className="sm" onClick={() => setHelp(p => !p)} title="shortcuts (?)">?</button>
          <span className="spacer" />
          <button className="lb-fullscreen" aria-label="Open image fullscreen" onClick={() => document.querySelector('.lb-stage')?.requestFullscreen?.()} title="fullscreen">{I.fullscreen}</button>
          <button className="lb-close" aria-label="Close image" onClick={close} title="close (Esc)">×</button>
        </div>
        <div className="lb-stage" ref={stageRef} onClick={e => e.stopPropagation()}
          onMouseMove={e => {
            if (!hoverMode || !shot) return
            const stage = stageRef.current!
            const r = stage.getBoundingClientRect()
            const imgEl = stage.querySelector('.lb-img') as HTMLImageElement
            if (!imgEl || !imgEl.naturalWidth) return
            const iR = imgEl.getBoundingClientRect()
            const D = 280, MAG = 2
            const wPct = D / iR.width * MAG * 100
            const hPct = D / iR.height * MAG * 100
            const nx = (e.clientX - iR.left) * imgEl.naturalWidth / iR.width
            const ny = (e.clientY - iR.top) * imgEl.naturalHeight / iR.height
            const winW = D * imgEl.naturalWidth / iR.width * MAG
            const winH = D * imgEl.naturalHeight / iR.height * MAG
            setLoupePos({
              sx: e.clientX - r.left, sy: e.clientY - r.top,
              wPct, hPct,
              px: Math.min(100, Math.max(0, (nx - winW / 2) / imgEl.naturalWidth * 100)),
              py: Math.min(100, Math.max(0, (ny - winH / 2) / imgEl.naturalHeight * 100)),
            })
          }}
          onMouseLeave={() => setLoupePos(null)}>
          <img className="lb-img" style={{ transform: `scale(${zoom})` }} src={api.fileUrl(shot.id)} alt={shot.name}
            onClick={() => setZoom(z => z === 1 ? 2 : 1)} />
          {shotNav && <>
            <button className="lb-prev" aria-label="Previous image" onClick={() => next(-1)} title="previous (←)">‹</button>
            <button className="lb-next" aria-label="Next image" onClick={() => next(1)} title="next (→)">›</button>
          </>}
          {hoverMode && loupePos && shot && <div className="lb-loupe"
            style={{
              left: loupePos.sx, top: loupePos.sy,
              backgroundSize: `${loupePos.wPct}% ${loupePos.hPct}%`,
              backgroundPosition: `${loupePos.px}% ${loupePos.py}%`,
              backgroundImage: `url(${api.fileUrl(shot.id)})`,
            }} />}
        </div>
        <div className="lb-cap">
          <b>{shot.name}</b>
          {shot.caption && <span className="muted"> · {shot.caption}</span>}
          <span className="muted"> · click the image to zoom</span>
        </div>
        {help && <div className="lb-help"><kbd>←</kbd><kbd>→</kbd> navigate <kbd>+</kbd><kbd>−</kbd> zoom <kbd>0</kbd> reset <kbd>A</kbd>/<kbd>space</kbd> auto <kbd>Esc</kbd> close</div>}
      </div>
    </div>
}

export const GALLERY_PAGE = 120

export function useLightbox(shots: Shot[], deps: unknown[] = []) {
  useEffect(() => {
    shotNav = (d: number) => {
      if (!shots.length || !openShot) return
      const cur = shots.findIndex(s => s.id === curId())
      const n = (cur + d + shots.length) % shots.length
      openShot(shots[n])
    }
    return () => { shotNav = null }
  // oxlint-disable-next-line react-hooks/exhaustive-deps — deps variádico passado pelas páginas
  }, deps)
}
let _curShotId = ''
function curId() { return _curShotId }
const setCurId = (id: string) => { _curShotId = id }

// modular filter builder rows: key -> display title; add new backend-supported filters here
export const ADV_KEYS: [string, string][] = [['status', 'status'], ['issue', 'issues'], ['license', 'license'], ['label', 'labels'], ['min_width', 'min width'], ['tag', 'tag']]

// ---------- hooks ----------

export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  // registry of in-flight polling loops so unmount aborts them (no leaked intervals)
  const loops = useRef<Set<string>>(new Set())
  useEffect(() => () => { loops.current.clear() }, [])
  const track = useCallback(async (id: string) => {
    const j: Job = await api.job(id)
    setJobs(prev => {
      const known = prev.find(x => x.id === id)
      return known ? prev.map(x => x.id === id ? j : x) : [...prev, j]
    })
    return j.status
  }, [])
  const start = useCallback(async (fn: () => Promise<{ job_id: string }>, onDone: () => void) => {
    const { job_id } = await fn()
    loops.current.add(job_id)
    // backoff exponencial: 800ms -> ~5s; jobs longos não martelam a API
    let delay = 800
    for (;;) {
      await new Promise<void>(resolve => window.setTimeout(resolve, delay))
      if (!loops.current.has(job_id)) return  // unmounted — abort polling
      const st = await track(job_id)
      if (st === 'completed' || st === 'failed' || st === 'cancelled') {
        loops.current.delete(job_id)
        onDone()
        return
      }
      delay = Math.min(delay * 1.6, 5000)
    }
  }, [track])
  return { jobs, start }
}
export function useModelCatalog() {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api.modelCatalog()
    .then(value => { setError(''); setCatalog(value); return value })
    .catch(e => { setError(apiErrorMessage(e)); throw e }), [])
  useEffect(() => { load().catch(() => {}) }, [load])
  return { catalog, error, reload: load }
}

export function ModelPicker({ capability, value, onChange }: { capability: string; value: string; onChange: (value: string) => void }) {
  const { catalog } = useModelCatalog()
  const choices = catalog?.models.filter(model => model.capability === capability) ?? []
  const activeModel = choices.find(model => model.active)
  const selected = value || activeModel?.id || ''
  return <label className="model-picker">model
    <select value={selected} onChange={e => onChange(e.target.value)} aria-label={`${capability} model`}>
      <option value="">automatic{activeModel ? ` (${activeModel.name})` : ' (none installed)'}</option>
      {choices.map(model => <option key={model.id} value={model.id} disabled={!model.installed}>{model.name}{model.installed ? '' : ' · install first'}</option>)}
    </select>
  </label>
}

// ---------- shared shell ----------

/** compact top bar: title + sub + actions (Curate-style) */
export function PageBar({ title, sub, children }: { title: React.ReactNode; sub?: React.ReactNode; children?: React.ReactNode }) {
  return <div className="pagebar">
    <h2>{title}</h2>
    {sub && <span className="sub">{sub}</span>}
    <span className="spacer" />
    {children}
  </div>
}

/** standard page layout */
export function Page({ bar, children, foot }: { bar: React.ReactNode; children: React.ReactNode; foot?: React.ReactNode }) {
  return <div className="page">
    {bar}
    <div className="page-body">{children}</div>
    {foot && <div className="footbar">{foot}</div>}
  </div>
}

export const distBar = (counts: Record<string, number> | undefined, total: number) => {
  const segs: [string, number][] = [['keep', counts?.keep ?? 0], ['review', counts?.review ?? 0], ['quarantine', counts?.quarantine ?? 0], ['reject', counts?.reject ?? 0]]
  const known = segs.reduce((s, [, n]) => s + n, 0)
  if (total > known) segs.push(['pending', total - known])
  return <div className="distbar" role="img" aria-label={`distribution: ${segs.map(([k, n]) => `${t(k)} ${n}`).join(', ')}`}>
    {segs.filter(([, n]) => n > 0).map(([k, n]) => <span key={k} className={k} style={{ width: `${(n / total) * 100}%` }} />)}
  </div>
}
/** Janela deslizante de itens para o anotador: nada de dataset
 * inteiro em memória. O servidor ordena (order=pending_first) e o
 * hook mantém um cache de páginas (ANN_PAGE por página) + total do
 * X-Total-Count; `items` é um array-like que busca a página sob demanda
 * (com prefetch da vizinha) e re-renderiza quando ela chega. */
const ANN_PAGE = 200
// dedup de fetch em voo por sessão; conflito só desperdiça um request
let _inflight = new Set<number>()
export function useItemWindow(ds: string) {
  const [pages, setPages] = useState<Record<number, Item[]>>({})
  const [total, setTotal] = useState(0)

  const fetchPage = useCallback((p: number) => {
    // oxlint-disable-next-line refs — fetchPage é callback de evento; o Proxy chama fora do ciclo de render
    if (p < 0 || _inflight.has(p)) return
    _inflight.add(p)
    api.itemsPage(ds, { limit: String(ANN_PAGE), offset: String(p * ANN_PAGE), order: 'pending_first' })
      .then(({ items: page, total: t }) => {
        setTotal(t)
        setPages(prev => {
          const next = { ...prev, [p]: page }
          // eviction FIFO: mantém só as 6 páginas mais recentes; a janela
          // deslizante re-busca qualquer página evictada sob demanda.
          const rawKeys = Object.keys(next)
          const keys = rawKeys.map(Number)
          keys.sort((a, b) => a - b)
        for (const k of keys.slice(0, keys.length - 6)) delete next[k]
          return next
        })
      }).catch(console.error)
      .finally(() => { _inflight.delete(p) })
  }, [ds])
  /* oxlint-disable set-state-in-effect */
  useEffect(() => {
    setPages({}); setTotal(0); fetchPage(0)
  }, [fetchPage])
  /* oxlint-enable set-state-in-effect refs */
  const reload = useCallback(() => { setPages({}); setTotal(0); fetchPage(0) }, [fetchPage])
  const items = useMemo(() => {
    const store = { pages, total, fetchPage }
    return new Proxy([] as unknown as Item[], {
      get(_, key) {
        if (key === 'length') return total
        const i = Number(key)
        if (!Number.isInteger(i)) return undefined
        const p = Math.floor(i / ANN_PAGE)
        const page = store.pages[p]
        if (page) {
          const it = page[i - p * ANN_PAGE]
          // prefetch da vizinha enquanto o usuário navega
          if (i % ANN_PAGE > ANN_PAGE * 0.9) store.fetchPage(p + 1)
          return it
        }
        store.fetchPage(p)
        return undefined
      },
    })
  }, [pages, total, fetchPage])
  const ensure = useCallback((i: number) => {
    if (i < 0 || i >= total) return
    fetchPage(Math.floor(i / ANN_PAGE))
  }, [total, fetchPage])
  return { items, reload, ensure }
}
