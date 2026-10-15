/** Offline authoring catalog. Entries are interface templates, not vendor IP models or implementation claims. */
export type CatalogPortRole = 'initiator' | 'target' | 'bidirectional';
export interface CatalogPortTemplate {
  id: string;
  role: CatalogPortRole;
  protocol: string;
  dataWidth: number;
  addressWidth?: number;
  capabilities: string[];
}
export interface CatalogItemV1 {
  id: string;
  name: string;
  vendor: string | null;
  family: string;
  version: string;
  class: 'router' | 'compute' | 'memory' | 'bridge' | 'peripheral';
  tags: string[];
  clocks: string[];
  resets: string[];
  powers: string[];
  ports: CatalogPortTemplate[];
  description: string;
}
export interface LocalCatalogV1 {
  schemaVersion: 1;
  catalogId: string;
  version: string;
  items: CatalogItemV1[];
}
export interface CatalogReferenceV1 { catalogId: string; itemId: string; version: string; fallbackMetadata: Record<string, unknown> }
export interface CatalogResolutionV1 {
  state: 'resolved' | 'missing' | 'outdated';
  item: CatalogItemV1 | null;
  fallbackMetadata: Record<string, unknown>;
  warning: string | null;
  requiredAction: 'none' | 'explicit-rebind';
}

const port = (id: string, role: CatalogPortRole, protocol: string, dataWidth: number, addressWidth?: number): CatalogPortTemplate => ({
  id, role, protocol, dataWidth, ...(addressWidth === undefined ? {} : { addressWidth }), capabilities: role === 'initiator' ? ['read', 'write'] : ['read', 'write'],
});

/** Generic interface templates only. Protocol, widths and roles are starter authoring values, not certified implementation limits. */
export const BUILTIN_CATALOG_V1: LocalCatalogV1 = {
  schemaVersion: 1,
  catalogId: 'veritx.generic',
  version: '1.0.0',
  items: [
    { id: 'router.generic-5p', name: 'Generic 5-port router', vendor: null, family: 'generic-router', version: '1.0.0', class: 'router', tags: ['router', 'switch', '5-port'], clocks: ['clk_core'], resets: ['rst_core'], powers: ['pwr_core'], ports: [0,1,2,3,4].map(i => port(`p${i}`, 'bidirectional', 'generic-flit', 512)), description: 'Editable generic router interface template; no microarchitecture or performance model.' },
    { id: 'compute.generic', name: 'Generic compute agent', vendor: null, family: 'generic-compute', version: '1.0.0', class: 'compute', tags: ['compute', 'npu'], clocks: ['clk_core'], resets: ['rst_core'], powers: ['pwr_core'], ports: [port('mem', 'initiator', 'AXI4', 512, 48)], description: 'Generic compute endpoint interface; does not model an NPU microarchitecture.' },
    { id: 'memory.hbm-controller.generic', name: 'Generic HBM controller endpoint', vendor: null, family: 'generic-memory', version: '1.0.0', class: 'memory', tags: ['hbm', 'memory', 'controller'], clocks: ['clk_mem'], resets: ['rst_mem'], powers: ['pwr_mem'], ports: [port('host', 'target', 'AXI4', 512, 48)], description: 'Generic memory-controller endpoint interface; not a physical HBM controller model.' },
    { id: 'memory.ddr-controller.generic', name: 'Generic DDR controller endpoint', vendor: null, family: 'generic-memory', version: '1.0.0', class: 'memory', tags: ['ddr', 'memory', 'controller'], clocks: ['clk_mem'], resets: ['rst_mem'], powers: ['pwr_mem'], ports: [port('host', 'target', 'AXI4', 256, 40)], description: 'Generic memory-controller endpoint interface; not a physical DDR controller model.' },
    { id: 'bridge.protocol-domain.generic', name: 'Generic protocol/domain bridge', vendor: null, family: 'generic-bridge', version: '1.0.0', class: 'bridge', tags: ['bridge', 'adapter', 'clock-domain'], clocks: ['clk_a', 'clk_b'], resets: ['rst_a', 'rst_b'], powers: ['pwr_core'], ports: [port('upstream', 'target', 'AXI4', 256, 48), port('downstream', 'initiator', 'AXI4', 256, 48)], description: 'Explicit bridge placeholder; conversion behavior is not implemented or simulated.' },
    { id: 'peripheral.generic', name: 'Generic peripheral endpoint', vendor: null, family: 'generic-peripheral', version: '1.0.0', class: 'peripheral', tags: ['peripheral', 'device'], clocks: ['clk_periph'], resets: ['rst_periph'], powers: ['pwr_core'], ports: [port('control', 'target', 'AXI4-Lite', 32, 32)], description: 'Generic peripheral interface template without vendor-specific behavior.' },
    { id: 'dma.generic', name: 'Generic DMA agent', vendor: null, family: 'generic-dma', version: '1.0.0', class: 'peripheral', tags: ['dma', 'initiator', 'device'], clocks: ['clk_dma'], resets: ['rst_dma'], powers: ['pwr_core'], ports: [port('memory', 'initiator', 'AXI4', 256, 48)], description: 'Generic DMA interface template without transfer-engine or performance modeling.' },
  ],
};

