// Export — publish wizard.
import { useCallback, useEffect, useState } from 'react'

import { api, type Dataset, type Issue, type Version } from './api'

import { Page, PageBar, apiErrorMessage } from './shared'
import type React from 'react'
export function ExportPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [issues, setIssues] = useState<Issue[]>([])
  const [versions, setVersions] = useState<Version[]>([])
  const [step, setStep] = useState(0)
  const [fmt, setFmt] = useState('imagefolder')
  const [versionId, setVersionId] = useState('')
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    const [nextDataset, nextIssues, nextVersions] = await Promise.all([api.dataset(ds), api.issues(ds), api.versions(ds)])
    setDataset(prev => prev?.id === nextDataset.id ? prev : nextDataset)
    setIssues(nextIssues); setVersions(nextVersions)
    setVersionId(nextDataset.current_version_id ?? nextVersions.at(-1)?.id ?? '')
  }, [ds])
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
  useEffect(() => { void load().catch(e => setError(apiErrorMessage(e))) }, [load]) // ponytail: load é async; void só agenda o fetch
  const openIssues = issues.filter(issue => issue.status === 'open').length
  const ic = dataset?.item_counts
  const included = (ic?.keep ?? 0) + (ic?.restore ?? 0)
  const excluded = (ic?.total ?? 0) - included
  const unknownLicense = dataset?.unknown_license ?? 0
  const licenseBlocked = dataset?.license_policy === 'strict' && unknownLicense > 0
  const blocked = !dataset || openIssues > 0 || licenseBlocked
  const exportData = async () => {
    setBusy(true); setError(''); setMessage('')
    try { setResult(await api.export(ds, fmt, versionId)); setMessage('package exported'); setStep(3) }
    catch (e) { setError(apiErrorMessage(e)) } finally { setBusy(false) }
  }
  const steps = ['Readiness', 'Package', 'Contents', 'Export']
  return <Page
    bar={<PageBar title="Publish" sub="prepare a trustworthy package" />}
    foot={foot}>
    {error && <div className="error" role="alert">{error}</div>}
    {message && <div className="ok" role="status">{message}</div>}
    <div className="workflow-screen publish-screen">
      <header className="workflow-heading">
        <div><span className="eyebrow">FINAL HANDOFF</span><h1>Ship only what you trust.</h1><p>Review the boundary, choose the package, then export a reproducible manifest.</p></div>
        <div className="workflow-summary"><b>{included}<small>included</small></b><b>{excluded}<small>outside package</small></b><b className={openIssues ? 'warn' : ''}>{openIssues}<small>open issues</small></b></div>
      </header>
      <div className="publish-layout">
        <nav className="publish-steps" aria-label="Publish steps">{steps.map((label, index) => <button key={label} className={step === index ? 'active' : ''} onClick={() => setStep(index)}><span>{index + 1}</span><b>{label}</b><small>{index === 0 ? 'make blockers visible' : index === 1 ? 'choose the handoff shape' : index === 2 ? 'inspect what travels' : 'confirm the handoff'}</small></button>)}</nav>
        <section className="publish-panel">
          {step === 0 && <div className="publish-step"><span className="eyebrow">STEP 1 OF 4</span><h2>Check before packaging.</h2><p>Export stays blocked until the curation boundary is honest.</p><div className="publish-cards"><section className="publish-card"><h3>Readiness checklist</h3><p>Dataset loaded <b className="good">Verified</b></p><p>Items included <b>{included}</b></p><p>Open issues <b className={openIssues ? 'bad' : 'good'}>{openIssues}</b></p><p>License gate <b className={licenseBlocked ? 'bad' : 'good'}>{licenseBlocked ? `${unknownLicense} unknown` : 'Clear'}</b></p></section><section className="publish-card"><h3>What will travel</h3><p>Kept and restored items enter the package. Review, quarantine, and rejected items stay outside.</p><p className="muted">The manifest records decisions, labels, provenance, and the selected checkpoint.</p></section></div><div className="publish-bottom"><span>{blocked ? `${openIssues || unknownLicense} blocker${(openIssues || unknownLicense) === 1 ? '' : 's'} to resolve.` : 'Ready to choose a package.'}</span><button className="primary" onClick={() => setStep(blocked ? 0 : 1)} disabled={blocked}>{blocked ? 'Resolve blockers' : 'Configure package →'}</button></div></div>}
          {step === 1 && <div className="publish-step"><span className="eyebrow">STEP 2 OF 4</span><h2>Choose the handoff shape.</h2><p>Every format keeps the same approved boundary; only the representation changes.</p><div className="publish-form"><label>Format<select value={fmt} onChange={e => setFmt(e.target.value)}><option value="imagefolder">ImageFolder</option><option value="coco">COCO</option><option value="yolo">YOLO</option><option value="parquet">Parquet</option><option value="manifest">Manifest</option></select></label><label>Checkpoint<select value={versionId} onChange={e => setVersionId(e.target.value)}><option value="">Current working state</option>{versions.map(v => <option key={v.id} value={v.id}>{v.description || v.id.slice(0, 8)}</option>)}</select></label></div><div className="publish-bottom"><span>{included} items will be included.</span><button className="primary" onClick={() => setStep(2)}>Inspect contents →</button></div></div>}
          {step === 2 && <div className="publish-step"><span className="eyebrow">STEP 3 OF 4</span><h2>See what will travel.</h2><p>Only kept or restored items are exported. Nothing is silently promoted.</p><div className="publish-cards"><section className="publish-card"><h3>Included</h3><strong className="publish-number">{included}</strong><p>kept or restored images</p></section><section className="publish-card"><h3>Outside package</h3><strong className="publish-number">{excluded}</strong><p>review, quarantine, or rejected</p></section></div><div className="publish-bottom"><span>Format: {fmt} · {versionId ? 'checkpoint selected' : 'working state'}</span><button className="primary" onClick={() => setStep(3)}>Review export →</button></div></div>}
          {step === 3 && <div className="publish-step"><span className="eyebrow">STEP 4 OF 4</span><h2>Confirm the final handoff.</h2><p>{blocked ? 'Resolve the blockers before generating a package.' : `Export ${included} items as ${fmt}.`}</p>{result ? <pre className="publish-result">{JSON.stringify(result, null, 2)}</pre> : <div className="publish-confirm"><b>{blocked ? 'Export unavailable' : 'Ready to export'}</b><span>{blocked ? `${openIssues} open issues remain in the review queue.` : 'The package includes its manifest and report.'}</span></div>}<div className="publish-bottom"><span>{result ? 'Package ready.' : blocked ? 'Resolve blockers to continue.' : 'No decisions will be changed.'}</span><button className="primary" disabled={busy || blocked} onClick={exportData}>{busy ? 'Exporting…' : result ? 'Export again' : 'Export dataset →'}</button></div></div>}
        </section>
      </div>
    </div>
  </Page>
}
