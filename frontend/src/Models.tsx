// Models — model center with install/automation.
import { useEffect, useState } from 'react'

import { api, type ModelCatalog, type ModelSpec, type ProviderSettings } from './api'

import { Page, PageBar, apiErrorMessage, useModelCatalog } from './shared'
import type { Theme } from './shared'
import type React from 'react'
const MODEL_FUNCTIONS = [
  { capability: 'embedding', title: 'Find images by meaning', tool: 'Find', usedIn: 'Semantic search', detail: 'Search the collection by visual meaning instead of filenames.' },
  { capability: 'preannotation', title: 'Suggest labels', tool: 'Annotate', usedIn: 'Label workspace', detail: 'Creates pending boxes and categories for human approval.' },
  { capability: 'pii', title: 'Detect private information', tool: 'Annotate', usedIn: 'PII scan', detail: 'Finds possible faces and other sensitive regions before redaction.' },
  { capability: 'ocr', title: 'Read text in images', tool: 'Annotate', usedIn: 'Text layers', detail: 'OCR text becomes reviewable text layers and export fields.' },
  { capability: 'detection', title: 'Detect objects', tool: 'Annotate', usedIn: 'Label workspace', detail: 'Optional object boxes for preannotation workflows.' },
  { capability: 'segmentation', title: 'Create masks', tool: 'Annotate', usedIn: 'Label workspace', detail: 'Optional masks from boxes or points.' },
  { capability: 'captioning', title: 'Generate training captions', tool: 'Gallery', usedIn: 'Caption editor and export', detail: 'Creates editable per-image captions with prompt, prefix, suffix, and template controls.' },
] as const

const RULE_FUNCTIONS = [
  { title: 'Review quality', tool: 'Review', detail: 'Blur, exposure, contrast, entropy, resolution, aspect ratio, grayscale, and screenshot checks.', model: 'No model — Pillow/OpenCV rules' },
  { title: 'Find exact duplicates', tool: 'Review', detail: 'Groups identical bytes using SHA-256.', model: 'No model — SHA-256' },
  { title: 'Find visual duplicates', tool: 'Review', detail: 'Groups near-identical images using perceptual hashes.', model: 'No model — dHash' },
  { title: 'Check label quality', tool: 'Review', detail: 'Optional statistical label checks when prediction probabilities exist.', model: 'Cleanlab optional' },
] as const

const FUNCTION_GROUPS = [
  { title: 'Discover', capabilities: ['embedding'] },
  { title: 'Understand', capabilities: ['preannotation', 'ocr', 'detection', 'segmentation', 'captioning'] },
  { title: 'Protect', capabilities: ['pii'] },
] as const

const CLOUD_PROVIDERS = [
  { id: 'openai_vision', label: 'OpenAI', keyLabel: 'OpenAI API key' },
  { id: 'replicate', label: 'Replicate', keyLabel: 'Replicate API token' },
  { id: 'falai', label: 'fal.ai', keyLabel: 'fal.ai key' },
] as const
const CLOUD_FUNCTIONS = [
  { id: 'preannotation', label: 'Pre-annotation' },
  { id: 'captioning', label: 'Captioning' },
  { id: 'pii', label: 'PII scan' },
] as const

