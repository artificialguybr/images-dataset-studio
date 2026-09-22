// API client — all calls go through here; the frontend never touches the filesystem.
const j = async (url: string, opts?: RequestInit) => {
  const r = await fetch(url, { headers: { 'content-type': 'application/json' }, ...opts })
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`)
  return r.json()
}

export interface Dataset { id: string; name: string; description: string; license: string; license_policy?: string; current_version_id: string | null; thresholds_json: Record<string, number>; item_counts?: Record<string, number>; open_issues?: number; running_jobs?: string[]; unknown_license?: number }
export interface Item { id: string; dataset_id: string; original_filename: string; relative_path: string; decision_status: string; ingest_status: string; width: number; height: number; byte_size: number; mime_type: string; tags_json: string[]; license: string; exif_json: Record<string, string>; created_at?: string; channels?: number; mode?: string }
export interface Issue { id: string; image_id: string; issue_type: string; score: number; threshold: number; detector_name: string; detector_version: string; status: string }
export interface Label { id: string; image_id: string; label_type: string; category: string; geometry_json: Record<string, number>; value_json?: Record<string, unknown>; source_type: string; status: string; confidence: number | null }
export interface Caption { id: string; image_id: string; text: string; prompt: string; prefix: string; suffix: string; template: string; source_type: string; source_id: string; confidence: number | null; status: string }
export interface Version { id: string; dataset_id: string; parent_version_id: string | null; item_count: number; checksum: string; description: string; created_at: string }
export interface Job { id: string; type: string; status: string; progress: number; total: number; processed: number; failed: number; error_summary: string }
export interface ProviderInfo { scope: string; name: string; version: string; active: boolean; available: boolean; setup: string }
export interface ProviderSettings { selection: Record<string, string>; providers: Record<string, { configured: boolean; model: string; models?: Record<string, string> }> }
export interface ModelSpec { id: string; name: string; capability: string; plugin_id: string; description: string; license: string; size_mb: number; source_url: string; revision: string; runtime: string; platforms: string[]; installable: boolean; memory_mb?: number; status: string; installed: boolean; active: boolean; installed_path?: string; sha256?: string; error?: string; sources?: { url: string; filename: string; sha256: string }[]; install_hint?: string; recommended?: boolean; quality_tier?: string; selection_reason?: string }
export interface PluginInfo { id: string; name?: string; version?: string; protocol?: string; capabilities?: string[]; permissions?: string[]; installed: boolean; path?: string }
export interface ModelCatalog { models: ModelSpec[]; plugins: PluginInfo[]; automation?: Record<string, { enabled: boolean; confidence: number; preview: boolean; auto_quarantine?: boolean }> }
export interface DupGroup { group: { id: string; method: string; threshold: number }; members: { image_id: string; similarity: number; is_canonical: boolean }[] }

export const api = {
  datasets: () => j('/api/datasets'),
  dataset: (id: string) => j(`/api/datasets/${id}`),
  createDataset: (name: string, description: string, folder?: string) =>
    j('/api/datasets', { method: 'POST', body: JSON.stringify({ name, description, ...(folder ? { folder } : {}) }) }),
  startImport: (ds: string, paths: string[], zips: string[]) =>
    j(`/api/datasets/${ds}/imports`, { method: 'POST', body: JSON.stringify({ paths, zips }) }),
  startJob: (ds: string, type: string, body: Record<string, unknown> = {}) =>
    j(`/api/datasets/${ds}/jobs/${type}`, { method: 'POST', body: JSON.stringify(body) }),
  job: (id: string) => j(`/api/jobs/${id}`),
  items: async (ds: string, params: Record<string, string>) => {
    const qs = new URLSearchParams(params).toString()
    const r = await fetch(`/api/datasets/${ds}/items?${qs}`)
    if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`)
    return (await r.json()) as Item[]
  },
  itemsPage: async (ds: string, params: Record<string, string>) => {
    const qs = new URLSearchParams(params).toString()
    const r = await fetch(`/api/datasets/${ds}/items?${qs}`)
    if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`)
    return { items: (await r.json()) as Item[], total: Number(r.headers.get('X-Total-Count') ?? 0) }
  },
  caption: (id: string) => j(`/api/items/${id}/caption`),
  updateCaption: (id: string, text: string, status = 'approved') =>
    j(`/api/items/${id}/caption`, { method: 'PATCH', body: JSON.stringify({ text, status }) }),
  reviewCaption: (id: string, status: string) =>
    j(`/api/captions/${id}/review`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  item: (id: string) => j(`/api/items/${id}`),
  thumbnailUrl: (id: string) => `/api/items/${id}/thumbnail`,
  fileUrl: (id: string, size = 0) => `/api/items/${id}/file${size ? `?size=${size}` : ''}`,
  setDecision: (id: string, decision: string, reason: string = '') =>
    j(`/api/items/${id}/decision`, { method: 'PATCH', body: JSON.stringify({ decision, reason }) }),
  setTags: (id: string, tags: string[]) =>
    j(`/api/items/${id}/tags`, { method: 'PATCH', body: JSON.stringify({ tags }) }),
  issues: (ds: string, issue_type = '') => {
    const qs = issue_type ? `?issue_type=${issue_type}` : ''
    return j(`/api/datasets/${ds}/issues${qs}`)
  },
  ackIssue: (id: string, status: string) =>
    j(`/api/issues/${id}/ack`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  duplicates: (ds: string) => j(`/api/datasets/${ds}/duplicates`),
  addLabel: (item: string, body: Record<string, unknown>) =>
    j(`/api/items/${item}/labels`, { method: 'POST', body: JSON.stringify(body) }),
  updateLabel: (id: string, category: string) =>
    j(`/api/labels/${id}`, { method: 'PATCH', body: JSON.stringify({ category }) }),
  reviewLabel: (id: string, status: string) =>
    j(`/api/labels/${id}/review`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  versions: (ds: string) => j(`/api/datasets/${ds}/versions`),
  createVersion: (ds: string, description: string) =>
    j(`/api/datasets/${ds}/versions`, { method: 'POST', body: JSON.stringify({ description }) }),
  versionDiff: (ds: string, old: string, neu: string) =>
    j(`/api/datasets/${ds}/versions/diff?old=${old}&new=${neu}`),
  restoreVersion: (ds: string, v: string) =>
    j(`/api/datasets/${ds}/versions/${v}/restore`, { method: 'POST', body: '{}' }),
  search: (ds: string, q: string, image_id = '') => {
    const qs = new URLSearchParams({ ...(q ? { q } : {}), ...(image_id ? { image_id } : {}), limit: '50' }).toString()
    return j(`/api/datasets/${ds}/search?${qs}`)
  },
  clusters: (ds: string) => j(`/api/datasets/${ds}/clusters`),
  export: (ds: string, fmt: string, version_id = '') =>
    j(`/api/datasets/${ds}/export`, { method: 'POST', body: JSON.stringify({ fmt, ...(version_id ? { version_id } : {}) }) }),
  cancelJob: (id: string) => j(`/api/jobs/${id}/cancel`, { method: 'POST', body: '{}' }),
  setLicense: (id: string, license: string) =>
    j(`/api/items/${id}/license`, { method: 'PATCH', body: JSON.stringify({ license }) }),
  derive: (ds: string, name: string, filters: Record<string, string>) =>
    j(`/api/datasets/${ds}/derive`, { method: 'POST', body: JSON.stringify({ name, filters }) }),
  merge: (datasetIds: string[], name: string) =>
    j('/api/datasets/merge', { method: 'POST', body: JSON.stringify({ dataset_ids: datasetIds, name }) }),
  split: (ds: string, ratios: number[]) =>
    j(`/api/datasets/${ds}/split`, { method: 'POST', body: JSON.stringify({ ratios }) }),
  providerSettings: () => j('/api/provider-settings') as Promise<ProviderSettings>,
  saveProviderSettings: (body: Record<string, unknown>) => j('/api/provider-settings', { method: 'PATCH', body: JSON.stringify(body) }) as Promise<ProviderSettings>,
  providers: () => j('/api/providers'),
  modelCatalog: () => j('/api/model-catalog'),
  installModel: (id: string, source?: string, sha256?: string, licenseAck?: boolean) =>
    j(`/api/models/${id}/install`, { method: 'POST', body: JSON.stringify({ source: source ?? '', sha256: sha256 ?? '', license_ack: licenseAck ?? false }) }),
  uninstallModel: (id: string) =>
    j(`/api/models/${id}/uninstall`, { method: 'POST', body: '{}' }),
  activateModel: (id: string, capability: string) =>
    j(`/api/models/${id}/active`, { method: 'PATCH', body: JSON.stringify({ capability }) }),
  setModelAutomation: (capability: string, enabled: boolean, confidence = 0.95, preview = true, auto_quarantine = false) =>
    j(`/api/model-automation/${capability}`, { method: 'PATCH', body: JSON.stringify({ enabled, confidence, preview, auto_quarantine }) }),
  installPlugin: (path: string) =>
    j('/api/plugins/install', { method: 'POST', body: JSON.stringify({ path }) }),
  uninstallPlugin: (id: string) =>
    j(`/api/plugins/${id}/uninstall`, { method: 'POST', body: '{}' }),
  preannotate: (ds: string, body: Record<string, unknown> = {}) => j(`/api/datasets/${ds}/preannotate`, { method: 'POST', body: JSON.stringify(body) }),
  piiScan: (ds: string, body: Record<string, unknown> = {}) => j(`/api/datasets/${ds}/pii-scan`, { method: 'POST', body: JSON.stringify(body) }),
  searchWithFilters: (ds: string, q: string, image_id: string, filters: Record<string, string>) => {
    const qs = new URLSearchParams({ ...(q ? { q } : {}), ...(image_id ? { image_id } : {}), limit: '50', ...filters }).toString()
    return j(`/api/datasets/${ds}/search?${qs}`)
  },
  itemsByLabel: (ds: string, category = '', label_type = '') => {
    const qs = new URLSearchParams({ ...(category ? { category } : {}), ...(label_type ? { label_type } : {}) }).toString()
    return j(`/api/datasets/${ds}/items-by-label?${qs}`)
  },
  swapCanonical: (group_id: string, item_id: string) =>
    j(`/api/duplicates/groups/${group_id}/canonical/${item_id}`, { method: 'PATCH', body: '{}' }),
  deriveFrom: (ds: string, name: string, body: Record<string, unknown>) =>
    j(`/api/datasets/${ds}/derive-from`, { method: 'POST', body: JSON.stringify({ name, ...body }) }),
  redactPii: (ds: string) => j(`/api/datasets/${ds}/redact-pii`, { method: 'POST', body: '{}' }),
  histogramUrl: (id: string) => `/api/items/${id}/histogram`,
  startJobWithBody: (ds: string, type: string, body: Record<string, unknown>) =>
    j(`/api/datasets/${ds}/jobs/${type}`, { method: 'POST', body: JSON.stringify(body) }),
  coverUrl: (ds: string) => `/api/datasets/${ds}/cover`,
}
