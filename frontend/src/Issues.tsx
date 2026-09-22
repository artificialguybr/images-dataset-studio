// Issues — quality ledger + detector calibration + duplicate review.
import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, type DupGroup, type Issue, type Item } from './api'

import { I, ISSUE_LABELS, PageBar, Page, openShot, t, useLightbox } from './shared'
import type React from 'react'
export function IssuesPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [duplicateGroups, setDuplicateGroups] = useState<DupGroup[]>([])
  const [reviewMode, setReviewMode] = useState<'issues' | 'duplicates'>('issues')
  const [duplicateView, setDuplicateView] = useState<'list' | 'fast'>('list')
  const [duplicatePage, setDuplicatePage] = useState(0)
  const [fastIndex, setFastIndex] = useState(0)
  const [fastDetails, setFastDetails] = useState<'left' | 'right' | null>(null)
  const [calib, setCalib] = useState('')
  const [thresholds, setThresholds] = useState<Record<string, number>>({})
  const load = useCallback(() => {
    api.issues(ds).then(setIssues)
    api.dataset(ds).then(d => setThresholds(d.thresholds_json ?? {})).catch(console.error)
  }, [ds])
  useEffect(() => { load() }, [load])
  const loadDuplicates = useCallback(() => {
    api.duplicates(ds).then(setDuplicateGroups).catch(console.error)
  }, [ds])
  useEffect(() => { loadDuplicates() }, [loadDuplicates])
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
    setDuplicatePage(0)
    setFastIndex(0)
    setFastDetails(null)
  }, [ds, reviewMode, duplicateView])
  const openIssues = issues.filter(i => i.status === 'open')
  // item fields now come inline on issues and duplicate members — no 1000-item fetch
  const itemById = useMemo(() => new Map<string, Item>([
    ...issues.map(i => [i.image_id, i as unknown as Item] as [string, Item]),
    ...duplicateGroups.flatMap(g => g.members.map(m => [m.image_id, m as unknown as Item] as [string, Item])),
  ]), [issues, duplicateGroups])
  useLightbox([
    ...openIssues.map(i => ({ id: i.image_id, name: i.issue_type })),
    ...duplicateGroups.flatMap(g => g.members.map(m => ({ id: m.image_id, name: m.is_canonical ? 'canonical' : 'duplicate' }))),
  ], [openIssues, duplicateGroups])
  const byType = useMemo(() => {
    const m = new Map<string, Issue[]>()
    for (const i of openIssues) m.set(i.issue_type, [...(m.get(i.issue_type) ?? []), i])
    for (const v of m.values()) v.sort((a, b) => b.score - a.score)
    return m
  }, [openIssues])
  const repeatedItems = duplicateGroups.reduce((total, group) => total + group.members.length, 0)
  const canonicalItems = duplicateGroups.reduce((total, group) => total + group.members.filter(member => member.is_canonical).length, 0)
  const duplicatePageSize = 3
  const duplicatePageCount = Math.max(1, Math.ceil(duplicateGroups.length / duplicatePageSize))
  const visibleDuplicateGroups = duplicateGroups.slice(duplicatePage * duplicatePageSize, (duplicatePage + 1) * duplicatePageSize)
  const fastPairs = useMemo(() => duplicateGroups.flatMap(({ group, members }) => {
    const left = members.find(member => member.is_canonical) ?? members[0]
    if (!left) return []
    return members.filter(member => member.image_id !== left.image_id).map(right => ({ groupId: group.id, left, right }))
  }), [duplicateGroups])
  const fastPair = fastPairs[fastIndex]
  const THRESHOLD_KEYS: Record<string, string> = {
    blur: 'blur_threshold', underexposed: 'dark_threshold', overexposed: 'bright_threshold',
    low_contrast: 'low_contrast_threshold', low_information: 'low_information_threshold',
    small_resolution: 'min_resolution', odd_aspect_ratio: 'aspect_limit',
  }
  const saveThreshold = (key: string, value: number) => {
    const next = { ...thresholds, [key]: value }
    setThresholds(next)
    fetch(`/api/datasets/${ds}`, { method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ thresholds_json: next }) }).then(load)
  }
  const quarantine = (imageId: string, reason: string) => api.setDecision(imageId, 'quarantine', reason).then(load)
  const quarantineDuplicates = (members: DupGroup['members']) => {
    const duplicates = members.filter(member => !member.is_canonical)
    return Promise.all(duplicates.map(member => api.setDecision(member.image_id, 'quarantine', 'duplicate')))
      .then(() => { load(); loadDuplicates() })
  }
  const chooseFast = useCallback((choice: 1 | 2) => {
    if (!fastPair) return
    const keep = choice === 1 ? fastPair.left : fastPair.right
    const discard = choice === 1 ? fastPair.right : fastPair.left
    Promise.all([
      api.setDecision(keep.image_id, 'keep', 'duplicate fast mode'),
      api.setDecision(discard.image_id, 'quarantine', 'duplicate fast mode'),
    ]).then(async () => {
      if (!keep.is_canonical) await api.swapCanonical(fastPair.groupId, keep.image_id)
      load()
      await loadDuplicates()
      setFastDetails(null)
      setFastIndex(index => Math.min(index, Math.max(0, fastPairs.length - 2)))
    }).catch(console.error)
  }, [fastPair, fastPairs.length, load, loadDuplicates])
  useEffect(() => {
    if (reviewMode !== 'duplicates' || duplicateView !== 'fast') return
    const onKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return
      if (e.key === '1') chooseFast(1)
      else if (e.key === '2') chooseFast(2)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [reviewMode, duplicateView, fastPair, chooseFast])
  const fastCard = (member: DupGroup['members'][number], number: 1 | 2, side: 'left' | 'right') => {
    const image = itemById.get(member.image_id)
    const details = fastDetails === side
    return <article className="fast-card">
      <div className="fast-card-head"><span>IMAGE {number}</span><b>{member.is_canonical ? 'current canonical' : 'duplicate candidate'}</b></div>
      <div className="fast-card-tabs" role="tablist" aria-label={`Image ${number} view`}>
        <button role="tab" aria-selected={!details} className={!details ? 'active' : ''} onClick={() => setFastDetails(null)}>image</button>
        <button role="tab" aria-selected={details} className={details ? 'active' : ''} onClick={() => setFastDetails(side)}>details</button>
      </div>
      {details
        ? <dl className="fast-details">
            <dt>filename</dt><dd>{image?.original_filename ?? 'unavailable'}</dd>
            <dt>location</dt><dd>{image?.relative_path || 'root'}</dd>
            <dt>dimensions</dt><dd>{image ? `${image.width}×${image.height}` : '—'}</dd>
            <dt>size</dt><dd>{image ? `${(image.byte_size / 1024).toFixed(0)} kB` : '—'}</dd>
            <dt>format</dt><dd>{image?.mime_type ?? '—'}</dd>
            <dt>similarity</dt><dd>{(member.similarity * 100).toFixed(0)}%</dd>
          </dl>
        : <button className="fast-image" aria-label={`Keep image ${number}`} onClick={() => chooseFast(number)}>
            {image ? <img loading="lazy" src={api.fileUrl(image.id, 1280)} alt={image.original_filename} /> : <span>image unavailable</span>}
          </button>}
      <button className="primary fast-keep" onClick={() => chooseFast(number)}>keep image {number} <kbd>{number}</kbd></button>
    </article>
  }
  const markReviewed = (issueId: string) => api.ackIssue(issueId, 'acknowledged').then(load)
  return <Page
    bar={<PageBar title="Review" sub={reviewMode === 'duplicates'
      ? `${duplicateGroups.length} duplicate ${duplicateGroups.length === 1 ? 'group' : 'groups'} · compare before deciding`
      : `${openIssues.length} open ${openIssues.length === 1 ? 'alert' : 'alerts'} · review the examples, then decide`}>
      {reviewMode === 'issues' && <span className="review-page-count"><strong>{String(openIssues.length).padStart(2, '0')}</strong><span>of {String(openIssues.length).padStart(2, '0')} open</span></span>}
    </PageBar>}
    foot={foot}>
    <div className="review-switch" role="tablist" aria-label="Review type">
      <button role="tab" aria-selected={reviewMode === 'issues'} className={reviewMode === 'issues' ? 'active' : ''} onClick={() => setReviewMode('issues')}>quality issues <b>{openIssues.length}</b></button>
      <button role="tab" aria-selected={reviewMode === 'duplicates'} className={reviewMode === 'duplicates' ? 'active' : ''} onClick={() => setReviewMode('duplicates')}>duplicates <b>{duplicateGroups.length}</b></button>
    </div>
    {reviewMode === 'issues' && <>
      {openIssues.length === 0 && <div className="empty"><b>No quality alerts</b>run the “Quality” job on the Home page to analyze the dataset</div>}
      {calib && byType.get(calib) && <div className="review-examples-panel card">
        <div className="review-examples-head">
          <div><h3>Review examples — {ISSUE_LABELS[calib] ?? calib}</h3><p>Inspect each image, then choose the outcome. The original stays safe until you decide.</p></div>
          <button className="go" onClick={() => setCalib('')}>close examples</button>
        </div>
        {THRESHOLD_KEYS[calib] && <div className="review-sensitivity">
          <span>detector sensitivity</span>
          <input type="range" style={{ flex: 1, minWidth: 160 }} min={0}
                 max={THRESHOLD_KEYS[calib] === 'blur_threshold' ? 2000 : THRESHOLD_KEYS[calib] === 'aspect_limit' ? 10 : 500}
                 step={THRESHOLD_KEYS[calib] === 'aspect_limit' || THRESHOLD_KEYS[calib] === 'min_resolution' ? 1 : 5}
                 value={thresholds[THRESHOLD_KEYS[calib]] ?? 0}
                 onChange={e => saveThreshold(THRESHOLD_KEYS[calib], Number(e.target.value))} />
          <b className="mono">{thresholds[THRESHOLD_KEYS[calib]] ?? '—'}</b>
          <span className="muted">rerun Quality to update the queue</span>
        </div>}
        <div className="review-example-list">
          {byType.get(calib)!.slice(0, 12).map((issue, index) => {
            const image = itemById.get(issue.image_id)
            return <div key={issue.id} className="review-example-row">
              <button className="review-example-thumb" aria-label={`View ${image?.original_filename ?? 'image'} large`} onClick={() => openShot!({ id: issue.image_id, name: image?.original_filename ?? 'image', caption: `score ${issue.score.toFixed(2)}` })}>
                {image?.ingest_status === 'error' ? <span>×</span> : <img src={api.thumbnailUrl(issue.image_id)} alt="" />}
              </button>
              <span className="review-example-index">{String(index + 1).padStart(2, '0')}</span>
              <span className="review-example-copy"><b>{image?.original_filename ?? issue.image_id.slice(0, 8)}</b><span>{image?.relative_path || 'root'} · {image ? `${image.width}×${image.height} · ${(image.byte_size / 1024).toFixed(0)} kB` : 'file details unavailable'}</span><span className="mono">{issue.detector_name} · score {issue.score.toFixed(2)} · threshold {issue.threshold.toFixed(2)}</span></span>
              <span className="review-example-status">{t(issue.status)}</span>
              <div className="review-example-actions">
                <button className="sm review-quarantine" onClick={() => quarantine(issue.image_id, issue.issue_type)}>quarantine</button>
                <button className="sm" onClick={() => markReviewed(issue.id)}>mark reviewed</button>
              </div>
            </div>
          })}
        </div>
      </div>}
      <div className="review-alerts">
        {[...byType.entries()].map(([k, list], groupIndex) => {
          const worst = list[0]
          const worstItem = itemById.get(worst.image_id)
          return <div key={k} className="review-alert-row">
            <span className="review-alert-number">{String(groupIndex + 1).padStart(2, '0')}</span>
            <span className="review-alert-icon">{I.warn}</span>
            <button className="review-alert-preview" aria-label={`View ${worstItem?.original_filename ?? 'issue image'} large`} onClick={() => openShot!({ id: worst.image_id, name: worstItem?.original_filename ?? k, caption: `score ${worst.score.toFixed(2)}` })}>
              {worstItem?.ingest_status === 'error' ? <span>×</span> : <img src={api.thumbnailUrl(worst.image_id)} alt="" />}
            </button>
            <span className="review-alert-copy"><b>{ISSUE_LABELS[k] ?? k}</b><span>{worstItem?.original_filename ?? worst.image_id.slice(0, 8)} · {worst.detector_name}</span></span>
            <span className="review-alert-count"><b>{list.length}</b><span>open</span></span>
            <button className="go review-alert-action" onClick={() => quarantine(worst.image_id, k)}>quarantine worst</button>
            <button className="go review-alert-action" onClick={() => setCalib(calib === k ? '' : k)}>{calib === k ? 'hide examples' : 'review examples'}</button>
          </div>
        })}
      </div>
    </>}
    {reviewMode === 'duplicates' && <>
      <div className="dup-overview" aria-label="Duplicates overview">
        <span><b>{duplicateGroups.length}</b> groups detected</span>
        <span><b>{repeatedItems}</b> images involved</span>
        <span><b>{canonicalItems}</b> canonicals set</span>
      </div>
      <div className="duplicate-mode-switch" role="tablist" aria-label="Duplicate review mode">
        <button role="tab" aria-selected={duplicateView === 'list'} className={duplicateView === 'list' ? 'active' : ''} onClick={() => setDuplicateView('list')}>all groups</button>
        <button role="tab" aria-selected={duplicateView === 'fast'} className={duplicateView === 'fast' ? 'active' : ''} onClick={() => setDuplicateView('fast')}>fast mode</button>
      </div>
      {duplicateView === 'fast'
        ? <div className="fast-review">
            {fastPair
              ? <>
                  <div className="fast-review-head">
                    <div><span className="eyebrow">FAST MODE</span><h3>Which image should stay?</h3><p>Choose one. The other is quarantined. Press <kbd>1</kbd> or <kbd>2</kbd>.</p></div>
                    <span className="fast-progress">{fastIndex + 1} of {fastPairs.length}</span>
                  </div>
                  <div className="fast-compare">
                    {fastCard(fastPair.left, 1, 'left')}
                    <span className="fast-vs">VS</span>
                    {fastCard(fastPair.right, 2, 'right')}
                  </div>
                  <div className="dup-pagination">
                    <button className="sm" disabled={fastIndex === 0} onClick={() => { setFastIndex(index => Math.max(0, index - 1)); setFastDetails(null) }}>previous</button>
                    <span>comparison {fastIndex + 1} / {fastPairs.length}</span>
                    <button className="sm" disabled={fastIndex >= fastPairs.length - 1} onClick={() => { setFastIndex(index => Math.min(fastPairs.length - 1, index + 1)); setFastDetails(null) }}>next</button>
                  </div>
                </>
              : <div className="empty"><b>No duplicate comparisons</b>all duplicate groups are resolved</div>}
          </div>
        : <>
            {duplicateGroups.length === 0 && <div className="empty"><b>No duplicates detected</b>run “exact dedup” or “phash dedup” from Explore</div>}
            <div className="duplicates-review-list">
              {visibleDuplicateGroups.map(({ group, members }, groupIndex) => <div key={group.id} className="dupG">
                <div className="dh">
                  <span className="dup-number">{String(duplicatePage * duplicatePageSize + groupIndex + 1).padStart(2, '0')}</span>
                  <b>{group.method === 'sha256' ? 'Exact matches' : 'Visual matches'}</b>
                  <span className="sim">{members.length} images</span>
                  <span className="spacer" style={{ flex: 1 }} />
                  {members.some(member => !member.is_canonical) && <button className="sm primary" onClick={() => quarantineDuplicates(members)}>quarantine duplicates ({members.filter(member => !member.is_canonical).length})</button>}
                </div>
                <div className="row">
                  {members.map(m => <span key={m.image_id} className={`duptable${m.is_canonical ? ' canon' : ''}`} title={m.is_canonical ? 'canonical' : `similarity ${(m.similarity * 100).toFixed(0)}%`}
                    onClick={() => openShot!({ id: m.image_id, name: m.is_canonical ? 'canonical' : 'duplicate', caption: `similarity ${(m.similarity * 100).toFixed(0)}%` })}>
                    <img loading="lazy" src={api.thumbnailUrl(m.image_id)} alt="" />
                    <span className="cap">{m.is_canonical ? '★ canonical' : `sim ${(m.similarity * 100).toFixed(0)}%`}</span>
                  </span>)}
                </div>
                <p className="dup-recommendation">Keep one canonical image and quarantine {members.filter(m => !m.is_canonical).length} duplicate{members.filter(m => !m.is_canonical).length === 1 ? '' : 's'}.</p>
              </div>)}
            </div>
            {duplicateGroups.length > duplicatePageSize && <div className="dup-pagination">
              <button className="sm" disabled={duplicatePage === 0} onClick={() => setDuplicatePage(page => Math.max(0, page - 1))}>previous</button>
              <span>groups {duplicatePage * duplicatePageSize + 1}–{Math.min((duplicatePage + 1) * duplicatePageSize, duplicateGroups.length)} of {duplicateGroups.length}</span>
              <button className="sm" disabled={duplicatePage >= duplicatePageCount - 1} onClick={() => setDuplicatePage(page => Math.min(duplicatePageCount - 1, page + 1))}>next</button>
            </div>}
          </>}
    </>}
  </Page>
}


// ---------- Duplicates page ----------