export function ModelCenter({ foot, theme, onThemeChange, reducedMotion, onReducedMotionChange }: { foot: React.ReactNode; theme: Theme; onThemeChange: (theme: Theme) => void; reducedMotion: boolean; onReducedMotionChange: (value: boolean) => void }) {

  const { catalog, error: catalogError, reload } = useModelCatalog()
  const [tab, setTab] = useState('catalog')
  const [filter, setFilter] = useState('embedding')
  const [installTarget, setInstallTarget] = useState<ModelSpec | null>(null)
  const [source, setSource] = useState('')
  const [sha256, setSha256] = useState('')
  const [pluginPath, setPluginPath] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [licenseAck, setLicenseAck] = useState(false)
  const [auto, setAuto] = useState<Record<string, { enabled: boolean; confidence: number; preview: boolean; auto_quarantine?: boolean }>>({})
  const [providerSettings, setProviderSettings] = useState<ProviderSettings | null>(null)
  const [providerKeys, setProviderKeys] = useState<Record<string, string>>({})
  const [providerMessage, setProviderMessage] = useState('')
  const [providerError, setProviderError] = useState('')
  const models = catalog?.models ?? []
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
  useEffect(() => { if (catalog?.automation) setAuto(catalog.automation) }, [catalog])
  // Provider keys are write-only; the API returns configured/model state only.
  useEffect(() => { api.providerSettings().then(setProviderSettings).catch(error => setProviderError(String(error))) }, [])
  const saveProviderSettings = async () => {
    if (!providerSettings) return
    setProviderError(''); setProviderMessage('')
    try {
      const providers = Object.fromEntries(CLOUD_PROVIDERS.map(provider => [provider.id, {
        ...(providerKeys[provider.id] ? { api_key: providerKeys[provider.id] } : {}),
        models: Object.fromEntries(CLOUD_FUNCTIONS.map(fn => [fn.id, providerSettings.providers[provider.id]?.models?.[fn.id] ?? ''])),
      }] as const))
      const saved = await api.saveProviderSettings({ selection: providerSettings.selection, providers })
      setProviderSettings(saved)
      setProviderKeys({})
      setProviderMessage('Provider settings saved')
    } catch (error) { setProviderError(apiErrorMessage(error)) }
  }
  const setProviderSelection = (capability: string, provider: string) => setProviderSettings(current => current ? {
    ...current,
    selection: { ...current.selection, [capability]: provider },
  } : current)
  const setProviderModel = (provider: string, capability: string, model: string) => setProviderSettings(current => current ? {
    ...current,
    providers: {
      ...current.providers,
      [provider]: {
        ...current.providers[provider],
        models: { ...current.providers[provider]?.models, [capability]: model },
      },
    },
  } : current)

  const run = async (action: () => Promise<unknown>, ok: string) => {
    setError(''); setMessage('')
    try { await action(); setMessage(ok); await reload() } catch (e) { setError(apiErrorMessage(e)) }
  }
  const openInstall = (model: ModelSpec) => {
    setInstallTarget(model); setSource(''); setSha256(''); setLicenseAck(false); setError('')
  }
  const install = () => {
    if (!installTarget) return
    if (!installTarget.sources?.length && (!source.trim() || !sha256.trim())) return
    run(() => api.installModel(installTarget.id, source.trim(), sha256.trim(), licenseAck), `${installTarget.name} installation started`)
    setInstallTarget(null); setSource(''); setSha256(''); setLicenseAck(false)
  }
  const turnkeyInstall = (model: ModelSpec) => run(async () => {
    await api.installModel(model.id)
    const delay = (ms: number) => new Promise<void>(resolve => { window.setTimeout(resolve, ms) })
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const state = (await reload()) as ModelCatalog
      const modelState = state.models.find(item => item.id === model.id)
      if (modelState?.status === 'installed') return
      if (modelState?.status === 'failed') throw new Error(modelState.error || 'model installation failed')
      await delay(500)
    }
    throw new Error('model installation timed out; reopen Configuration to retry')
  }, `${model.name} installed and validated`)
  const updateAutomation = (capability: string, patch: Partial<{ enabled: boolean; confidence: number; preview: boolean; auto_quarantine: boolean }>) => {
    const current = auto[capability] ?? { enabled: false, confidence: 0.95, preview: true, auto_quarantine: false }
    const next = { ...current, ...patch, confidence: Math.max(0, Math.min(1, Number(current.confidence) || 0.95)) }
    setAuto(value => ({ ...value, [capability]: next }))
    run(() => api.setModelAutomation(capability, next.enabled, next.confidence, next.preview, Boolean(next.auto_quarantine)), `${capability} automation saved`)
  }
  const modelLine = (model: ModelSpec) => {
    const turnkey = Boolean(model.sources?.length)
    const needsLicense = !['Apache-2.0', 'MIT'].includes(model.license)
    const status = model.installed ? 'active' : model.status === 'installing' ? 'installing' : model.status === 'failed' ? 'failed' : 'not installed'
    return <article className={`model-line${model.active ? ' is-active' : ''}`} key={model.id}>
      <div className="model-line-main">
        <div><h3>{model.name}</h3><p>{model.description}</p></div>
        <div className="model-line-state"><span className={`model-status ${model.installed ? 'ready' : model.status === 'installing' ? 'busy' : model.status === 'failed' ? 'bad' : 'off'}`}>{status}</span>{model.recommended && <span className="model-recommended">recommended default</span>}</div>
      </div>
      <div className="model-line-meta"><span>{model.size_mb ? `${model.size_mb} MB` : 'cloud'}</span><span>~{model.memory_mb ?? '—'} MB RAM</span><span>{model.runtime}</span><span>{model.license}</span><span>{model.platforms.join(' · ')}</span></div>
      {model.selection_reason && <p className="model-line-reason">{model.selection_reason}</p>}
      <div className="model-line-actions">
        {model.installed
          ? <><button className={model.active ? 'primary sm' : 'sm'} onClick={() => run(() => api.activateModel(model.id, model.capability), `${model.name} is now active`)}>{model.active ? 'active' : 'use this'}</button><button className="sm" onClick={() => run(() => api.uninstallModel(model.id), `${model.name} removed`)}>remove</button></>
          : model.installable
            ? <button className="primary sm" disabled={model.status === 'installing'} onClick={() => turnkey && !needsLicense ? turnkeyInstall(model) : openInstall(model)}>{model.status === 'installing' ? 'downloading…' : turnkey ? needsLicense ? 'review & install from HF' : 'install from HF' : 'advanced install'}</button>
            : <span className="muted">not available — configure provider</span>}
        {(model.sources?.length || model.source_url) && <details className="model-provenance"><summary>source & files</summary><div>{model.sources?.map(file => file ? <a key={file.filename} href={file.url} target="_blank" rel="noreferrer">{file.filename} · SHA-256 {file.sha256.slice(0, 12)}…</a> : null) ?? <a href={model.source_url} target="_blank" rel="noreferrer">upstream source</a>}<span>revision {model.revision || 'not pinned'}</span></div></details>}
      </div>
    </article>
  }
  const capabilityPanel = (fn: typeof MODEL_FUNCTIONS[number]) => {
    const choices = models.filter(model => model.capability === fn.capability)
    const active = choices.find(model => model.active && model.installed)
    const cloudFn = CLOUD_FUNCTIONS.find(item => item.id === fn.capability)
    const selectedProvider = providerSettings?.selection[fn.capability] ?? ''
    const cloudProvider = CLOUD_PROVIDERS.find(provider => provider.id === selectedProvider)
    const cloudModel = cloudProvider ? providerSettings?.providers[cloudProvider.id]?.models?.[fn.capability] ?? '' : ''
    const usingCloud = Boolean(cloudFn && selectedProvider)
    return <section className="config-detail">
      <header className="config-detail-head">
        <div><span className="eyebrow">{fn.tool} · FUNCTION</span><h2>{fn.title}</h2><p>{fn.detail}</p></div>
        <span className="model-function-default">{usingCloud ? 'cloud-backed' : active ? 'local model' : 'not configured'}</span>
      </header>
      <div className="config-active">
        <div><span>{usingCloud ? 'ACTIVE CLOUD IMPLEMENTATION' : 'ACTIVE LOCAL IMPLEMENTATION'}</span><b>{usingCloud ? `${cloudProvider?.label ?? 'Cloud'} · ${cloudModel || 'model not configured'}` : active?.name ?? 'None selected'}</b><small className={usingCloud ? cloudModel ? 'config-running' : '' : active ? 'config-running' : ''}>{usingCloud ? cloudModel ? 'READY' : 'MODEL REQUIRED' : active ? 'RUNNING' : 'WAITING FOR MODEL'}</small></div>
        {!usingCloud && active && <div className="config-active-facts"><span><b>{active.size_mb} MB</b><small>size</small></span><span><b>{active.memory_mb ?? '—'} MB</b><small>ram</small></span><span><b>{active.runtime}</b><small>runtime</small></span><span><b>{active.license}</b><small>license</small></span></div>}
      </div>
      {cloudFn && <section className="function-source">
        <div><span className="eyebrow">EXECUTION SOURCE</span><b>Choose local or cloud for this function.</b><p>Cloud keys stay on this server and are never returned.</p></div>
        <select value={selectedProvider} onChange={event => setProviderSelection(fn.capability, event.target.value)} aria-label={`${fn.title} execution source`} disabled={!providerSettings}>
          <option value="">Local model</option>
          {CLOUD_PROVIDERS.map(provider => <option value={provider.id} key={provider.id}>{provider.label}</option>)}
        </select>
        {selectedProvider && cloudProvider && providerSettings && <div className="function-cloud-config">
          <div><b>{cloudProvider.label}</b><span className={providerSettings.providers[cloudProvider.id]?.configured ? 'settings-state' : 'muted'}>{providerSettings.providers[cloudProvider.id]?.configured ? 'key configured' : 'key required'}</span></div>
          <label className="field-label">{cloudProvider.keyLabel}<input type="password" value={providerKeys[cloudProvider.id] || ''} onChange={event => setProviderKeys({ ...providerKeys, [cloudProvider.id]: event.target.value })} placeholder={providerSettings.providers[cloudProvider.id]?.configured ? 'leave unchanged' : 'paste key'} autoComplete="off" /></label>
          <label className="field-label">{cloudFn.label} model<input value={providerSettings.providers[cloudProvider.id]?.models?.[fn.capability] ?? ''} onChange={event => setProviderModel(cloudProvider.id, fn.capability, event.target.value)} placeholder="model ID" /></label>
          <button className="primary sm" onClick={saveProviderSettings}>Save cloud settings</button>
        </div>}
        {providerError && <div className="error" role="alert">{providerError}</div>}
        {providerMessage && <div className="ok" role="status">{providerMessage}</div>}
      </section>}
      <div className="config-options"><span className="eyebrow">LOCAL MODELS</span>{!choices.length ? <p className="muted">No verified local model for this function.</p> : choices.map(modelLine)}</div>
    </section>
  }
  const activeRows = MODEL_FUNCTIONS.map(fn => ({ fn, model: models.find(model => model.capability === fn.capability && model.active && model.installed) }))
  const selectedFn = MODEL_FUNCTIONS.find(fn => fn.capability === filter)
  const selectedRule = RULE_FUNCTIONS.find(fn => `rule:${fn.title}` === filter)
  const automationEnabled = MODEL_FUNCTIONS.filter(fn => auto[fn.capability]?.enabled).length
  const automationPreview = MODEL_FUNCTIONS.filter(fn => auto[fn.capability]?.preview).length
  const automationQuarantine = MODEL_FUNCTIONS.filter(fn => auto[fn.capability]?.auto_quarantine).length
  const tabs = [
    { id: 'catalog', label: 'Functions & Models' },
    { id: 'automation', label: 'Automation' },
    { id: 'preferences', label: 'Appearance' },
    { id: 'storage', label: 'Data & Privacy' },
    { id: 'plugins', label: 'Extensions' },
  ]

  return <Page bar={<PageBar title="Settings" />} foot={foot}>
    {message && <div className="ok" role="status">{message}</div>}
    {(error || catalogError) && <div className="error" role="alert">{error || catalogError} <button className="sm" onClick={() => reload().catch(() => {})}>retry</button></div>}
    <div className="model-tabs" role="tablist" aria-label="Configuration sections">
      {tabs.map((item, index) => <button key={item.id} role="tab" aria-selected={tab === item.id} aria-controls={`model-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)} onKeyDown={e => { if (e.key === 'ArrowRight') setTab(tabs[(index + 1) % tabs.length].id); if (e.key === 'ArrowLeft') setTab(tabs[(index + tabs.length - 1) % tabs.length].id) }}>{item.label}</button>)}
    </div>
    <div id={`model-panel-${tab}`} role="tabpanel" tabIndex={0} className="model-tabpanel">
      {tab === 'preferences' && <div className="settings-screen">
        <header className="settings-head"><div><span className="eyebrow">APPEARANCE</span><h2>Make the workspace yours.</h2><p>Simple preferences that apply across every screen.</p></div></header>
        <section className="settings-list">
          <div className="settings-row"><div><b>Theme</b><p>Choose the surface that is easiest to read.</p></div><div className="seg settings-choice" role="group" aria-label="Theme"><button className={theme === 'light' ? 'on' : ''} aria-pressed={theme === 'light'} onClick={() => onThemeChange('light')}>Light</button><button className={theme === 'dark' ? 'on' : ''} aria-pressed={theme === 'dark'} onClick={() => onThemeChange('dark')}>Dark</button></div></div>
          <div className="settings-row"><div><b>Reduce motion</b><p>Remove transitions and animations from the interface.</p></div><label className="settings-toggle"><input type="checkbox" checked={reducedMotion} onChange={e => onReducedMotionChange(e.target.checked)} /> <span>{reducedMotion ? 'On' : 'Off'}</span></label></div>
          <div className="settings-row"><div><b>Language</b><p>The interface is currently available in English.</p></div><select value="English" disabled aria-label="Interface language"><option>English</option></select></div>
        </section>
      </div>}
      {tab === 'storage' && <div className="settings-screen">
        <header className="settings-head"><div><span className="eyebrow">DATA & PRIVACY</span><h2>Your files stay yours.</h2><p>These safeguards describe how this local workspace handles data.</p></div></header>
        <section className="settings-list">
          <div className="settings-row"><div><b>Original files</b><p>Source files are never overwritten by curation or redaction.</p></div><span className="settings-state">Protected</span></div>
          <div className="settings-row"><div><b>Processing</b><p>Installed local models and plugins can run without network access.</p></div><span className="settings-state">Local first</span></div>
          <div className="settings-row"><div><b>Cloud providers</b><p>Cloud processing is opt-in and never used as a silent fallback.</p></div><span className="settings-state">Opt-in only</span></div>
        </section>
      </div>}
      {!catalog && !catalogError && <p className="muted">Loading model catalog…</p>}
      {catalog && tab === 'catalog' && <div className="config-layout">
        <nav className="config-functions" aria-label="Functions">
          {FUNCTION_GROUPS.map(group => <div className="config-function-group" key={group.title}><span className="config-list-label">{group.title}</span>{group.capabilities.map(capability => {
            const fn = MODEL_FUNCTIONS.find(item => item.capability === capability)!
            const active = models.find(model => model.capability === fn.capability && model.active && model.installed)
            return <button key={fn.capability} className={filter === fn.capability ? 'active' : ''} onClick={() => setFilter(fn.capability)}><b>{fn.title}</b><small>{fn.tool} · {active?.name ?? 'no model selected'}</small></button>
          })}</div>)}
          <div className="config-function-group"><span className="config-list-label">Built-in · no download</span>{RULE_FUNCTIONS.map(fn => <button key={fn.title} className={filter === `rule:${fn.title}` ? 'active' : ''} onClick={() => setFilter(`rule:${fn.title}`)}><b>{fn.title}</b><small>{fn.model}</small></button>)}</div>
        </nav>
        <div className="config-detail-wrap">
          {selectedFn && capabilityPanel(selectedFn)}
          {selectedRule && <section className="config-detail">
            <header className="config-detail-head"><div><span className="eyebrow">{selectedRule.tool} · BUILT IN</span><h2>{selectedRule.title}</h2><p>{selectedRule.detail}</p></div><span className="model-function-default">no download</span></header>
            <div className="config-active"><span>IMPLEMENTATION</span><b>{selectedRule.model}</b><small>Available immediately. Nothing to install.</small></div>
          </section>}
        </div>
      </div>}
      {catalog && tab === 'automation' && <div className="automation-screen">
        <header className="automation-head"><div><span className="eyebrow">AUTOMATION</span><h2>Let models suggest. You decide.</h2><p>Actions stay previewed until you turn them on.</p></div><div className="automation-summary"><b>{automationEnabled}<small>enabled</small></b><b>{automationPreview}<small>preview first</small></b><b>{automationQuarantine}<small>auto-quarantine</small></b></div></header>
        <div className="automation-list">{MODEL_FUNCTIONS.map(fn => { const model = activeRows.find(row => row.fn.capability === fn.capability)?.model; const config = auto[fn.capability] ?? { enabled: false, confidence: 0.95, preview: true, auto_quarantine: false }; return <section className={`automation-row${model ? '' : ' is-unavailable'}`} key={fn.capability}><div className="automation-row-main"><span className="eyebrow">{fn.tool} · {fn.capability}</span><h3>{fn.title}</h3><p>{model ? model.name : 'Install and activate a model in Functions first.'}</p></div>{model ? <div className="automation-controls"><label className="automation-switch"><input type="checkbox" checked={config.enabled} onChange={e => updateAutomation(fn.capability, { enabled: e.target.checked })} /><span>enabled</span></label><label>threshold <input aria-label={`${fn.title} confidence threshold`} type="number" min="0" max="1" step="0.01" value={config.confidence} onChange={e => setAuto(value => ({ ...value, [fn.capability]: { ...config, confidence: Number(e.target.value) } }))} onBlur={() => updateAutomation(fn.capability, {})} /></label><label><input type="checkbox" checked={config.preview} onChange={e => updateAutomation(fn.capability, { preview: e.target.checked })} /> preview</label><label><input type="checkbox" checked={Boolean(config.auto_quarantine)} onChange={e => updateAutomation(fn.capability, { auto_quarantine: e.target.checked })} /> quarantine</label></div> : <span className="automation-unavailable">not configured · choose a model in Functions</span>}</section>})}</div>
      </div>}
      {catalog && tab === 'plugins' && <div className="extensions-screen">
        <header className="extensions-head"><div><span className="eyebrow">EXTENSIONS</span><h2>Add capabilities</h2><p>Install a self-contained plugin only when the built-in functions are not enough.</p></div><span className="model-function-default">{catalog.plugins.length} installed</span></header>
        <section className="extension-install"><div><b>Install plugin</b><span>Use a local .pluginpack file. Its manifest declares capabilities and permissions.</span></div><div className="row"><input value={pluginPath} onChange={e => setPluginPath(e.target.value)} placeholder="/path/to/plugin.pluginpack" /><button disabled={!pluginPath.trim()} onClick={() => run(() => api.installPlugin(pluginPath.trim()), 'plugin installed')}>install</button></div></section>
        <section className="model-plugins"><div><span className="eyebrow">INSTALLED</span><h3>Capability providers</h3></div>{catalog.plugins.length ? catalog.plugins.map(plugin => <div className="plugin-row" key={plugin.id}><div><b>{plugin.name ?? plugin.id}</b><span className="muted">{plugin.version ?? 'version unknown'} · {plugin.protocol ?? 'protocol unknown'}</span></div><div className="plugin-chips">{(plugin.capabilities ?? []).map(value => <span key={value}>{value}</span>)}{(plugin.permissions ?? []).map(value => <span key={value}>permission: {value}</span>)}</div><button className="sm" onClick={() => run(() => api.uninstallPlugin(plugin.id), `${plugin.name ?? plugin.id} removed`)}>remove</button></div>) : <p className="muted">No extensions installed.</p>}</section>
      </div>}
    </div>
    {installTarget && <div className="model-install" role="dialog" aria-label={`Install ${installTarget.name}`}><div><span className="eyebrow">INSTALL MODEL</span><h3>{installTarget.name}</h3><p>{installTarget.install_hint || 'The catalog provides pinned files and checksums. Advanced sources require a URL/path and SHA-256.'}</p></div>{installTarget.sources?.length ? <div className="model-artifacts">{installTarget.sources.map(file => <span key={file.filename}>{file.filename} · {file.sha256.slice(0, 12)}…</span>)}</div> : <><label className="field-label">Source URL or local path<input value={source} onChange={e => setSource(e.target.value)} placeholder="https://… or /path/model.onnx" autoFocus /></label><label className="field-label">SHA-256<input value={sha256} onChange={e => setSha256(e.target.value)} placeholder="64 hexadecimal characters" /></label></>}{!['Apache-2.0', 'MIT'].includes(installTarget.license) && <label className="field-label"><input type="checkbox" checked={licenseAck} onChange={e => setLicenseAck(e.target.checked)} /> I accept the {installTarget.license} license terms</label>}<div className="row"><button className="primary" disabled={(!source.trim() || !sha256.trim()) && !installTarget.sources?.length || (!['Apache-2.0', 'MIT'].includes(installTarget.license) && !licenseAck)} onClick={install}>install and validate</button><button onClick={() => setInstallTarget(null)}>cancel</button></div></div>}
  </Page>
}

// ---------- Versions page: ledger rows ----------
