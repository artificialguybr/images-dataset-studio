// Versions — checkpoint ledger + diff + restore.
import { useCallback, useEffect, useState } from 'react'

import { api, type Dataset, type Issue, type Version } from './api'

import { Page, PageBar, apiErrorMessage } from './shared'
import type React from 'react'
export function VersionsPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [versions, setVersions] = useState<Version[]>([])
  const [dsInfo, setDsInfo] = useState<Dataset | null>(null)
  const [issues, setIssues] = useState<Issue[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [oldV, setOldV] = useState('')
  const [newV, setNewV] = useState('')
  const [diff, setDiff] = useState<{ added: string[]; removed: string[] } | null>(null)
  const [confirmRestore, setConfirmRestore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const load = useCallback(async () => {
    const [nextVersions, nextDs, nextIssues] = await Promise.all([api.versions(ds), api.dataset(ds), api.issues(ds)])
    setVersions(nextVersions)
    setDsInfo(nextDs); setIssues(nextIssues)
    setSelectedId(current => current || nextVersions.at(-1)?.id || '')
  }, [ds])
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
  useEffect(() => { void load().catch(e => setError(apiErrorMessage(e))) }, [load]) // ponytail: load é async; void só agenda o fetch
  const selected = versions.find(v => v.id === selectedId)
  const visibleVersions = versions.slice(-3)
  const firstVisible = versions.length - visibleVersions.length
  const counts = dsInfo?.item_counts ?? {}
  const create = async () => {
    setBusy(true); setError(''); setMessage('')
    try { const v = await api.createVersion(ds, `checkpoint ${new Date().toLocaleString()}`); await load(); setSelectedId(v.id); setMessage('checkpoint saved') }
    catch (e) { setError(apiErrorMessage(e)) } finally { setBusy(false) }
  }
  const compare = async () => {
    if (!oldV || !newV) return
    setBusy(true); setError('')
    try { setDiff(await api.versionDiff(ds, oldV, newV)) } catch (e) { setError(apiErrorMessage(e)) } finally { setBusy(false) }
  }
  const restore = async () => {
    if (!selected || !confirmRestore) return
    setBusy(true); setError('')
    try { await api.restoreVersion(ds, selected.id); setMessage(`restored ${selected.description || selected.id.slice(0, 8)}`); setConfirmRestore(false); await load() }
    catch (e) { setError(apiErrorMessage(e)) } finally { setBusy(false) }
  }
  return <Page
    bar={<PageBar title="History"><button className="primary sm" disabled={busy} onClick={create}>save checkpoint</button></PageBar>}
    foot={foot}>
    {error && <div className="error" role="alert">{error}</div>}
    {message && <div className="ok" role="status">{message}</div>}
    <div className="workflow-screen history-screen">
      <div className="history-summarybar">
        <span className="history-current-label">CURRENT WORKING STATE</span>
        <span>{dsInfo?.item_counts?.total ?? 0} items · {counts.keep ?? 0} kept · {issues.filter(i => i.status === 'open').length} open issues</span>
        <span className="history-summary-count">{versions.length} checkpoint{versions.length === 1 ? '' : 's'}</span>
      </div>
      {versions.length === 0
        ? <div className="empty"><b>No checkpoints yet</b>Save the current curation state before making a larger change.</div>
        : <div className="history-layout">
          <section className="history-map" aria-label="Curation checkpoints">
            <div className="history-map-head"><span>CHECKPOINTS</span><span className="history-head-status">CURRENT · {selected?.description || 'working state'}</span></div>
            <div className="history-track">
              {visibleVersions.map((version, index) => <button key={version.id} className={`history-checkpoint${version.id === selectedId ? ' selected' : ''}`} onClick={() => { setSelectedId(version.id); setDiff(null) }}>
                <span className="history-node">v{firstVisible + index + 1}</span><span className="history-checkpoint-body"><b>{version.description || 'Unnamed checkpoint'}</b><small>{version.item_count} items · {new Date(version.created_at).toLocaleDateString()}</small><code>{version.checksum.slice(0, 12)}…</code></span>
              </button>)}
              <div className="history-working-node"><span className="history-node">now</span><span><b>Working state</b><small>{dsInfo?.item_counts?.total ?? 0} items · {counts.keep ?? 0} kept · {counts.quarantine ?? 0} quarantined</small></span></div>
            </div>
            {diff && <div className="history-diff"><b>{oldV.slice(0, 8)} → {newV.slice(0, 8)}</b><span>{diff.added.length} added · {diff.removed.length} removed</span></div>}
          </section>
          <aside className="history-inspector">
            <span className="eyebrow">SELECTED CHECKPOINT</span>
            {selected ? <><h2>{selected.description || 'Unnamed checkpoint'}</h2><p>{selected.item_count} items captured on {new Date(selected.created_at).toLocaleDateString()}.</p><div className="history-facts"><span><b>{selected.item_count}</b><small>items</small></span><span><b>{selected.checksum.slice(0, 8)}</b><small>checksum</small></span><span><b>{selected.parent_version_id ? 'child' : 'root'}</b><small>lineage</small></span></div><div className="history-compare"><span className="eyebrow">COMPARE</span><div><select aria-label="Older checkpoint" value={oldV} onChange={e => setOldV(e.target.value)}><option value="">from…</option>{versions.map(v => <option key={v.id} value={v.id}>{v.description || v.id.slice(0, 8)}</option>)}</select><select aria-label="Newer checkpoint" value={newV} onChange={e => setNewV(e.target.value)}><option value="">to…</option>{versions.map(v => <option key={v.id} value={v.id}>{v.description || v.id.slice(0, 8)}</option>)}</select><button className="sm" disabled={busy || !oldV || !newV} onClick={compare}>compare</button></div></div><label className="history-confirm"><input type="checkbox" checked={confirmRestore} onChange={e => setConfirmRestore(e.target.checked)} /> I understand restore changes current decisions.</label><div className="history-actions"><button className="primary" disabled={busy || !confirmRestore} onClick={restore}>restore checkpoint</button></div></> : <p className="muted">Select a checkpoint to inspect it.</p>}
          </aside>
        </div>}
    </div>
  </Page>
}