export function validateLocalCatalog(value: unknown): string[] {
  const issues: string[] = [];
  const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
  if (!record(value)) return ['$: must be an object'];
  for (const k of Object.keys(value)) if (!['schemaVersion','catalogId','version','items'].includes(k)) issues.push(`$.${k}: unknown field`);
  if (value.schemaVersion !== 1) issues.push('$.schemaVersion: must equal 1');
  for (const k of ['catalogId','version']) if (typeof value[k] !== 'string' || !value[k].trim()) issues.push(`$.${k}: must be a non-empty string`);
  if (!Array.isArray(value.items)) return [...issues, '$.items: must be an array'];
  const ids = new Set<string>();
  value.items.forEach((raw, i) => {
    const p = `$.items[${i}]`;
    if (!record(raw)) { issues.push(`${p}: must be an object`); return; }
    for (const k of Object.keys(raw)) if (!['id','name','vendor','family','version','class','tags','clocks','resets','powers','ports','description'].includes(k)) issues.push(`${p}.${k}: unknown field`);
    for (const k of ['id','name','family','version','description']) if (typeof raw[k] !== 'string' || !raw[k].trim()) issues.push(`${p}.${k}: must be a non-empty string`);
    if (typeof raw.id === 'string') { if (ids.has(raw.id)) issues.push(`${p}.id: duplicate catalog item ID ${raw.id}`); ids.add(raw.id); }
    if (raw.vendor !== null && typeof raw.vendor !== 'string') issues.push(`${p}.vendor: must be a string or null`);
    if (!['router','compute','memory','bridge','peripheral'].includes(String(raw.class))) issues.push(`${p}.class: unsupported class`);
    for (const k of ['tags','clocks','resets','powers'] as const) if (!Array.isArray(raw[k]) || raw[k].some(v => typeof v !== 'string' || !v.trim())) issues.push(`${p}.${k}: must be an array of non-empty strings`);
    if (!Array.isArray(raw.ports) || raw.ports.length === 0) { issues.push(`${p}.ports: must be a non-empty array`); return; }
    const portIds = new Set<string>();
    raw.ports.forEach((rp, j) => {
      const q = `${p}.ports[${j}]`;
      if (!record(rp)) { issues.push(`${q}: must be an object`); return; }
      for (const k of Object.keys(rp)) if (!['id','role','protocol','dataWidth','addressWidth','capabilities'].includes(k)) issues.push(`${q}.${k}: unknown field`);
      for (const k of ['id','protocol']) if (typeof rp[k] !== 'string' || !rp[k].trim()) issues.push(`${q}.${k}: must be a non-empty string`);
      if (typeof rp.id === 'string') { if (portIds.has(rp.id)) issues.push(`${q}.id: duplicate port ID ${rp.id}`); portIds.add(rp.id); }
      if (!['initiator','target','bidirectional'].includes(String(rp.role))) issues.push(`${q}.role: unsupported role`);
      if (!Number.isSafeInteger(rp.dataWidth) || (rp.dataWidth as number) <= 0) issues.push(`${q}.dataWidth: must be a positive integer`);
      if (rp.addressWidth !== undefined && (!Number.isSafeInteger(rp.addressWidth) || (rp.addressWidth as number) <= 0 || (rp.addressWidth as number) > 64)) issues.push(`${q}.addressWidth: must be an integer from 1 through 64`);
      if (!Array.isArray(rp.capabilities) || rp.capabilities.some(c => typeof c !== 'string' || !c.trim())) issues.push(`${q}.capabilities: must be an array of non-empty strings`);
    });
  });
  return issues;
}

/** Resolve exact provenance only. Embedded fallback data is retained for inspection and never silently substituted as equivalent IP. */
export function resolveCatalogReference(catalog: LocalCatalogV1, ref: CatalogReferenceV1): CatalogResolutionV1 {
  const item = catalog.catalogId === ref.catalogId ? catalog.items.find(candidate => candidate.id === ref.itemId) ?? null : null;
  if (!item) return {
    state: 'missing', item: null, fallbackMetadata: ref.fallbackMetadata,
    warning: `Catalog item ${ref.catalogId}/${ref.itemId}@${ref.version} is unavailable; embedded fallback is inspection data only.`,
    requiredAction: 'explicit-rebind',
  };
  if (item.version !== ref.version) return {
    state: 'outdated', item: null, fallbackMetadata: ref.fallbackMetadata,
    warning: `Catalog item ${ref.catalogId}/${ref.itemId} version ${ref.version} differs from available ${item.version}; replacement requires explicit action.`,
    requiredAction: 'explicit-rebind',
  };
  return { state: 'resolved', item, fallbackMetadata: ref.fallbackMetadata, warning: null, requiredAction: 'none' };
}

export function parseLocalCatalog(json: string): LocalCatalogV1 {
  let value: unknown;
  try { value = JSON.parse(json) as unknown; }
  catch (error) { throw new Error(`invalid catalog JSON: ${error instanceof Error ? error.message : String(error)}`); }
  const issues = validateLocalCatalog(value);
  if (issues.length) throw new Error(`invalid catalog: ${issues.join('; ')}`);
  return value as LocalCatalogV1;
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, canonical(v)]));
  return value;
}

/** Deterministic local interchange serialization; authored item/port array order is preserved. */
export function serializeLocalCatalog(catalog: LocalCatalogV1): string {
  const issues = validateLocalCatalog(catalog);
  if (issues.length) throw new Error(`invalid catalog: ${issues.join('; ')}`);
  return JSON.stringify(canonical(catalog), null, 2);
}

export function searchCatalog(catalog: LocalCatalogV1, query: string, itemClass?: CatalogItemV1['class']): CatalogItemV1[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return catalog.items.filter(item => (!itemClass || item.class === itemClass) && terms.every(term =>
    [item.id,item.name,item.vendor ?? '',item.family,item.class,...item.tags,item.ports.map(p => p.protocol).join(' ')].join(' ').toLowerCase().includes(term)));
}
